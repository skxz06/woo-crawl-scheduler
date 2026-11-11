import sys
import unittest
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worker import AccessDenied, ContractBroken, classify_response


class Response:
    def __init__(self, status_code, content_type="application/json"):
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FailurePolicyTest(unittest.TestCase):
    def test_access_denied_does_not_use_browser(self):
        with self.assertRaises(AccessDenied):
            classify_response(Response(403))

    def test_missing_json_is_a_contract_failure(self):
        with self.assertRaises(ContractBroken):
            classify_response(Response(404))

    def test_rate_limit_stays_retryable(self):
        with self.assertRaises(requests.HTTPError):
            classify_response(Response(429))


if __name__ == "__main__":
    unittest.main()
