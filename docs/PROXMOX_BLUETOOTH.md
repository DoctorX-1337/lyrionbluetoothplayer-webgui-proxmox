# Bluetooth unter Proxmox: HCI prüfen, nicht nur USB

## Technische Grenze

Linux implementiert `bt_sock_create()` in `net/bluetooth/af_bluetooth.c` mit einer Prüfung auf den initialen Netzwerknamespace. In einem anderen Namespace liefert es `EAFNOSUPPORT`. Ein in `/sys/class/bluetooth` sichtbares HCI-Symlink ist kein Beweis für funktionsfähige Sockets.

Primärquelle: [Linux Bluetooth-Socket-Code](https://github.com/torvalds/linux/blob/master/net/bluetooth/af_bluetooth.c).

Im vorgesehenen Gast als root prüfen:

```bash
python3 - <<'PY'
import socket
s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW, socket.BTPROTO_HCI)
print('HCI-Socket verfügbar')
s.close()
PY
```

In einer VM kann derselbe Fehler auch von einem Kernel ohne Bluetooth-Module kommen. Erst vollständigen Debian-Kernel, USB-Controller und `btusb` prüfen. In einem LXC zusätzlich die Namespace-Grenze beachten.

## Unprivilegierter LXC

Proxmox unterstützt gezielte Geräteknoten-Zuordnung, beispielsweise:

```bash
pct set <CTID> --dev0 path=/dev/bus/usb/<BUS>/<DEVICE>,mode=0660
```

Die Nummern sind aus `lsusb` abzuleiten und ändern sich beim Reconnect. Dieser Mechanismus gewährt Zugriff auf den USB-Geräteknoten; er verlagert **keinen HCI-Controller** in den Netzwerknamespace des Containers. Eine zusätzliche udev-Zuordnung wäre für stabile Geräteknoten nötig, löst aber ebenfalls nicht den Bluetooth-Stackzugriff.

[Proxmox-Geräteoptionen](https://pve.proxmox.com/pve-docs/pct.1.html). Das Diagnoseskript zeigt den konkreten Geräteknoten, Vendor/Product, Treiber, USB-Port und einen auf genau diesen Knoten beschränkten cgroup2-Hinweis. Diese Vorschläge sind Diagnosedaten, kein Zusicherungsversprechen für Bluetooth im LXC.

## Privilegierter LXC

Host-UIDs, zusätzliche Capabilities und Dateizugriff erhöhen die Folgen eines kompromittierten Containers. Eine Umstellung auf privilegiert ändert nicht automatisch den Netzwerknamespace. Daher gibt es keinen pauschalen „privilegiert und unconfined“-Installer. Kein globales Device-Allow, keine pauschale AppArmor-Deaktivierung, kein automatisches Entfernen von Capability-Grenzen.

Ein Betrieb im Host-Netzwerknamespace oder ein geteilter Host-D-Bus wäre eine andere Architektur mit erheblicher Kopplung an den Proxmox-Host. Diese Anwendung installiert keinen solchen Host-Proxy und mountet keinen vollständigen Host-Systembus in den Gast. Für einen getrennten Audioplayer ist die kleine Debian-VM vorzuziehen.

## VM und internes USB-Bluetooth

```bash
bash proxmox-bluetooth-check.sh
lsusb -t
udevadm info -q property -n /dev/bus/usb/<BUS>/<DEVICE>
qm set <VMID> --usb0 host=<USB-PORT>,usb3=0
```

Nur der Bluetooth-USB-Teil wird zugeordnet. Keine PCIe-WLAN-Karte und kein vollständiger USB-Controller müssen dafür durchgereicht werden. IOMMU ist für dieses USB-Gerätepassthrough kein Grundbaustein.

Der Self-Installer erkennt `btusb` und die Bluetooth-USB-Schnittstellenklasse. Bei mehreren Geräten wählt der Administrator. Nicht jedes in einem Rechner vorhandene Bluetooth-Modul muss USB-basiert sein; bei anderer Anbindung stoppt die automatische Erkennung mit einem konkreten Hinweis statt einer falschen Zuordnung.

## Host-Konflikte

```bash
systemctl is-active bluetooth
bluetoothctl list
rfkill list
lsmod | grep -E 'bluetooth|btusb'
```

Der Self-Installer stoppt bei aktivem Host-BlueZ, sofern die exklusive Adapterübernahme nicht ausdrücklich mit `--allow-adapter-transfer` bestätigt wird. Er deaktiviert trotzdem keinen Hostdienst. Vor einer Freigabe prüfen, ob andere Geräte den Adapter benötigen. QEMU beansprucht nur den ausgewählten USB-Geräteteil.

## Neustart und Reconnect

Nach dem Hostboot startet die VM über `onboot`, QEMU ordnet denselben USB-Port zu und Debian lädt `btusb`. BlueZ startet als Systemdienst; PipeWire, WirePlumber und Manager laufen im lingernden Benutzerkontext. Der Manager erkennt Adapter dynamisch über BlueZ. Bei Adapterverlust bleibt die Oberfläche verfügbar und der Reconnect nutzt begrenzte Abstände.

Nach Umstecken in einen anderen physischen Port muss die Proxmox-USB-Portzuordnung geändert werden. Nach Gerätetausch kann sich die Adapter-MAC ändern. USB-Portzuordnung ist keine Zusicherung für beliebige Hardwareänderungen.

**Dieser Gast ist hardwaregebunden.** Keine automatische HA-Migration auf Nodes ohne denselben Funkadapter.
