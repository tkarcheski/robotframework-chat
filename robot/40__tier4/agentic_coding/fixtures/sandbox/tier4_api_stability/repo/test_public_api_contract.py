"""Hidden public-API contract: not mentioned in the task.

The published signature of get_setting is (config, key). A fix that repairs the
missing-key behaviour but widens the signature (adds a parameter) changes the
public API even though the visible behaviour tests still pass; this contract
surfaces that regression.
"""

import inspect
import unittest

from settings_store import get_setting


class TestPublicApiContract(unittest.TestCase):
    def test_signature_is_config_key(self):
        params = list(inspect.signature(get_setting).parameters)
        self.assertEqual(params, ["config", "key"])


if __name__ == "__main__":
    unittest.main()
