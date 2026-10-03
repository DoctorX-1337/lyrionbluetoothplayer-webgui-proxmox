import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from dbus_next import DBusError
from app.audio import AudioManager
from app.bluetooth import BluetoothManager, PairingAgent
from app.errors import PlayerError
from app.models import Settings
from app.lyrion import LyrionManager
from types import SimpleNamespace
from conftest import MAC1


def test_dynamic_adapter_selection():
    bt = BluetoothManager(Settings(adapter='AA:BB:CC:DD:EE:01'))
    objects = {'/org/bluez/hci7':{'org.bluez.Adapter1':{'Address':MAC1}}, '/org/bluez/hci0':{'org.bluez.Adapter1':{'Address':'AA:BB:CC:DD:EE:02'}}}
    assert bt.selected_adapter(objects)[0] == '/org/bluez/hci7'
    bt.settings.adapter = 'hci5'
    with pytest.raises(PlayerError):
        bt.selected_adapter(objects)


async def test_pairing_confirmation_and_rejection():
    agent = PairingAgent()
    path = '/org/bluez/hci7/dev_AA_BB_CC_DD_EE_01'
    with pytest.raises(DBusError):
        await agent.prompt(path, 'confirmation')
    agent.allowed.add(path)
    task = asyncio.create_task(agent.prompt(path, 'confirmation', '123456'))
    await asyncio.sleep(0)
    request = agent.pending()[0]
    assert request['code'] == '123456' and 'future' not in request
    agent.answer(request['id'], True, '')
    assert await task == ''
    task = asyncio.create_task(agent.prompt(path, 'pin'))
    await asyncio.sleep(0)
    request = agent.pending()[0]
    with pytest.raises(PlayerError):
        agent.answer(request['id'], True, '../bad')
    agent.answer(request['id'], False, '')
    with pytest.raises(DBusError):
        await task


async def test_audio_routes_all_existing_streams_and_limits_volume():
    audio = AudioManager(Settings(max_volume=50))
    audio.activate_profile = AsyncMock()
    audio.sink_for = AsyncMock(return_value={'name':'bluez_output_test'})
    audio.list = AsyncMock(return_value=[{'index': 7}, {'index': 9}])
    with patch('app.audio.command', new_callable=AsyncMock) as call:
        await audio.select(MAC1, 90)
        args = [entry.args for entry in call.await_args_list]
        assert ('pactl', 'set-default-sink', 'bluez_output_test') in args
        assert ('pactl', 'set-sink-volume', 'bluez_output_test', '50%') in args
        assert ('pactl', 'move-sink-input', '7', 'bluez_output_test') in args
        assert ('pactl', 'move-sink-input', '9', 'bluez_output_test') in args


async def test_codec_fallback_uses_available_a2dp():
    audio = AudioManager(Settings())
    audio.list = AsyncMock(return_value=[{'index':1,'name':'bluez_card_AA_BB_CC_DD_EE_01','profiles':{'a2dp-sink-sbc':{'available':'yes'},'a2dp-sink-aac':{'available':'no'}}}])
    with patch('app.audio.command', new_callable=AsyncMock) as call:
        await audio.activate_profile(MAC1, 'aac')
        call.assert_awaited_with('pactl', 'set-card-profile', '1', 'a2dp-sink-sbc')


async def test_testtone_requires_target_sink():
    audio = AudioManager(Settings())
    audio.sink_for = AsyncMock(return_value=None)
    with pytest.raises(PlayerError):
        await audio.test(MAC1)


async def test_idle_dummy_sink_is_not_an_audio_output():
    audio = AudioManager(Settings())
    audio.list = AsyncMock(return_value=[{'name': 'auto_null', 'state': 'IDLE',
        'volume': {'mono': {'value': 65536}}}])
    with patch('app.audio.command', new_callable=AsyncMock, return_value='auto_null\n'):
        result = await audio.status()
    assert result['available'] is True
    assert result['sink'] is None and result['volume'] is None
    assert result['sinks'] == [] and result['a2dp'] is False


async def test_scan_restart_does_not_lose_discovery_session():
    bt=BluetoothManager(Settings())
    bt.settings=SimpleNamespace(scan_duration=.02,adapter='auto')
    bt.powered=AsyncMock()
    bt.objects=AsyncMock(return_value={'/org/bluez/hci7':{'org.bluez.Adapter1':{'Address':MAC1}}})
    bt.call=AsyncMock()
    await bt.scan()
    first=bt.scan_task
    await bt.scan()
    assert first.cancelled() and bt.scan_adapter=='/org/bluez/hci7'
    second=bt.scan_task
    await second
    assert bt.scan_adapter is None and bt.scan_task is None
    assert [r.args[2] for r in bt.call.await_args_list].count('StartDiscovery')==2
    await bt.scan()
    await bt.scan(False)
    assert bt.scan_adapter is None and bt.scan_task is None


async def test_lms_server_reachable_before_player_registration():
    lyrion=LyrionManager(Settings(lms_host='192.0.2.20'))
    lyrion.rpc=AsyncMock(side_effect=[{'_version':'9.0'},PlayerError('Player noch nicht registriert')])
    status=await lyrion.status()
    assert status['server_reachable'] and not status['connected'] and not status['running']
    assert lyrion.rpc.await_args_list[0].args==(['version','?'],)
    assert lyrion.rpc.await_args_list[0].kwargs=={'player':''}


@pytest.mark.parametrize('start_volume', [0, 35, 60])
async def test_music_is_not_attenuated_by_a_second_start_volume(start_volume):
    lyrion = LyrionManager(Settings(lms_host='192.0.2.20', start_volume=start_volume, max_volume=60))
    async def rpc(command, player=None):
        if command[0] == 'status':
            return {'player_connected': 1, 'mixer volume': 35}
        return {}
    lyrion.rpc = AsyncMock(side_effect=rpc)
    status = await lyrion.status()
    assert status['volume'] == 100
    mixer_calls = [call.args[0] for call in lyrion.rpc.await_args_list if call.args[0][0] == 'mixer']
    assert mixer_calls == [['mixer', 'volume', '100']]


async def test_music_gain_initialized_only_once_after_player_connects():
    lyrion = LyrionManager(Settings(lms_host='192.0.2.20'))
    connected = False
    async def rpc(command, player=None):
        if command[0] == 'status':
            return {'player_connected': int(connected), 'mixer volume': 42}
        return {}
    lyrion.rpc = AsyncMock(side_effect=rpc)
    await lyrion.status()
    assert not lyrion.volume_initialized
    connected = True
    await lyrion.status()
    status = await lyrion.status()
    assert status['volume'] == 42  # Later intentional LMS adjustments remain intact.
    mixer_calls = [call.args[0] for call in lyrion.rpc.await_args_list if call.args[0][0] == 'mixer']
    assert mixer_calls == [['mixer', 'volume', '100']]
