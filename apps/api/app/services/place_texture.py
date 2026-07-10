"""Country + place "texture" for the chat place drawer.

Two public-domain / free sources enrich a resolved place beyond what Google
returns:

* **CIA World Factbook** — country-level color (background, climate, terrain,
  languages, population, capital) fetched from the ``factbook.json`` mirror
  (public domain). Countries are keyed by GEC code inside region folders, so a
  small curated map translates the country name Google resolves to into a
  ``{region}/{gec}.json`` path. An unmapped or unfetchable country simply
  yields no Factbook block — texture is garnish, never load-bearing.
* **Wikipedia** — a place-level summary from the REST ``page/summary``
  endpoint (no key). Disambiguation pages are dropped rather than shown.

Both fetches degrade to ``None`` on any failure and cache in-process keyed by
their lookup, mirroring the Places photo-URL cache: texture for "Kyoto" should
cost one upstream round-trip per process, not one per drawer open.
"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict

from app.config import Settings

# ── Response shapes ─────────────────────────────────────────────────────


class FactbookTexture(BaseModel):
    """Country-level color pulled from the CIA World Factbook."""

    model_config = ConfigDict(extra="forbid")

    country_name: str
    background: str | None = None
    climate: str | None = None
    terrain: str | None = None
    languages: str | None = None
    population: str | None = None
    capital: str | None = None


class WikipediaTexture(BaseModel):
    """Place-level summary from Wikipedia's REST summary endpoint."""

    model_config = ConfigDict(extra="forbid")

    title: str
    extract: str
    url: str | None = None
    thumbnail_url: str | None = None


# ── Country name → factbook.json path ───────────────────────────────────
#
# factbook.json keys countries by GEC (ex-FIPS) code inside CIA region
# folders — neither is derivable from an ISO code or the English name, so a
# curated map covers the destinations this product actually sells. A miss
# costs only the Factbook block. Keys are normalized country names as they
# appear at the tail of a Google ``formattedAddress``.

