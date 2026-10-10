# Hermes Touch v0.6: sichere Pi-Livedaten über HTTPS/TLS

**Auf echter Hardware bestätigt:** v0.6 nutzt erfolgreich WLAN/HTTPS zur Pi-Bridge. Vier fotografierte Bildschirmseiten zeigen `HERMES-API ERREICHBAR`, `Dashboard: OK | Gateway: ON`, eine reale CPU-Temperaturkurve und den weiterhin gesperrten Chat. Bei der ersten v0.6-Version trat ein **LVGL-Formatierungsfehler bei Fließkommawerten** auf (`f C`, `f %`, korrupte Diagrammbeschriftung). Der daraufhin eingecheckte Fix muss erst neu kompiliert und auf dem OpenNextion überprüft werden.

## Architektur / Sicherheitsgrenzen

```text
ESP32 ONX3248G035
  └─ WLAN → HTTPS/TLS auf Pi-LAN-IP:8766
       - CA-Zertifikat auf dem ESP32 fest hinterlegt
       - Serverzertifikat mit IP-SAN, Zeit- und Kettenprüfung
       - separater HTTPS-Geräte-Token (abweichend vom Bridge-Token), nur GET-/v1/status-Berechtigung
           ↓
Pi: TLS-only Statusdienst (nur private LAN-Adresse)
           ↓ GET /v1/status
Pi: bestehende HTTP-Bridge (127.0.0.1:8765)
           ↓ read-only
Hermes API /health, Dashboard /api/status, Pi /proc + /sys
```

**Kein unverschlüsselter HTTP-Zugang über das Netzwerk.** 
Der bestehende lokale Port **8765** bleibt Loopback-only.
Der TLS-Dienst erlaubt ausschließlich `GET /v1/status`; POST/PUT/PATCH/DELETE werden abgewiesen.
Die Firmware besitzt keinen Chat-Versand und keinen Hermes-API-Schlüssel. Sie erhält auch **nicht** den lokalen Bridge-Token: Ab v0.6 wird ein unabhängiger Geräte-Token in `config/tls.env` erzeugt.
Der Geräte-Token steckt später im Flash des ESP32 – das Gerät sollte deshalb nicht für Dritte zugänglich sein.

**Kein Router-Portforwarding**, kein Internetzugriff auf 8766; ausschließlich eigenes vertrauenswürdiges LAN/WLAN. Möglichst eine Host-Firewall auf den ESP32 einschränken. Bei kompromittiertem Gerät Token erneuern, vgl. unten.

## 1. Pi: Repository aktualisieren und vorhandene Bridge prüfen

```bash
cd ~/Projekte/OpenNextion_Hermes_Dashboard
git status --short
git pull --ff-only
python3 -m unittest discover -s tests -v
bash scripts/pi/smoke-status.sh
```

Die bestehende Bridge muss im eigenen Terminal mit `bash scripts/pi/run-local.sh` laufen. Sie muss **weiterhin ausschließlich an 127.0.0.1:8765** binden.

## 2. Die korrekte LAN-IP des Pi bestimmen

```bash
ip -4 -br addr show scope global
```

Wähle die IPv4-Adresse des Pi im gleichen LAN/WLAN wie der ESP32, z. B. `192.168.178.42`. Nicht einfach eine Docker- oder Tunnel-IP übernehmen. Die Adresse muss dauerhaft erreichbar bleiben; ggf. DHCP-Reservierung im Router setzen.

## 3. CA und Serverzertifikat EINMAL erstellen

```bash
bash scripts/pi/tls-create-cert.sh 192.168.178.42
bash scripts/pi/export-ca-header.sh
```

