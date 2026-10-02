# Lyrion Bluetooth Player

Ein lokaler Netzwerkplayer für einen vorhandenen **Lyrion Music Server**. Squeezelite empfängt Musik über Ethernet; PipeWire und WirePlumber geben sie an einen Bluetooth-A2DP-Lautsprecher aus. Die deutsche Weboberfläche verwaltet Lautsprecher, Kopplung, Standardausgabe, Lautstärke, Diagnose und Updates.

Der LMS wird **nicht** auf diesem Player installiert. Es gibt keine Cloud-Abhängigkeit für Wiedergabe oder Verwaltung. Nur Installation und ausdrücklich angeforderte Updates benötigen Paketquellen und dieses öffentliche Repository.

## Schnellinstallation auf Proxmox

Auf dem Proxmox-Node mit dem Bluetooth-Adapter als root:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/DoctorX-1337/lyrionbluetoothplayer-webgui-proxmox/main/pve-install.sh)"
```

Der Self-Installer fragt das Passwort für die neue VM verdeckt ab. Er erkennt USB-Bluetooth einschließlich des USB-Teils interner Combo-Karten, lädt das offizielle Debian-13-Image, prüft dessen SHA512-Prüfsumme, erstellt einen neuen Gast und installiert die komplette Anwendung. Bestehende Gäste werden nicht gelöscht. Hersteller und CPU-Modell sind nicht fest vorgegeben.

**Eine kleine Debian-VM ist der funktionierende Standard des Self-Installers.** Ein isolierter LXC-Netzwerknamespace hat im Linux-Kernel keinen AF_BLUETOOTH-Zugriff. USB-Geräteknoten-Passthrough und ein privilegierter Container beheben diese Grenze allein nicht. Der Installer erzeugt deshalb keinen LXC mit nur scheinbar sichtbarem Bluetooth. [Technische Erläuterung](docs/PROXMOX_BLUETOOTH.md).

Standard: 2 vCPU, 1 GB RAM, 8 GB Disk, DHCP, Bridge `vmbr0`, freie VMID. Für eigene Optionen das Skript herunterladen:

```bash
curl -fsSLo /tmp/lyrion-bt-install.sh \
  https://raw.githubusercontent.com/DoctorX-1337/lyrionbluetoothplayer-webgui-proxmox/main/pve-install.sh
bash /tmp/lyrion-bt-install.sh --storage <VM-SPEICHER> --bridge <LAN-BRIDGE> --usb <USB-PORT>
```

Details und unbeaufsichtigte Installation: [Self-Installer](docs/SELF_INSTALLER.md).

## 1. Übersicht

- Dashboard im Dark Mode mit grünen Akzenten, lokalen Logos und Favicons.
- Bluetooth-Suche mit Zeitlimit, Pairing-Agent für PIN, Passkey und Bestätigung.
- Mehrere gekoppelte Lautsprecher, genau eine gewählte Standardausgabe.
- Automatischer Reconnect mit 5, 10, 20, 30 und maximal 60 Sekunden Abstand.
- A2DP-Profilwahl, Audio-Routing und Testton ohne externe Audiodatei.
- Titel, Interpret, Album und Wiedergabesteuerung über die LMS-JSON-RPC-API.
- Direkter Webzugang im LAN ohne Anmeldung; optionale lokale Anmeldung mit Passwortwechsel. CSRF-Schutz bleibt aktiv.
- REST-API, SSE-Livestatus, CLI, systemd-Units und SQLite-Migrationen.
- Explizite Updates über dieses öffentliche Repository in Einstellungen oder per CLI.

## 2. Architektur

```text
Lyrion Music Server ── Ethernet ── Squeezelite
                                      │ ALSA-Pulse-Plugin
                                pipewire-pulse
                                      │
                                  PipeWire
                                      │ WirePlumber
                                  A2DP-Sink
                                      │
                             Bluetooth-Lautsprecher

