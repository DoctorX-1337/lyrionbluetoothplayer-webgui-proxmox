#!/usr/bin/env python3
"""Root update helper. Fixed public upstream; validated immutable commits only."""
import argparse
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

REPOSITORY='DoctorX-1337/lyrionbluetoothplayer-webgui-proxmox'
RUNTIME=Path('/run/lyrion-bt-update')


def report(state,message,progress):
    path=RUNTIME/'status.json'
    temporary=RUNTIME/('status-'+str(os.getpid())+'.tmp')
    fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o640)
    with os.fdopen(fd,'w') as file:
        json.dump({'state':state,'message':message,'progress':progress,'timestamp':time.time()},file)
    import grp
    os.chown(temporary,0,grp.getgrnam('lyrionbt').gr_gid)
    temporary.replace(path)


def safe_members(archive):
    members=archive.getmembers()
    for member in members:
        path=PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts or member.issym() or member.islnk() or member.isdev() or member.isfifo():
            raise ValueError('Unsicheres Repository-Archiv')
    return members


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--request',action='store_true')
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    if os.geteuid()!=0:
        sys.exit('Update als root ausführen.')
    if not RUNTIME.is_dir() or RUNTIME.stat().st_uid!=0:
        sys.exit('Sicheres Update-Verzeichnis fehlt.')
    with open('/run/lyrion-bt-updater.lock','a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit('Ein Update läuft bereits.')
        request=RUNTIME/'request'
        try:
            headers={'Accept':'application/vnd.github+json','User-Agent':'Lyrion-Bluetooth-Player-Updater'}
            if args.request:
                fd=os.open(request,os.O_RDONLY|os.O_NOFOLLOW)
                with os.fdopen(fd,'r') as file:
                    commit=file.read(128).strip()
                request.unlink()
                if not re.fullmatch(r'[0-9a-f]{40}',commit):
                    raise ValueError('Ungültige Update-Anfrage')
                url=f'https://api.github.com/repos/{REPOSITORY}/commits/{commit}'
            else:
                url=f'https://api.github.com/repos/{REPOSITORY}/commits/main'
            with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=30) as response:
                remote=json.load(response)['sha']
            if not re.fullmatch(r'[0-9a-f]{40}',remote):
                raise ValueError('Ungültiger Repository-Commit')
            if args.request and remote!=commit:
                raise ValueError('Repository-Commit stimmt nicht überein')
            commit=remote
            if args.check:
                current=Path('/opt/lyrion-bt-player/SOURCE_COMMIT').read_text().strip()
                print('Aktuell' if current==commit else 'Update verfügbar: '+commit[:12])
                return
            report('running','Repository-Version wird geladen.',15)
            with tempfile.TemporaryDirectory(prefix='lyrion-update-',dir='/var/tmp') as directory:
                directory=Path(directory)
                archive_path=directory/'source.tar.gz'
                urllib.request.urlretrieve(f'https://github.com/{REPOSITORY}/archive/{commit}.tar.gz',archive_path)
                with tarfile.open(archive_path,'r:gz') as archive:
                    members=safe_members(archive)
                    archive.extractall(directory,members=members,filter='data')
                source=next(p for p in directory.iterdir() if p.is_dir())
                (source/'SOURCE_COMMIT').write_text(commit+'\n')
                report('running','Anwendung und Abhängigkeiten werden aktualisiert.',45)
                subprocess.run(['bash',str(source/'scripts/update.sh')],check=True,timeout=600)
                report('running','Dienste und API werden geprüft.',90)
                subprocess.run(['curl','--fail','--silent','http://127.0.0.1:8080/api/auth/session'],check=True,stdout=subprocess.DEVNULL,timeout=15)
            report('success','Update abgeschlossen.',100)
            print('Repository-Update erfolgreich.')
        except Exception:
            if request.exists() or request.is_symlink():
                request.unlink()
            report('failed','Update fehlgeschlagen. Installierte Dienste und Journal prüfen.',0)
            print('Update fehlgeschlagen; journalctl -u lyrion-bt-update prüfen.',file=sys.stderr)
            sys.exit(1)


if __name__=='__main__':
    main()