**Die Beispiel-IP durch die echte Pi-IP ersetzen.**
Die lokale Zertifizierungsstelle und der für diese IP signierte Server-Schlüssel werden in `config/pki/` erstellt. Für neue Installationen wird auch ein separater HTTPS-Geräte-Token angelegt. Die Zertifikatsgültigkeit beträgt 365 Tage (Server) und 1095 Tage (CA). Das Skript verweigert Überschreibungen. Bei IP-Wechsel oder Ablauf wird eine geplante Rotation mit anschließender Neuauslieferung des CA-Zertifikats erforderlich.

**Wichtig:** `config/pki/ca.key` und `config/pki/server.key` sind PRIVATE; `config/pki/ca.crt` ist öffentlich und wird über `export-ca-header.sh` nach `firmware/HermesTouch/LocalCa.h` kopiert. `LocalCa.h`, `Config.h`, `config/pki/` und `config/tls.env` sind in `.gitignore` ausgeschlossen. Privatdateien nicht posten, nicht nach GitHub committen.

## Bestehende Installation von v0.6 aktualisieren (bereits Zertifikate erstellt)

**Nur falls `config/tls.env` und `config/pki/` bereits vorhanden sind**, wie bei der ersten Inbetriebnahme auf dem Pi `192.168.178.63`:

```bash
cd ~/Projekte/OpenNextion_Hermes_Dashboard
git pull --ff-only
python3 -m unittest discover -s tests -v
bash scripts/pi/create-device-token.sh
```

Das Skript ergänzt **nur** einen neuen `HERMES_TOUCH_DEVICE_TOKEN` in der vorhandenen lokalen `config/tls.env`, falls er fehlt. Es zeigt den Wert nicht an und verändert **weder** das Zertifikat **noch** `config/bridge.env`. Wiederholte Aufrufe erhalten den bereits existierenden Wert.

Anschließend den **TLS-Prozess auf Port 8766 mit Strg+C** beenden und per `bash scripts/pi/run-tls.sh` neu starten, damit er das neue Token lädt. Die HTTP-Bridge auf `127.0.0.1:8765` bleibt unverändert. Danach `bash scripts/pi/tls-smoke.sh` ausführen.

**Wichtig:** Der TLS-Smoke-Test verwendet ab jetzt den neuen Geräte-Token. Ein bereits laufender alter HTTPS-Prozess kann daher bis zum Neustart HTTP 401 zurückgeben; dies bedeutet keinen Zertifikatsfehler.

## 4. TLS-Dienst starten und getrennt prüfen

**Terminal A:** bereits laufende Read-only-Bridge auf 127.0.0.1:8765 behalten.

**Terminal B:**

```bash
cd ~/Projekte/OpenNextion_Hermes_Dashboard
bash scripts/pi/run-tls.sh
```

Erwartet: `https://<PI-IP>:8766/v1/status (GET ONLY)`.

**Terminal C:**

```bash
cd ~/Projekte/OpenNextion_Hermes_Dashboard
bash scripts/pi/tls-smoke.sh
```

Erwartet: `TLS verified against locally generated CA: YES`, `Bridge JSON status: ok`, Hermes- und Systemwerte.

Falls die Bindung fehlschlägt, zunächst `ip -4 -br addr show scope global` und die IP-Einstellung in der ignorierten `config/tls.env` prüfen. Kein Wechsel auf `0.0.0.0` und kein Deaktivieren der TLS-Prüfung. Der TLS-Dienst wird nicht automatisch als systemd-Dienst installiert.

**Fehler `HTTPError` beim TLS-Smoke-Test (v0.6):** Ältere Skriptversionen zeigten den tatsächlichen HTTP-Statuscode nicht an. Die aktualisierte Version verwendet explizit `ProxyHandler({})`, um `HTTPS_PROXY`/`HTTP_PROXY` beim Aufruf der eigenen LAN-IP zu umgehen. Sie prüft weiterhin die Zertifikatskette und die IP-SAN; TLS-Sicherheitsprüfungen werden **nicht** abgeschaltet. Auch die TLS-Bridge leitet das Token grundsätzlich nur direkt an `127.0.0.1:8765` weiter, ohne Systemproxy.

