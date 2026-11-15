"""The one model client. All model access in Weft goes through here (product rule 4).

Pins model + revision, forces temperature 0 and a fixed seed, and writes every call
to a log sink (the `model_calls` table in production) before returning.
"""

import contextvars
import hashlib
import json
import os
import random
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from weft_core.ledger import Ledger

TEMPERATURE = 0.0
SEED = 20260101  # fixed so reruns of the same input are comparable


@dataclass(frozen=True)
class ModelCall:
    """One row of `model_calls`."""

    called_at: str
    model: str
    revision: str
    temperature: float
    seed: int
    prompt_template: str  # name@version, e.g. "merge-check@1"
    input_hash: str
    input: str
    output: str
    # Added in #157; NULLABLE columns, so older rows stay valid.
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None
    status: str | None = None  # "ok", "empty" or "error:<reason>"
    latency_ms: int | None = None
    caller: str | None = None


class ModelRefused(Exception):
    """No usable answer: callers degrade (skip, leave unread) instead of crashing the stage."""


class BudgetExceeded(ModelRefused):
    """The day's token or cost cap for this caller is spent. No request was sent."""


class EmptyOutput(ModelRefused, ValueError):
    """The provider answered with no content (refusal, or an error body with HTTP 200)."""


# Set by pipeline.ctx.Budget.take just before a call: the per-beat scope to charge real usage to.
scope: contextvars.ContextVar[str | None] = contextvars.ContextVar("model_scope", default=None)

MAX_ATTEMPTS = 3
RETRY_STATUS = {429, 500, 502, 503, 504}
LOG_ATTEMPTS = 3


LogSink = Callable[[ModelCall], None]


def quote_untrusted(text: str) -> str:
    """Wrap scraped text as quoted data. Never concatenate it into instructions."""
    return "<untrusted_data>\n" + json.dumps(text, ensure_ascii=False) + "\n</untrusted_data>"


