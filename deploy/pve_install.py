"""Generic, model-independent Proxmox VM self-installer (standard library only)."""
import argparse
import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import urllib.request

REPOSITORY = 'DoctorX-1337/lyrionbluetoothplayer-webgui-proxmox'
SOURCE = Path(__file__).resolve().parents[1]
COLOR = sys.stdout.isatty() and not os.environ.get('NO_COLOR')
GREEN, CYAN, RED, RESET = ('\033[38;5;84m','\033[38;5;79m','\033[38;5;203m','\033[0m') if COLOR else ('','','','')


def run(*args, timeout=180):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        # Arguments may contain a password hash. Never include arguments in errors.
        raise RuntimeError(f'{args[0]} konnte den Arbeitsschritt nicht ausführen.')
    return result.stdout


def step(number, text):
    print(f'\n{GREEN}[{number}/7]{RESET} {text}', flush=True)
    print(f'{GREEN}  [{"━" * (number * 4)}{"·" * ((7-number) * 4)}] {number*100//7}%{RESET}', flush=True)


def usb_adapters(root=Path('/sys')):
    result = {}
    for interface in (root / 'bus/usb/devices').glob('*:*'):
        try:
            driver = (interface/'driver').resolve().name if (interface/'driver').exists() else ''
            klass = (interface/'bInterfaceClass').read_text().strip()
            subclass = (interface/'bInterfaceSubClass').read_text().strip()
            protocol = (interface/'bInterfaceProtocol').read_text().strip()
            if driver != 'btusb' and (klass,subclass,protocol) != ('e0','01','01'):
                continue
            parent = interface.resolve().parent
            port = parent.name
            if not re.fullmatch(r'\d+-\d+(?:\.\d+)*',port):
                continue
            result[port] = {'port':port, 'vendor':(parent/'idVendor').read_text().strip(),
                'product':(parent/'idProduct').read_text().strip(),
                'name':(parent/'product').read_text().strip() if (parent/'product').exists() else 'Bluetooth-Adapter'}
        except OSError:
            continue
    return sorted(result.values(), key=lambda d:d['port'])


def validate_network(ipconfig):
    if ipconfig == 'ip=dhcp':
        return ipconfig
    match = re.fullmatch(r'ip=([^,]+),gw=([^,]+)',ipconfig)
    if not match:
        raise ValueError('Netzwerkformat: ip=dhcp oder ip=<IPv4/CIDR>,gw=<Gateway>')
    interface = ipaddress.IPv4Interface(match[1])
    gateway = ipaddress.IPv4Address(match[2])
    if gateway not in interface.network:
        raise ValueError('Gateway liegt nicht im angegebenen IPv4-Netz')
    return ipconfig


def adapter_assigned(adapter, directory=Path('/etc/pve/qemu-server')):
    """A stopped VM still owns its configured USB adapter."""
    for config in directory.glob('*.conf'):
        for host in re.findall(r'^usb\d+:.*?\bhost=([^,\s]+)',config.read_text(),re.M):
            if host.lower() in (adapter['port'],adapter['vendor']+':'+adapter['product']):
                return True
    return False


def static_address_in_use(address, vmid=None, directory=Path('/etc/pve/nodes')):
    """Check addresses recorded in the cluster; DHCP must exclude these."""
    for kind in ('lxc','qemu-server'):
        for config in directory.glob('*/'+kind+'/*.conf'):
            if config.stem==str(vmid):
                continue
            for line in config.read_text().splitlines():
                if not re.match(r'^(net|ipconfig)\d+:',line):
                    continue
                match=re.search(r'(?:[:,]\s*|,)ip=([0-9.]+)(?:/\d+)?(?:,|$)',line)
                if match and match[1]==address:
                    return True
    return False


def guest_addresses(data):
    interfaces=data.get('result',data) if isinstance(data,dict) else data
    return [entry['ip-address'] for interface in interfaces for entry in interface.get('ip-addresses',[])
        if entry.get('ip-address-type')=='ipv4' and not ipaddress.IPv4Address(entry['ip-address']).is_loopback]


def guest_exec(vmid, command, timeout=30):
    data = json.loads(run('qm','guest','exec',str(vmid),'--timeout',str(timeout),'--','bash','-lc',command,timeout=timeout+15))
    if data.get('exitcode') != 0:
        raise RuntimeError('Gastprüfung noch nicht erfolgreich')
    return data.get('out-data','')


