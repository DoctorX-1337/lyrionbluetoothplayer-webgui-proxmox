import sqlite3
import pytest
from pydantic import ValidationError
from app.database import DeviceRepository
from app.models import Settings, mac_address
from conftest import MAC1, MAC2


@pytest.mark.parametrize('value', ['aa:bb:cc:dd:ee:ff', '00:11:22:33:44:55'])
def test_mac_normalized(value):
    assert mac_address(value) == value.upper()


@pytest.mark.parametrize('value', ['AA:BB:CC:DD:EE:FF;reboot', '../etc', 'AA:BB', 'GG:BB:CC:DD:EE:FF'])
def test_mac_rejects_injection(value):
    with pytest.raises(ValueError):
        mac_address(value)


@pytest.mark.parametrize('host', ['music.example', '192.0.2.20', 'lms'])
def test_lms_valid_host(host):
    assert Settings(lms_host=host).lms_host == host


@pytest.mark.parametrize('host', ['bad;reboot', '999.1.1.1', 'http://host', '-lms', 'hello\nworld', '::1', 'host:9000'])
def test_lms_invalid_host(host):
    with pytest.raises(ValidationError):
        Settings(lms_host=host)


def test_repository_persists_and_migration_is_idempotent(tmp_path):
    path = tmp_path / 'db.sqlite'
    repo = DeviceRepository(path)
    repo.remember(MAC1, 'Speaker', friendly_name='Terrasse', preferred_volume=50)
    repo.save_settings(Settings(lms_host='lms.local'))
    repo.close()
    repo = DeviceRepository(path)
    repo.migrate()
    assert repo.get(MAC1)['friendly_name'] == 'Terrasse'
    assert repo.settings().lms_host == 'lms.local'
    assert repo.db.execute('PRAGMA user_version').fetchone()[0] == 1
    repo.close()


def test_single_default_and_unknown_device_preserves_default(manager):
    repo = manager.repo
    repo.remember(MAC1)
    repo.remember(MAC2)
    repo.set_default(MAC1)
    repo.set_default(MAC2)
    assert sum(d['is_default'] for d in repo.devices()) == 1
    with pytest.raises(ValueError):
        repo.set_default('AA:BB:CC:DD:EE:03')
    assert repo.default()['mac_address'] == MAC2
    with pytest.raises(sqlite3.IntegrityError):
        with repo.db:
            repo.db.execute('UPDATE devices SET is_default=1')


def test_newer_database_rejected(tmp_path):
    path = tmp_path / 'db.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA user_version=99')
    with pytest.raises(RuntimeError):
        DeviceRepository(path)


def test_events_bounded(manager):
    for i in range(1020):
        manager.repo.event('test', str(i))
    assert manager.repo.db.execute('SELECT count(*) FROM events').fetchone()[0] == 1000
    assert len(manager.repo.events()) == 50