Weboberfläche ── REST / SSE ── Webservice (lyrionbt)
                                     │ private Unix-Socket
                                Player-Manager (lyrionbt)
                                   ├── BlueZ D-Bus + Pairing-Agent
                                   ├── AudioManager
                                   ├── LyrionManager + Squeezelite-Unterprozess
                                   └── SQLite
```

Squeezelite wird zentral vom Manager nach Herstellung der Ausgabe gestartet und überwacht. Es gibt keinen konkurrierenden distributionsseitigen Squeezelite-Dienst. Die CLI spricht denselben Manager an. Root wird nur für Installation und einen ausdrücklich angeforderten Software-Updateprozess benötigt.

## 3. Voraussetzungen

Proxmox VE auf amd64, LAN-Bridge, Internet während Installation, VM-Speicher, ein USB-Bluetooth-Controller und ein vorhandener LMS. Internes Bluetooth wird bevorzugt. A2DP-Unterstützung des Lautsprechers ist erforderlich. Für direkte Debian-Installation werden amd64 und arm64 unterstützt.

## 4. Lenovo ThinkCentre M75q Gen 2

Ein möglicher Zielhost, aber keine Voraussetzung. Kein fester Bluetooth-Hersteller und keine Intel-Annahme. [Hardwarediagnose](docs/M75Q_GEN2.md).

## 5. Ethernet-Netzwerk

Proxmox, Player, LMS und Browser kommunizieren über das LAN. Die VM erhält eine IPv4-Adresse per DHCP oder statischer Cloud-Init-Konfiguration. Für stabilen Betrieb eine DHCP-Reservation oder feste Adresse verwenden. WLAN muss weder aktiv noch konfiguriert sein.

## 6. Internes WLAN-/Bluetooth-Modul

WLAN liegt häufig am PCIe-Bus, Bluetooth am USB-Bus. Nur den Bluetooth-Teil der VM zuordnen; die WLAN-Komponente bleibt ungenutzt. Bei mehreren Adaptern muss der Administrator einen auswählen. Externe Dongles sind ein technischer Fallback.

## 7. LXC erstellen

Ein Debian-13-LXC ist für Softwareentwicklung oder ein separates, bewusst geplantes Bluetooth-Backend geeignet, aber **kein direkt nutzbarer Bluetooth-Player im eigenen Netzwerknamespace**. Die Anwendung selbst verwendet keine Proxmox-spezifischen APIs. Der direkte Installer verweigert die Installation ohne echten HCI-Socketzugriff. [LXC-Einschränkungen und Privilegien](docs/PROXMOX_BLUETOOTH.md).

## 8. Hardware erkennen

```bash
bash proxmox-bluetooth-check.sh
lsusb
lsusb -t
lspci -nnk
rfkill list
bluetoothctl list
```

Das Diagnoseskript ist ausschließlich lesend und installiert keine Hostpakete.

## 9. Bluetooth zuordnen

```bash
qm set <VMID> --usb0 host=<USB-PORT>,usb3=0
```

Der USB-Port bleibt bei einer Änderung der Bus/Device-Nummer in der Regel stabil. Beim Umstecken oder Austausch den neuen Port prüfen. Eine VID:PID-Zuordnung ist bei identischen Geräten mehrdeutig. Host-BlueZ darf denselben Adapter nicht gleichzeitig verwalten. Der Self-Installer deaktiviert keine Hostdienste.

## 10. Direkte Installation im Debian-Gast

```bash
git clone https://github.com/DoctorX-1337/lyrionbluetoothplayer-webgui-proxmox.git
cd lyrionbluetoothplayer-webgui-proxmox
sudo bash install.sh
```

Ein zugänglicher HCI-Controller muss bereits vorhanden sein. Das generische Debian-VM-Image des Self-Installers enthält den vollständigen Kernel. Ein **genericcloud**-Image kann USB-/Bluetooth-Module vermissen; dann im Gast einen vollständigen Kernel und passende Firmware installieren, bevor der Anwendungsinstaller gestartet wird.

## 11. Erstkonfiguration

Webinterface im Browser unter `http://<PLAYER-IP>:8080` öffnen. Das Dashboard ist standardmäßig direkt ohne Benutzername oder Passwort zugänglich. Alle Geräte mit Netzwerkzugriff auf Port 8080 können den Player bedienen; den Zugriff deshalb auf das eigene LAN begrenzen. CSRF-Schutz bleibt auch ohne Anmeldung aktiv.

