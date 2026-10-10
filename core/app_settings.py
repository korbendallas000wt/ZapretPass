import json
import re
import tempfile
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any

DEFAULT_REGION = "RU"

DEFAULT_SETTINGS = {
    "schema_version": 1,
    "region": DEFAULT_REGION,
    "white_hosts": {
        "RU": ["ozon.ru", "vk.com", "yandex.ru"],
        "BY": ["onliner.by", "vk.com"],
        "IR": ["digikala.com"],
        "CN": ["taobao.com"],
        "default": ["ozon.ru"]
    },
    "timeouts": {
        "dns": 5,
        "tls": 8,
        "http_head": 8,
        "http_get": 20,
        "resource_validation": 20,
        "blockcheck": 180,
        "service_restart": 15
    },
    "blockcheck": {
        "scanlevel": "quick",
        "repeats": 4,
        "enable_http": True,
        "enable_https_tls12": False,
        "enable_https_tls13": True,
        "enable_http3": True
    },
    "validation": {
        "max_critical_assets": 8,
        "min_successful_bytes": 1024,
        "allow_partial_screenshot": False
    }
}

def _deep_merge(defaults: Dict, loaded: Dict) -> Dict:
    """Рекурсивно объединяет loaded в defaults."""
    result = dict(defaults)
    for key, value in loaded.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result

class AppSettings:
    """Изолированный менеджер настроек приложения."""
    
    def __init__(self, config_path: Optional[str | Path] = None):
        if config_path is None:
            self._config_path = Path(__file__).resolve().parents[1] / "data" / "config.json"
        else:
            self._config_path = Path(config_path)
        self._data: Dict[str, Any] = {}
    
    @property
    def config_path(self) -> Path:
        return self._config_path
    
    def load(self, *, create_if_missing: bool = True) -> Dict[str, Any]:
        """Загружает настройки из JSON."""
        try:
            if not self._config_path.exists():
                if create_if_missing:
                    self._data = dict(DEFAULT_SETTINGS)
                    self.save(self._data)
                    return dict(self._data)
                else:
                    return dict(DEFAULT_SETTINGS)
            
            try:
                with open(self._config_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                if not isinstance(loaded, dict):
                    loaded = {}
            except (json.JSONDecodeError, ValueError):
                # Corrupt JSON - backup and recreate
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                corrupt_path = self._config_path.with_name(f"{self._config_path.name}.corrupt.{timestamp}")
                try:
                    os.rename(self._config_path, corrupt_path)
                except Exception:
                    pass
                self._data = dict(DEFAULT_SETTINGS)
                self.save(self._data)
                return dict(self._data)
            
            # Merge loaded into defaults
            self._data = _deep_merge(dict(DEFAULT_SETTINGS), loaded)
            self.save(self._data)
            return dict(self._data)
            
        except Exception:
            self._data = dict(DEFAULT_SETTINGS)
            return dict(self._data)
    
    def save(self, data: Optional[Dict[str, Any]] = None) -> None:
        """Атомарно сохраняет настройки."""
        try:
            if data is not None:
                self._data = dict(data)
            
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=str(self._config_path.parent),
                delete=False
            ) as tmp:
                tmp_path = tmp.name
                json.dump(self._data, tmp, ensure_ascii=False, indent=2)
                tmp.flush()
                os.fsync(tmp.fileno())
            
            os.replace(tmp_path, self._config_path)
        except Exception:
            # Try to clean up temp file if it exists
            try:
                if 'tmp_path' in locals():
                    os.unlink(tmp_path)
            except Exception:
                pass
    
    def get_region(self) -> str:
        """Возвращает текущий region."""
        try:
            region = self._data.get("region", DEFAULT_REGION)
            return region if region else DEFAULT_REGION
        except Exception:
            return DEFAULT_REGION
    
    def set_region(self, region: str) -> bool:
        """Устанавливает region."""
        try:
            if not region or not isinstance(region, str):
                return False
            region = region.strip()
            if not region or ' ' in region or len(region) > 64:
                return False
            
            # Normalize: upper-case except "default"
            if region.lower() == "default":
                normalized = "default"
            else:
                normalized = region.upper()
            
            self._data["region"] = normalized
            self.save()
            return True
        except Exception:
            return False
    
    def get_white_hosts(self, region: Optional[str] = None) -> List[str]:
        """Возвращает список белых хостов для региона."""
        try:
            if region is None:
                region = self.get_region()
            
            white_hosts = self._data.get("white_hosts", {})
            hosts = white_hosts.get(region, [])
            
            if not hosts:
                hosts = white_hosts.get("default", [])
            
            return list(hosts) if hosts else []
        except Exception:
            return []
    
    def get_first_white_host(self, region: Optional[str] = None) -> str:
        """Возвращает первый белый хост для региона."""
        hosts = self.get_white_hosts(region)
        if not hosts:
            raise ValueError("no_white_hosts")
        return hosts[0]
    
    def add_white_host(self, region: str, host: str) -> bool:
        """Добавляет белый хост в регион."""
        try:
            if not region or not host:
                return False
            
            host = host.strip().lower()
            if not host:
                return False
            
            # Validate host
            if ' ' in host or '\t' in host or '\n' in host:
                return False
            if len(host) > 253:
                return False
            if not re.match(r'^[A-Za-z0-9._-]+$', host):
                return False
            if host != "localhost" and '.' not in host:
                return False
            
            # Normalize region
            if region.lower() == "default":
                region_normalized = "default"
            else:
                region_normalized = region.upper()
            
            # Get current list
            white_hosts = self._data.setdefault("white_hosts", {})
            current = white_hosts.get(region_normalized, [])
            
            if host in current:
                return False
            
            current.append(host)
            white_hosts[region_normalized] = current
            self.save()
            return True
        except Exception:
            return False
    
    def remove_white_host(self, region: str, host: str) -> bool:
        """Удаляет белый хост из региона."""
        try:
            if not region or not host:
                return False
            
            host = host.strip().lower()
            if not host:
                return False
            
            # Normalize region
            if region.lower() == "default":
                region_normalized = "default"
            else:
                region_normalized = region.upper()
            
            white_hosts = self._data.get("white_hosts", {})
            current = white_hosts.get(region_normalized, [])
            
            if host not in current:
                return False
            
            current.remove(host)
            white_hosts[region_normalized] = current
            self.save()
            return True
        except Exception:
            return False
    
    def get_timeout(self, name: str, default: int = 10) -> int:
        """Возвращает таймаут по имени."""
        try:
            timeouts = self._data.get("timeouts", {})
            value = timeouts.get(name)
            if value is None:
                return default
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                return int(value)
            if isinstance(value, str):
                return int(value)
            return default
        except Exception:
            return default
    
    def get_blockcheck_settings(self) -> Dict[str, Any]:
        """Возвращает копию секции blockcheck."""
        try:
            return dict(self._data.get("blockcheck", DEFAULT_SETTINGS["blockcheck"]))
        except Exception:
            return dict(DEFAULT_SETTINGS["blockcheck"])
    
    def get_validation_settings(self) -> Dict[str, Any]:
        """Возвращает копию секции validation."""
        try:
            return dict(self._data.get("validation", DEFAULT_SETTINGS["validation"]))
        except Exception:
            return dict(DEFAULT_SETTINGS["validation"])
