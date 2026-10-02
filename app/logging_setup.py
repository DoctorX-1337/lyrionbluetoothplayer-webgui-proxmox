import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({"time": self.formatTime(record), "level": record.levelname,
                           "component": record.name, "message": record.getMessage()}, ensure_ascii=False)


def configure(path="/var/log/lyrion-bt-player"):
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    console = logging.StreamHandler()
    console.setFormatter(JsonFormatter())
    root.addHandler(console)
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        for name, logger in (("application", root), ("bluetooth", logging.getLogger("bluetooth")), ("audio", logging.getLogger("audio"))):
            handler = RotatingFileHandler(Path(path) / f"{name}.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
            handler.setFormatter(JsonFormatter())
            logger.addHandler(handler)
    except OSError:
        root.info("Dateilogs nicht verfügbar; Journal-Ausgabe bleibt aktiv")