_FACTBOOK_COUNTRIES: dict[str, tuple[str, str, str]] = {
    # normalized name → (region folder, gec code, display name)
    "japan": ("east-n-southeast-asia", "ja", "Japan"),
    "china": ("east-n-southeast-asia", "ch", "China"),
    "south korea": ("east-n-southeast-asia", "ks", "South Korea"),
    "taiwan": ("east-n-southeast-asia", "tw", "Taiwan"),
    "thailand": ("east-n-southeast-asia", "th", "Thailand"),
    "vietnam": ("east-n-southeast-asia", "vm", "Vietnam"),
    "cambodia": ("east-n-southeast-asia", "cb", "Cambodia"),
    "laos": ("east-n-southeast-asia", "la", "Laos"),
    "myanmar": ("east-n-southeast-asia", "bm", "Myanmar"),
    "burma": ("east-n-southeast-asia", "bm", "Myanmar"),
    "malaysia": ("east-n-southeast-asia", "my", "Malaysia"),
    "singapore": ("east-n-southeast-asia", "sn", "Singapore"),
    "indonesia": ("east-n-southeast-asia", "id", "Indonesia"),
    "philippines": ("east-n-southeast-asia", "rp", "Philippines"),
    "mongolia": ("east-n-southeast-asia", "mg", "Mongolia"),
    "india": ("south-asia", "in", "India"),
    "nepal": ("south-asia", "np", "Nepal"),
    "bhutan": ("south-asia", "bt", "Bhutan"),
    "sri lanka": ("south-asia", "ce", "Sri Lanka"),
    "maldives": ("south-asia", "mv", "Maldives"),
    "france": ("europe", "fr", "France"),
    "italy": ("europe", "it", "Italy"),
    "spain": ("europe", "sp", "Spain"),
    "portugal": ("europe", "po", "Portugal"),
    "greece": ("europe", "gr", "Greece"),
    "united kingdom": ("europe", "uk", "United Kingdom"),
    "uk": ("europe", "uk", "United Kingdom"),
    "england": ("europe", "uk", "United Kingdom"),
    "scotland": ("europe", "uk", "United Kingdom"),
    "wales": ("europe", "uk", "United Kingdom"),
    "ireland": ("europe", "ei", "Ireland"),
    "iceland": ("europe", "ic", "Iceland"),
    "norway": ("europe", "no", "Norway"),
    "sweden": ("europe", "sw", "Sweden"),
    "finland": ("europe", "fi", "Finland"),
    "denmark": ("europe", "da", "Denmark"),
    "switzerland": ("europe", "sz", "Switzerland"),
    "austria": ("europe", "au", "Austria"),
    "germany": ("europe", "gm", "Germany"),
    "netherlands": ("europe", "nl", "Netherlands"),
    "the netherlands": ("europe", "nl", "Netherlands"),
    "belgium": ("europe", "be", "Belgium"),
    "croatia": ("europe", "hr", "Croatia"),
    "montenegro": ("europe", "mj", "Montenegro"),
    "slovenia": ("europe", "si", "Slovenia"),
    "czechia": ("europe", "ez", "Czechia"),
    "czech republic": ("europe", "ez", "Czechia"),
    "hungary": ("europe", "hu", "Hungary"),
    "poland": ("europe", "pl", "Poland"),
    "turkey": ("middle-east", "tu", "Turkey"),
    "türkiye": ("middle-east", "tu", "Turkey"),
    "israel": ("middle-east", "is", "Israel"),
    "jordan": ("middle-east", "jo", "Jordan"),
    "oman": ("middle-east", "mu", "Oman"),
    "qatar": ("middle-east", "qa", "Qatar"),
    "saudi arabia": ("middle-east", "sa", "Saudi Arabia"),
    "united arab emirates": ("middle-east", "tc", "United Arab Emirates"),
    "georgia": ("middle-east", "gg", "Georgia"),
    "kazakhstan": ("central-asia", "kz", "Kazakhstan"),
    "uzbekistan": ("central-asia", "uz", "Uzbekistan"),
    "kyrgyzstan": ("central-asia", "kg", "Kyrgyzstan"),
    "russia": ("central-asia", "rs", "Russia"),
    "morocco": ("africa", "mo", "Morocco"),
    "egypt": ("africa", "eg", "Egypt"),
    "kenya": ("africa", "ke", "Kenya"),
    "tanzania": ("africa", "tz", "Tanzania"),
    "south africa": ("africa", "sf", "South Africa"),
    "namibia": ("africa", "wa", "Namibia"),
    "botswana": ("africa", "bc", "Botswana"),
    "rwanda": ("africa", "rw", "Rwanda"),
    "seychelles": ("africa", "se", "Seychelles"),
    "mauritius": ("africa", "mp", "Mauritius"),
    "united states": ("north-america", "us", "United States"),
    "usa": ("north-america", "us", "United States"),
    "us": ("north-america", "us", "United States"),
    "canada": ("north-america", "ca", "Canada"),
    "greenland": ("north-america", "gl", "Greenland"),
    "mexico": ("north-america", "mx", "Mexico"),
    "costa rica": ("central-america-n-caribbean", "cs", "Costa Rica"),
    "panama": ("central-america-n-caribbean", "pm", "Panama"),
    "belize": ("central-america-n-caribbean", "bh", "Belize"),
    "the bahamas": ("central-america-n-caribbean", "bf", "The Bahamas"),
    "bahamas": ("central-america-n-caribbean", "bf", "The Bahamas"),
    "jamaica": ("central-america-n-caribbean", "jm", "Jamaica"),
    "dominican republic": ("central-america-n-caribbean", "dr", "Dominican Republic"),
    "saint lucia": ("central-america-n-caribbean", "st", "Saint Lucia"),
    "barbados": ("central-america-n-caribbean", "bb", "Barbados"),
    "brazil": ("south-america", "br", "Brazil"),
    "argentina": ("south-america", "ar", "Argentina"),
    "chile": ("south-america", "ci", "Chile"),
    "peru": ("south-america", "pe", "Peru"),
    "colombia": ("south-america", "co", "Colombia"),
    "ecuador": ("south-america", "ec", "Ecuador"),
    "uruguay": ("south-america", "uy", "Uruguay"),
    "bolivia": ("south-america", "bl", "Bolivia"),
    "australia": ("australia-oceania", "as", "Australia"),
    "new zealand": ("australia-oceania", "nz", "New Zealand"),
    "fiji": ("australia-oceania", "fj", "Fiji"),
    "french polynesia": ("australia-oceania", "fp", "French Polynesia"),
    "antarctica": ("antarctica", "ay", "Antarctica"),
}


def country_from_address(formatted_address: str) -> str | None:
    """The mapped country in a Google ``formattedAddress``, or ``None``.

    Most locales put the country last, but some (Japanese-format addresses)
    put it first — try both ends against the curated Factbook map.
    """
    parts = [p.strip() for p in formatted_address.split(",") if p.strip()]
    candidates = [parts[-1], parts[0]] if len(parts) > 1 else parts
    for candidate in candidates:
        if _normalize_country(candidate) in _FACTBOOK_COUNTRIES:
            return candidate
    return None


