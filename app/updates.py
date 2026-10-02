import asyncio
import json
import os
from pathlib import Path
import re
import time
import httpx
from app.errors import PlayerError

REPOSITORY = 'DoctorX-1337/lyrionbluetoothplayer-webgui-proxmox'
API = 'https://api.github.com/repos/' + REPOSITORY + '/commits/main'


class UpdateChecker:
    def __init__(self, installation=Path('/opt/lyrion-bt-player'), runtime=Path('/run/lyrion-bt-update')):
        self.installation = installation
        self.runtime = runtime
        self.cached = None
        self.lock = asyncio.Lock()

    def status(self):
        try:
            current = (self.installation/'SOURCE_COMMIT').read_text().strip()
        except OSError:
            current = ''
        try:
            progress = json.loads((self.runtime/'status.json').read_text())
        except (OSError, ValueError):
            progress = {'state':'idle','message':'Bereit','progress':0}
        return {'current_version':'1.0.0','current_commit':current,
                'latest_commit':None,'available':False,'checked_at':None,
                **(self.cached or {}), 'installation':progress}

    async def check(self):
        async with self.lock:
            try:
                async with httpx.AsyncClient(timeout=12, trust_env=False) as client:
                    response = await client.get(API,headers={'Accept':'application/vnd.github+json','User-Agent':'Lyrion-Bluetooth-Player'})
                    response.raise_for_status()
                    latest = response.json()['sha']
                if not re.fullmatch(r'[0-9a-f]{40}',latest):
                    raise ValueError('Invalid commit')
                current = self.status()['current_commit']
                self.cached = {'latest_commit':latest,'available':latest!=current,'checked_at':time.time(),'error':None}
            except (httpx.HTTPError, ValueError, KeyError):
                self.cached = {'latest_commit':None,'available':False,'checked_at':time.time(),'error':'Öffentliches Repository zurzeit nicht erreichbar.'}
            return self.status()

    def request(self):
        status = self.status()
        if not status.get('latest_commit'):
            raise PlayerError('Bitte zuerst nach Updates suchen.', 'invalid')
        if not status['available']:
            raise PlayerError('Die installierte Version ist aktuell.', 'invalid')
        if status['installation'].get('state') in {'queued','running'}:
            raise PlayerError('Ein Update läuft bereits.', 'busy')
        if not self.runtime.is_dir():
            raise PlayerError('Update-Dienst fehlt. Führen Sie den Installer erneut aus.', 'unavailable')
        path = self.runtime/'request'
        try:
            fd = os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'w') as file:
                file.write(status['latest_commit']+'\n')
        except FileExistsError:
            raise PlayerError('Ein Update ist bereits angefordert.', 'busy') from None
        return {'ok':True,'message':'Update angefordert. Die Oberfläche verbindet sich nach dem Neustart wieder.'}
