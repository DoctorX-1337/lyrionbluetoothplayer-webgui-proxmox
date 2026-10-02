#!/usr/bin/env bash
set -uo pipefail
ctid=${1:-}
[[ -z "$ctid" || "$ctid" =~ ^[0-9]+$ ]] || { echo 'CTID muss numerisch sein'; exit 1; }
show() { printf '\n%s\n' "$1"; shift; if command -v "$1" >/dev/null 2>&1; then "$@" 2>&1 || true; else echo "$1 nicht installiert"; fi; }
echo 'Lyrion Bluetooth Proxmox Hardware Check — ausschließlich lesend'
show 'Hersteller/Modell:' cat /sys/class/dmi/id/sys_vendor /sys/class/dmi/id/product_name /sys/class/dmi/id/product_version
show 'CPU / AMD-Plattform:' lscpu
show 'Ethernet/WLAN und Treiber:' lspci -nnk
show 'Ethernet-Link:' ip -brief link
show 'USB-Geräte (Vendor/Product):' lsusb
show 'USB-Topologie:' lsusb -t
show 'Kernelmodule:' lsmod
show 'HCI:' ls -l /sys/class/bluetooth
show 'rfkill:' rfkill list
show 'BlueZ-Hostdienst (aktiver Dienst kann konkurrieren):' systemctl is-active bluetooth
show 'BlueZ-Adapter:' bluetoothctl list
show 'HCI-Details:' hciconfig -a
printf '\nBluetooth-/Firmware-Kernelmeldungen:\n'
dmesg 2>/dev/null | grep -Ei 'bluetooth|btusb|firmware.*rtl' | tail -60 || true
for hci in /sys/class/bluetooth/hci*; do
  [[ -e "$hci" ]] || continue
  device=$(readlink -f "$hci/device")
  while [[ "$device" != / && ! -f "$device/idVendor" ]]; do device=$(dirname "$device"); done
  [[ -f "$device/idVendor" ]] || continue
  bus=$(cat "$device/busnum"); dev=$(cat "$device/devnum")
  printf -v usb '/dev/bus/usb/%03d/%03d' "$bus" "$dev"
  printf '\nHCI=%s USB-Port=%s VID:PID=%s:%s Gerät=%s\n' "$(basename "$hci")" "$(basename "$device")" "$(cat "$device/idVendor")" "$(cat "$device/idProduct")" "$usb"
  ls -l "$usb"
  udevadm info -q property -n "$usb" 2>/dev/null || true
  echo 'VM: qm set <VMID> --usb0 host='"$(basename "$device")"
  echo 'Nur als Gerätezugriffsdiagnose, NICHT als Lösung der Bluetooth-Namespace-Grenze:'
  echo "pct set ${ctid:-<CTID>} --dev0 path=$usb,mode=0660"
  echo "cgroup2 (nur dieser Geräteknoten): lxc.cgroup2.devices.allow: c $(stat -c '%t:%T' "$usb" | awk -F: '{printf "%d:%d", "0x"$1, "0x"$2}') rw"
done
cat <<'TEXT'

Wichtig: Ein sichtbarer USB-Geräteknoten oder /sys/class/bluetooth-Link ist kein
Nachweis für HCI-Zugriff. AF_BLUETOOTH ist im Linux-Kernel auf init_net beschränkt.
Ein privilegierter LXC mit eigenem Netzwerknamespace behebt das nicht automatisch.
Keine AppArmor-Deaktivierung, kein globales Device-Allow und kein Host-Networking
als automatischer Workaround. Details: docs/PROXMOX_BLUETOOTH.md.
Dieser LXC / diese VM ist hardwaregebunden. Kein HA-Start auf anderen Nodes.
Es wurden keine Änderungen durchgeführt.
TEXT
if [[ -n "$ctid" ]] && command -v pct >/dev/null; then
  pct exec "$ctid" -- python3 -c 'import socket; s=socket.socket(socket.AF_BLUETOOTH,socket.SOCK_RAW,socket.BTPROTO_HCI); print("HCI-Socket verfügbar"); s.close()' || echo 'HCI im Ziel-LXC nicht zugänglich.'
fi
