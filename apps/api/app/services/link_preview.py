"""Best-effort OpenGraph / meta link preview for Collection web-link cards.

A traveler (or the agent) pastes a URL — a restaurant's site, a hotel, a blog
about a hike. We fetch it and pull OpenGraph tags (``og:title`` / ``og:image``
/ ``og:description``), falling back to ``<title>`` and ``<meta
name="description">``, so the saved Collection card looks intentional rather
than a bare URL.

Every failure path degrades to ``LinkPreview(url=url, title=url)`` — a link is
always saveable even if the fetch times out, the host is unreachable, or the
page is unparseable. Parsing uses the stdlib :mod:`html.parser` (no new
dependency); only ``text/html`` responses up to a size cap are parsed.

Only ``http`` / ``https`` URLs are fetched; anything else short-circuits to the
fallback (a small guard against ``file://`` and friends).
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

import httpx

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger("ov_black.services.link_preview")

# Short timeout: a link preview must never hold up a chat turn. Match the OV
# provider's snappy budget rather than the 15s inventory providers use.
_DEFAULT_TIMEOUT = httpx.Timeout(5.0)

# Cap how much HTML we parse — OG/meta/title all live in <head>, so the first
# chunk is plenty and we avoid pulling multi-MB pages into memory.
_MAX_HTML_BYTES = 512 * 1024

# A realistic UA; some sites 403 an empty/py-httpx agent.
_USER_AGENT = "Mozilla/5.0 (compatible; OutdoorVoyageBot/1.0; +https://outdoorvoyage.com/bot)"


@dataclass(frozen=True, slots=True)
class LinkPreview:
    """Resolved preview for a pasted URL. ``title`` is never empty (falls back
    to the URL); ``image`` / ``description`` are None when the page had none."""

    url: str
    title: str
    image: str | None = None
    description: str | None = None

    def to_snapshot(self) -> dict[str, str]:
        """The legacy ``snapshot`` card shape (see ``card_mapping``), so the
        existing snapshot-reading cards render a web link like an experience.

        ``cover_image`` is the key the cards read for the hero image; ``url`` is
        carried so the card can link back out to the source.
        """
        snapshot: dict[str, str] = {"title": self.title, "url": self.url}
        if self.image:
            snapshot["cover_image"] = self.image
        if self.description:
            snapshot["description"] = self.description
        return snapshot


class _MetaParser(HTMLParser):
    """Collect OpenGraph + standard ``<meta>`` values and the first ``<title>``.

    Deliberately forgiving: unknown/malformed tags are ignored and we stop
    caring once ``</head>`` is seen (feeds may omit it, so this is best-effort).
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.og: dict[str, str] = {}
        self.meta: dict[str, str] = {}
        self.title: str | None = None
        self._in_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
            return
        if tag != "meta":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        content = a.get("content")
        if not content:
            return
        prop = a.get("property", "").lower()
        if prop.startswith("og:") and prop not in self.og:
            self.og[prop] = content
        name = a.get("name", "").lower()
        if name and name not in self.meta:
            self.meta[name] = content

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
            if self._title_parts and self.title is None:
                self.title = "".join(self._title_parts).strip() or None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)


def _extract(html: str, *, base_url: str) -> tuple[str | None, str | None, str | None]:
    """Return ``(title, image, description)`` from HTML; any may be None.

    OpenGraph wins over the plain ``<title>`` / ``<meta name=description>``.
    A relative ``og:image`` is resolved against the page URL.
    """
    parser = _MetaParser()
    # Malformed HTML must never raise past here — a link is always previewable.
    with contextlib.suppress(Exception):
        parser.feed(html)

    title = parser.og.get("og:title") or parser.title
    description = parser.og.get("og:description") or parser.meta.get("description")
    image = parser.og.get("og:image") or parser.og.get("og:image:url")
    if image:
        image = urljoin(base_url, image)
    return (
        (title.strip() or None) if title else None,
        (image.strip() or None) if image else None,
        (description.strip() or None) if description else None,
    )


def _looks_like_html(headers: Mapping[str, str]) -> bool:
    ctype = headers.get("content-type", "")
    return "html" in ctype.lower() or ctype == ""


async def fetch_link_preview(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> LinkPreview:
    """Fetch ``url`` and build a :class:`LinkPreview`; never raises.

    Follows redirects, caps the parsed body, and only parses ``text/html``.
    On any error — bad scheme, timeout, non-2xx, non-HTML, parse failure — the
    result still carries the URL with ``title=url`` so the caller can save it.
    ``client`` is injectable for tests (mirrors the inventory-provider pattern).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return LinkPreview(url=url, title=url)

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True)
    try:
        resp = await http.get(url, headers={"User-Agent": _USER_AGENT})
    except httpx.HTTPError as exc:
        logger.info("link_preview.fetch_failed", extra={"reason": exc.__class__.__name__})
        return LinkPreview(url=url, title=url)
    finally:
        if owns_client:
            await http.aclose()

    if resp.status_code >= 400 or not _looks_like_html(resp.headers):
        return LinkPreview(url=url, title=url)

    body = resp.content[:_MAX_HTML_BYTES]
    html = body.decode(resp.encoding or "utf-8", errors="replace")
    # Prefer the final URL after redirects as the base + saved url.
    final_url = str(resp.url) or url
    title, image, description = _extract(html, base_url=final_url)
    return LinkPreview(
        url=final_url,
        title=title or final_url,
        image=image,
        description=description,
    )
