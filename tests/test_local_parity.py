"""The local Pub/Sub stand-ins (local/init.py) must give up on a message after the same number of
deliveries as the Terraform subscriptions (#159), so a stall seen locally is a stall seen in prod."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _limits(text: str) -> list[int]:
    return [int(n) for n in re.findall(r"max_delivery_attempts\s*=\s*(\d+)", text)]


def test_local_and_terraform_dead_letter_limits_match() -> None:
    tf = [n for f in (ROOT / "infra/modules").glob("*/main.tf") for n in _limits(f.read_text())]
    local = (ROOT / "local/init.py").read_text()
    (const,) = re.findall(r"^MAX_DELIVERY_ATTEMPTS\s*=\s*(\d+)", local, re.MULTILINE)
    assert tf and set(tf) == {int(const)}


def test_every_local_subscription_has_a_dead_letter_policy() -> None:
    local = (ROOT / "local/init.py").read_text()
    subs = len(re.findall(r'^\s+\("[a-z-]+", "[a-z-]+", "http://', local, re.MULTILINE))
    assert subs == 3 and local.count("create_subscription(") == 1 and "dead_letter_policy" in local
    # one Terraform push subscription per local one: fetcher, stream worker, stream worker documents
    tf = sum(
        len(re.findall(r'resource "google_pubsub_subscription" "(?!pull)', f.read_text()))
        for f in (ROOT / "infra/modules").glob("*/main.tf")
    )
    assert tf == subs