Nach `git pull --ff-only` laufenden TLS-Dienst mit Strg+C stoppen und neu starten. Portprüfung, ohne Geheimnisse:

```bash
ss -ltnp | grep -E ':(8765|8766)[[:space:]]' || true
```

Wenn `8765` nicht lauscht, in einem Terminal `bash scripts/pi/run-local.sh` starten. Wenn `8766` nicht lauscht, in einem **zweiten Terminal** `bash scripts/pi/run-tls.sh` starten. Anschließend:

```bash
python3 -m unittest discover -s tests -v
bash scripts/pi/tls-smoke.sh
```

Die neue Diagnose unterscheidet:

- **HTTP 401:** HTTPS-Dienst hat den Geräte-Token nicht akzeptiert. Passenden Prozess neu starten; Schlüssel niemals zur Diagnose ausgeben.
- **HTTP 503:** HTTPS-Dienst läuft, aber seine lokale Bridge auf Port 8765 antwortet nicht erfolgreich.
- **HTTP 404:** Falscher Dienst oder Endpunkt auf Port 8766.
- **`CONNECTION FAIL`:** Erreichbarkeit, Listener oder Firewall.
- **`TLS FAIL`:** IP-SAN, CA, Gültigkeitszeit oder TLS-Handshake prüfen.

Bei HTTP-Fehlern erreicht der direkte Client den TLS-Dienst und hat dessen Zertifikat erfolgreich geprüft; der Fehler betrifft dann die Anwendungsebene. **Zertifikate nicht ungeprüft löschen oder erneut erzeugen.**



## 5. Verbindungs-Firmware erst nach bestandenem TLS-Test vorbereiten

```bash
python3 scripts/pi/configure-device.py
bash scripts/pi/firmware-build-connected.sh
```

Die Konfiguration fragt WLAN-SSID und WLAN-Passwort interaktiv ab (Passwort ohne Echo), übernimmt den unabhängigen HTTPS-Geräte-Token aus der lokalen `config/tls.env` und erzeugt die ignorierte `Config.h`. Die CA-Kette wird aus `LocalCa.h` verwendet.

Der ESP32 verlangt eine `https://`-URL, ein echtes CA-Zertifikat und synchronisierte UTC-Zeit (NTP über `pool.ntp.org` oder `time.google.com`). Er **fällt nicht auf HTTP** oder `setInsecure()` zurück. Hat er keinen NTP-Zugang, wird die HTTPS-Abfrage aus Sicherheitsgründen verweigert.

Der Build mit `firmware-build-connected.sh` enthält WLAN-Passwort und **HTTPS-Geräte-Token** **im Binärimage**. Deshalb wird er unter `build/firmware-connected/` lokal und mit beschränkten Rechten erzeugt. Kein automatisches Flashen.

**Erst nach erfolgreicher Prüfung** des TLS-Smoketests, der verbundenen Kompilierung und des USB-Geräts folgt ein separat bestätigter Firmware-Upload. Der bis dahin funktionierende Offline-Firmwarestand bleibt erhalten.

```bash
# Nur nach erfolgreichem verbundenem Build; noch nicht vorzeitig ausführen!
ls -l /dev/serial/by-id/
bash scripts/pi/firmware-upload-connected.sh \
  /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0
```

Das Upload-Skript verwendet **ausschließlich** `build/firmware-connected/`, prüft aktuelle Konfiguration/Binärartefakte sowie den TLS-Smoketest und erfordert die interaktive Eingabe `FLASH-HERMES-TLS`. Es ersetzt dann die vorhandene Offline-Testfirmware. Es ist nicht möglich, versehentlich mit dem Offline-Build-Verzeichnis weiterzufahren.

**Wichtig:** Das verbundene Firmware-Binary enthält das lokale WLAN-Passwort und den Bridge-Token; das gesamte `build/`-Verzeichnis darf nicht veröffentlicht oder geteilt werden.

