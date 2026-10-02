# Debian-VM für Bluetooth-Audio

Empfehlung: 2 vCPU, 1 GB RAM, 8 GB Disk; bei Bedarf 2 GB RAM und 16 GB Disk. Nur Ethernet-LAN und den Bluetooth-USB-Geräteteil zuordnen. Kein Docker, keine vollständige PCIe-WLAN-Zuteilung.

Der Self-Installer verwendet `debian-13-generic-amd64.qcow2` vom offiziellen Debian-Cloud-Image-Server und prüft SHA512. Das **generic**-Image hat den vollständigen Kernel. Das schlankere **genericcloud**-Image kann USB-/Bluetooth-Module vermissen.

Manuelle Diagnose in der VM:

```bash
uname -r
lsusb
lsusb -t
ls /sys/class/bluetooth
modinfo btusb
rfkill list
bluetoothctl list
```

Bei einem Cloud-Kernel ohne Module in Debian zuerst `linux-image-amd64` und die passende Firmware installieren, den vollständigen Kernel als Bootkernel auswählen und die VM neu starten. Kein Proxmox-Host-Reboot erforderlich. Bereits installierte Kernel müssen nicht entfernt werden.

Die Anwendung selbst ist dieselbe wie bei einer direkt nutzbaren Debian-Installation. Konfiguration, SQLite und UI sind nicht an Proxmox gebunden. Bei einer Migration die Bluetooth-Gerätezuordnung prüfen. Die VM darf nicht auf einem Node ohne Adapter automatisch gestartet werden.
