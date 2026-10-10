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

Auf dem Raspberry Pi 5 (Linux aarch64) wird eine geprüfte, stabile **Arduino CLI 1.5.1** ohne `sudo` installiert. Das Installationsskript prüft die offizielle SHA-256-Summe des ARM64-Archivs und bricht bei Abweichungen ab.

```bash
cd ~/Projekte/OpenNextion_Hermes_Dashboard
git pull --ff-only
bash scripts/pi/install-arduino-cli.sh
bash scripts/pi/firmware-preflight.sh
```

Arduino CLI liegt anschließend unter `~/.local/bin/arduino-cli`. Die Pi-Skripte ergänzen diesen Pfad vorübergehend in ihrer eigenen Umgebung, ohne `~/.bashrc` oder Systemverzeichnisse anzufassen. Für direkte CLI-Befehle in deinem Terminal optional einmalig:

```bash
export PATH="$HOME/.local/bin:$PATH"
arduino-cli version
```

Erst **danach**, als separater Schritt, ESP32-Arduino-Core und benötigte Bibliotheken installieren (Netzwerk-Download, benötigt entsprechend freien Speicherplatz):

```bash
bash scripts/pi/setup-arduino-toolchain.sh
```

Das Skript installiert ESP32-Arduino-Core **3.3.2**, LVGL **8.3.11**, ArduinoJson **7.4.2** und die benötigten GFX-, CST8XX- und PCF8574-Bibliotheken. Es führt keinerlei Flash-Vorgang aus und verändert keine Hermes-Installation.

Anschließend nur die Firmware kompilieren:

```bash
bash scripts/pi/firmware-build-offline.sh
```

Dieses Skript verweigert die Kompilierung, wenn eine private `firmware/HermesTouch/Config.h` vorhanden ist. Es verwendet ausschließlich die Offline-Demo und legt Binärdateien unter `build/firmware-offline` ab. **Es flasht niemals.**

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

## 5. Seriellen Port prüfen und Offline-Test flashen

Nach dem erfolgreich bestätigten Clean-Build liegen im Ordner
`build/firmware-offline/` die Bootloader-, Partitionen- und Applikationsdatei.
Beim Pi 5 wurde ein USB-Seriell-Wandler mit Herstellerkennung `1a86`
unter `/dev/ttyUSB0` gefunden. **Diese Kennung identifiziert nur einen
USB-Seriell-Adapter und beweist noch nicht, dass es das OpenNextion ist.**

Vor jeglichem Flashen den Anschluss **physisch prüfen**: Gerät abziehen,
`ls -l /dev/serial/by-id/` aufrufen, OpenNextion wieder anschließen und die
neu erscheinende Zuordnung kontrollieren. Vorhandene serielle Geräte nicht
blind überschreiben.

```bash
cd ~/Projekte/OpenNextion_Hermes_Dashboard
git pull --ff-only
ls -l /dev/serial/by-id/
arduino-cli board list
```

Falls das OpenNextion nach diesem Verfahren tatsächlich unter dem
folgenden Pfad erscheint, kann das Upload-Skript verwendet werden:

```bash
bash scripts/pi/firmware-upload-offline.sh \
  /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0
```

Das Skript prüft vorhandene Firmware-Artefakte und Zugriffsrechte. **Es flasht
erst nach der ausdrücklich eingegebenen Bestätigung
`FLASH-OPENNEXTION`.** Das vorhandene Geräteprogramm wird dabei ersetzt.
Der Aufruf startet keine Neukompilierung, verändert keine Hermes-Dienste
und verwendet kein WLAN-Token.

Falls USB-Zugriffsrechte fehlen, zunächst nur diagnostizieren:

```bash
ls -l /dev/ttyUSB0
id -nG
```

Nicht ungeprüft mit `sudo` flashen. Ein Gruppenwechsel (typischerweise
`dialout`) wäre ein separater, bewusst ausgeführter Einrichtungsschritt.

Nach erfolgreichem Flashen:
- Display zeigt `HERMES TOUCH | TEST`.
- `DEMO: WLAN deaktiviert` erscheint.
- PSRAM und freier Heap haben sinnvolle Werte.
- Der Button `Aktualisieren` erhöht den Touch-Zähler.
- Serielle Debug-Ausgabe läuft mit 115200 Baud.

Wenn Upload oder Start scheitert, zuerst den vollständigen seriellen
Fehlerbericht bzw. ein Foto des Displays prüfen, bevor Einstellungen oder
Pins geändert werden.

## 6. Netzwerk erst im nächsten Schritt

Zur Aktivierung der Live-Daten wird `Config.h.example` später lokal als `Config.h` kopiert. Ein konkreter privater Bridge-Endpunkt sowie ein Geräte-Token werden dann benötigt. `Config.h` ist in `.gitignore` aufgenommen und darf nicht nach GitHub gelangen.

**Sicherheit:** Aktuell spricht der Client HTTP, nicht HTTPS; ein Token allein schützt die Übertragung **nicht** vor Mitschnitt auf dem WLAN. Deswegen vor Freischalten der Netzwerkvariante einen passenden authentifizierten und verschlüsselten Transport einrichten. Keine Router-Portweiterleitung und niemals den Hermes-API-Key auf dem ESP32 ablegen.
