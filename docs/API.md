# REST API und Events

Öffentliche API unter `/api/`. Standardmäßig ist keine Anmeldung erforderlich. Zuerst `GET /api/auth/session` aufrufen, das gesetzte Cookie behalten und den zurückgegebenen `csrf`-Wert für Änderungen im Header `X-CSRF-Token` senden. Beispiele beziehen sich auf den Player; tatsächliche Adressen bleiben Benutzerkonfiguration.

Bei optional aktivierter Anmeldung: `POST /api/auth/login` mit `username` und `password`. Antwort enthält `csrf` und `must_change`; das Session-Cookie wird gesetzt. Falls `must_change=true`, zuerst `POST /api/auth/password` mit `old_password`, `new_password` und Header `X-CSRF-Token` ausführen. Danach denselben Header für alle Änderungen verwenden.

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/status` | Gesamter Status |
| GET | `/api/events` | SSE, Ereignistyp `status` |
| GET | `/api/bluetooth/devices` | Gespeicherte/entdeckte Geräte |
| POST | `/api/bluetooth/scan/start`, `/stop` | Suche starten/stoppen |
| POST | `/api/bluetooth/power` | JSON `powered: true/false` |
| POST | `/api/bluetooth/{mac}/pair` | Asynchrones Pairing |
| POST | `/api/bluetooth/{mac}/connect`, `/disconnect` | Verbindung |
| POST | `/api/bluetooth/{mac}/trust`, `/untrust` | Vertrauensstatus |
| POST | `/api/bluetooth/{mac}/default` | Transaktionaler Ausgabegerätewechsel |
| POST | `/api/bluetooth/{mac}/test` | Lokaler Testton |
| PATCH | `/api/bluetooth/{mac}` | Friendly Name, Auto-Connect, Lautstärke, Codec |
| DELETE | `/api/bluetooth/{mac}?confirm=true` | Kopplung und Anwendungsdaten entfernen |
| POST | `/api/pairing/{id}` | JSON `accepted`, optional `value` |
| GET | `/api/audio/status`, `/lyrion/status`, `/system/status` | Komponentenstatus |
| POST | `/api/audio/volume` | JSON `value`, 0–100, begrenzt durch Maximum |
| POST | `/api/lyrion/play`, `/pause`, `/stop`, `/next`, `/previous` | Wiedergabe |
| POST | `/api/lyrion/test` | LMS-Verbindung mit Settings-Payload testen |
| GET / PUT | `/api/settings` | Konfiguration lesen/speichern |
| GET | `/api/diagnostics` | Diagnose und Ereignisse |
| POST | `/api/services/{service}/restart` | Projektbezogene Dienste |
| GET | `/api/update/status` | Lokaler Updatezustand, kein externer Zugriff |
| POST | `/api/update/check` | Öffentlichen Repository-Stand prüfen |
| POST | `/api/update/install` | Geprüften Commit installieren |

Gerätenamen werden als Daten behandelt, MAC und Serveradressen validiert. Kein Endpoint nimmt Shellkommandos an. Dienstnamen sind auf Squeezelite, Bluetooth-Manager, PipeWire, WirePlumber, PipeWire Pulse und Weboberfläche begrenzt. Kein Host-Reboot-Endpoint.

SSE überträgt Statusänderungen einschließlich Discovery, Pairing-Anfragen, Wiedergabe und Reconnect. Fehlende Livewerte sind `null`, keine erfundenen Messwerte. Fehlerantworten enthalten `detail` und bei Managerfehlern einen maschinenlesbaren `code`.

Interne API und CLI verwenden denselben Manager über einen privaten Unix-Socket. Dieser Socket ist ausschließlich im Kontext des Servicebenutzers erreichbar; er ist kein öffentliches Debug-Interface.
