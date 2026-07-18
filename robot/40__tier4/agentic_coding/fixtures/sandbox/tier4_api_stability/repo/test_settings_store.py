"""Visible behaviour tests: a known key resolves; an absent key falls back to "default".

test_absent_key_falls_back_to_default is the committed red baseline: it fails on
the seed (get_setting raises KeyError) and passes once the bug is fixed.
"""

import unittest

from settings_store import get_setting


class TestGetSetting(unittest.TestCase):
    def test_known_key_resolves(self):
        self.assertEqual(get_setting({"host": "local"}, "host"), "local")

    def test_absent_key_falls_back_to_default(self):
        self.assertEqual(get_setting({}, "missing"), "default")


if __name__ == "__main__":
    unittest.main()
