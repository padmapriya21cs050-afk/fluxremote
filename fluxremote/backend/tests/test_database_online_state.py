import os
import tempfile
import unittest

from fluxremote.backend import database as db


class DatabaseOnlineStateTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="fluxremote-test-")
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir, "test.db")
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.original_db_path

    def test_update_device_status_creates_row_when_missing(self):
        db.update_device_status("missing-device", True)

        device = db.get_device("missing-device")
        self.assertIsNotNone(device)
        self.assertEqual(device["device_id"], "missing-device")
        self.assertEqual(device["is_online"], 1)

        online_devices = db.get_online_devices()
        self.assertEqual(len(online_devices), 1)
        self.assertEqual(online_devices[0]["device_id"], "missing-device")


if __name__ == "__main__":
    unittest.main()
