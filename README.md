# OpenNextion Hermes Dashboard

**Hermes Touch** – ESP32-S3 Touchscreen für den vorhandenen Hermes-Agent auf dem Raspberry Pi 5.

**Aktueller Hardwarestand (11.10.2026):** **v0.8.3 läuft auf dem OpenNextion ONX3248G035**, nach **130/130 Pi-Tests**, erfolgreichem Connected-Build und manuellen Hardwareprüfungen: PDM-Mikrofon, PCM-/PSRAM-Diagnose, PTT-Timeout, **hörbarer NS4168-Testton**, `SPK: OK 1`, weiter reagierender Mikrofonpegel und `TLS OK`. Der Textchat und alle Hermes-Schreibzugriffe sind gesperrt. **Neu im GitHub-Quellcode: v0.8.4-Kandidat**, noch **nicht** auf dem Pi getestet, kompiliert oder geflasht: **Landscape 480x320**, fünf separate Tabs **STATUS / GRAPH / SYSTEM / CHAT / SPRACHE**, eigener SPRACHE-Tab mit PTT, PCM-Diagnose, Lautsprecher-Testton, Lautstärkeregler und STOP-Taste; Chat bleibt ein eigener deaktivierter Text-Tab. Es werden **141 Tests** sowie ein erneuter Connected-Build erwartet. Kein automatischer Flash und weiterhin keine Audioübertragung oder Hermes-TTS.

## Architektur

