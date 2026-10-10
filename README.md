# OpenNextion Hermes Dashboard

**Hermes Touch** – ESP32-S3 Touchscreen für den vorhandenen Hermes-Agent auf dem Raspberry Pi 5.

**Stand: v0.1 – Status-MVP.** Quellcode im Repository; Bridge-Tests laufen automatisiert. Hardware-Build und Installation auf dem Pi sind noch **nicht** nachgewiesen.

## Architektur

```
ONX3248G035 (ESP32-S3 / LVGL)
    │  WLAN, HTTP/JSON, gerätespezifisches Token
    ▼
Pi 5: Hermes-Touch-Bridge (:8765)
    ├── Linux-Systemdaten (/proc, /sys) – nur lesen
    └── optionaler Dashboard-Reachability-Check (localhost:9119)
        [bestehender Hermes-Agent bleibt unverändert]
```

Die erste Version enthält **keine Befehle zum Starten, Stoppen oder Ändern von Hermes**. Chat ist **aus Sicherheitsgründen noch nicht freigeschaltet**. Der offizielle Hermes-API-Server gewährt einem Client potenziell Zugriff auf sämtliche Agent-Tools – daher keine direkte API-Key-Weitergabe an ESP32-Geräte.

## Schnellstart Raspberry Pi

```bash
cd ~/Projekte
git clone https://github.com/mason82-dotcom/OpenNextion_Hermes_Dashboard.git
cd OpenNextion_Hermes_Dashboard
bash scripts/pi/doctor.sh
python3 -m unittest discover -s tests -v
bash scripts/pi/create-local-config.sh
bash scripts/pi/run-local.sh
```

Anschließend im zweiten Terminal auf dem Pi:

```bash
cd ~/Projekte/OpenNextion_Hermes_Dashboard
set -a; . config/bridge.env; set +a
curl --fail-with-body -sS -H "X-Hermes-Touch-Token: $HERMES_TOUCH_TOKEN" http://127.0.0.1:8765/v1/status
```

`config/bridge.env` bleibt **lokal** und wird nicht versioniert. Das erzeugte Token wird nicht in GitHub gespeichert. Die Bridge bindet zunächst ausschließlich an `127.0.0.1`. Für das Display muss später eine abgesicherte Verbindung vom WLAN zum Pi eingerichtet werden; eine öffentliche Portfreigabe ist **nicht** zulässig.

## Firmware

Unter `firmware/HermesTouch/`:

1. `Config.h.example` lokal nach `Config.h` kopieren.
2. WLAN-SSID, WLAN-Passwort, Bridge-URL und **Bridge-Gerätetoken** eintragen, **niemals den Hermes-API-Key**.
3. Arduino IDE 2.x: Board **ESP32S3 Dev Module**, Flash **16 MB**, PSRAM **OPI**, Partition **16 MB (3MB APP/9.9MB FATFS)**.
4. Bibliotheken: **GFX Library for Arduino**, **Adafruit CST8XX**, **Adafruit PCF8574**, **lvgl 8.3.x**, **ArduinoJson 7.x**.
5. `HermesTouch.ino` kompilieren und auf das OpenNextion ONX3248G035 übertragen.

Vor dem Flashen bei Problemen bitte die offiziellen Beispiele `01_touch_test` und `09_outofbox_demo` testen:
https://github.com/OpenNextion/OpenNextion-SKU-ONX3248G035

## Entwicklung auf dem Pi

Siehe [docs/PI-SETUP.md](docs/PI-SETUP.md). Die Dateien können auf dem Pi per `git pull --ff-only` synchronisiert werden; installierte Agent-Dateien unter `~/.hermes` werden dabei nicht angerührt.

## Geplante Ausbaustufen

- v0.1: Statusanzeige, sichere lokale Grundkonfiguration, Tests
- v0.2: realer Firmware-Build, LVGL-Touchtest und WLAN-Verbindung
- v0.3: gesicherter Device-to-Pi-Transport, Gateway- und Task-Status
- v0.4: kontrollierter Chat über Hermes-API mit separater Freigabe
- v0.5: Mikrofon/Lautsprecher und optionaler Sprachdialog

Lizenz: noch festzulegen.