def _normalize_country(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().lower()


# ── In-process TTL caches (mirrors the Places photo-URL cache) ──────────

_FACTBOOK_TTL_SECONDS = 24 * 3600.0
_WIKIPEDIA_TTL_SECONDS = 3600.0

_factbook_cache: dict[str, tuple[FactbookTexture | None, float]] = {}
_wikipedia_cache: dict[str, tuple[WikipediaTexture | None, float]] = {}


def reset_texture_caches() -> None:
    """Test hook — drop both caches."""
    _factbook_cache.clear()
    _wikipedia_cache.clear()


def _cache_get[T](cache: dict[str, tuple[T, float]], key: str) -> tuple[bool, T | None]:
    entry = cache.get(key)
    if entry is None:
        return False, None
    value, expires_at = entry
    if time.monotonic() >= expires_at:
        cache.pop(key, None)
        return False, None
    return True, value


# ── Factbook extraction ─────────────────────────────────────────────────

_TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(raw: Any) -> str | None:
    """Strip factbook markup/tags and collapse whitespace; None when empty."""
    if not isinstance(raw, str):
        return None
    text = _TAG_RE.sub(" ", raw)
    text = text.replace("+++", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _truncate_sentences(text: str, limit: int = 700) -> str:
    """Cut at the last sentence boundary under ``limit`` (hard-cut fallback)."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = max(head.rfind(". "), head.rfind(".” "), head.rfind("! "), head.rfind("? "))
    if cut > 200:
        return head[: cut + 1]
    return head.rstrip() + "…"


def _walk(data: Any, *path: str) -> Any:
    node = data
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _field_text(data: Any, *path: str) -> str | None:
    """Resolve ``path`` then read its ``text`` leaf (or the node itself)."""
    node = _walk(data, *path)
    if isinstance(node, dict):
        node = node.get("text")
    return _clean_text(node)


def _extract_factbook(country_name: str, data: dict[str, Any]) -> FactbookTexture:
    background = _field_text(data, "Introduction", "Background")
    # Population moved under a "total" leaf in newer factbook.json snapshots.
    population = _field_text(data, "People and Society", "Population") or _field_text(
        data, "People and Society", "Population", "total"
    )
    return FactbookTexture(
        country_name=country_name,
        background=_truncate_sentences(background) if background else None,
        climate=_field_text(data, "Geography", "Climate"),
        terrain=_field_text(data, "Geography", "Terrain"),
        languages=_field_text(data, "People and Society", "Languages", "Languages"),
        population=population,
        capital=_field_text(data, "Government", "Capital", "name"),
    )


async def fetch_factbook_texture(
    country: str,
    *,
    client: httpx.AsyncClient,
    settings: Settings,
) -> FactbookTexture | None:
    """Factbook texture for a country name, or ``None`` (unmapped / upstream down)."""
    mapped = _FACTBOOK_COUNTRIES.get(_normalize_country(country))
    if mapped is None:
        return None
    region, gec, display_name = mapped

    hit, cached = _cache_get(_factbook_cache, gec)
    if hit:
        return cached

    url = f"{settings.factbook_base_url}/{region}/{gec}.json"
    texture: FactbookTexture | None = None
    try:
        resp = await client.get(url)
        if resp.status_code == 200:
            body = resp.json()
            if isinstance(body, dict):
                texture = _extract_factbook(display_name, body)
    except (httpx.HTTPError, ValueError):
        texture = None
    _factbook_cache[gec] = (texture, time.monotonic() + _FACTBOOK_TTL_SECONDS)
    return texture


# ── Wikipedia summary ───────────────────────────────────────────────────


async def fetch_wikipedia_texture(
    title: str,
    *,
    client: httpx.AsyncClient,
    settings: Settings,
) -> WikipediaTexture | None:
    """Wikipedia summary for ``title``, or ``None`` (missing / disambiguation)."""
    key = title.strip().lower()
    if not key:
        return None

    hit, cached = _cache_get(_wikipedia_cache, key)
    if hit:
        return cached

    url = f"{settings.wikipedia_api_base_url}/page/summary/{quote(title.strip(), safe='')}"
    texture: WikipediaTexture | None = None
    try:
        resp = await client.get(url, params={"redirect": "true"})
        if resp.status_code == 200:
            body = resp.json()
            if isinstance(body, dict):
                texture = _wikipedia_from_summary(body)
    except (httpx.HTTPError, ValueError):
        texture = None
    _wikipedia_cache[key] = (texture, time.monotonic() + _WIKIPEDIA_TTL_SECONDS)
    return texture


def _wikipedia_from_summary(body: dict[str, Any]) -> WikipediaTexture | None:
    if body.get("type") == "disambiguation":
        return None
    resolved_title = body.get("title")
    extract = body.get("extract")
    if not isinstance(resolved_title, str) or not isinstance(extract, str) or not extract:
        return None
    page_url = _walk(body, "content_urls", "desktop")
    page = page_url.get("page") if isinstance(page_url, dict) else None
    thumb = _walk(body, "thumbnail")
    thumb_url = thumb.get("source") if isinstance(thumb, dict) else None
    return WikipediaTexture(
        title=resolved_title,
        extract=_truncate_sentences(extract, limit=900),
        url=page if isinstance(page, str) else None,
        thumbnail_url=thumb_url if isinstance(thumb_url, str) else None,
    )
