# Lokaler Zugriff und Firewall

Die Anwendung bindet standardmäßig an `0.0.0.0:8080`. Port 8080 nur aus dem eigenen LAN/Managementnetz freigeben. HTTP wird ausschließlich im lokalen Netz verwendet; bei TLS über einen eigenen Reverse Proxy `cookie_secure=true` einstellen. Keine öffentliche Portfreigabe.

Die Weboberfläche öffnet standardmäßig ohne Anmeldung (`auth_enabled=false`). Jeder Rechner mit Zugriff auf den Webport kann den Player bedienen. Mutationen benötigen weiterhin einen CSRF-Token und weisen fremde Origins zurück. Cookies haben HttpOnly und SameSite=Strict. Zugangsdaten stehen nicht in API-Antworten oder Anwendungslogs.

Optional kann `auth_enabled=true` gesetzt werden; die Aktivierung ist im README beschrieben. Passwort-Hashes verwenden dann scrypt; Sessions sind zufällig, zeitlich begrenzt und serverseitig widerrufbar. Beim Passwortwechsel werden andere Sitzungen widerrufen.

## Netzwerkverkehr

| Richtung | Zweck | Port |
|---|---|---|
| Managementnetz → Player | Weboberfläche | TCP 8080 |
| Managementnetz → Player | optionale Administration | TCP 22 |
| Player → LMS | SlimProto | TCP 3483 |
| Player ↔ LMS | optionale Discovery | UDP 3483 |
| Player → LMS | JSON-RPC / HTTP | TCP 9000, konfigurierbar |
| Player → eigene Resolver / Zeitserver | DNS / NTP | nach lokalem Netzkonzept |
| Player → Paketquellen / GitHub | ausschließlich Installation/Update | HTTPS; distributionsabhängige Paketquellen |

Kein zusätzlicher eingehender Audiostream-Port wird pauschal freigegeben. Der Player startet die Verbindung zum angegebenen LMS. HTTP-Port und SlimProto-Port können für abweichende Serverkonfigurationen geändert werden.

## Proxmox-Firewall-Beispiel

Die Platzhalter vor Anwendung ersetzen. Bestehende Regeln zuerst prüfen; die Anwendung installiert keine pauschale Firewallregel automatisch.

```ini
[OPTIONS]
enable: 1

[RULES]
IN ACCEPT -source <MANAGEMENT-CIDR> -p tcp -dport 8080
IN ACCEPT -source <MANAGEMENT-CIDR> -p tcp -dport 22
```

Der Self-Installer setzt das Firewall-Flag an der Gast-Netzwerkkarte. Dies ersetzt nicht ein eingerichtetes Cluster-/Node-/Gast-Regelwerk.

## Optionaler HTTPS-Reverse-Proxy

Eine vorhandene Nginx-Instanz kann HTTPS mit ihrem eigenen Zertifikat terminieren und auf `http://<PLAYER-IP>:8080` weiterleiten. Für Livestatus/SSE `proxy_buffering off`, HTTP/1.1 und einen langen `proxy_read_timeout` setzen. Der Proxy muss `Host` erhalten und `X-Forwarded-Proto https` setzen. Eine eigene virtuelle Hostkonfiguration verhindert, dass die Adresse auf den Standardserver des Proxys fällt.

Auf dem Player in `/etc/systemd/user/lyrion-bt-web.service.d/10-reverse-proxy.conf` ausschließlich die tatsächliche Proxy-Adresse freigeben:

```ini
[Service]
Environment=FORWARDED_ALLOW_IPS=127.0.0.1,<PROXY-IP>
```

Anschließend die User-Units neu laden und den Webdienst neu starten. So erkennt die API HTTPS korrekt und prüft den Browser-Origin weiterhin. Keine pauschale Freigabe mit `*` setzen. Dieser lokale systemd-Drop-in bleibt bei Repository-Updates erhalten. Bei ausschließlichem HTTPS-Zugriff kann zusätzlich `cookie_secure=true` gesetzt werden; Cookies werden dann über direktes HTTP nicht übertragen.

## Persistenz und Berechtigungen

Konfiguration: root:lyrionbt, 0640. Initialpasswort: root, 0600. SQLite-Dateien: lyrionbt, 0600. Unix-Manager-Socket liegt im privaten Runtime-Verzeichnis des Servicebenutzers. Anwendungscode und root-eigene Updateprogramme sind für diesen Benutzer nicht schreibbar.

Das Update-Runtime-Verzeichnis ist root-eigen mit Sticky-Bit und Gruppenrecht für lyrionbt. Der Updater liest Anfragen mit `O_NOFOLLOW`, validiert ausschließlich eine Git-SHA und akzeptiert keine Kommandos. Der Player und die Weboberfläche laufen als `lyrionbt`, nicht als root.