Der Self-Installer legt den interaktiv bestimmten **root-Zugang zur VM** an. Dieses Passwort dient der VM-Administration. SSH-Passwortanmeldung wird entsprechend diesem Installationsweg aktiviert; SSH und HTTP nur im lokalen Managementnetz freigeben.

Eine lokale Webanmeldung lässt sich bei Bedarf aktivieren: In `/etc/lyrion-bt-player/config.toml` unter `[application]` `auth_enabled=true` setzen, als root `lyrion-bt init-admin` ausführen und die Web-Unit mit `runuser -u lyrionbt -- env XDG_RUNTIME_DIR=/run/user/$(id -u lyrionbt) systemctl --user restart lyrion-bt-web` neu starten. Benutzer ist dann **admin**. Das zufällige Initialpasswort liegt ausschließlich in `/etc/lyrion-bt-player/secrets.env` (root, 0600); beim ersten Login muss es geändert werden.

## 12. Lyrion konfigurieren

In Einstellungen die LMS-Adresse und den HTTP-Port eingeben, Verbindung testen und speichern. Standardports: HTTP/JSON-RPC 9000 und SlimProto 3483. Der CLI-Port 9090 ist als Konfigurationsinformation vorgesehen; die Anwendung nutzt JSON-RPC. Ein optionaler fester Player-MAC-Wert sorgt für eine stabile LMS-Player-ID. Squeezelite meldet sich nach Wahl einer nutzbaren Standardausgabe automatisch beim LMS.

## 13. Lautsprecher koppeln

Lautsprecher in den Kopplungsmodus versetzen, Bluetooth → Geräte suchen → Koppeln. PIN- und Code-Anfragen erscheinen in einem Dialog. Nach erfolgreichem Pairing setzt der Manager Trust und speichert nur die Anwendungsdaten. BlueZ verwaltet die kryptografischen Kopplungsdaten.

## 14. Standardlautsprecher setzen

„Als Standard“ verbindet den neuen Lautsprecher, aktiviert A2DP, erkennt seinen Sink und verschiebt vorhandene Audiostreams. Die Datenbank wird erst nach erfolgreichem Routing umgestellt. Bei einem Fehler bleibt die bisherige Standardwahl erhalten; die vorherige Ausgabe wird nach Möglichkeit wiederhergestellt. Ein Container-/VM-Neustart ist nicht erforderlich.

## 15. Auto-Reconnect

Das gespeicherte Standardgerät wird beim Booten automatisch verbunden. Ein manuelles Trennen setzt Reconnect für dieses Gerät bis zum erneuten Verbinden oder zum nächsten Anwendungsstart aus. Ausgeschaltete Lautsprecher führen zu Wartezuständen statt einer schnellen Endlosschleife. Ein zurückkehrender Adapter wird dynamisch erkannt; bei mehreren Adaptern bevorzugt die stabile Adapter-MAC auswählen.

## 16. Fehlerdiagnose und CLI

```bash
sudo -u lyrionbt lyrion-bt check
sudo -u lyrionbt lyrion-bt status
sudo -u lyrionbt lyrion-bt devices
sudo -u lyrionbt lyrion-bt scan
sudo -u lyrionbt lyrion-bt connect <BLUETOOTH-MAC>
sudo -u lyrionbt lyrion-bt disconnect <BLUETOOTH-MAC>
sudo -u lyrionbt lyrion-bt default <BLUETOOTH-MAC>
sudo -u lyrionbt lyrion-bt test <BLUETOOTH-MAC>
sudo -u lyrionbt lyrion-bt restart-player
```

