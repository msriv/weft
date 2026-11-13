"""The one model client. All model access in Weft goes through here (product rule 4).

Pins model + revision, forces temperature 0 and a fixed seed, and writes every call
to a log sink (the `model_calls` table in production) before returning.
"""

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

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
    ) -> None:
        if not revision:
            raise ValueError("revision must be pinned")
        self._provider = provider or os.environ.get("MODEL_PROVIDER")
        self._model, self._revision, self._log = model, revision, log
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
        json_schema: dict[str, Any] | None = None,
    ) -> str:
        """Run one call. `instructions` is our template text; `data` is untrusted and gets quoted.
        With `json_schema` the provider is asked for output that matches it (forced JSON)."""
        body: dict[str, Any] = {
            "model": self._model,
            "temperature": TEMPERATURE,
            "seed": SEED,
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
        if json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": prompt_template.split("@")[0],
                    "schema": json_schema,
                    "strict": True,
                },
            }
        resp = self._http.post("/chat/completions", json=body)
        resp.raise_for_status()
        output: str = resp.json()["choices"][0]["message"]["content"]
        payload = json.dumps(body, sort_keys=True, ensure_ascii=False)
        self._log(
            ModelCall(
                called_at=datetime.now(UTC).isoformat(),
                model=self._model,
                revision=self._revision,
                temperature=TEMPERATURE,
                seed=SEED,
                prompt_template=prompt_template,
                input_hash=hashlib.sha256(payload.encode()).hexdigest(),
                input=payload,
                output=output,
            )
        )
        return output


def as_row(call: ModelCall) -> dict[str, Any]:
    return asdict(call)
