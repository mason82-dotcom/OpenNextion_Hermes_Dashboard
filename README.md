# OpenNextion Hermes Dashboard

**Hermes Touch** – ESP32-S3 Touchscreen für den vorhandenen Hermes-Agent auf dem Raspberry Pi 5.

**Stand: v0.5 – Touch-Dashboard auf echter Hardware bestätigt.** Vier Seiten (Status, Graph, System, Chat) laufen sichtbar auf dem ONX3248G035. Display, Touch, Graph und 8192 KB PSRAM sind nachgewiesen. Die Pi-Bridge und Hermes-Healthchecks funktionieren. Eine nachfolgende kleine Korrektur an der Graph-Beschriftung ist noch nicht neu kompiliert/geflasht.

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

## Firmware v0.5: vier Seiten im sicheren Offline-Modus

Die neue Oberfläche unter `firmware/HermesTouch/` zeigt **STATUS**, **GRAPH**, **SYSTEM** und **CHAT**.

- **STATUS:** Lokaler ESP32-Heap, PSRAM, Laufzeit und Touch-Aktionen.
- **GRAPH:** Echte Heap-Messwerte als 24-Punkte-LVGL-Verlauf; Zurücksetzen per Touch.
- **SYSTEM:** Display-/Controller-Infos und aktuelle ESP32-Speicherwerte.
- **CHAT:** Sichtbar, aber technisch gesperrt – keinerlei Schreibzugriffe oder Nachrichtenversand.

**Ohne `Config.h`** bleibt die Firmware vollständig offline: kein WLAN, kein HTTP, kein Hermes-Zugriff. Insbesondere gibt es **keine simulierten Pi-Livedaten**. Der Nutzer hat inzwischen auch alle vier Seiten der neuen v0.5-Firmware fotografisch auf dem Display bestätigt.

Anleitung für Build, Flashen und die vier Touchseiten:
[**v0.5 Touch-Test**](docs/V0.5-TOUCH-TEST.md).

```bash
cd ~/Projekte/OpenNextion_Hermes_Dashboard
git pull --ff-only
python3 -m unittest discover -s tests -v
bash scripts/pi/firmware-build-offline.sh
# Erst nach erfolgreichem Build und USB-Geräteprüfung:
bash scripts/pi/firmware-upload-offline.sh \
  /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0
```

Dieses Upload-Skript erfordert eine ausdrückliche Bestätigung. Die bereits installierte Pi-Toolchain bleibt auf ESP32-Core **3.3.2**, LVGL **8.3.11** und ArduinoJson **7.4.2** fixiert. Nach einem früheren Core-Linkerfehler hat ein Clean-Build funktioniert. Auch die GitHub-Action nutzt deshalb `--clean`: [Firmware-Builds](https://github.com/mason82-dotcom/OpenNextion_Hermes_Dashboard/actions/workflows/firmware-build.yml).

Die **Live-Anbindung** an den Pi ist eine spätere, getrennte Entwicklungsstufe: Der aktuelle Client-Code für den Verbindungstest verwendet noch unverschlüsseltes HTTP und darf nicht als sichere produktive WLAN-Verbindung betrachtet werden. Hermes-API-Schlüssel gehören niemals auf den ESP32.

## Entwicklung auf dem Pi

Siehe [docs/PI-SETUP.md](docs/PI-SETUP.md). Die Dateien können auf dem Pi per `git pull --ff-only` synchronisiert werden; installierte Agent-Dateien unter `~/.hermes` werden dabei nicht angerührt.

## Entwicklungsstand und nächste Schritte

- v0.1–v0.3: read-only Python-Bridge auf dem Pi, Hermes-API- und Dashboard-Healthchecks, Status-Endpunkt und automatisierte Tests
- v0.4: nachweislich erfolgreicher ESP32-S3-Clean-Build; Display und Touch auf realer ONX3248G035-Hardware getestet
- v0.5: vier LVGL-Touchseiten, lokaler Messverlauf, Systemseite und gesperrter Chat-Platzhalter – **fotografisch auf dem ONX3248G035 bestätigt**; kleinere Zähler-Korrektur noch zu testen
- Nächste Etappe: robuste Geräte-Telemetrie, TLS/Authentifizierung, echte Pi-Livewerte; erst danach ein eingeschränkter Chat-Modus

Lizenz: noch festzulegen.
