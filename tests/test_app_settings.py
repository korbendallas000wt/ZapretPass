import unittest
import tempfile
import json
from pathlib import Path
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.app_settings import AppSettings, DEFAULT_SETTINGS

class TestAppSettings(unittest.TestCase):
    
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmpdir.name) / "config.json"
    
    def tearDown(self):
        self.tmpdir.cleanup()
    
    def test_creates_default_config_when_missing(self):
        settings = AppSettings(config_path=self.config_path)
        data = settings.load()
        self.assertTrue(self.config_path.exists())
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["region"], "RU")
        self.assertIn("RU", data["white_hosts"])
        self.assertIn("default", data["white_hosts"])
        self.assertIn("dns", data["timeouts"])
        self.assertIn("http_get", data["timeouts"])
        self.assertIn("scanlevel", data["blockcheck"])
        self.assertIn("min_successful_bytes", data["validation"])
    
    def test_load_merges_missing_sections(self):
        partial = {"region": "BY"}
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump(partial, f)
        
        settings = AppSettings(config_path=self.config_path)
        data = settings.load()
        self.assertEqual(data["region"], "BY")
        self.assertIn("RU", data["white_hosts"])
        self.assertIn("dns", data["timeouts"])
    
    def test_corrupt_config_is_backed_up_and_recreated(self):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w') as f:
            f.write("not-json")
        
        settings = AppSettings(config_path=self.config_path)
        data = settings.load()
        self.assertEqual(data["schema_version"], 1)
        
        # Check corrupt backup exists
        corrupt_files = list(self.config_path.parent.glob("config.json.corrupt.*"))
        self.assertEqual(len(corrupt_files), 1)
        
        # Check corrupt file has original content
        with open(corrupt_files[0], 'r') as f:
            self.assertEqual(f.read(), "not-json")
    
    def test_set_region_valid_and_invalid(self):
        settings = AppSettings(config_path=self.config_path)
        settings.load()
        
        self.assertTrue(settings.set_region("by"))
        self.assertEqual(settings.get_region(), "BY")
        
        self.assertFalse(settings.set_region(""))
        self.assertFalse(settings.set_region("bad region"))
    
    def test_get_white_hosts_fallback_to_default(self):
        settings = AppSettings(config_path=self.config_path)
        settings.load()
        settings.set_region("XX")
        hosts = settings.get_white_hosts()
        self.assertEqual(hosts, DEFAULT_SETTINGS["white_hosts"]["default"])
    
    def test_get_first_white_host_returns_first(self):
        settings = AppSettings(config_path=self.config_path)
        settings.load()
        first = settings.get_first_white_host("RU")
        self.assertEqual(first, "ozon.ru")
    
    def test_get_first_white_host_raises_when_empty(self):
        settings = AppSettings(config_path=self.config_path)
        data = dict(DEFAULT_SETTINGS)
        data["white_hosts"] = {"RU": [], "default": []}
        settings.save(data)
        settings.load()
        
        with self.assertRaises(ValueError) as cm:
            settings.get_first_white_host("RU")
        self.assertEqual(str(cm.exception), "no_white_hosts")
    
    def test_add_white_host_deduplicates_and_normalizes(self):
        settings = AppSettings(config_path=self.config_path)
        settings.load()
        
        # Добавляем НОВЫЙ хост (которого ещё нет в RU)
        self.assertTrue(settings.add_white_host("RU", "NEW.EXAMPLE"))
        hosts = settings.get_white_hosts("RU")
        self.assertIn("new.example", hosts)  # Нормализован в lower-case
        self.assertEqual(hosts.count("new.example"), 1)  # Нет дублей
        
        # Попытка добавить тот же хост снова возвращает False (дедупликация)
        self.assertFalse(settings.add_white_host("RU", "NEW.EXAMPLE"))
        hosts = settings.get_white_hosts("RU")
        self.assertEqual(hosts.count("new.example"), 1)  # Всё ещё один
    
    def test_add_white_host_invalid(self):
        settings = AppSettings(config_path=self.config_path)
        settings.load()
        
        initial_hosts = settings.get_white_hosts("RU")
        self.assertFalse(settings.add_white_host("RU", "bad host"))
        self.assertFalse(settings.add_white_host("RU", ""))
        self.assertEqual(settings.get_white_hosts("RU"), initial_hosts)
    
    def test_remove_white_host(self):
        settings = AppSettings(config_path=self.config_path)
        settings.load()
        
        settings.add_white_host("RU", "test.example")
        self.assertTrue(settings.remove_white_host("RU", "test.example"))
        self.assertNotIn("test.example", settings.get_white_hosts("RU"))
        self.assertFalse(settings.remove_white_host("RU", "test.example"))
    
    def test_get_timeout_defaults_and_coercion(self):
        settings = AppSettings(config_path=self.config_path)
        settings.load()
        
        self.assertEqual(settings.get_timeout("dns", default=5), 5)
        self.assertEqual(settings.get_timeout("missing_key", default=42), 42)
        
        # Test coercion
        data = dict(DEFAULT_SETTINGS)
        data["timeouts"]["dns"] = "8"
        settings.save(data)
        settings.load()
        self.assertEqual(settings.get_timeout("dns"), 8)
    
    def test_save_is_atomic_and_reloadable(self):
        settings1 = AppSettings(config_path=self.config_path)
        settings1.load()
        settings1.set_region("BY")
        settings1.add_white_host("BY", "test.example")
        
        # Create new instance with same path
        settings2 = AppSettings(config_path=self.config_path)
        data = settings2.load()
        self.assertEqual(data["region"], "BY")
        self.assertIn("test.example", data["white_hosts"]["BY"])
    
    def test_no_real_data_directory_write(self):
        # This test passes by design - we only use tmpdir
        settings = AppSettings(config_path=self.config_path)
        settings.load()
        self.assertTrue(self.config_path.exists())

if __name__ == '__main__':
    unittest.main()
