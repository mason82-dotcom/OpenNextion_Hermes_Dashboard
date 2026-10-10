# OpenNextion Hermes Dashboard

**Hermes Touch** – ESP32-S3 Touchscreen für den vorhandenen Hermes-Agent auf dem Raspberry Pi 5.

**Stand: v0.4 – Status-MVP + Offline-Hardware-Test.** Quellcode im Repository; Der Anwender hat die Status-Bridge und den Hermes-API-Healthcheck auf seinem Pi erfolgreich getestet. Neue v0.3-Änderungen und der Firmware-Build sind noch **nicht** auf Hardware bestätigt.

## Architektur

```
ONX3248G035 (ESP32-S3 / LVGL)
    │  WLAN, HTTP/JSON, gerätespezifisches Token
    ▼
Pi 5: Hermes-Touch-Bridge (:8765)
    ├── Linux-Systemdaten (/proc, /sys) – nur lesen
    ├── Hermes API /health (localhost:8642) – nur lesen
    └── Dashboard /api/status und /api/health (localhost:9119) – nur lesen
        [bestehender Hermes-Agent bleibt unverändert]
```

Die erste Version enthält **keine Befehle zum Starten, Stoppen oder Ändern von Hermes**. Chat ist **aus Sicherheitsgründen noch nicht freigeschaltet**. Der offizielle Hermes-API-Server gewährt einem Client potenziell Zugriff auf sämtliche Agent-Tools – daher keine direkte API-Key-Weitergabe an ESP32-Geräte.

## Schnellstart Raspberry Pi

```bash
cd ~/Projekte
git clone https://github.com/mason82-dotcom/OpenNextion_Hermes_Dashboard.git
cd OpenNextion_Hermes_Dashboard
bash scripts/pi/doctor.sh
python3 scripts/pi/diagnose-dashboard.py  # zeigt keine Antwortinhalte oder Schlüssel
python3 -m unittest discover -s tests -v
bash scripts/pi/create-local-config.sh
bash scripts/pi/run-local.sh
```

Anschließend im zweiten Terminal auf dem Pi (oder mit `bash scripts/pi/smoke-status.sh` den Verbindungsstatus beider Hermes-Komponenten prüfen):

```bash
cd ~/Projekte/OpenNextion_Hermes_Dashboard
set -a; . config/bridge.env; set +a
curl --fail-with-body -sS -H "X-Hermes-Touch-Token: $HERMES_TOUCH_TOKEN" http://127.0.0.1:8765/v1/status
```

`config/bridge.env` bleibt **lokal** und wird nicht versioniert. Das erzeugte Token wird nicht in GitHub gespeichert. Die Bridge bindet zunächst ausschließlich an `127.0.0.1`. Für das Display muss später eine abgesicherte Verbindung vom WLAN zum Pi eingerichtet werden; eine öffentliche Portfreigabe ist **nicht** zulässig.

## Firmware: zuerst sicherer Offline-Test

Die Firmware liegt unter `firmware/HermesTouch/`. **Ohne `Config.h`** startet sie im Offline-Testmodus und versucht **keine** WLAN-, Hermes- oder API-Verbindung. Auf dem Display erscheinen ein Testbildschirm, PSRAM-/Heap-Informationen sowie ein Touch-Zähler. Der Button „Aktualisieren“ muss den Zähler erhöhen.

Zum hardwareseitigen Test: [Schritt-für-Schritt-Anleitung](docs/BOARD-BRINGUP.md). Auf dem Raspberry Pi 5:

```bash
git pull --ff-only
bash scripts/pi/install-arduino-cli.sh     # geprüftes v1.5.1 Linux ARM64 Binary
bash scripts/pi/firmware-preflight.sh
bash scripts/pi/setup-arduino-toolchain.sh  # großer Paketdownload
bash scripts/pi/firmware-build-offline.sh   # baut, flasht NICHT
```

Diese Skripte benötigen kein `sudo` und greifen nicht in laufende Hermes-Dienste ein.

Ein GitHub-Actions-Build mit ESP32-Arduino-Core 3.3.2, LVGL 8.3.11 und ArduinoJson 7.4.2 prüft künftig beide Codepfade: [Firmware-Builds](https://github.com/mason82-dotcom/OpenNextion_Hermes_Dashboard/actions/workflows/firmware-build.yml). **Ein grüner Build ist vorerst noch nicht verifiziert.**

Board-Einstellungen: ESP32S3 Dev Module, 16MB Flash, OPI PSRAM, 16M Flash (3MB APP/9.9MB FATFS). Benötigte Libraries: GFX Library for Arduino, Adafruit CST8XX Library und Adafruit PCF8574.

**Nicht vorzeitig vernetzen:** `Config.h.example` dient später als Vorlage für eine lokale `Config.h`, niemals den Hermes-API-Key eintragen. Der derzeitige HTTP-Client verschlüsselt das WLAN-Token nicht. Produktiver Betrieb erst nach Einführung eines sicheren Transports.

## Entwicklung auf dem Pi

Siehe [docs/PI-SETUP.md](docs/PI-SETUP.md). Die Dateien können auf dem Pi per `git pull --ff-only` synchronisiert werden; installierte Agent-Dateien unter `~/.hermes` werden dabei nicht angerührt.

## Geplante Ausbaustufen

- v0.1–0.2: Statusanzeige, Hermes-API- und Dashboard-Healthchecks, sichere lokale Grundkonfiguration, Tests
- v0.3: Diagnosecodes, Fallback-Healthcheck und Hintergrundabfragen; Systemstatus-Anfragen warten nicht auf das Dashboard
- Nächster Schritt: realer Firmware-Build, LVGL-Touchtest und WLAN-Verbindung
- v0.3: gesicherter Device-to-Pi-Transport, Gateway- und Task-Status
- v0.4: kontrollierter Chat über Hermes-API mit separater Freigabe
- v0.5: Mikrofon/Lautsprecher und optionaler Sprachdialog

Lizenz: noch festzulegen.
