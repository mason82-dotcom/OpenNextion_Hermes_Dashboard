# OpenNextion ONX3248G035 – hardware bring-up (v0.4)

## Ziel und Sicherheit

Zuerst **ohne WLAN-Zugangsdaten oder Hermes-Token** nur Grafik, Displayausrichtung, Touch, Flash und PSRAM verifizieren. Die Firmware baut sich ohne `Config.h` automatisch als Offline-Demo. In diesem Modus sind sämtliche Hermes- und WLAN-Zugriffe deaktiviert.

Ein erfolgreicher Compile-Job beweist **nicht**, dass das Board richtig verdrahtet ist oder dass der Touch reagiert. Hardwaretests müssen am tatsächlichen ONX3248G035 durchgeführt werden.

## 1. Projekt aktualisieren

```bash
cd ~/Projekte/OpenNextion_Hermes_Dashboard
git status --short
git pull --ff-only
python3 -m unittest discover -s tests -v
```

## 2. CI-Build prüfen

Die GitHub Action `.github/workflows/firmware-build.yml` baut zwei Varianten:
- **Offline-Demo** ohne `Config.h`, ohne geheime Daten oder Netzwerkzugriff.
- **Connected-Compile** mit `Config.h.example` (nur Platzhalterwerte; wird nicht geflasht).

Die ersten Builds müssen in GitHub Actions grün werden, bevor man von einer erfolgreich kompilierten Firmware sprechen kann:
https://github.com/mason82-dotcom/OpenNextion_Hermes_Dashboard/actions/workflows/firmware-build.yml

## 2a. Offline-Build direkt auf dem Raspberry Pi 5

Die Pi-Installation ist unabhängig vom laufenden Hermes-Agent. Zuerst ohne Änderungen prüfen:

```bash
cd ~/Projekte/OpenNextion_Hermes_Dashboard
bash scripts/pi/firmware-preflight.sh
```

Falls die Arduino CLI bereits installiert ist, aber der ESP32-Core oder Bibliotheken fehlen, installiere sie **ausdrücklich** mit diesen Befehlen (lädt Pakete aus dem Internet, benötigt freien Speicherplatz):

```bash
arduino-cli core update-index --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core install esp32:esp32@3.3.2 --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli lib install "GFX Library for Arduino"
arduino-cli lib install "Adafruit CST8XX Library"
arduino-cli lib install "Adafruit PCF8574"
arduino-cli lib install "ArduinoJson@7.4.2"
arduino-cli lib install "lvgl@8.3.11"
```

Falls `arduino-cli` noch nicht installiert ist, zunächst das offiziell bereitgestellte Binary für Linux ARM64 installieren: https://arduino.github.io/arduino-cli/latest/installation/ . Die Pi-Preflight-Diagnose ändert keine Pakete.

Erst danach das eigentliche Offline-Projekt kompilieren:

```bash
bash scripts/pi/firmware-build-offline.sh
```

Dieses Skript verweigert den Build, wenn eine private `firmware/HermesTouch/Config.h` vorhanden ist. Es verwendet ausschließlich die Offline-Demo und legt Dateien unter `build/firmware-offline` ab. **Es flasht niemals.** Die Firmware muss anschließend gezielt über den erkannten seriellen Anschluss mit der Arduino CLI oder IDE übertragen werden.

## 3. Arduino IDE (alternativ, manuell)

Hersteller-Beispiele: https://github.com/OpenNextion/OpenNextion-SKU-ONX3248G035

Benötigt werden:
- ESP32 Boardpaket, ESP32S3 Dev Module (CI zunächst esp32 core 3.3.2)
- Flash Size: **16MB**
- PSRAM: **OPI PSRAM**
- Partition Scheme: **16M Flash (3MB APP/9.9MB FATFS)**
- LVGL **8.3.x**, ArduinoJson **7.x**
- GFX Library for Arduino, Adafruit CST8XX Library, Adafruit PCF8574

Öffne `firmware/HermesTouch/HermesTouch.ino` als Sketch; `Config.h` für den Offline-Test **nicht** anlegen. Das Gerät zeigt beim Start `HERMES TOUCH | TEST`, `DEMO: WLAN deaktiviert`, `LVGL: aktiv`, die PSRAM-Größe und freien Heap. Der Button **Aktualisieren** erhöht `Touch-Eingaben`. Das bestätigt, dass der Touch-Callback mit LVGL arbeitet.

Serial-Monitor auf 115200 Baud aktivieren. Erwartete Meldung: `HERMES TOUCH: OFFLINE DEMO (no credentials / no network)`.

## 4. Hardwarecheck

1. Sichere USB-Datenverbindung zwischen Board und Entwicklungssystem herstellen.
2. Board-Port unter Tools auswählen; bei Linux ggf. `ls -l /dev/serial/by-id/` überprüfen.
3. Test-Firmware aus der IDE kompilieren und flashen.
4. Foto vom Display oder die Ergebnisse für Display, Ausrichtung, Touch, PSRAM melden.
5. Falls Bildschirm weiß/schwarz bleibt, zuerst offizielles Beispiel `09_outofbox_demo` und Touch-Test `01_touch_test` verwenden.

**Nicht** wahllos Board-Pins oder Spannungen ändern. Das LCD-Reset läuft über den PCF8574, und die Touch-I²C-Adresse ist board-spezifisch.

## 5. Netzwerk erst im nächsten Schritt

Zur Aktivierung der Live-Daten wird `Config.h.example` später lokal als `Config.h` kopiert. Ein konkreter privater Bridge-Endpunkt sowie ein Geräte-Token werden dann benötigt. `Config.h` ist in `.gitignore` aufgenommen und darf nicht nach GitHub gelangen.

**Sicherheit:** Aktuell spricht der Client HTTP, nicht HTTPS; ein Token allein schützt die Übertragung **nicht** vor Mitschnitt auf dem WLAN. Deswegen vor Freischalten der Netzwerkvariante einen passenden authentifizierten und verschlüsselten Transport einrichten. Keine Router-Portweiterleitung und niemals den Hermes-API-Key auf dem ESP32 ablegen.
