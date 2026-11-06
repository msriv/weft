"""Which perspective a source speaks for. A perspective is usually a country (spec: Perspective).

Order: the source's recorded country, else its country-code domain, else 'unattributed'. Nothing
here claims the source's owner or editorial line; an admin can set `country` with a citation.
"""

from typing import Any

GENERIC = {"com", "org", "net", "info", "news", "io", "tv", "co", "media", "app", "me"}
SPECIAL = {"uk": "GB"}  # ccTLD that differs from ISO 3166


def perspective_of(source: dict[str, Any]) -> str:
    if source.get("country"):
        return str(source["country"]).upper()
    host = source.get("homepage", "").split("//")[-1].split("/")[0].split(":")[0]
    tld = host.rsplit(".", 1)[-1].lower() if "." in host else ""
    if len(tld) == 2 and tld not in GENERIC:
        return SPECIAL.get(tld, tld.upper())
    return "unattributed"