```
ONX3248G035 (ESP32-S3 / LVGL)
    │  WLAN / HTTPS (lokale CA, gültige Zeit, Geräte-Token)
    ▼
Pi 5: TLS-Statusdienst (private LAN-IP:8766) – GET ONLY
    │  ausschließlich lokales HTTP über Loopback
    ▼
Pi 5: Hermes-Touch-Bridge (127.0.0.1:8765)
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

`config/bridge.env` bleibt **lokal** und wird nicht versioniert. Das erzeugte Token wird nicht in GitHub gespeichert. Die Bridge bindet zunächst ausschließlich an `127.0.0.1`. Die v0.6-TLS-Schicht erlaubt verschlüsselten Read-only-Zugriff im privaten LAN, sobald sie lokal eingerichtet und getestet wurde. Eine öffentliche Portfreigabe ist **nicht** zulässig.

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

## Neu in v0.6: vertrauenswürdige Pi-Livedaten

Der Client im verbundenen Modus verwendet jetzt **ausschließlich HTTPS/TLS** und prüft das Serverzertifikat gegen die lokal generierte CA, den Servernamen beziehungsweise die IP-Adresse und die TLS-Gültigkeit nach NTP-Zeitabgleich. Es gibt keinen `setInsecure()`- oder HTTP-Rückfall. Der TLS-Server auf dem Pi akzeptiert nur `GET /v1/status` mit einem **separaten HTTPS-Geräte-Token**, der sich vom lokalen Bridge-Token unterscheidet.

**Live auf dem OpenNextion getestet:** HTTPS-Kommunikation, Hermes-Status und CPU-Diagramm funktionieren. Die erste v0.6-Firmware zeigte fehlerhafte Fließkomma-Labels (`f C`, `f %`). Der Fix mit Festkomma-Zahlenformatierung plus `%s` wurde anschließend erfolgreich auf der Hardware getestet: Statusseite `51.8 C`, `62.8 %`, `0.71`; Graphseite `Pi: 52.9 C | 12/24 Werte` (Momentaufnahmen, keine fest hinterlegten Werte).

**Anleitung:** [TLS-Live-Setup](docs/TLS-LIVE-SETUP.md).

```bash
cd ~/Projekte/OpenNextion_Hermes_Dashboard
git pull --ff-only
python3 -m unittest discover -s tests -v
# Bei bestehender TLS-Installation nach dem Update zuerst:
bash scripts/pi/create-device-token.sh
ip -4 -br addr show scope global
# Erst nach Auswahl der korrekten privaten LAN-IP:
bash scripts/pi/tls-create-cert.sh 192.168.178.42  # Beispiel! echte Pi-LAN-IP einsetzen
bash scripts/pi/export-ca-header.sh
# In einem separaten Terminal bei laufender loopback Bridge:
bash scripts/pi/run-tls.sh
# In einem dritten Terminal:
bash scripts/pi/tls-smoke.sh
```

Nach dem Hinzufügen des separaten Geräte-Tokens muss der TLS-Prozess auf Port 8766 neu gestartet und `bash scripts/pi/tls-smoke.sh` erneut erfolgreich ausgeführt werden. Danach kann die lokale Geräte-Konfiguration ohne Passwortausgabe mit `python3 scripts/pi/configure-device.py` erstellt und die verbundene Firmware mit `bash scripts/pi/firmware-build-connected.sh` kompiliert werden. Dieser Schritt flasht **nicht**.

## Neu in v0.7: blockierungsfreie Touch-Oberfläche

Der Live-Modus nutzt jetzt einen dedizierten **FreeRTOS-Netzwerk-Task** für WLAN, NTP, HTTPS, Zertifikatsprüfung und JSON. Die LVGL-Hauptschleife liest nur noch einen per Mutex geschützten, sofort kopierbaren Status-Snapshot. Damit blockiert ein langsamer HTTPS-Handshake nicht mehr den Touch-Loop.

Die Anzeige zeigt **TLS OK** bzw. den Fehlerzustand und das **Alter der letzten gültigen Messung**. Nach Netzwerkfehlern sind Pi-Werte ausdrücklich als nicht aktuell gekennzeichnet; die Grafik zeichnet jede erfolgreiche Antwort nur **einmal**. Der Chat bleibt gesperrt.

**Normalbetrieb auf Hardware bestätigt:** Statusseite mit `TLS OK`, 52.4 C, 63.8 % RAM, 0.90 Load und `Pi/TLS | vor 3 s`; Graphseite mit `Pi: 53.5 C | 11/24 Werte` (Momentaufnahmen). **Kontrollierter TLS-Ausfalltest erfolgreich, Langzeittest noch offen.** Die Zertifikate und das lokale `Config.h` bleiben unverändert. Der Pi-Build bleibt **inkrementell ohne `--clean`**.

[**v0.7 Testanleitung für Pi und ESP32**](docs/V0.7-ASYNC-TEST.md)

```bash
cd ~/Projekte/OpenNextion_Hermes_Dashboard
git pull --ff-only
python3 -m unittest discover -s tests -v
bash scripts/pi/tls-smoke.sh
bash scripts/pi/firmware-build-connected.sh
# Kein automatischer Flash-Vorgang.
```

## v0.7.1: geprüfte Firmware-Eingaben und ablaufende Healthchecks

**Zwei gezielte Korrekturen – 56/56 Pi-Tests und inkrementeller Connected-Build erfolgreich (vom Anwender bestätigt).** Das manuelle Connected-Upload-Skript prüft jetzt einen in `build/firmware-connected/` gespeicherten SHA-256-Fingerabdruck aller relevanten lokalen Sketch-Dateien, einschließlich `TelemetryWorker.h` und privater Konfigurationsdateien. Veraltete Build-Artefakte werden verweigert, auch wenn Datei-Zeitstempel unverändert geblieben sind. Erst ein neuer erfolgreicher **inkrementeller** Connected-Build erzeugt die Freigabe.

Die Pi-Bridge markiert gecachte Hermes-Healthchecks nach **45 Sekunden ohne vollständigen neuen Prüfzyklus** als veraltet; API-/Gateway-Status wird dann nicht als gesund bzw. aktiv ausgegeben. Die HTTPS-Smokediagnose zeigt das Alter des Healthcheck-Caches. Die ESP32-Firmware selbst wurde dafür **nicht** geändert.

[**Korrekturen, Tests und sichere Aktivierung auf dem Pi**](docs/V0.7.1-FIXES.md)

## Historie: Hermes Touch v0.8 – ESP32-Diagnose

Die **v0.8-Diagnose-Firmware wurde mit 64/64 Tests und erfolgreichem Connected-Build auf dem Pi geprüft und auf dem OpenNextion in Betrieb genommen**. Die anschließend entwickelte, zunächst deaktivierte CHAT-Vorschau wurde später mit **83/83 Tests**, erfolgreichem Connected-Build und einem Hardwarefoto bestätigt. Auf der SYSTEM-Seite stehen künftig zusätzlich der kleinste seit Boot beobachtete freie Heap, der größte zusammenhängende interne Heapblock und die im HTTPS-FreeRTOS-Task ermittelte minimale Stackreserve in Bytes. Laufzeit, PSRAM und Touch-Aktionen bleiben sichtbar. Die Status-/Graph-/Chat-Seiten und alle bisherigen read-only TLS-Sicherheitsgrenzen bleiben unverändert.

**Nächster Prüfschritt für den neuen Repo-Stand:** **83 erwartete Tests** (64 bereits erfolgreich, 6 neue CHAT-Sicherheitstests, 13 neue Offline-Stabilitätsauswertungstests) sowie ein **inkrementeller** Connected-Build. Kein Update auf dem Gerät ohne separate manuelle Flash-Bestätigung.

[**v0.8 – Diagnosefunktionen, Tests und Hardware-Abnahme**](docs/V0.8-DIAGNOSTICS.md)

```bash
cd ~/Projekte/OpenNextion_Hermes_Dashboard
git pull --ff-only
python3 -m unittest discover -s tests -v
bash scripts/pi/firmware-build-connected.sh
# NICHT AUTOMATISCH FLASHEN
```

## Historie: v0.8-CHAT-Vorschau und offline Stabilitätsbericht

Der CHAT-Reiter erhält einen scrollbaren **leeren Verlauf**, eine sichtbare, aber deaktivierte Eingabe sowie eine **gesperrte SENDEN-Taste ohne Callback**. Weder Nachrichten noch Befehle gelangen an den Hermes-Agent. **Die gesperrte CHAT-Vorschau wurde danach manuell auf Hardware geprüft.**

[**CHAT-Vorschau und notwendige Sicherheitsfreigaben**](docs/V0.8-CHAT-PREVIEW.md)

Der neue Offline-Auswerter beurteilt die bereits vom Pi-Monitor erzeugte `.summary.json` nach transparenten Kriterien als `PASS`, `WARN`, `FAIL` oder `INCOMPLETE`. Er prüft nur den **Pi-HTTPS-Pfad**, nicht die ESP32-Speicherwerte, und startet keine neuen Netzwerkabfragen. **Erst nach Beendigung des laufenden Tests** und dem nächsten `git pull` ausführen:

```bash
python3 scripts/pi/stability_report.py --latest
```

[**Auswertung und Grenzwerte**](docs/V0.7-STABILITY-TEST.md)

## v0.8.1 – lokaler Mikrofonpegel auf Hardware bestätigt

Das Nextion Dual MIC Board ist inzwischen physisch am ONX3248G035 angeschlossen. In der auf dem Board bestätigten Version **v0.8.1** funktioniert ein rein lokaler PDM-Pegeltest: **CLK GPIO19**, **DATA GPIO20**, Arduino-ESP32 3.3.2 `ESP_I2S`, eigener FreeRTOS-Task. Im CHAT-Reiter erscheint ein Pegelbalken und die zuvor auffällig helle deaktivierte Eingabe wurde dunkel gestaltet.

**Die Aufnahme bleibt standardmäßig AUS (`HT_MIC_TEST_ENABLED=0`).** Zum Hardwaretest muss diese Option später ausdrücklich in der privaten `firmware/HermesTouch/Config.h` aktiviert, der Connected-Build erneut erstellt und das Gerät manuell geflasht werden. Audio wird weder gespeichert noch übertragen; nur der relative Pegel wird an die lokale Oberfläche übergeben. Hermes-CHAT bleibt vollständig gesperrt.

**Abnahme:** **94/94 Python-Tests**, Connected-Build, `TLS OK` und auf Sprache reagierende Pegelanzeige bestätigt. v0.8.2-Push-to-Talk ist ein eigener, noch ungetesteter Quellcode-Kandidat.

[**v0.8.1 PDM-Mikrofon: Sicherheit, Aktivierung und Testablauf**](docs/V0.8.1-MIC-VU.md)

## v0.8.2 Quellcode-Kandidat – lokaler Push-to-Talk-Test mit OpenNextion-Referenz

Die nächste Version greift die Hersteller-Interaktion aus **[OpenNextion `07_microphone_test`](https://github.com/OpenNextion/OpenNextion-SKU-ONX3248G035/tree/main/Example%20Programs/ESP-Arduino/07_microphone_test)** auf: MIC drücken, gedrückt halten, beim Loslassen/Touch-Verlust stoppen. Die verifizierten PDM-Pins **GPIO19/GPIO20**, **16 kHz**, **16-bit Mono**, **256-Sample-Chunks** und **PSRAM-Pufferung** stimmen mit der Arduino-Vorlage überein. Die Herstellerdemo verwendet 30 Sekunden mit Lautsprecherwiedergabe; Hermes Touch setzt aus Sicherheitsgründen eine **4-Sekunden-/128.000-Byte-Grenze**, verwirft PCM beim Stoppen und schaltet **keinen** Audio-Transport oder Hermes-Chat frei. Der bereits auf Hardware funktionierende ESP_I2S-Treiber bleibt erhalten; auf die unbenötigte NS4168-Lautsprechersteuerung wird verzichtet.

**v0.8.2 wurde noch nicht auf dem Pi kompiliert oder auf Hardware getestet.** Die bestehende v0.8.1 läuft weiter. **106 Python-Tests erwartet** (94 bestätigte + 12 neue PTT-Tests) und Connected-Build; kein automatischer Flash.

[**PTT-Konzept, Hardwareprüfung und Sicherheitsgrenzen**](docs/V0.8.2-LOCAL-PTT.md)

## v0.8.3 – Bestätigte lokale PCM-Diagnose und NS4168-Ausgabe

Der Raspberry Pi hat die v0.8.3 mit **130/130 Tests und `CONNECTED COMPILE OK`** geprüft. Auf dem echten OpenNextion bestätigte der Anwender die 4-Sekunden-PTT-Funktion, gemessene PCM-Samplezahlen, RMS/Peak/Clip-Anteil sowie den temporären PSRAM-Verbrauch und die anschließende Freigabe. Ein **hörbarer NS4168-Testton** einschließlich `SPK: OK 1` und weiter funktionierendem Mikrofonpegel wurde ebenfalls überprüft. Damit bildet **v0.8.3 den zuletzt bestätigten Hardwarestand**.

Die damalige Hochkantbedienung und die Audiofelder innerhalb von CHAT gehören zur **historischen v0.8.3**; ab v0.8.4 werden beide Audiowege vollständig auf den eigenständigen Tab **SPRACHE** verlegt.

[**v0.8.3 PCM-Diagnose**](docs/V0.8.3-AUDIO-DIAGNOSTICS.md) ·
[**v0.8.3 Lautsprecherausgabe**](docs/V0.8.3-SPEAKER-OUTPUT.md)

## v0.8.4 – Landscape mit eigenem SPRACHE-Tab (Quellcode-Kandidat)

Die mit v0.8.3 hardwarebestätigten PDM-Mikrofon- und NS4168-Lautsprecherwege bleiben erhalten; ihre lokale Bedienung wurde auf die neue fünfte Registerkarte **SPRACHE** verschoben. Der separate **CHAT-Tab** zeigt weiterhin nur einen **gesperrten Textchat**. Neu sind **480x320 Landscape**, eine auf 90° transformierte CST826-Toucheingabe, 0–100% begrenzte **Testton-Pegelwahl** (100% = höchstens die zuvor bereits geprüfte leise Amplitude), **STOP** und der weiterhin zeitlich begrenzte viersekündige PTT-Test. Keine Hermes-Audiofunktion, kein TTS, kein Audio über die Bridge und keine Agent-Befehle.

**Hardwarebefund v0.8.4 (11.10.2026):** 141/141 Pi-Tests und Connected-Build erfolgreich, TLS-Smoke erfolgreich. Nach manuellem Flash wurde jedoch eine **diagonal versetzte CST826-Toucheingabe** gemeldet. Die bisherige Landscape-Abbildung ist deshalb **nicht hardwarebestätigt**. Der nachfolgende Diagnosepatch bietet mit explizit aktivierter privater Option `HT_TOUCH_CALIBRATION_ENABLED 1` eine **USB-only Rohkoordinaten-Ausgabe und volatile T0..T7-Profilwahl**; **146 Tests erwartet**, Pi-Build für diesen neuen Patch noch ausstehend. Bis zum Ergebnis keine weiteren blinden Rotations-/Pinänderungen vornehmen. [Kalibrier-Anleitung](docs/V0.8.4-TOUCH-CALIBRATION.md).

[**v0.8.4 Landscape-/Sprach-Tab-Anleitung und Prüfplan**](docs/V0.8.4-LANDSCAPE-VOICE.md)

## 30-Minuten-Stabilitätstest für v0.8 (kein Flashen)

Nach dem bestätigten TLS-Ausfall- und Wiederherstellungstest kann die Pi-Seite mit einem **lokalen, lesenden HTTPS-Monitor** über 30 Minuten geprüft werden. Das Tool zeichnet Antwortzeiten, Ausfälle und ausgewählte Pi-Messwerte im ignorierten `build/stability/`-Verzeichnis auf. Ergänzend müssen die ESP32-Heap- und PSRAM-Werte am Anfang und am Ende direkt auf der SYSTEM-Seite verglichen werden – der Pi-Monitor kann diese nicht auslesen.

[**Testanleitung: v0.7 30-Minuten-Stabilität**](docs/V0.7-STABILITY-TEST.md)

```bash
cd ~/Projekte/OpenNextion_Hermes_Dashboard
git pull --ff-only
python3 -m unittest discover -s tests -v
bash scripts/pi/stability-monitor.sh --samples 3
# Nach erfolgreichem Kurztest und Startfoto vom SYSTEM-Tab:
bash scripts/pi/stability-monitor.sh --minutes 30 --interval 5
```

**Keine Änderung an Firmware, Zertifikaten oder Hermes erforderlich.** Der Monitor sendet nur zertifikatsgeprüfte HTTPS-GET-Anfragen, ohne Proxy/Redirects.

## Entwicklung auf dem Pi

Siehe [docs/PI-SETUP.md](docs/PI-SETUP.md). Die Dateien können auf dem Pi per `git pull --ff-only` synchronisiert werden; installierte Agent-Dateien unter `~/.hermes` werden dabei nicht angerührt.

## Entwicklungsstand und nächste Schritte

- v0.1–v0.3: read-only Python-Bridge auf dem Pi, Hermes-API- und Dashboard-Healthchecks, Status-Endpunkt und automatisierte Tests
- v0.4: nachweislich erfolgreicher ESP32-S3-Clean-Build; Display und Touch auf realer ONX3248G035-Hardware getestet
- v0.5: vier LVGL-Touchseiten, lokaler Messverlauf, Systemseite und gesperrter Chat-Platzhalter – **fotografisch auf dem ONX3248G035 bestätigt**, einschließlich der tatsächlichen Graph-Zählung
- v0.6: IP-SAN-HTTPS-Statusdienst, separate Geräteauthentifizierung, NTP-/CA-Prüfung – **auf Pi und ESP32 bestätigt**, einschließlich korrigierter Zahlenformatierung und Temperaturkurve
- v0.7: FreeRTOS-Hintergrundtask, Snapshot-Mutex, Anzeigealter, stale-data-Sperre, Temperaturgrafik – **35 Tests, Pi-Build, Livebetrieb, kontrollierter TLS-Ausfall und Wiederherstellung auf ONX3248G035 bestätigt**
- v0.7.1: SHA-256-Fingerabdruck für Connected-Build/Upload einschließlich `TelemetryWorker.h`, Healthcheck-Cache mit 45-s-Gültigkeitsdauer – **56/56 Tests, Connected-Build und frischer Cache über HTTPS am Pi bestätigt**; kein Flash erforderlich
- v0.8: SYSTEM-Diagnose (Heap-Minimum, größter Block, HTTPS-Task-Stackreserve) – **64/64 Tests, Connected-Build und erste Hardwaremessungen bestätigt**, Graph mit 24/24 echten Pi-Temperaturwerten
- Neue Entwicklung: strikt deaktivierte CHAT-Vorschau (Verlauf, Eingabefeld, SENDEN-Sperre) und rein lokale Qualitätsauswertung der Pi-HTTPS-Messreihe; **Tests/Build für diese Erweiterung stehen noch aus**. Chat bleibt gesperrt
- v0.8.1 (noch ungeprüfter Quellcode-Kandidat): lokaler PDM-Mikrofonpegel, separat aktivierbar und ohne Audio-/Chat-Übertragung; gesperrte CHAT-Eingabe jetzt dunkel formatiert
- Nächste Etappe: 94 erwartete Tests und inkrementellen v0.8.1-Build auf dem Pi prüfen; erst dann den lokalen Mikrofontest bewusst aktivieren und das Board manuell flashen

Lizenz: noch festzulegen.
