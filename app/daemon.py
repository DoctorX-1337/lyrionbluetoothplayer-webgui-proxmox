import os
from pathlib import Path
import uvicorn
from app.config import Config
from app.internal_api import manager_app
from app.logging_setup import configure
from app.manager import PlayerManager


def main():
    configure()
    config = Config.load()
    path = Path(config.socket)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.umask(0o077)
    uvicorn.run(manager_app(PlayerManager(config)), uds=str(path), access_log=False, log_level="warning", timeout_graceful_shutdown=5)


if __name__ == "__main__":
    main()
