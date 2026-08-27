"""app.py の SSRF 防御の単体テスト。

外部ネットワークへは接続せず、socket.getaddrinfo と requests.get を差し替えて
_validate_url / _fetch_image を直接検証する。
"""

import socket
import sys
from contextlib import contextmanager
from io import BytesIO

from fastapi import HTTPException
from PIL import Image

import app


def _addrinfo(ip):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]


@contextmanager
def _patched(obj, name, value):
    original = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, original)


def _assert_http_400(fn, label):
    try:
        fn()
    except HTTPException as e:
        if e.status_code == 400:
            return
        raise AssertionError(f"{label}: status_code={e.status_code}, expected 400") from e
    raise AssertionError(f"{label}: HTTPException(400) が発生しなかった")


def _png_bytes():
    buf = BytesIO()
    Image.new("RGB", (2, 1), (128, 32, 16)).save(buf, format="PNG")
    return buf.getvalue()


class FakeResponse:
    def __init__(self, status_code, headers=None, body=b""):
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body
        self.closed = False

    @property
    def is_redirect(self):
        return self.status_code in (301, 302, 303, 307, 308) and "Location" in self.headers

    def raise_for_status(self):
        if self.status_code >= 400:
            raise app.requests.HTTPError(f"{self.status_code} error")

    def iter_content(self, chunk_size):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

    def close(self):
        self.closed = True


def test_validate_rejects_empty_addrinfo():
    def fake_getaddrinfo(host, port):
        return []

    with _patched(app.socket, "getaddrinfo", fake_getaddrinfo):
        _assert_http_400(
            lambda: app._validate_url("https://public.example/image.png"),
            "empty addrinfo",
        )


def test_validate_rejects_unparseable_addrinfo():
    def fake_getaddrinfo(host, port):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("not-an-ip", 0)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("also-not-an-ip%en0", 0, 0, 0)),
        ]

    with _patched(app.socket, "getaddrinfo", fake_getaddrinfo):
        _assert_http_400(
            lambda: app._validate_url("https://public.example/image.png"),
            "unparseable addrinfo",
        )


def test_validate_existing_reject_cases():
    _assert_http_400(lambda: app._validate_url("file:///tmp/image.png"), "non-http scheme")
    _assert_http_400(lambda: app._validate_url("https:///image.png"), "missing host")

    def raise_gaierror(host, port):
        raise socket.gaierror("mock resolution failure")

    with _patched(app.socket, "getaddrinfo", raise_gaierror):
        _assert_http_400(
            lambda: app._validate_url("https://missing.example/image.png"),
            "socket.gaierror",
        )

    def internal_getaddrinfo(host, port):
        return _addrinfo("127.0.0.1")

    with _patched(app.socket, "getaddrinfo", internal_getaddrinfo):
        _assert_http_400(
            lambda: app._validate_url("http://127.0.0.1/image.png"),
            "direct internal IP",
        )


def test_fetch_revalidates_redirect_chain_and_blocks_internal():
    start = "https://start.example/image.png"
    mid = "https://mid.example/next.png"
    private = "http://private.example/secret.png"
    dns_calls = []
    request_calls = []

    def fake_getaddrinfo(host, port):
        dns_calls.append(host)
        if host == "start.example":
            return _addrinfo("8.8.8.8")
        if host == "mid.example":
            return _addrinfo("1.1.1.1")
        if host == "private.example":
            return _addrinfo("127.0.0.1")
        raise AssertionError(f"unexpected host: {host}")

    def fake_get(url, timeout, stream, headers, allow_redirects):
        assert timeout == app.REQUEST_TIMEOUT_SEC
        assert stream is True
        assert headers == {"User-Agent": "fibrous-lipstick-api"}
        assert allow_redirects is False
        request_calls.append(url)
        if url == start:
            return FakeResponse(302, {"Location": mid})
        if url == mid:
            return FakeResponse(302, {"Location": private})
        raise AssertionError(f"internal redirect target was fetched: {url}")

    with _patched(app.socket, "getaddrinfo", fake_getaddrinfo), _patched(app.requests, "get", fake_get):
        _assert_http_400(lambda: app._fetch_image(start), "redirect to internal IP")

    assert dns_calls == ["start.example", "mid.example", "private.example"]
    assert request_calls == [start, mid]


def test_fetch_public_to_public_redirect_returns_final_image():
    start = "https://start.example/image.png"
    final = "https://cdn.example/final.png"
    body = _png_bytes()
    request_calls = []

    def fake_getaddrinfo(host, port):
        if host == "start.example":
            return _addrinfo("8.8.8.8")
        if host == "cdn.example":
            return _addrinfo("1.1.1.1")
        raise AssertionError(f"unexpected host: {host}")

    def fake_get(url, timeout, stream, headers, allow_redirects):
        request_calls.append(url)
        assert allow_redirects is False
        if url == start:
            return FakeResponse(302, {"Location": final})
        if url == final:
            return FakeResponse(200, {"Content-Length": str(len(body))}, body)
        raise AssertionError(f"unexpected url: {url}")

    with _patched(app.socket, "getaddrinfo", fake_getaddrinfo), _patched(app.requests, "get", fake_get):
        image = app._fetch_image(start)

    assert request_calls == [start, final]
    assert image.mode == "RGB"
    assert image.size == (2, 1)


def test_fetch_rejects_too_many_redirects():
    start = "https://redirect.example/0.png"
    request_calls = []

    def fake_getaddrinfo(host, port):
        if host == "redirect.example":
            return _addrinfo("8.8.8.8")
        raise AssertionError(f"unexpected host: {host}")

    def fake_get(url, timeout, stream, headers, allow_redirects):
        request_calls.append(url)
        assert allow_redirects is False
        next_index = len(request_calls)
        return FakeResponse(302, {"Location": f"https://redirect.example/{next_index}.png"})

    with _patched(app.socket, "getaddrinfo", fake_getaddrinfo), _patched(app.requests, "get", fake_get):
        _assert_http_400(lambda: app._fetch_image(start), "too many redirects")

    assert len(request_calls) == 30


def main():
    tests = [
        test_validate_rejects_empty_addrinfo,
        test_validate_rejects_unparseable_addrinfo,
        test_validate_existing_reject_cases,
        test_fetch_revalidates_redirect_chain_and_blocks_internal,
        test_fetch_public_to_public_redirect_returns_final_image,
        test_fetch_rejects_too_many_redirects,
    ]

    failures = []
    for test in tests:
        try:
            test()
            print(f"  [OK] {test.__name__}")
        except Exception as e:
            print(f"  [NG] {test.__name__}: {e}")
            failures.append((test.__name__, e))

    print()
    if failures:
        print(f"FAIL ({len(failures)} 件)")
        sys.exit(1)
    print("PASS: 全テスト通過")


if __name__ == "__main__":
    main()
