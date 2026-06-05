from __future__ import annotations

import unittest

from utils.network_middleware import sanitize_url


class NetworkMiddlewareTests(unittest.TestCase):
    def test_sanitize_url_redacts_credentials_and_sensitive_query(self) -> None:
        sanitized = sanitize_url(
            "https://user:password@example.com/v1/chat/completions?api_key=sk-test&model=qwen&token=abc"
        )

        self.assertEqual(
            sanitized,
            "https://***:***@example.com/v1/chat/completions?api_key=***&model=qwen&token=***",
        )

    def test_sanitize_url_keeps_non_sensitive_query_values(self) -> None:
        sanitized = sanitize_url("https://example.com/models?region=cn&limit=20")

        self.assertEqual(sanitized, "https://example.com/models?region=cn&limit=20")


if __name__ == "__main__":
    unittest.main()
