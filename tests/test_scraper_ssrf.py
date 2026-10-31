"""SSRF regression tests for the page scraper."""

import ipaddress
import socket
from unittest.mock import AsyncMock, patch
from urllib.parse import urlparse

import httpx
import pytest

from src.web_scraper import scrape_url_content

PUBLIC_IP = "93.184.216.34"
PRIVATE_BODY = (
    b"<html><head><title>Private</title></head><body><main>"
    b"ROUTER ADMIN SECRET: internal interface listing"
    b"</main></body></html>"
)


@pytest.fixture(autouse=True)
def _no_scraper_delay():
    with patch("src.web_scraper.asyncio.sleep", new=AsyncMock()):
        yield


def _addr_info(*addresses: str) -> list[tuple]:
    infos = []
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.version == 6:
            sockaddr = (str(ip), 0, 0, 0)
            family = socket.AF_INET6
        else:
            sockaddr = (str(ip), 0)
            family = socket.AF_INET
        infos.append((family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr))
    return infos


def _patch_resolution(mapping: dict[str, list[tuple]]):
    async def _resolve(hostname: str) -> list[tuple]:
        return mapping.get(hostname, [])

    return patch("src.web_scraper._resolve_hostname", new=_resolve)


def _patch_transport(transport: httpx.MockTransport):
    real_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    return patch("src.web_scraper.httpx.AsyncClient", new=_factory)


def _html_response(body: bytes = PRIVATE_BODY) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/html; charset=utf-8", "content-length": str(len(body))},
        content=body,
    )


@pytest.mark.asyncio
async def test_redirect_to_loopback_is_refused():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "http://127.0.0.1:8080/health"})
        return _html_response()

    resolution = {
        "allowed.example": _addr_info(PUBLIC_IP),
        "127.0.0.1": _addr_info("127.0.0.1"),
    }
    with _patch_resolution(resolution), _patch_transport(httpx.MockTransport(handler)):
        result = await scrape_url_content("http://allowed.example/start")

    assert result is None, f"redirect to loopback leaked private body: {result}"


@pytest.mark.asyncio
async def test_redirect_chain_longer_than_three_is_refused():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in {"/0", "/1", "/2", "/3"}:
            next_hop = int(path[1:]) + 1
            return httpx.Response(302, headers={"location": f"/{next_hop}"})
        return _html_response()

    with (
        _patch_resolution({"allowed.example": _addr_info(PUBLIC_IP)}),
        _patch_transport(httpx.MockTransport(handler)),
    ):
        result = await scrape_url_content("http://allowed.example/0")

    assert result is None, f"redirect chain longer than 3 hops was followed: {result}"


@pytest.mark.asyncio
async def test_direct_call_to_loopback_is_refused():
    contacted = []

    def handler(request: httpx.Request) -> httpx.Response:
        contacted.append(request.url)
        return _html_response()

    with (
        _patch_resolution({"127.0.0.1": _addr_info("127.0.0.1")}),
        _patch_transport(httpx.MockTransport(handler)),
    ):
        result = await scrape_url_content("http://127.0.0.1:8080/health")

    assert result is None, f"direct scrape of loopback leaked private body: {result}"
    assert contacted == []


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://100.64.0.1/",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[fe80::1]/",
        "http://[fc00::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:10.0.0.5]/",
        "http://[::ffff:100.64.0.1]/",
    ],
)
@pytest.mark.asyncio
async def test_non_global_addresses_are_refused(url: str):
    contacted = []

    def handler(request: httpx.Request) -> httpx.Response:
        contacted.append(request.url)
        return _html_response()

    hostname = urlparse(url).hostname
    with (
        _patch_resolution({hostname: _addr_info(hostname)}),
        _patch_transport(httpx.MockTransport(handler)),
    ):
        result = await scrape_url_content(url)

    assert result is None, f"non-global address was scraped: {result}"
    assert contacted == []


@pytest.mark.parametrize(
    "addresses",
    [
        (PUBLIC_IP, "10.0.0.5"),
        ("10.0.0.5", PUBLIC_IP),
    ],
)
@pytest.mark.asyncio
async def test_mixed_global_and_private_resolution_is_refused(addresses: tuple[str, ...]):
    contacted = []

    def handler(request: httpx.Request) -> httpx.Response:
        contacted.append(request.url)
        return _html_response()

    with (
        _patch_resolution({"mixed.example": _addr_info(*addresses)}),
        _patch_transport(httpx.MockTransport(handler)),
    ):
        result = await scrape_url_content("http://mixed.example/article")

    assert result is None, f"mixed public/private DNS answer was scraped: {result}"
    assert contacted == []


@pytest.mark.asyncio
async def test_public_url_still_scrapes_successfully():
    body = (
        b"<html><head><title>Public Article</title></head><body><main>"
        b"This is a sufficiently long public article body used to verify that the "
        b"SSRF hardening still permits ordinary scraping to work correctly."
        b"</main></body></html>"
    )
    contacted = []

    def handler(request: httpx.Request) -> httpx.Response:
        contacted.append(request)
        return _html_response(body)

    with (
        _patch_resolution({"public.example": _addr_info(PUBLIC_IP)}),
        _patch_transport(httpx.MockTransport(handler)),
    ):
        result = await scrape_url_content("http://public.example/article")

    assert result is not None
    assert "Title: Public Article" in result
    assert contacted


@pytest.mark.asyncio
async def test_https_request_keeps_original_hostname_for_tls():
    body = (
        b"<html><head><title>Secure Article</title></head><body><main>"
        b"This is a sufficiently long secure article body used to verify that the "
        b"scraper does not pin HTTPS connections to a bare IP address."
        b"</main></body></html>"
    )
    contacted = []

    def handler(request: httpx.Request) -> httpx.Response:
        contacted.append(request)
        return _html_response(body)

    with (
        _patch_resolution({"secure.example": _addr_info(PUBLIC_IP)}),
        _patch_transport(httpx.MockTransport(handler)),
    ):
        result = await scrape_url_content("https://secure.example/article")

    assert result is not None
    assert "Title: Secure Article" in result
    assert contacted[0].url.host == "secure.example"
