import tempfile
import unittest
from pathlib import Path
from sboc.security import Store

class UserSettingsTests(unittest.TestCase):
    def test_password_and_language_survive_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'events.sqlite3'
            store=Store(db)
            store.setup('admin','old-password-123',store.setup_code())
            token=store.login('admin','old-password-123')
            self.assertEqual(store.language('admin'),'en')
            store.set_language('admin','de')
            with self.assertRaises(ValueError):store.set_language('admin','fr')
            with self.assertRaises(ValueError):store.change_password('admin','wrong','new-password-123','new-password-123')
            self.assertEqual(store.user(token),'admin')
            store.change_password('admin','old-password-123','new-password-123','new-password-123')
            self.assertIsNone(store.user(token))
            self.assertIsNone(store.login('admin','old-password-123'))
            self.assertIsNotNone(store.login('admin','new-password-123'))
            self.assertEqual(Store(db).language('admin'),'de')
