import unittest

from fluxremote.backend.tunnel_auth import extract_ws_auth_token, is_ws_request_authorized


class TunnelAuthTests(unittest.TestCase):
    def test_extracts_token_from_query_params(self):
        self.assertEqual(extract_ws_auth_token({"token": "abc123"}), "abc123")
        self.assertEqual(extract_ws_auth_token({"auth_token": "abc123"}), "abc123")
        self.assertEqual(extract_ws_auth_token({"session_token": "abc123"}), "abc123")

    def test_requires_matching_token_when_configured(self):
        self.assertTrue(is_ws_request_authorized({"token": "abc123"}, "abc123"))
        self.assertFalse(is_ws_request_authorized({"token": "wrong"}, "abc123"))
        self.assertTrue(is_ws_request_authorized({}, None))


if __name__ == "__main__":
    unittest.main()
