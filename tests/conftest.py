from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.config import Config
from app.manager import PlayerManager

MAC1 = 'AA:BB:CC:DD:EE:01'
MAC2 = 'AA:BB:CC:DD:EE:02'


@pytest.fixture
def manager(tmp_path):
    config = Config(database=str(tmp_path / 'player.sqlite'), auth_enabled=True)
    bluetooth = SimpleNamespace(
        status=AsyncMock(return_value={'adapter': {'id': 'hci7', 'Powered': True}, 'adapters': [], 'devices': [], 'scanning': False}),
        connect=AsyncMock(), disconnect=AsyncMock(), remove=AsyncMock(), trust=AsyncMock(), powered=AsyncMock(), scan=AsyncMock(),
        pair=AsyncMock(), close=AsyncMock(), agent=SimpleNamespace(pending=lambda: []), pair_results={})
    audio = SimpleNamespace(status=AsyncMock(return_value={'sink': None, 'available': True}),
                            select=AsyncMock(), sink_for=AsyncMock(return_value=None), volume=AsyncMock(return_value=40), test=AsyncMock())
    lyrion = SimpleNamespace(status=AsyncMock(return_value={'mode': 'stop'}), start=AsyncMock(), stop=AsyncMock(), control=AsyncMock(), restart=AsyncMock())
    system = SimpleNamespace(status=AsyncMock(return_value={'hostname':'test'}), services=AsyncMock(return_value={}))
    manager = PlayerManager(config, bluetooth, audio, lyrion, system)
    yield manager
    manager.repo.close()
