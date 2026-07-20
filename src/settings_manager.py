import json
import os
from enum import StrEnum, auto
from pathlib import Path

class MonoMode(StrEnum):
    sum = auto()
    left = auto()
    right = auto()
    
class NormalizeType(StrEnum):
    TP = auto()
    LUFS_I = auto()
    LUFS_M_Max = auto()

class Keys(StrEnum):
    gain = auto()
    mono_mode = auto()
    normalize_level = auto()
    normalize_type = auto()
    settings_path = auto()
    temp_path = auto()
    max_jobs = auto()

    

class _Settings():
    def __init__(self):
        self.data = {}
        self.path = Path(os.path.join(os.environ["LOCALAPPDATA"], "audio-dome-lite", "settings.json"))
        
        if self.path.exists():
            self._load_settings()
        
    def _load_settings(self):
        self.data = json.loads(self.path.read_text(encoding="utf-8"))
        
    def _save_settings(self):
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        
    def update_setting(self, key:str, new_value:str):
        if key == Keys.settings_path or key == Keys.temp_path:
            return
        self._load_settings()
        self.data[key] = new_value
        self._save_settings()
        
    def get_value(self, key:str):
        self._load_settings()
        if key in self.data:
            return self.data[key]
        return None
    
Settings = _Settings()