class ModelClient:
    def __init__(
        self,
        *,
        base_url: str,  # any OpenAI-compatible API; provider is a deployment choice (D7)
        api_key: str,
        model: str,
        revision: str,
        log: LogSink,  # required: no unlogged calls
        transport: httpx.BaseTransport | None = None,
        provider: str
        | None = None,  # OpenRouter only: pin one upstream host, else it may switch hosts
        ledger: Ledger | None = None,  # spend ledger, reuse of stored answers, daily cap
        caller: str = "pipeline",  # who spends: "pipeline", "stream" or "ask"
        daily_tokens: int | None = None,  # this caller's share of the day's cap
        daily_cost_usd: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not revision:
            raise ValueError("revision must be pinned")
        self._provider = provider or os.environ.get("MODEL_PROVIDER")
        self._model, self._revision, self._log = model, revision, log
        self._ledger, self._caller, self._sleep = ledger, caller, sleep
        self._daily_tokens, self._daily_cost = daily_tokens, daily_cost_usd
        self._ask_cost = "openrouter" in base_url  # OpenRouter reports cost when asked
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
            timeout=60,
        )

    @property
    def name(self) -> str:
        """Pinned model and revision, shown beside model speculation (D22)."""
        return f"{self._model}@{self._revision}"

    def complete(
        self,
        *,
        prompt_template: str,
        instructions: str,
        data: str,
        max_tokens: int,  # required: a runaway completion is billed in full
        json_schema: dict[str, Any] | None = None,
    ) -> str:
        """Run one call. `instructions` is our template text; `data` is untrusted and gets quoted.
        With `json_schema` the provider is asked for output that matches it (forced JSON).
        Raises BudgetExceeded (no request sent) or EmptyOutput; both are ModelRefused."""
        body: dict[str, Any] = {
            "model": self._model,
            "temperature": TEMPERATURE,
            "seed": SEED,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": quote_untrusted(data)},
            ],
        }
        if self._provider:
            body["provider"] = {
                "order": [self._provider],
                "allow_fallbacks": False,
                "require_parameters": True,
            }
        if self._ask_cost:
            body["usage"] = {"include": True}
        if json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": prompt_template.split("@")[0],
                    "schema": json_schema,
                    "strict": True,
                },
            }
        payload = json.dumps(body, sort_keys=True, ensure_ascii=False)
        input_hash = hashlib.sha256(payload.encode()).hexdigest()
        key = f"{prompt_template}|{input_hash}"
        # Temperature 0 and a fixed seed: the same input and template get the same answer, so
        # a stored one is reused and a stage re-run on unchanged input costs nothing.
        if self._ledger and (hit := self._ledger.cached(key)) is not None:
            return hit
        day = datetime.now(UTC).date().isoformat()
        self._check_cap(day)

        began = time.monotonic()
        try:
            resp = self._post(body)
        except Exception as exc:
            self._record(
                prompt_template, input_hash, payload, "", "error:" + type(exc).__name__, began, None
            )
            raise
        data_json: dict[str, Any] = resp.json()
        usage = data_json.get("usage") or {}
        try:
            output = data_json["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            output = None
        status = "ok" if output else "empty"
        self._record(prompt_template, input_hash, payload, output or "", status, began, usage, day)
        if not output:
            raise EmptyOutput(f"{prompt_template}: empty answer")
        if self._ledger:
            self._ledger.remember(key, output)
        return str(output)

    def _check_cap(self, day: str) -> None:
        if not self._ledger:
            return
        tokens, cost = self._ledger.spent(day, self._caller)
        if self._daily_tokens is not None and tokens >= self._daily_tokens:
            raise BudgetExceeded(f"{self._caller}: daily token cap {self._daily_tokens} reached")
        if self._daily_cost is not None and cost >= self._daily_cost:
            raise BudgetExceeded(f"{self._caller}: daily cost cap ${self._daily_cost} reached")

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        """POST with up to MAX_ATTEMPTS tries on 429, 5xx and timeouts: exponential backoff with
        jitter, or the provider's Retry-After when given."""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            wait = 2.0**attempt * (0.5 + random.random() / 2)
            try:
                resp = self._http.post("/chat/completions", json=body)
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt == MAX_ATTEMPTS:
                    raise
            else:
                if resp.status_code not in RETRY_STATUS or attempt == MAX_ATTEMPTS:
                    resp.raise_for_status()
                    return resp
                after = resp.headers.get("Retry-After", "")
                if after.isdigit():
                    wait = min(float(after), 60.0)
            self._sleep(wait)
        raise AssertionError("unreachable")

    def _record(
        self,
        template: str,
        input_hash: str,
        payload: str,
        output: str,
        status: str,
        began: float,
        usage: dict[str, Any] | None,
        day: str | None = None,
    ) -> None:
        usage = usage or {}
        pt, ct = usage.get("prompt_tokens"), usage.get("completion_tokens")
        cost = usage.get("cost")
        call = ModelCall(
            called_at=datetime.now(UTC).isoformat(),
            model=self._model,
            revision=self._revision,
            temperature=TEMPERATURE,
            seed=SEED,
            prompt_template=template,
            input_hash=input_hash,
            input=payload,
            output=output,
            prompt_tokens=pt,
            completion_tokens=ct,
            cost_usd=float(cost) if cost is not None else None,
            status=status,
            latency_ms=int((time.monotonic() - began) * 1000),
            caller=self._caller,
        )
        # Spend first: the answer is already paid for, so the ledger and log must not lose it.
        if self._ledger and day and (pt or ct):
            used = int(pt or 0) + int(ct or 0)
            self._ledger.add(day, self._caller, used, float(cost or 0.0))
            if (sc := scope.get()) is not None:
                self._ledger.add(day, sc, used, 0.0)
        scope.set(None)
        self._write_log(call)

    def _write_log(self, call: ModelCall) -> None:
        """Retry the log insert on its own. If it still fails, the call goes to stderr (Cloud
        Logging) rather than being thrown away with its paid output."""
        for attempt in range(1, LOG_ATTEMPTS + 1):
            try:
                self._log(call)
                return
            except Exception:  # noqa: BLE001 - any sink failure falls back to stderr
                if attempt < LOG_ATTEMPTS:
                    self._sleep(float(attempt))
        print(json.dumps({"event": "model_call_unlogged", **as_row(call)}), file=sys.stderr)


def as_row(call: ModelCall) -> dict[str, Any]:
    return asdict(call)
