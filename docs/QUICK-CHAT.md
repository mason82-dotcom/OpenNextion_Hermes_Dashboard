# Schnellbefehle im CHAT-Tab

Der CHAT-Tab zeigt bis zu **sechs Knöpfe**. Ein Tipp lässt Hermes einen
festgelegten Prompt beantworten; die Antwort erscheint als kurzer Text im
Verlauf darunter. **Standardmäßig AUS** – auf dem Pi und in der Firmware
getrennt aktivierbar.

## Sicherheitsmodell

Der `api_server` von Hermes hat auf diesem Pi u. a. die Toolsets `terminal`,
`file` und `code_execution`. Freitext vom Display wäre damit eine Shell auf
dem Pi für jeden, der das Geräte-Token besitzt (z. B. durch Auslesen des
ESP32-Flash). Deshalb:

| Grenze | Umsetzung |
|---|---|
| Kein Freitext | Das Display sendet nur `{"prompt_id": "<id>"}`. Die Prompt-Texte stehen ausschließlich in `config/chat-prompts.json` auf dem Pi und werden nie zum Gerät übertragen. |
| Doppelte Prüfung | TLS-Dienst und Bridge validieren die ID unabhängig (`^[a-z0-9_]{1,16}$`, Body ≤ 256 Bytes, keine weiteren Felder). Der TLS-Dienst leitet nur eine neu serialisierte ID weiter. |
| Kein API-Key auf dem Gerät | Die Bridge liest `API_SERVER_KEY` beim Start aus `~/.hermes/.env` und spricht nur `127.0.0.1:8642` an. |
| Begrenzung | Ein Auftrag gleichzeitig, frühestens alle 15 s, höchstens 20 pro Stunde, 180 s Zeitlimit. |
| Keine Fehlerdetails | Das Gerät erhält nur Codes (`timeout`, `auth`, `upstream`, …), nie Fehlertexte von Hermes. |
| Kein Speicher | Antworten nur im RAM des Displays (Verlauf ca. 3 KB, neueste zuerst); nichts im Flash. Die Bridge hält nur die letzte Antwort im Speicher. Im Journal steht nur `chat job=… prompt=… result=…`. |
| Anzeigefähig | Antworten werden auf 700 ASCII-Zeichen gekürzt; Umlaute werden umschrieben (ä → ae), Markdown entfernt. |

**Restrisiko:** Hermes führt die freigegebenen Prompts mit allen Toolsets des
`api_server` aus. Prompts, die Webinhalte lesen (z. B. Wetter), können über
manipulierte Webseiten eine Prompt-Injection erleben – wie bei jeder anderen
Hermes-Nutzung. Formuliere Prompts deshalb lesend („nichts verändern“) und
erwäge, die `api_server`-Toolsets in `~/.hermes/config.yaml` zu reduzieren,
falls kein anderer Client sie braucht.

## Einrichtung

### Pi

```bash
cd ~/Projekte/OpenNextion_Hermes_Dashboard
git pull --ff-only
python3 -m unittest discover -s tests -q
cp deploy/chat-prompts.example.json config/chat-prompts.json
nano config/chat-prompts.json        # Prompts anpassen
systemctl --user restart hermes-touch-bridge hermes-touch-tls
journalctl --user -u hermes-touch-bridge -n 5   # "Quick chat: ENABLED (ok, 5 prompts)"
```

Format: 1–6 Einträge mit `id` (`a-z0-9_`, max. 16), `label` (ASCII, max. 14
Zeichen, wird auf dem Knopf angezeigt) und `prompt` (max. 2000 Zeichen).
Optional `"vary": true`: Für Befehle wie WITZ, bei denen jede Antwort
anders sein soll. Ohne diese Option schickt die Bridge jedes Mal denselben
Prompt in eine neue Hermes-Sitzung, und das Modell wählt meist dieselbe
„wahrscheinlichste“ Antwort. Mit `vary` merkt sich die Bridge die letzten 5
Antworten dieses Befehls (nur im RAM, weg nach Neustart der Bridge), hängt sie
mit der Bitte „nicht wiederholen“ an den Prompt und ergänzt eine zufällige
Variantennummer. Für Statusabfragen nicht verwenden.
**Ist ein einziger Eintrag ungültig, bleibt der Chat vollständig aus.**
Änderungen werden nach einem Neustart der Bridge wirksam; das Display lädt die
Liste innerhalb von 30 s neu, wenn es den Chat vorher als „AUS“ gesehen hat,
sonst nach einem Neustart des Displays.

Status der Bridge: `"Quick chat: off (no_prompt_file | invalid_prompt_file | no_api_key …)"`.

### Firmware

In der privaten `firmware/HermesTouch/Config.h` genau eine Zeile:

```c
#define HT_CHAT_QUICK_ENABLED 1
```

Dann wie gewohnt `bash scripts/pi/firmware-build-connected.sh` und manuell mit
`firmware-upload-connected.sh` flashen. Ohne diese Zeile bleibt die gesperrte
Vorschau unverändert. Im Offline-Modus ist die Option ein Compile-Fehler.

## Bedienung und Anzeigen

| Anzeige oben rechts | Bedeutung |
|---|---|
| `LADE BEFEHLE ...` | Display wartet auf die Liste vom Pi |
| `CHAT AUF PI AUS` | Keine/ungültige `chat-prompts.json` oder kein API-Key |
| `SENDE ...` / `HERMES ARBEITET 12 s` | Auftrag läuft; alle Knöpfe gesperrt |
| `ANTWORT DA` | Antwort steht oben im Verlauf |
| `FEHLER: LIMIT: WARTEN` | 15-s-Abstand oder Stundenlimit erreicht |
| `FEHLER: PI BESCHAEFTIGT` | Ein anderer Auftrag läuft noch |
| `FEHLER: ZEITLIMIT` / `HERMES-FEHLER` / `API-SCHLUESSEL` | Hermes hat nicht rechtzeitig oder nicht erfolgreich geantwortet |

Während eines Auftrags fragt das Display alle 2 s den Stand ab, sonst wie
bisher alle 5 s den Status. Beide Abfragen laufen nacheinander im selben
Netzwerk-Task; die Oberfläche wartet nie auf HTTPS.

## Abnahme auf Hardware

**Bestätigt am 11.10.2026** auf dem ONX3248G035 (Connected-Build mit Mikrofon,
Lautsprecher und Schnellbefehlen): fünf Knöpfe aus `chat-prompts.json`,
Antworten auf HERMES, PI-STATUS und WITZ nach ca. 4–10 s im Verlauf,
Status `ANTWORT DA`, `TLS OK`; SPRACHE-Tab (Mikrofon 38 %, PTT 3,1 s mit
100 % Anteil, Lautsprecher bereit) arbeitet parallel. Der Limit-Test
(Schritt 3) steht noch aus; serverseitig ist er durch Tests abgedeckt.

Prüfschritte:

1. CHAT-Tab zeigt die Knöpfe aus `chat-prompts.json` (Beschriftung = `label`).
2. `WITZ` antippen → `HERMES ARBEITET …` → Antwort oben im Verlauf.
3. Sofort erneut tippen → `FEHLER: LIMIT: WARTEN`.
4. `config/chat-prompts.json` umbenennen, Bridge neu starten → nach ≤ 30 s
   bzw. Neustart des Displays `CHAT AUF PI AUS`, keine Knöpfe.
5. Andere Tabs (STATUS, GRAPH, SPRACHE) funktionieren währenddessen normal.