def provision(args):
    if os.geteuid() != 0:
        raise ValueError('Bitte als root auf einem Proxmox-Host starten.')
    print(GREEN + (SOURCE/'deploy/banner.txt').read_text() + RESET)
    print(f'{CYAN}  Proxmox Self-Installer · Debian 13 · vollständig lokal{RESET}\n')
    for executable in ('qm','pvesh','pvesm','openssl'):
        run('which',executable)
    if run('dpkg','--print-architecture').strip() != 'amd64':
        raise ValueError('Proxmox-VM-Self-Installer benötigt einen amd64-Host. Direkte Debian-Installation unterstützt auch arm64.')
    if args.mode == 'lxc':
        raise ValueError('Isolierte LXC-Netzwerknamespaces unterstützen AF_BLUETOOTH nicht. Es wird kein unbrauchbarer LXC angelegt. Nutzen Sie --mode vm; Details in docs/PROXMOX_BLUETOOTH.md.')
    adapters = usb_adapters()
    if not adapters:
        raise ValueError('Kein USB-Bluetooth-Teil erkannt. BIOS, Hardware und btusb prüfen. Ein vorhandenes internes Modul wird bevorzugt; kein zusätzlicher Dongle ist Voraussetzung.')
    if args.usb:
        choices = [d for d in adapters if args.usb in (d['port'], d['vendor']+':'+d['product'])]
        if len(choices)!=1:
            raise ValueError('USB-Auswahl muss genau einen erkannten Bluetooth-Adapter treffen.')
        adapter = choices[0]
    elif len(adapters)==1:
        adapter = adapters[0]
    elif sys.stdin.isatty():
        for index, device in enumerate(adapters,1):
            print(f"  {index}: {device['name']} · USB {device['port']}")
        choice = input('Bluetooth-Adapter auswählen: ').strip()
        if not choice.isdigit() or not 1<=int(choice)<=len(adapters):
            raise ValueError('Ungültige Adapterauswahl')
        adapter=adapters[int(choice)-1]
    else:
        raise ValueError('Mehrere Adapter erkannt. Mit --usb <USB-Port> auswählen.')
    if adapter_assigned(adapter):
        raise ValueError('Dieser Bluetooth-Adapter ist bereits einer VM zugeordnet. Vor einer neuen Installation die vorhandene Zuordnung prüfen.')
    active = subprocess.run(['systemctl','is-active','--quiet','bluetooth'],capture_output=True).returncode==0
    if active and not args.allow_adapter_transfer:
        raise ValueError('Host-BlueZ ist aktiv. Adapterverwendung prüfen. --allow-adapter-transfer bestätigt die exklusive Zuordnung an die VM; Hostdienste werden nicht deaktiviert.')
    vmid = args.vmid or int(run('pvesh','get','/cluster/nextid').strip())
    if not 100<=vmid<=999999999:
        raise ValueError('VMID muss mindestens 100 sein.')
    if Path(f'/etc/pve/qemu-server/{vmid}.conf').exists() or Path(f'/etc/pve/lxc/{vmid}.conf').exists():
        raise ValueError('VMID ist bereits vergeben. Bestehende Gäste bleiben unverändert.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,62}',args.hostname):
        raise ValueError('Ungültiger Hostname')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',args.bridge):
        raise ValueError('Ungültige Bridge')
    run('ip','link','show',args.bridge)
    validate_network(args.ip_config)
    if args.ip_config!='ip=dhcp' and static_address_in_use(args.ip_config.split('=',1)[1].split('/',1)[0]):
        raise ValueError('Die gewünschte Adresse ist bereits einem Proxmox-Gast zugeordnet.')
    if args.dns:
        ipaddress.IPv4Address(args.dns)
    if args.cores<1 or args.memory<1024 or args.disk<8:
        raise ValueError('Mindestens 1 vCPU, 1024 MB RAM und 8 GB Disk vorsehen.')
    storages = [line.split()[0] for line in run('pvesm','status','--content','images').splitlines()[1:] if len(line.split())>2 and line.split()[2]=='active']
    storage = args.storage or (storages[0] if storages else '')
    if storage not in storages:
        raise ValueError('Kein aktiver VM-Speicher ausgewählt')
    commit=(SOURCE/'SOURCE_COMMIT').read_text().strip()
    if not re.fullmatch(r'[0-9a-f]{40}',commit):
        raise ValueError('Installer muss aus einem festen Repository-Commit gestartet werden.')
    if args.password_file and (args.password_file.stat().st_uid!=0 or args.password_file.stat().st_mode & 0o077):
        raise ValueError('Passwortdatei muss root gehören und darf keine Gruppen-/Fremdrechte haben (0600).')
    password=args.password_file.read_text().strip() if args.password_file else ''
    if not password and sys.stdin.isatty():
        password=getpass.getpass('Root-Passwort für die neue VM: ')
        if password!=getpass.getpass('Root-Passwort wiederholen: '):
            raise ValueError('Passwörter stimmen nicht überein')
    if len(password)<12 or '\n' in password:
        raise ValueError('Mindestens 12 Zeichen für das VM-Passwort; ohne Terminal --password-file <root-0600-Datei> verwenden.')
    print(f'  VM {vmid} · {args.cores} vCPU · {args.memory} MB · {args.disk} GB · {storage}')
    print(f"  Bluetooth: {adapter['name']} · USB {adapter['port']} · {adapter['vendor']}:{adapter['product']}")
    print('  Neuer Gast; bestehende Gäste und Hostdienste bleiben erhalten. Hardwaregebunden, keine automatische HA.')
    step(1,'Debian-Image herunterladen und prüfen')
    base='https://cloud.debian.org/images/cloud/trixie/latest/'
    filename='debian-13-generic-amd64.qcow2'  # Full USB/Bluetooth kernel; NOT genericcloud.
    directory=Path('/var/lib/vz/template/qcow2');directory.mkdir(parents=True,exist_ok=True)
    checksums=urllib.request.urlopen(base+'SHA512SUMS',timeout=30).read().decode()
    expected=re.search(r'^([0-9a-f]{128})\s+\*?'+re.escape(filename)+r'$',checksums,re.M)
    if not expected:
        raise ValueError('Offizielle Debian-Prüfsumme fehlt')
    image=directory/filename
    if image.exists():
        with image.open('rb') as handle:
            valid=hashlib.file_digest(handle,'sha512').hexdigest()==expected[1]
    else:
        valid=False
    if not valid:
        download=image.with_suffix('.download')
        urllib.request.urlretrieve(base+filename,download)
        with download.open('rb') as handle:
            if hashlib.file_digest(handle,'sha512').hexdigest()!=expected[1]:
                raise ValueError('Debian-Image hat eine falsche SHA512-Prüfsumme')
        download.replace(image)
    step(2,'Debian-VM erstellen')
    run('qm','create',str(vmid),'--name',args.hostname,'--cores',str(args.cores),'--memory',str(args.memory),
        '--ostype','l26','--scsihw','virtio-scsi-pci','--net0',f'virtio,bridge={args.bridge},firewall=1',
        '--serial0','socket','--vga','serial0','--agent','enabled=1','--onboot','1')
    run('qm','importdisk',str(vmid),str(image),storage,timeout=300)
    disk=re.search(r'^unused\d+: (\S+)',run('qm','config',str(vmid)),re.M)[1]
    run('qm','set',str(vmid),'--scsi0',disk,'--ide2',storage+':cloudinit','--boot','order=scsi0',
        '--ipconfig0',args.ip_config,'--usb0','host='+adapter['port']+',usb3=0')
    if args.dns:
        run('qm','set',str(vmid),'--nameserver',args.dns)
    run('qm','resize',str(vmid),'scsi0',str(args.disk)+'G')
    step(3,'Erstkonfiguration und Installation vorbereiten')
    hashed=subprocess.run(['openssl','passwd','-6','-stdin'],input=password+'\n',capture_output=True,text=True,check=True).stdout.strip()
    password=''
    snippet_storage='lyrion-bt-snippets'
    snippet_dir=Path('/var/lib/vz/lyrion-bt-snippets');(snippet_dir/'snippets').mkdir(parents=True,exist_ok=True)
    all_storages=[line.split()[0] for line in run('pvesm','status').splitlines()[1:] if line.strip()]
    if snippet_storage not in all_storages:
        run('pvesm','add','dir',snippet_storage,'--path',str(snippet_dir),'--content','snippets')
    # This storage contains only cloud-init metadata. It is not an application backup.
    guest_script=f'''set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
sed -i 's/^Components: main$/Components: main non-free-firmware/' /etc/apt/sources.list.d/debian.sources
apt-get update
apt-get install -y ca-certificates curl firmware-realtek firmware-iwlwifi firmware-atheros firmware-mediatek firmware-brcm80211 qemu-guest-agent
modprobe -r btusb
modprobe btusb
systemctl start qemu-guest-agent
mkdir -p /opt/lyrion-bt-player-source
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --retry 3 https://github.com/{REPOSITORY}/archive/{commit}.tar.gz | tar -xz --strip-components=1 -C /opt/lyrion-bt-player-source
printf '%s\\n' {commit} > /opt/lyrion-bt-player-source/SOURCE_COMMIT
bash /opt/lyrion-bt-player-source/install.sh
'''
    cloud={'hostname':args.hostname,'disable_root':False,'ssh_pwauth':True,
        'users':[{'name':'root','lock_passwd':False,'hashed_passwd':hashed}],
        'chpasswd':{'expire':False,'users':[{'name':'root','password':hashed,'type':'hash'}]},
        'write_files':[{'path':'/run/lyrion-setup.sh','permissions':'0700','content':guest_script},
            {'path':'/etc/ssh/sshd_config.d/00-lyrion-access.conf','permissions':'0600','content':'PasswordAuthentication yes\nPermitRootLogin yes\n'}],
        'runcmd':[['bash','/run/lyrion-setup.sh']], 'final_message':'Lyrion Bluetooth Player: cloud-init abgeschlossen.'}
    snippet=snippet_dir/'snippets'/f'lyrion-bt-{vmid}.yaml'
    fd=os.open(snippet,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as handle:
        handle.write('#cloud-config\n'+json.dumps(cloud))
    run('qm','set',str(vmid),'--cicustom',f'user={snippet_storage}:snippets/{snippet.name}')
    step(4,'VM starten und Bluetooth exklusiv zuordnen')
    run('qm','start',str(vmid))
    step(5,'Automatische Gastinstallation abwarten')
    deadline=time.monotonic()+args.wait_timeout
    while time.monotonic()<deadline:
        try:
            addresses=guest_addresses(json.loads(run('qm','guest','cmd',str(vmid),'network-get-interfaces',timeout=20)))
        except (RuntimeError,subprocess.TimeoutExpired,ValueError):
            time.sleep(5)
            continue
        if any(static_address_in_use(address,vmid) for address in addresses):
            try:
                run('qm','shutdown',str(vmid),'--timeout','30',timeout=45)
            except RuntimeError:
                run('qm','stop',str(vmid))
            raise ValueError('IP-Konflikt mit einem vorhandenen Proxmox-Gast. Die neue VM wurde angehalten. DHCP-Bereich korrigieren oder --ip-config mit einer freien festen Adresse verwenden.')
        try:
            guest_exec(vmid,'curl --fail --silent http://127.0.0.1:8080/api/auth/session',timeout=15)
            break
        except (RuntimeError,subprocess.TimeoutExpired,ValueError):
            time.sleep(5)
    else:
        raise RuntimeError('Gastinstallation noch nicht bereit. VM bleibt zur Diagnose erhalten: cloud-init status --long und journalctl prüfen.')
    step(6,'Dienste, HCI und Webinterface prüfen')
    guest_exec(vmid,"python3 -c 'import socket; s=socket.socket(socket.AF_BLUETOOTH,socket.SOCK_RAW,socket.BTPROTO_HCI); s.close()'",timeout=15)
    guest_exec(vmid,'systemctl is-active bluetooth; runuser -u lyrionbt -- env XDG_RUNTIME_DIR=/run/user/$(id -u lyrionbt) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u lyrionbt)/bus systemctl --user is-active lyrion-bt-manager lyrion-bt-web',timeout=15)
    step(7,'Fertig — Lautsprecher und LMS in der Oberfläche einrichten')
    print(f'{GREEN}✓ Player installiert. VM {vmid}, Webinterface auf Port 8080.{RESET}')
    print('Die Weboberfläche öffnet ohne Anmeldung. Authentifizierung ist optional in config.toml aktivierbar.')
    print('Zugriff in der Firewall auf das LAN begrenzen. Keine Internet-Portfreigabe.')
    print('Updates: Einstellungen → Software-Update, oder lyrion-bt-update im Gast.')


def main():
    parser=argparse.ArgumentParser(description='Lyrion Bluetooth Player Proxmox Self-Installer')
    parser.add_argument('--vmid',type=int)
    parser.add_argument('--hostname',default='lyrion-player')
    parser.add_argument('--cores',type=int,default=2)
    parser.add_argument('--memory',type=int,default=1024)
    parser.add_argument('--disk',type=int,default=8)
    parser.add_argument('--storage')
    parser.add_argument('--bridge',default='vmbr0')
    parser.add_argument('--ip-config',default='ip=dhcp')
    parser.add_argument('--dns')
    parser.add_argument('--usb')
    parser.add_argument('--mode',choices=['vm','lxc'],default='vm')
    parser.add_argument('--allow-adapter-transfer',action='store_true')
    parser.add_argument('--password-file',type=Path)
    parser.add_argument('--wait-timeout',type=int,default=1200)
    args=parser.parse_args()
    try:
        provision(args)
    except (ValueError,RuntimeError,OSError,subprocess.SubprocessError) as exc:
        # Never emit unfiltered exception arguments from subprocess/SSH.
        safe=str(exc) if isinstance(exc,(ValueError,RuntimeError)) else type(exc).__name__
        print(f'\n{RED}Installation angehalten: {safe}{RESET}',file=sys.stderr)
        print('Bereits erstellte Gäste bleiben zur Diagnose erhalten; keine automatische Löschung.',file=sys.stderr)
        sys.exit(1)


if __name__=='__main__':
    main()
