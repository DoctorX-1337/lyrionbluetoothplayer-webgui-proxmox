import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tarfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
import httpx
from app.errors import PlayerError
from app.updates import UpdateChecker
from deploy.pve_install import validate_network, adapter_assigned, static_address_in_use, guest_addresses


@pytest.mark.parametrize('network',['ip=dhcp','ip=192.0.2.10/24,gw=192.0.2.1'])
def test_installer_network_validation(network):
    assert validate_network(network)==network


@pytest.mark.parametrize('network',['ip=999.1.1.1/24,gw=192.0.2.1','ip=192.0.2.10/24,gw=198.51.100.1','ip=dhcp;reboot','ip=dhcp,gw=host'])
def test_installer_rejects_network_injection(network):
    with pytest.raises(ValueError):
        validate_network(network)


def test_installer_detects_usb_ownership_even_for_stopped_guests(tmp_path):
    adapter={'port':'2-3.1','vendor':'1234','product':'5678'}
    config=tmp_path/'200.conf'
    config.write_text('usb0: host=2-3.1,usb3=0\n')
    assert adapter_assigned(adapter,tmp_path)
    config.write_text('usb1: host=1234:5678\n')
    assert adapter_assigned(adapter,tmp_path)
    config.write_text('usb0: host=9-1\n')
    assert not adapter_assigned(adapter,tmp_path)


def test_installer_detects_dhcp_conflicts_with_static_guests(tmp_path):
    lxc=tmp_path/'node'/'lxc';lxc.mkdir(parents=True)
    vm=tmp_path/'node'/'qemu-server';vm.mkdir()
    (lxc/'200.conf').write_text('net0: name=eth0,ip=192.0.2.20/24,gw=192.0.2.1\n')
    (vm/'201.conf').write_text('ipconfig0: ip=192.0.2.21/24,gw=192.0.2.1\n')
    assert static_address_in_use('192.0.2.20',directory=tmp_path)
    assert static_address_in_use('192.0.2.21',directory=tmp_path)
    assert not static_address_in_use('192.0.2.1',directory=tmp_path)
    assert not static_address_in_use('192.0.2.21',vmid=201,directory=tmp_path)
    assert guest_addresses({'result':[{'ip-addresses':[{'ip-address-type':'ipv4','ip-address':'127.0.0.1'},{'ip-address-type':'ipv4','ip-address':'192.0.2.22'}]}]})==['192.0.2.22']


async def test_update_check_is_explicit_and_pins_commit(tmp_path):
    installation=tmp_path/'app';installation.mkdir()
    runtime=tmp_path/'run';runtime.mkdir()
    (installation/'SOURCE_COMMIT').write_text('a'*40)
    checker=UpdateChecker(installation,runtime)
    client=AsyncMock()
    client.get.return_value=httpx.Response(200,json={'sha':'b'*40},request=httpx.Request('GET','https://api.github.com'))
    with patch('app.updates.httpx.AsyncClient') as factory:
        factory.return_value.__aenter__.return_value=client
        assert checker.status()['available'] is False
        client.get.assert_not_awaited()
        result=await checker.check()
        assert result['available'] and result['latest_commit']=='b'*40
        checker.request()
    assert (runtime/'request').read_text().strip()=='b'*40
    with pytest.raises(PlayerError):
        checker.request()


async def test_update_check_rejects_untrusted_payload(tmp_path):
    checker=UpdateChecker(tmp_path,tmp_path)
    client=AsyncMock()
    client.get.return_value=httpx.Response(200,json={'sha':'http://untrusted'},request=httpx.Request('GET','https://api.github.com'))
    with patch('app.updates.httpx.AsyncClient') as factory:
        factory.return_value.__aenter__.return_value=client
        assert (await checker.check())['error']
    with pytest.raises(PlayerError):
        checker.request()


def test_update_archive_rejects_traversal_and_symlinks():
    spec=importlib.util.spec_from_file_location('repo_update',Path(__file__).parents[1]/'scripts/repo_update.py')
    module=importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules,{'fcntl':SimpleNamespace()}):
        spec.loader.exec_module(module)
    for name,kind in [('../secrets',tarfile.REGTYPE),('/etc/passwd',tarfile.REGTYPE),('root/unsafe',tarfile.SYMTYPE)]:
        data=io.BytesIO()
        with tarfile.open(fileobj=data,mode='w') as archive:
            info=tarfile.TarInfo(name);info.type=kind
            archive.addfile(info)
        data.seek(0)
        with tarfile.open(fileobj=data,mode='r') as archive:
            with pytest.raises(ValueError):
                module.safe_members(archive)


@pytest.mark.skipif(os.name!='posix',reason='Linux service file permissions')
def test_update_progress_readable_with_restrictive_service_umask(tmp_path):
    spec=importlib.util.spec_from_file_location('repo_update_permissions',Path(__file__).parents[1]/'scripts/repo_update.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.RUNTIME=tmp_path
    previous=os.umask(0o077)
    try:
        with patch('grp.getgrnam',return_value=SimpleNamespace(gr_gid=os.getgid())),patch.object(module.os,'chown'):
            module.report('success','Update abgeschlossen.',100)
    finally:
        os.umask(previous)
    assert (tmp_path/'status.json').stat().st_mode & 0o777 == 0o640
    assert json.loads((tmp_path/'status.json').read_text())['state']=='success'
