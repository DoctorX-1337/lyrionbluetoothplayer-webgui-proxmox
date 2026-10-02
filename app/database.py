import json
import sqlite3
import time
from pathlib import Path
from app.models import Settings, mac_address


class DeviceRepository:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.migrate()

    def migrate(self):
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            raise RuntimeError("Datenbank ist neuer als diese Anwendung")
        if version == 0:
            self.db.executescript('''
            BEGIN;
            CREATE TABLE devices (
              mac_address TEXT PRIMARY KEY, bluetooth_name TEXT NOT NULL DEFAULT '',
              friendly_name TEXT NOT NULL DEFAULT '', auto_connect INTEGER NOT NULL DEFAULT 1,
              preferred_volume INTEGER NOT NULL DEFAULT 35, is_default INTEGER NOT NULL DEFAULT 0,
              preferred_profile TEXT NOT NULL DEFAULT 'a2dp', preferred_codec TEXT NOT NULL DEFAULT 'auto',
              created_at REAL NOT NULL, updated_at REAL NOT NULL);
            CREATE UNIQUE INDEX one_default ON devices(is_default) WHERE is_default=1;
            CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE events(id INTEGER PRIMARY KEY, timestamp REAL NOT NULL, type TEXT NOT NULL,
                                device TEXT, message TEXT NOT NULL);
            CREATE TABLE auth(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE sessions(token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL);
            PRAGMA user_version=1;
            COMMIT;
            ''')

    def devices(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM devices ORDER BY is_default DESC, friendly_name, bluetooth_name")]

    def get(self, mac):
        row = self.db.execute("SELECT * FROM devices WHERE mac_address=?", (mac_address(mac),)).fetchone()
        return dict(row) if row else None

    def remember(self, mac, name="", **fields):
        mac = mac_address(mac)
        allowed = {"friendly_name", "auto_connect", "preferred_volume", "preferred_profile", "preferred_codec"}
        if fields.keys() - allowed:
            raise ValueError("Unbekannte Gerätefelder")
        with self.db:
            self.db.execute("INSERT INTO devices(mac_address,bluetooth_name,created_at,updated_at) VALUES (?,?,?,?) ON CONFLICT(mac_address) DO UPDATE SET bluetooth_name=CASE WHEN excluded.bluetooth_name='' THEN devices.bluetooth_name ELSE excluded.bluetooth_name END,updated_at=excluded.updated_at", (mac, name, time.time(), time.time()))
            for key, value in fields.items():
                self.db.execute(f"UPDATE devices SET {key}=?,updated_at=? WHERE mac_address=?", (value, time.time(), mac))
        return self.get(mac)

    def set_default(self, mac):
        mac = mac_address(mac)
        if not self.get(mac):
            raise ValueError("Gerät ist nicht gespeichert")
        with self.db:
            self.db.execute("UPDATE devices SET is_default=0")
            self.db.execute("UPDATE devices SET is_default=1,updated_at=? WHERE mac_address=?", (time.time(), mac))

    def default(self):
        row = self.db.execute("SELECT * FROM devices WHERE is_default=1").fetchone()
        return dict(row) if row else None

    def remove(self, mac):
        with self.db:
            self.db.execute("DELETE FROM devices WHERE mac_address=?", (mac_address(mac),))

    def settings(self, defaults=None):
        values = defaults.model_dump() if defaults else {}
        values.update({r["key"]: json.loads(r["value"]) for r in self.db.execute("SELECT * FROM settings")})
        return Settings(**values)

    def save_settings(self, settings):
        with self.db:
            self.db.executemany("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", [(k, json.dumps(v)) for k, v in settings.model_dump().items()])

    def event(self, kind, message, device=None):
        with self.db:
            self.db.execute("INSERT INTO events(timestamp,type,device,message) VALUES (?,?,?,?)", (time.time(), kind, device, message))
            self.db.execute("DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 1000)")

    def events(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 50")]

    def close(self):
        self.db.close()
