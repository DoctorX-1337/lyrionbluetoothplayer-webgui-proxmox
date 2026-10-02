#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Bitte auf dem Proxmox-Host als root ausführen.' >&2; exit 1; }
for executable in python3 curl qm pvesh pvesm; do
  command -v "$executable" >/dev/null || { echo "$executable fehlt; Proxmox VE wird benötigt." >&2; exit 1; }
done
repository='DoctorX-1337/lyrionbluetoothplayer-webgui-proxmox'
release=${LBP_REF:-main}
[[ "$release" =~ ^[A-Za-z0-9._-]+$ ]] || { echo 'Ungültige Version.' >&2; exit 1; }
source_dir=$(mktemp -d /var/tmp/lyrion-bt-installer.XXXXXXXX)
trap 'rm -rf -- "$source_dir"' EXIT
commit=$(curl --fail --silent --show-error --proto '=https' --tlsv1.2 --connect-timeout 10 --max-time 45 --retry 3 \
  -H 'Accept: application/vnd.github+json' "https://api.github.com/repos/$repository/commits/$release" | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha"])')
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || { echo 'Kein gültiger Repository-Commit gefunden.' >&2; exit 1; }
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --tlsv1.2 --connect-timeout 10 --max-time 180 --retry 3 \
  "https://github.com/$repository/archive/$commit.tar.gz" | tar -xz --strip-components=1 -C "$source_dir"
printf '%s\n' "$commit" > "$source_dir/SOURCE_COMMIT"
python3 "$source_dir/deploy/pve_install.py" "$@"
