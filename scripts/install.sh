#!/usr/bin/env bash
set -euo pipefail
umask 027
[[ $EUID -eq 0 ]] || { echo 'Bitte als root ausführen.' >&2; exit 1; }
source /etc/os-release
[[ "$ID" == debian && "$VERSION_ID" == 13 ]] || { echo 'Unterstützt wird Debian 13.' >&2; exit 1; }
case $(dpkg --print-architecture) in amd64|arm64) ;; *) echo 'Nicht unterstützte Architektur'; exit 1;; esac
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
platform=$(systemd-detect-virt || true)
echo "Installation auf Debian 13 ($platform)"
# A visible sysfs HCI link alone does NOT prove container access.
python3 - <<'PY'
import socket, sys
try:
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW, socket.BTPROTO_HCI)
    s.close()
except OSError:
    sys.exit('Bluetooth-HCI ist nicht zugänglich. Hardware/Kerneltreiber prüfen; in LXC auch Netzwerknamespace prüfen. Siehe docs/PROXMOX_BLUETOOTH.md. Es werden keine Host-Workarounds durchgeführt.')
PY
compgen -G '/sys/class/bluetooth/hci*' >/dev/null || { echo 'Kein HCI-Controller: Hardware/Firmware und VM-USB-Zuordnung prüfen.'; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv bluez dbus dbus-user-session pipewire pipewire-pulse pipewire-alsa wireplumber libspa-0.2-bluetooth libasound2-plugins pulseaudio-utils squeezelite rfkill usbutils curl
getent group bluetooth >/dev/null || groupadd --system bluetooth
id lyrionbt >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/lyrionbt --shell /usr/sbin/nologin --groups audio,bluetooth lyrionbt
usermod -aG audio,bluetooth lyrionbt
player_uid=$(id -u lyrionbt)
install -d -m 0755 /opt/lyrion-bt-player /etc/lyrion-bt-player
install -d -o lyrionbt -g lyrionbt -m 0750 /var/lib/lyrion-bt-player /var/log/lyrion-bt-player /var/lib/lyrionbt/.config/wireplumber/wireplumber.conf.d
install -d -o lyrionbt -g lyrionbt -m 0750 /var/lib/lyrionbt/.config /var/lib/lyrionbt/.config/systemd /var/lib/lyrionbt/.config/systemd/user /var/lib/lyrionbt/.config/wireplumber
if [[ "$source_dir" != /opt/lyrion-bt-player ]]; then
  cp -a "$source_dir/app" "$source_dir/pyproject.toml" "$source_dir/requirements.txt" /opt/lyrion-bt-player/
fi
[[ ! -f "$source_dir/SOURCE_COMMIT" ]] || install -m 0644 "$source_dir/SOURCE_COMMIT" /opt/lyrion-bt-player/SOURCE_COMMIT
python3 -m venv /opt/lyrion-bt-player/.venv
/opt/lyrion-bt-player/.venv/bin/pip install --disable-pip-version-check /opt/lyrion-bt-player
chmod -R a+rX /opt/lyrion-bt-player
if [[ ! -f /etc/lyrion-bt-player/config.toml ]]; then
  sed "s/@UID@/$player_uid/g" "$source_dir/config/config.toml" > /etc/lyrion-bt-player/config.toml
fi
chown root:lyrionbt /etc/lyrion-bt-player/config.toml
chmod 0640 /etc/lyrion-bt-player/config.toml
install -o lyrionbt -g lyrionbt -m 0644 "$source_dir/config/90-headless-bluetooth.conf" /var/lib/lyrionbt/.config/wireplumber/wireplumber.conf.d/90-lyrion-headless.conf
[[ -f /var/lib/lyrionbt/.asoundrc ]] || install -o lyrionbt -g lyrionbt -m 0644 "$source_dir/config/asoundrc" /var/lib/lyrionbt/.asoundrc
install -m 0644 "$source_dir/config/lyrionbt-dbus.conf" /etc/dbus-1/system.d/lyrionbt.conf
install -m 0644 "$source_dir/systemd/lyrion-bt-manager.service" "$source_dir/systemd/lyrion-bt-web.service" /etc/systemd/user/
install -m 0755 "$source_dir/scripts/repo_update.py" /usr/local/sbin/lyrion-bt-update
install -m 0644 "$source_dir/systemd/lyrion-bt-update.service" "$source_dir/systemd/lyrion-bt-update.path" /etc/systemd/system/
install -m 0644 "$source_dir/config/lyrion-bt-tmpfiles.conf" /etc/tmpfiles.d/lyrion-bt-player.conf
systemd-tmpfiles --create /etc/tmpfiles.d/lyrion-bt-player.conf
systemctl daemon-reload
systemctl enable --now lyrion-bt-update.path
ln -sfn /opt/lyrion-bt-player/.venv/bin/lyrion-bt /usr/local/bin/lyrion-bt
# Debian's generic Squeezelite unit must not compete with our supervised process.
systemctl disable --now squeezelite.service || true
systemctl enable --now bluetooth.service
systemctl reload dbus.service
rfkill unblock bluetooth
loginctl enable-linger lyrionbt
systemctl start "user@$player_uid.service"
export XDG_RUNTIME_DIR="/run/user/$player_uid"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
userctl() { runuser -u lyrionbt -- env XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS" systemctl --user "$@"; }
userctl stop lyrion-bt-web.service lyrion-bt-manager.service || true
LYRION_BT_CONFIG=/etc/lyrion-bt-player/config.toml /usr/local/bin/lyrion-bt init-admin
chown -R lyrionbt:lyrionbt /var/lib/lyrion-bt-player
find /var/lib/lyrion-bt-player -type f -exec chmod 0600 {} +
userctl daemon-reload
userctl enable --now pipewire.service pipewire-pulse.service wireplumber.service lyrion-bt-manager.service lyrion-bt-web.service
echo 'Webinterface auf TCP 8080. Zugriff in Proxmox-Firewall auf das lokale LAN begrenzen; keine Internet-Portfreigabe.'
echo 'Weboberfläche standardmäßig ohne Anmeldung. Optionale Authentifizierung über config.toml aktivierbar.'
sleep 5
runuser -u lyrionbt -- /usr/local/bin/lyrion-bt check || [[ $? -eq 2 ]]
