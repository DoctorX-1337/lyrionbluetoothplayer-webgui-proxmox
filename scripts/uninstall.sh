#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Bitte als root ausführen.'; exit 1; }
read -r -p 'Anwendung entfernen? [j/N] ' answer
[[ "$answer" == j ]] || exit 0
player_uid=$(id -u lyrionbt)
systemctl disable --now lyrion-bt-update.path
systemctl stop lyrion-bt-update.service || true
rm -f /etc/systemd/system/lyrion-bt-update.path /etc/systemd/system/lyrion-bt-update.service /usr/local/sbin/lyrion-bt-update /etc/tmpfiles.d/lyrion-bt-player.conf
runuser -u lyrionbt -- env XDG_RUNTIME_DIR="/run/user/$player_uid" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$player_uid/bus" systemctl --user disable --now lyrion-bt-web.service lyrion-bt-manager.service
rm -f /etc/systemd/user/lyrion-bt-web.service /etc/systemd/user/lyrion-bt-manager.service /usr/local/bin/lyrion-bt /etc/dbus-1/system.d/lyrionbt.conf
rm -f /var/lib/lyrionbt/.config/wireplumber/wireplumber.conf.d/90-lyrion-headless.conf
systemctl reload dbus.service
systemctl daemon-reload
rm -rf -- /opt/lyrion-bt-player
for entry in /etc/lyrion-bt-player /var/lib/lyrion-bt-player /var/log/lyrion-bt-player; do
  read -r -p "$entry behalten? [J/n] " answer
  [[ "$answer" != n ]] || rm -rf -- "$entry"
done
echo 'Systempakete, Benutzer und BlueZ-Pairing-Daten bleiben erhalten; ihre exklusive Nutzung ist nicht belegbar.'
