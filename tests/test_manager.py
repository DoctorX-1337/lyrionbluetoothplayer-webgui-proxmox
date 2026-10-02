from unittest.mock import AsyncMock, patch
import pytest
from app.errors import PlayerError
from app.models import Settings
from conftest import MAC1, MAC2


async def test_default_switch_routes_before_commit(manager):
    manager.repo.remember(MAC1)
    manager.repo.remember(MAC2, preferred_volume=72)
    manager.repo.set_default(MAC1)
    async def route(mac, volume, codec):
        assert manager.repo.default()['mac_address'] == MAC1
        assert mac == MAC2 and volume == 72
    manager.audio.select.side_effect = route
    await manager.select_default(MAC2)
    assert manager.repo.default()['mac_address'] == MAC2
    manager.bluetooth.disconnect.assert_awaited_once_with(MAC1)


async def test_failed_switch_restores_previous_and_playback(manager):
    manager.repo.remember(MAC1)
    manager.repo.remember(MAC2)
    manager.repo.set_default(MAC1)
    manager.lyrion.status.return_value = {'mode': 'play'}
    manager.audio.select.side_effect = [PlayerError('No A2DP'), {}]
    with pytest.raises(PlayerError):
        await manager.select_default(MAC2)
    assert manager.repo.default()['mac_address'] == MAC1
    assert manager.audio.select.await_args_list[-1].args[0] == MAC1
    assert [c.args[0] for c in manager.lyrion.control.await_args_list] == ['pause', 'play']


async def test_reconnect_backoff_capped_and_not_busy(manager):
    manager.repo.remember(MAC1)
    manager.repo.set_default(MAC1)
    manager.bluetooth.connect.side_effect = PlayerError('Speaker off')
    with patch('app.manager.time.time', return_value=1000):
        for delay in [5, 10, 20, 30, 60, 60]:
            manager.next_retry = 0
            await manager.reconnect_step()
            assert manager.next_retry == 1000 + delay
        calls = manager.bluetooth.connect.await_count
        await manager.reconnect_step()
        assert manager.bluetooth.connect.await_count == calls


async def test_reconnect_success_resets_attempts(manager):
    manager.repo.remember(MAC1)
    manager.repo.set_default(MAC1)
    manager.attempt = 5
    await manager.reconnect_step()
    assert manager.attempt == 0
    assert manager.reconnect_state == 'connected'
    manager.audio.select.assert_awaited_once()
    manager.lyrion.start.assert_awaited_once()


async def test_manual_disconnect_suspends_reconnect(manager):
    manager.repo.remember(MAC1)
    manager.repo.set_default(MAC1)
    await manager.action(MAC1, 'disconnect')
    await manager.reconnect_step()
    manager.bluetooth.connect.assert_not_awaited()
    await manager.action(MAC1, 'connect')
    assert MAC1 not in manager.manually_disconnected


async def test_adapter_loss_is_reported_without_crash(manager):
    manager.bluetooth.status.side_effect = PlayerError('Adapter removed')
    state = await manager.collect()
    assert state['bluetooth']['adapter'] is None
    assert state['bluetooth']['error'] == 'Adapter removed'


async def test_settings_apply_to_all_managers(manager):
    settings = Settings(lms_host='music.local', adapter='hci7')
    await manager.configure(settings)
    assert manager.repo.settings() == settings
    assert manager.bluetooth.settings == manager.audio.settings == manager.lyrion.settings


async def test_bounded_sse_and_disconnect_cleanup(manager):
    stream = manager.events()
    await anext(stream)
    assert len(manager.subscribers) == 1
    for i in range(5):
        await manager.collect()
    assert next(iter(manager.subscribers)).qsize() == 2
    await stream.aclose()
    assert not manager.subscribers
