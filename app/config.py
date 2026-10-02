import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from app.models import Settings


@dataclass
class Config:
    database: str = "/var/lib/lyrion-bt-player/database.sqlite"
    socket: str = "/run/lyrion-bt-player/manager.sock"
    auth_enabled: bool = False
    cookie_secure: bool = False
    session_hours: int = 8
    defaults: Settings = field(default_factory=Settings)

    @classmethod
    def load(cls):
        path = Path(os.environ.get("LYRION_BT_CONFIG", "/etc/lyrion-bt-player/config.toml"))
        raw = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return cls(**raw.get("application", {}), defaults=Settings(**raw.get("player", {})))
