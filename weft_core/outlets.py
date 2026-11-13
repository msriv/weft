"""Home country of well-known outlets whose domain has no country code (.com, .org, ...).

Perspective needs a country (see perspectives.py). Discovery fills `country` from this table
and records `country_source` so the admin can see it came from the table, not a citation. The
admin source editor overrides it. Add outlets here as discovery finds them.
"""

from typing import Any

OUTLET_COUNTRY = {
    # Israel
    "timesofisrael.com": "IL",
    "jpost.com": "IL",
    "haaretz.com": "IL",
    "ynetnews.com": "IL",
    "i24news.tv": "IL",
    "israelhayom.com": "IL",
    "israelnationalnews.com": "IL",
    # Iran
    "tehrantimes.com": "IR",
    "presstv.com": "IR",
    "mehrnews.com": "IR",
    "tasnimnews.com": "IR",
    "ifpnews.com": "IR",
    "en.irna.ir": "IR",
    # Ukraine
    "kyivindependent.com": "UA",
    "kyivpost.com": "UA",
    "ukrinform.net": "UA",
    "unian.info": "UA",
    "euromaidanpress.com": "UA",
    # Russia
    "tass.com": "RU",
    "rt.com": "RU",
    "sputnikglobe.com": "RU",
    "interfax.com": "RU",
    # United States
    "nytimes.com": "US",
    "washingtonpost.com": "US",
    "cnn.com": "US",
    "foxnews.com": "US",
    "nbcnews.com": "US",
    "cbsnews.com": "US",
    "abcnews.go.com": "US",
    "apnews.com": "US",
    "politico.com": "US",
    "thehill.com": "US",
    "axios.com": "US",
    "npr.org": "US",
    "wsj.com": "US",
    "usatoday.com": "US",
    "bloomberg.com": "US",
    "newsweek.com": "US",
    "cnbc.com": "US",
    "nypost.com": "US",
    "latimes.com": "US",
    "rollcall.com": "US",
    "pbs.org": "US",
    "voanews.com": "US",
    "breitbart.com": "US",
    "msnbc.com": "US",
    "foreignpolicy.com": "US",
    "theatlantic.com": "US",
    "senate.gov": "US",
    "house.gov": "US",
    "whitehouse.gov": "US",
    "state.gov": "US",
    "defense.gov": "US",
    # United Kingdom
    "bbc.com": "GB",
    "theguardian.com": "GB",
    "reuters.com": "GB",
    "ft.com": "GB",
    "economist.com": "GB",
    "independent.co.uk": "GB",
    "telegraph.co.uk": "GB",
    "iranintl.com": "GB",
    "middleeasteye.net": "GB",
    # India
    "thehindu.com": "IN",
    "hindustantimes.com": "IN",
    "indianexpress.com": "IN",
    "ndtv.com": "IN",
    "indiatimes.com": "IN",
    "livemint.com": "IN",
    "deccanherald.com": "IN",
    "news18.com": "IN",
    "business-standard.com": "IN",
    "thequint.com": "IN",
    "firstpost.com": "IN",
    "tribuneindia.com": "IN",
    "telegraphindia.com": "IN",
    "newindianexpress.com": "IN",
    "outlookindia.com": "IN",
    "dnaindia.com": "IN",
    "zeenews.india.com": "IN",
    "republicworld.com": "IN",
    "thestatesman.com": "IN",
    # Others often found on these beats
    "aljazeera.com": "QA",
    "france24.com": "FR",
    "dw.com": "DE",
    "euronews.com": "FR",
    "thenationalnews.com": "AE",
    "gulfnews.com": "AE",
    "khaleejtimes.com": "AE",
    "arabnews.com": "SA",
    "alarabiya.net": "SA",
    "dailysabah.com": "TR",
    "trtworld.com": "TR",
    "cgtn.com": "CN",
    "dawn.com": "PK",
    "thenews.com.pk": "PK",
    "aa.com.tr": "TR",
}


def country_for(domain: str) -> str | None:
    """Country for a domain or any of its parent domains (www.bbc.com -> bbc.com)."""
    parts = domain.lower().split(".")
    for i in range(len(parts) - 1):
        if c := OUTLET_COUNTRY.get(".".join(parts[i:])):
            return c
    return None


def fill_countries(db: Any) -> int:
    """Give sources with no country the table's country, and re-tag their reports. Returns how
    many sources changed. Admin-set countries are never overwritten."""
    from weft_core import store

    n = 0
    for s in store.all_sources(db, "n.country IS NULL"):
        if c := country_for(s.get("domain") or ""):
            store.set_country(db, s["id"], c, "outlet table (unverified)")
            n += 1
    return n


_SLD = {"co", "com", "org", "net", "gov", "ac", "edu", "gen", "nic"}


def site_owner(homepage: str | None) -> str | None:
    """Owner key from a homepage's registrable domain ("edition.cnn.com" and "cnn.com" share
    "site:cnn.com"), so copy shared between one outlet's own sites is not counted as copying
    (#94). It never claims a corporate owner; a cited `owner_id` replaces it."""
    if not homepage:
        return None
    from urllib.parse import urlsplit

    host = urlsplit(homepage if "//" in homepage else f"//{homepage}").netloc.lower()
    parts = host.split(":")[0].removeprefix("www.").split(".")
    if len(parts) < 2:
        return None
    n = 3 if len(parts) >= 3 and parts[-2] in _SLD and len(parts[-1]) == 2 else 2
    return "site:" + ".".join(parts[-n:])
