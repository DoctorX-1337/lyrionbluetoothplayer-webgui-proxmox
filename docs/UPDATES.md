# Updates aus dem öffentlichen Repository

Feste Quelle: [lyrionbluetoothplayer-webgui-proxmox](https://github.com/DoctorX-1337/lyrionbluetoothplayer-webgui-proxmox). Es werden weder private URLs noch lokale Zugangsdaten benötigt. Im laufenden Audiobetrieb findet keine automatische GitHub-Abfrage statt.

Die Oberfläche zeigt den installierten Commit aus `/opt/lyrion-bt-player/SOURCE_COMMIT`. „Nach Updates suchen“ fragt den Stand von `main` ab. „Update jetzt installieren“ schreibt ausschließlich eine validierte Git-SHA in eine lokale Anfrage. Ein systemd-Pathdienst startet den root-eigenen Updater, der denselben Commit erneut gegen das feste Repository validiert.

Das Archiv wird auf absolute Pfade, Pfadtraversal, Geräte und Symlinks geprüft. Danach aktualisiert der Updater den Anwendungscode, die Python-Abhängigkeiten, Datenbankmigrationen und Units. Er startet die Dienste neu und prüft die lokale HTTP-Erreichbarkeit. Konfiguration, Geräte und BlueZ-Pairing-Daten bleiben erhalten.

```bash
sudo lyrion-bt-update --check
sudo lyrion-bt-update
sudo systemctl status lyrion-bt-update.path
sudo journalctl -u lyrion-bt-update.service
```

Der Webprozess läuft niemals als root. Nur der eng begrenzte Update-Helper benötigt Rootrechte für Installation und systemd. Keine URL, kein Shellkommando und keine frei wählbare Quelle werden vom Browser angenommen. Ein Upstream-Codeupdate bedeutet bewusstes Vertrauen in dieses Projekt und dessen Maintainer.

Updates werden vorab im Staging entpackt. Bei Installationsfehlern wird ein klarer Fehlerstatus gezeigt; ein automatisches Zurückrollen von Paketinstallationen oder Datenbankmigrationen wird nicht zugesichert. Es gibt keine eigene Backup-Funktion; die reguläre PBS-Sicherung des Gasts bleibt dafür zuständig.
