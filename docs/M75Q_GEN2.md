# Lenovo ThinkCentre M75q Gen 2 und andere PCs

Der Player unterstützt einen Lenovo ThinkCentre M75q Gen 2 als möglichen Host, aber weder Installer noch Backend benötigen diesen Modellnamen. AMD- und Intel-Rechner verwenden dieselbe Anwendung. Funkchips dürfen nicht aus dem CPU-Hersteller abgeleitet werden.

```bash
cat /sys/class/dmi/id/sys_vendor
cat /sys/class/dmi/id/product_name
cat /sys/class/dmi/id/product_version
lscpu
lspci -nnk
lsusb
lsusb -t
lsmod
rfkill list
bluetoothctl list
hciconfig -a
dmesg | grep -Ei 'bluetooth|btusb|firmware'
```

Bei Combo-Karten kann WLAN als PCIe-Netzwerkgerät und Bluetooth separat am internen USB-Bus erscheinen. Der Bluetooth-USB-Port wird anhand der tatsächlichen Topologie ausgewählt. WLAN bleibt unkonfiguriert; das Heimnetz ist über Ethernet verbunden.

Zuerst das vorhandene interne Bluetooth nutzen. Bei Problemen BIOS-Einstellungen, USB-Erkennung, `btusb`, Firmware und rfkill untersuchen. Firmware ist herstellerabhängig: Beispielsweise kann Debian für Realtek `firmware-realtek` aus `non-free-firmware` benötigen. Andere Chips brauchen andere Pakete oder bereits enthaltene Firmware. Der Self-Installer installiert die Debian-Standardpakete; fehlende modellspezifische Firmware wird diagnostiziert, nicht durch eine Intel-Annahme ersetzt.

Ein externer Bluetooth-Dongle ist erst dann ein Fallback, wenn das interne Modul fehlt, ungeeignet ist oder nicht stabil zugeordnet werden kann. Eine VM mit USB-Gerätezuteilung vermeidet die AF_BLUETOOTH-Namespace-Sperre eines normalen LXC.
