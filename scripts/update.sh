#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Bitte als root ausführen.'; exit 1; }
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
player_uid=$(id -u lyrionbt)
export XDG_RUNTIME_DIR="/run/user/$player_uid" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$player_uid/bus"
userctl() { runuser -u lyrionbt -- env XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS" systemctl --user "$@"; }
userctl stop lyrion-bt-web.service lyrion-bt-manager.service
if [[ "$source_dir" != /opt/lyrion-bt-player ]]; then
  cp -a "$source_dir/app" "$source_dir/pyproject.toml" "$source_dir/requirements.txt" /opt/lyrion-bt-player/
fi
/opt/lyrion-bt-player/.venv/bin/pip install --upgrade /opt/lyrion-bt-player
chmod -R a+rX /opt/lyrion-bt-player
runuser -u lyrionbt -- /usr/local/bin/lyrion-bt migrate
install -m 0644 "$source_dir/systemd/lyrion-bt-manager.service" "$source_dir/systemd/lyrion-bt-web.service" /etc/systemd/user/
install -m 0755 "$source_dir/scripts/repo_update.py" /usr/local/sbin/lyrion-bt-update
install -m 0644 "$source_dir/systemd/lyrion-bt-update.service" "$source_dir/systemd/lyrion-bt-update.path" /etc/systemd/system/
systemctl daemon-reload
userctl daemon-reload
userctl start lyrion-bt-manager.service lyrion-bt-web.service
sleep 5
runuser -u lyrionbt -- /usr/local/bin/lyrion-bt check || [[ $? -eq 2 ]]
[[ ! -f "$source_dir/SOURCE_COMMIT" ]] || install -m 0644 "$source_dir/SOURCE_COMMIT" /opt/lyrion-bt-player/SOURCE_COMMIT
