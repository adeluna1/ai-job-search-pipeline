"""Trust-boundary and extraction tests for the original MIT web intelligence layer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from job_pipeline.web_intelligence import (
    DnsPinError,
    FetchLimits,
    HttpResponse,
    ResponseTooLargeError,
    SafeUrlPolicy,
    UnsafeContentTypeError,
    UnsafeUrlError,
    WebCache,
    WebIntelligence,
)


PUBLIC_IP = "93.184.216.34"


class FakeTransport:
    """Return controlled HTTP responses without network access."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, url, *, timeout_seconds, max_bytes, pinned_addresses):
        self.calls.append((url, timeout_seconds, max_bytes, tuple(pinned_addresses)))
        response = self.responses[url]
        return response() if callable(response) else response


def response(url, body, *, status=200, headers=None, peer_ip=PUBLIC_IP):
    return HttpResponse(
        url=url,
        status=status,
        headers=headers or {"content-type": "text/html; charset=utf-8"},
        body=body.encode("utf-8") if isinstance(body, str) else body,
        peer_ip=peer_ip,
    )


class WebIntelligenceTests(unittest.TestCase):
    """Cover SSRF defenses, redirects, limits, cache, extraction, and crawling."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.cache = WebCache(Path(self.temp.name) / "web-cache.sqlite3")
        self.resolver_calls = []

        def resolver(host):
            self.resolver_calls.append(host)
            return [PUBLIC_IP]

        self.policy = SafeUrlPolicy(resolver=resolver)

    def tearDown(self) -> None:
        self.cache.close()
        self.temp.cleanup()

    def test_private_link_local_userinfo_and_non_http_urls_are_rejected(self) -> None:
        for url in (
            "http://127.0.0.1/admin",
            "http://169.254.169.254/latest/meta-data",
            "http://[::1]/",
            "https://user:secret" + "@" + "example.test/",
            "file:///C:/Windows/System32/config",
        ):
            with self.subTest(url=url), self.assertRaises(UnsafeUrlError):
                self.policy.resolve(url)

    def test_redirect_target_is_revalidated_before_following(self) -> None:
        start = "https://public.test/start"
        transport = FakeTransport({
            start: response(
                start,
                "",
                status=302,
                headers={"location": "http://127.0.0.1/private", "content-type": "text/html"},
            )
        })
        client = WebIntelligence(policy=self.policy, transport=transport, cache=self.cache)
        with self.assertRaises(UnsafeUrlError):
            client.fetch(start)
        self.assertEqual(len(transport.calls), 1)

    def test_connected_peer_must_match_the_validated_dns_answers(self) -> None:
        url = "https://public.test/page"
        transport = FakeTransport({url: response(url, "hello", peer_ip="8.8.8.8")})
        client = WebIntelligence(policy=self.policy, transport=transport, cache=self.cache)
        with self.assertRaises(DnsPinError):
            client.fetch(url)

    def test_content_length_streamed_bytes_and_mime_type_are_bounded(self) -> None:
        limits = FetchLimits(max_bytes=64)
        too_large_header = "https://public.test/header"
        too_large_body = "https://public.test/body"
        binary = "https://public.test/image"
        transport = FakeTransport({
            too_large_header: response(
                too_large_header,
                b"small",
                headers={"content-type": "text/html", "content-length": "2048"},
            ),
            too_large_body: response(too_large_body, b"x" * 65),
            binary: response(binary, b"PNG", headers={"content-type": "image/png"}),
        })
        client = WebIntelligence(
            policy=self.policy, transport=transport, cache=self.cache, limits=limits
        )
        with self.assertRaises(ResponseTooLargeError):
            client.fetch(too_large_header)
        with self.assertRaises(ResponseTooLargeError):
            client.fetch(too_large_body)
        with self.assertRaises(UnsafeContentTypeError):
            client.fetch(binary)

    def test_extract_links_challenge_and_robots_signals_are_structured(self) -> None:
        url = "https://public.test/jobs/42"
        html = """
        <html><head><title>Recruiting Coordinator</title>
        <meta name="description" content="Coordinate interviews">
        <meta name="robots" content="noindex,nofollow"></head>
        <body><h1>Recruiting Coordinator</h1>
        <p>Verify you are human before continuing.</p>
        <a href="/apply/42">Apply</a><script>ignore()</script></body></html>
        """
        client = WebIntelligence(
            policy=self.policy,
            transport=FakeTransport({url: response(url, html)}),
            cache=self.cache,
        )
        document = client.fetch(url)
        fields = client.extract(
            document,
            {
                "role": "title",
                "summary": "meta:description",
                "heading": "heading:h1",
                "human_check": "regex:verify you are human",
            },
        )
        self.assertEqual(fields["role"], "Recruiting Coordinator")
        self.assertEqual(fields["summary"], "Coordinate interviews")
        self.assertEqual(fields["heading"], "Recruiting Coordinator")
        self.assertEqual(fields["human_check"].casefold(), "verify you are human")
        self.assertEqual(client.links(document), ["https://public.test/apply/42"])
        self.assertTrue(document.challenge_detected)
        self.assertEqual(document.robots, "noindex,nofollow")
        self.assertNotIn("ignore()", document.text)

    def test_fresh_cache_avoids_a_second_transport_call(self) -> None:
        url = "https://public.test/cache"
        transport = FakeTransport({url: response(url, "<p>cached page</p>")})
        client = WebIntelligence(policy=self.policy, transport=transport, cache=self.cache)
        first = client.fetch(url, freshness_seconds=60)
        second = client.fetch(url, freshness_seconds=60)
        self.assertEqual(first.text, second.text)
        self.assertEqual(len(transport.calls), 1)
        self.assertTrue(second.from_cache)

    def test_crawl_obeys_depth_page_and_same_site_limits(self) -> None:
        start = "https://public.test/start"
        one = "https://public.test/one"
        two = "https://public.test/two"
        external = "https://external.test/out"
        transport = FakeTransport({
            start: response(
                start,
                '<a href="/one">one</a><a href="/two">two</a>'
                '<a href="https://external.test/out">outside</a>',
            ),
            one: response(one, "<p>one</p>"),
            two: response(two, "<p>two</p>"),
            external: response(external, "<p>outside</p>"),
        })
        client = WebIntelligence(
            policy=self.policy,
            transport=transport,
            cache=self.cache,
            limits=FetchLimits(max_pages=2, max_depth=1),
        )
        documents = client.crawl(start, same_site=True)
        self.assertEqual([item.url for item in documents], [start, one])
        self.assertEqual([call[0] for call in transport.calls], [start, one])


if __name__ == "__main__":
    unittest.main()
