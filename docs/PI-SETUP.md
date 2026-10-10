# Raspberry Pi 5: Installation und Entwicklung

Diese Anleitung ist **nicht** auf dem Pi ausgeführt worden. Sie verändert nicht die bestehende Hermes-Installation.

## Verzeichnis

```bash
mkdir -p ~/Projekte
cd ~/Projekte
git clone https://github.com/mason82-dotcom/OpenNextion_Hermes_Dashboard.git
cd OpenNextion_Hermes_Dashboard
```

Falls das Repository bereits geklont wurde: `git status --short` überprüfen und anschließend `git pull --ff-only`. Vorhandene lokale Änderungen nicht verwerfen.

## Prüfen, testen, lokal starten

```bash
bash scripts/pi/doctor.sh
python3 -m unittest discover -s tests -v
bash scripts/pi/create-local-config.sh
bash scripts/pi/run-local.sh
```

Die Bridge läuft **nur im aktuellen Terminal**, nicht als neuer systemd-Dienst. Stoppen mit Strg+C. Eine zweite Shell kann den Status abrufen:

```bash
cd ~/Projekte/OpenNextion_Hermes_Dashboard
set -a; . config/bridge.env; set +a
curl -fsS -H "X-Hermes-Touch-Token: $HERMES_TOUCH_TOKEN" http://127.0.0.1:8765/v1/status
```

## Zusätzlicher Status-Smoke-Test

In einem zweiten Terminal `bash scripts/pi/smoke-status.sh` ausführen. Das Skript zeigt nur reduzierte Statusinformationen und niemals den Bridge-Token oder Hermes-Konfigurationswerte. Der Hermes-API-Healthcheck auf Port 8642 erfordert laut Hersteller keinen API-Schlüssel. Er bestätigt nur Liveness, nicht Tool-Berechtigungen oder Modellverfügbarkeit.

## WLAN-Gerät anbinden (später)

Nur für den späteren Hardwaretest: Binding auf die **konkrete private IP-Adresse** des Pi umstellen. Keine Portweiterleitung im Router konfigurieren. Der HTTP-Header mit dem Gerätetoken ist auf einem nicht vertrauenswürdigen WLAN abhörbar. Für den dauerhaften Betrieb sind TLS/Proxydienst mit validiertem Zertifikat, eingeschränkte Firewallregeln und begrenzte Geräteberechtigungen vorgesehen.

Der Token ist **nicht** der Hermes-API-Key und darf nur auf Pi und Gerät liegen. `Config.h` und `config/bridge.env` werden durch `.gitignore` ausgeschlossen.

## Diagnose

- `/v1/status`: authentifizierte JSON-Statusdaten des Pi
- `hermes.dashboard_reachable`: nur Statusantwort des Dashboards, **keine** vollständige Prüfung des Hermes-Gateways
- `hermes.api_healthy`: öffentlicher Hermes-API-/health-Endpunkt liefert Status `ok`, **kein** Modelltest
- `/v1/chat`: absichtlich gesperrt (HTTP 403)
- Keine Admin-, Shell-, Konfigurations- oder Dateisystem-Write-Endpunkte

Für Chat muss erst der tatsächliche Hermes-API-Server (normalerweise Loopback-Port 8642, mit API_SERVER_KEY) überprüft und eine sichere, explizit freigegebene Integration implementiert werden.
