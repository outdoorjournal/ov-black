"""Unit coverage for the Collection web-link preview (``fetch_link_preview``).

Drives the fetch with an injected ``httpx.AsyncClient`` backed by
``MockTransport`` (no network), proving OpenGraph wins over plain title/meta,
relative images resolve, and every failure mode degrades to a saveable
``LinkPreview(title=url)`` rather than raising.
"""

from __future__ import annotations

import httpx
import pytest
from app.services.link_preview import LinkPreview, fetch_link_preview

_OG_HTML = """
<html><head>
  <title>Fallback Title</title>
  <meta property="og:title" content="Kikunoi Kyoto" />
  <meta property="og:image" content="https://cdn.example.com/kikunoi.jpg" />
  <meta property="og:description" content="Three-Michelin-star kaiseki." />
  <meta name="description" content="ignored when og present" />
</head><body>…</body></html>
"""

_PLAIN_HTML = """
<html><head>
  <title>  Blue Bottle Kiyosumi  </title>
  <meta name="description" content="Pour-over in a converted warehouse." />
</head><body>…</body></html>
"""

_RELATIVE_IMG_HTML = """
<html><head>
  <meta property="og:title" content="Relative image" />
  <meta property="og:image" content="/assets/hero.png" />
</head></html>
"""


def _client(handler: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


async def test_parses_opengraph_tags() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=_OG_HTML)

    async with _client(handler) as client:
        preview = await fetch_link_preview("https://kikunoi.jp/", client=client)

    assert preview == LinkPreview(
        url="https://kikunoi.jp/",
        title="Kikunoi Kyoto",
        image="https://cdn.example.com/kikunoi.jpg",
        description="Three-Michelin-star kaiseki.",
    )
    # The snapshot uses the card-friendly keys the existing cards read.
    snap = preview.to_snapshot()
    assert snap["cover_image"] == "https://cdn.example.com/kikunoi.jpg"
    assert snap["url"] == "https://kikunoi.jp/"


async def test_falls_back_to_title_and_meta_description() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=_PLAIN_HTML)

    async with _client(handler) as client:
        preview = await fetch_link_preview("https://bluebottlecoffee.jp/", client=client)

    assert preview.title == "Blue Bottle Kiyosumi"  # trimmed
    assert preview.description == "Pour-over in a converted warehouse."
    assert preview.image is None


async def test_relative_og_image_resolved_against_url() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=_RELATIVE_IMG_HTML)

    async with _client(handler) as client:
        preview = await fetch_link_preview("https://example.com/spot", client=client)

    assert preview.image == "https://example.com/assets/hero.png"


async def test_non_html_content_type_falls_back_to_url() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-")

    async with _client(handler) as client:
        preview = await fetch_link_preview("https://example.com/menu.pdf", client=client)

    assert preview == LinkPreview(
        url="https://example.com/menu.pdf", title="https://example.com/menu.pdf"
    )


async def test_http_error_status_falls_back_to_url() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    async with _client(handler) as client:
        preview = await fetch_link_preview("https://example.com/", client=client)

    assert preview.title == "https://example.com/"
    assert preview.image is None


async def test_transport_error_falls_back_to_url() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=req)

    async with _client(handler) as client:
        preview = await fetch_link_preview("https://unreachable.example/", client=client)

    assert preview == LinkPreview(
        url="https://unreachable.example/", title="https://unreachable.example/"
    )


@pytest.mark.parametrize("url", ["ftp://example.com/x", "file:///etc/passwd", "not-a-url"])
async def test_non_http_scheme_never_fetches(url: str) -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        calls.append(str(req.url))
        return httpx.Response(200, text="x")

    async with _client(handler) as client:
        preview = await fetch_link_preview(url, client=client)

    assert calls == []
    assert preview == LinkPreview(url=url, title=url)