Benutzerdienste prüfen:

```bash
player_uid=$(id -u lyrionbt)
runuser -u lyrionbt -- env XDG_RUNTIME_DIR=/run/user/$player_uid \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$player_uid/bus \
  systemctl --user status lyrion-bt-manager lyrion-bt-web pipewire wireplumber
journalctl _UID="$player_uid" --since '-15 minutes'
```

Zusätzliche Logs: `/var/log/lyrion-bt-player/`, JSON-Format mit größenbasierter Rotation. Nicht vorhandene Akku-, RSSI- oder Codecwerte bleiben als „Nicht verfügbar“ markiert.

## 17. Firewall

Nur TCP 8080 und gegebenenfalls SSH aus dem eigenen Managementnetz erlauben. Der Player benötigt ausgehend TCP 3483 zu LMS, TCP 9000 zur JSON-RPC-API und gegebenenfalls UDP 3483 für Servererkennung; ein expliziter Server ist empfohlen. Außerdem DNS und NTP nach Bedarf. Paketquellen und GitHub sind nur während Installation/Update erforderlich. [Firewall und Sicherheit](docs/SECURITY.md).

## 18. Updates

Einstellungen → Software-Update → Nach Updates suchen → Update jetzt installieren. Der Updatecheck läuft **nicht** automatisch gegen GitHub. Für den Betrieb ist kein GitHub-Konto oder Token erforderlich. Ein root-eigener Helper lädt ausschließlich einen validierten Commit des festen öffentlichen Repositories. Die Webanwendung bleibt unprivilegiert.

```bash
sudo lyrion-bt-update --check
sudo lyrion-bt-update
journalctl -u lyrion-bt-update
```

Updates erhalten `/etc/lyrion-bt-player/` und `/var/lib/lyrion-bt-player/`. Die Dateien aus einer lokalen, geprüften Quellenkopie lassen sich mit `sudo bash update.sh` installieren. Kein automatisches Backup und kein unbeaufsichtigtes Update. [Updateverfahren](docs/UPDATES.md).

## 19. Deinstallation

```bash
sudo bash uninstall.sh
```

Das Skript fragt einzeln nach Beibehaltung von Konfiguration, Datenbank und Logs. Gemeinsam genutzte Systempakete, der Servicebenutzer und die BlueZ-Kopplungsdaten werden nicht automatisch entfernt.

## 20. Proxmox Backup Server

Die Anwendung benötigt kein eigenes Backup. Der vollständige Gast wird über Proxmox Backup Server gesichert. Persistente Pfade: `/etc/lyrion-bt-player/`, `/var/lib/lyrion-bt-player/` und `/var/log/lyrion-bt-player/`. Sicherungsjobs werden außerhalb dieser Anwendung administriert.

## 21. VM-Fallback

Auf üblichen Proxmox-LXC-Konfigurationen ist die VM wegen der nachgewiesenen Bluetooth-Namespace-Grenze der praktische Betriebsweg. Anwendung, UI und Datenmodell bleiben gleich. [VM-Anleitung](docs/VM_FALLBACK.md).

## 22. Migration und Cluster

**Dieser Gast ist hardwaregebunden.** Kein automatischer HA-Start auf einem Node ohne den zugeordneten Bluetooth-Adapter. Bei manueller Migration USB-Zuordnung und Firmware am Ziel neu prüfen. Replikation und PBS-Sicherung ersetzen keine verfügbare Funkhardware.

## Entwicklung und Tests

```bash
python3 -m venv .venv
.venv/bin/pip install '.[test]'
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app deploy scripts
find scripts -name '*.sh' -exec bash -n {} \;
```

Tests verwenden Mock-Bluetooth und Mock-Audio und benötigen keinen Adapter. Die CI prüft Python, kritische Backendfunktionen und Shellsyntax. [API-Dokumentation](docs/API.md). MIT-Lizenz, siehe [LICENSE](LICENSE).
