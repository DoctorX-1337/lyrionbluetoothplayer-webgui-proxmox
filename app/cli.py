import argparse
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path
import httpx
from app.auth import Auth
from app.config import Config
from app.database import DeviceRepository
from app.models import mac_address


def health(state):
    bt, audio, lyrion = state['bluetooth'], state['audio'], state['lyrion']
    default = next((d for d in bt['devices'] if d.get('is_default')), None)
    checks = [('BlueZ',state['services'].get('bluetooth')),('D-Bus',state['services'].get('dbus')),
              ('Bluetooth-Adapter',bool(bt.get('adapter'))),('Adapter eingeschaltet',bool(bt.get('adapter',{}).get('Powered')) if bt.get('adapter') else False),
              ('PipeWire',state['services'].get('pipewire')),('WirePlumber',state['services'].get('wireplumber')),
              ('Standardlautsprecher konfiguriert',bool(default)),('Standardlautsprecher verbunden',bool(default and default.get('connected'))),
              ('A2DP-Sink',audio.get('a2dp')),('Squeezelite',lyrion.get('running')),('LMS verbunden',lyrion.get('connected'))]
    print('Lyrion Bluetooth Player Health Check\n')
    for label, ok in checks:
        print(f"[{'OK' if ok else 'PRÜFEN'}] {label}")
    if not bt.get('adapter'):
        print('\nHardwarezuordnung prüfen: scripts/proxmox-bluetooth-check.sh und docs/PROXMOX_BLUETOOTH.md')
    if not default:
        print('\nIn der Weboberfläche einen Lautsprecher koppeln und als Standard auswählen.')
    if not lyrion.get('server'):
        print('\nIn Einstellungen die LMS-Adresse eintragen.')
    print('\nOverall status: ' + ('HEALTHY' if all(ok for _,ok in checks) else 'SETUP / DIAGNOSE ERFORDERLICH'))
    return 0 if all(ok for _,ok in checks) else 2


async def execute(args, config):
    transport = httpx.AsyncHTTPTransport(uds=config.socket)
    async with httpx.AsyncClient(transport=transport, base_url='http://manager', timeout=150) as client:
        if args.command in {'status','check','devices'}:
            response = await client.get('/api/status' if args.command != 'devices' else '/api/bluetooth/devices')
        elif args.command == 'scan':
            response = await client.post('/api/bluetooth/scan/start')
        elif args.command == 'restart-player':
            response = await client.post('/api/services/squeezelite/restart')
        else:
            mac = mac_address(args.mac)
            response = await client.post(f'/api/bluetooth/{mac}/{args.command}')
        if not response.is_success:
            print(response.json().get('detail','Aktion fehlgeschlagen'), file=sys.stderr)
            return 1
        if args.command == 'check':
            return health(response.json())
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
        return 0


def main():
    parser = argparse.ArgumentParser(prog='lyrion-bt')
    subs = parser.add_subparsers(dest='command', required=True)
    for name in ('status','check','devices','scan','restart-player','migrate'):
        subs.add_parser(name)
    for name in ('connect','disconnect','default','test'):
        subs.add_parser(name).add_argument('mac')
    init = subs.add_parser('init-admin')
    init.add_argument('--password-stdin', action='store_true')
    init.add_argument('--initial-file', default='/etc/lyrion-bt-player/secrets.env')
    args = parser.parse_args()
    config = Config.load()
    if args.command in {'init-admin','migrate'}:
        repo = DeviceRepository(config.database)
        if args.command == 'init-admin':
            if not config.auth_enabled:
                print('Weboberfläche ohne Anmeldung im lokalen Netzwerk. Optional: auth_enabled=true und init-admin.')
                repo.close()
                return
            value = sys.stdin.readline().rstrip('\r\n') if args.password_stdin else None
            password = Auth(repo, config).initialize(value)
            if password and not args.password_stdin:
                path = Path(args.initial_file)
                path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w') as handle:
                    handle.write('LYRION_BT_INITIAL_PASSWORD=' + password + '\n')
                print(f'Initialpasswort geschützt in {path} gespeichert; keine Passwortausgabe.')
            else:
                print('Lokale Anmeldung initialisiert; bestehende Konten bleiben erhalten.')
        repo.close()
        return
    try:
        sys.exit(asyncio.run(execute(args, config)))
    except (httpx.HTTPError, ValueError) as exc:
        print('Player-Manager nicht erreichbar oder Eingabe ungültig. CLI als Benutzer lyrionbt ausführen.', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
