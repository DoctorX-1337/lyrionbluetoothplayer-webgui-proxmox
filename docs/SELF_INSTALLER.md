# Vollständiger Self-Installer

Der Startbefehl ist in der README. Der Installer verwendet grüne Fortschrittsanzeigen, gedämpfte Hinweise und die projektbezogene ASCII-Überschrift. `NO_COLOR=1` unterdrückt ANSI-Farben.

## Was geschieht automatisch?

1. Proxmox, Architektur, VMID, Speicher, Bridge und USB-Bluetooth prüfen.
2. Offizielles generisches Debian-13-Image laden und SHA512 vergleichen.
3. Neue VM mit 2 vCPU, 1 GB RAM und 8 GB Disk erstellen.
4. Gewählten Bluetooth-USB-Port exklusiv zuordnen; WLAN bleibt ungenutzt.
5. Root-Passwort gehasht über Cloud-Init hinterlegen und die Gastinstallation starten.
6. BlueZ, PipeWire, WirePlumber, Squeezelite, Python-App und lokale Assets installieren.
7. HCI-Socket, Dienste und direkten Webzugang im Gast prüfen.

Die Quelle wird auf einen unveränderlichen Repository-Commit festgelegt. Der Installer lädt diesen Stand einmal für sich und denselben Stand für die Gastanwendung. Er verwendet keine fremden Installationsskripte.

## Optionen

```text
--vmid <NUMMER>             Standard: freie Cluster-ID
--hostname <NAME>           Standard: lyrion-player
--cores <ANZAHL>            Standard: 2
--memory <MB>               Standard: 1024
--disk <GB>                 Standard: 8
--storage <STORAGE-ID>      Standard: erster aktiver VM-Speicher
--bridge <BRIDGE>           Standard: vmbr0
--ip-config ip=dhcp         Standard: DHCP
--ip-config ip=<IP/CIDR>,gw=<GATEWAY>
--dns <IPv4>                Optionaler Resolver
--usb <USB-PORT>            Bei mehreren Adaptern erforderlich
--password-file <DATEI>     Für unbeaufsichtigte Installation
--allow-adapter-transfer    Übernahme trotz aktivem Host-BlueZ bestätigen
--wait-timeout <SEKUNDEN>   Standard: 1200
```

`LBP_REF` wählt vor dem Start einen Branch, Tag oder Commit des festen Repositories; Standard ist `main`. Namen werden validiert, der tatsächliche Stand anschließend auf die Git-SHA gepinnt.

Für eine unbeaufsichtigte Installation eine root-eigene Datei mit Modus 0600 verwenden, die ausschließlich das gewünschte VM-Passwort enthält. Passwort nicht als Kommandozeilenargument eingeben. Es wird nicht ausgegeben. Die Weboberfläche öffnet standardmäßig ohne Anmeldung; der root-Zugang dient der VM-Administration.

## Hoständerungen

Ein neuer VM-Gast, dessen Disk, genau eine USB-Zuordnung und ein eigener Storage-Eintrag `lyrion-bt-snippets` für Cloud-Init-Metadaten werden angelegt. Diese Änderungen gehören zum Self-Installer. Bestehende Gäste, WLAN und Host-BlueZ werden nicht gelöscht, umkonfiguriert oder deaktiviert. Keine globale AppArmor-/cgroup-Lockerung und keine HA-Konfiguration.

Cloud-Init-Metadaten liegen unter `/var/lib/vz/lyrion-bt-snippets/snippets/`, root-eigen mit Modus 0600. Sie enthalten den VM-Passwort-Hash, kein Klartextpasswort. Diese Dateien nicht veröffentlichen. Der Storage-Eintrag ist keine Anwendungssicherung.

## Andere Hardware

Die Erkennung prüft `btusb` oder USB-Klasse/Subklasse/Protokoll für Bluetooth. Hersteller-IDs und CPU-Modelle sind nicht fest vorgegeben. Der Gast erhält die Debian-Firmwarepakete für die üblichen Realtek-, Intel-, Atheros-, MediaTek- und Broadcom-Familien. Das konfiguriert keine WLAN-Verbindung. Bei fehlendem Adapter stoppt der Installer, bevor eine VM erstellt wird. Bei mehreren Geräten muss die Auswahl eindeutig sein. Firmwareanforderungen hängen vom konkreten Chip ab; Diagnosemeldungen bei fehlendem HCI im Gast nicht ignorieren.

## Wiederholung und Fehler

Ein bereits belegter VM-Identifier führt zum Abbruch. Der Self-Installer ersetzt keine bestehenden Gäste. Der direkte `install.sh` im Gast ist wiederholbar und erhält die vorhandene Konfiguration sowie das vorhandene Administratorkonto.

Bei einem Fehler bleibt ein bereits erstellter Gast zur Diagnose erhalten. In dessen Konsole `cloud-init status --long`, `journalctl` und die HCI-Prüfung aus der Bluetooth-Dokumentation ausführen. Eine automatische Löschung einer fehlgeschlagenen VM findet nicht statt.