## 6. Beobachtungen nach dem Flash

Auf **STATUS** werden Pi-CPU-Temperatur, Pi-RAM, Systemlast und Hermes-API-Status aus der Bridge dargestellt. Im Tab **GRAPH** erscheint der echte Temperaturverlauf des Pi (maximal 24 Messpunkte). **SYSTEM** zeigt weiterhin lokale ESP32-Hardwaredaten. **CHAT** bleibt gesperrt.

Eine fehlgeschlagene Zertifikatsprüfung, fehlende Netzwerkverbindung, fehlender NTP-Sync oder ungültiges Token muss zu **keinen aktuellen Pi-Daten** führen, nicht zu erfundenen Werten.

### v0.6-Hardwarebefund: Fließkommaformatierung in LVGL korrigieren

Am OpenNextion wurden zunächst auf der **STATUS**-Seite `f C`, `f %` und `f` statt numerischer Werte angezeigt. Auf der **GRAPH**-Seite war die Messkurve plausibel, während die Beschriftung große falsche Zähler enthielt. Ursache ist die standardmäßig fehlende `%f`-Unterstützung bei `lv_label_set_text_fmt()` in LVGL 8.3; zudem kann diese einen nachfolgenden Argumentversatz auslösen.

Der Fix formatiert Pi-CPU, Pi-RAM und Pi-Load über eine validierte, begrenzte Festkomma-Konvertierung mit C++-Ganzzahlformaten (`std::isfinite`, `snprintf`) und übergibt die Ergebnisse als `%s` an LVGL. Die Chat-Sperre, TLS-CA, PIN-Belegung und Konfiguration bleiben unangetastet.

**Nächste Schritte mit vorhandener privater `Config.h` und `LocalCa.h`:**

```bash
cd ~/Projekte/OpenNextion_Hermes_Dashboard
git pull --ff-only
python3 -m unittest discover -s tests -v
bash scripts/pi/tls-smoke.sh
bash scripts/pi/firmware-build-connected.sh
```

Nur bei Erfolg und nach erneuter Kontrolle des tatsächlichen USB-Geräts die Firmware mit `bash scripts/pi/firmware-upload-connected.sh /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0` manuell übertragen. Danach überprüfen, ob z. B. `51.2 C`, `62.8 %`, `0.53` und `Pi: 51.2 C | x/24 Werte` dargestellt werden. Das sind **Beispielwerte**, keine aktuellen Live-Messungen.

Es müssen **keine neuen Zertifikate und keine neuen WLAN-Schlüssel erstellt werden**. Die existierende `Config.h` wird wiederverwendet; der private verbundene Build muss nach dem Quellcode-Fix neu erstellt werden.

## Fehlerdiagnose und Grenzen

- **TLS-Verbindung scheitert:** Datum/Uhrzeit auf ESP32, Cert-SAN/IP, CA-Header, Pi-LAN-Bindung und Firewall prüfen.
- **HTTP 401:** Gerätetoken stimmt nicht mit `config/bridge.env` überein.
- **HTTP 503:** lokaler Bridge-Prozess unter 127.0.0.1:8765 läuft nicht.
- **Zeitanzeige/NTP ausstehend:** DNS/UDP-123 für ESP32 prüfen; nicht `setInsecure()` aktivieren.
- **HTTP im Config.h:** absichtlich abgelehnt.
- **Hohe Latenz:** verbundener ESP32-Code fragt synchron innerhalb des LVGL-Loops ab; bei Verbindungsproblemen kann die Oberfläche vorübergehend stocken. Hintergrundtask ist für einen Folgeschritt vorgesehen.

**Hinweis:** Die TLS-Projekttests prüfen die Server-Autorisierung und das Python-Zertifikats-Handling. Ein erfolgreicher Build garantiert nicht, dass die ESP32/mbedTLS-Verifikation auf realer Hardware funktioniert. Diese ist separat nachzuweisen.
