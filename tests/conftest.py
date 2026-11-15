import pytest

from weft_core import polite


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test hosts (x.test, ...) do not resolve. Literal IPs resolve to themselves."""
    import ipaddress

    def fake(host: str) -> list[str]:
        try:
            return [str(ipaddress.ip_address(host))]
        except ValueError:
            return ["93.184.216.34"]

    monkeypatch.setattr(polite, "resolve", fake)
