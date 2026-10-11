# Autostart mit systemd (Bridge + TLS-Dienst)

Bridge (`127.0.0.1:8765`) und TLS-Statusdienst (`<Pi-LAN-IP>:8766`) laufen als
**systemd-User-Units** – wie die vorhandenen Dienste `hermes-gateway` und
`hermes-dashboard`. Kein `sudo`, keine Änderung an Hermes-Units, keine Tokens
in den Unit-Dateien: Gestartet wird über die bestehenden, prüfenden Skripte
`run-local.sh` und `run-tls.sh`, die `config/bridge.env` bzw. `config/tls.env`
lokal einlesen.

## Voraussetzungen

- TLS-Einrichtung abgeschlossen ([TLS-Live-Setup](TLS-LIVE-SETUP.md)):
  `config/bridge.env`, `config/tls.env`, `config/pki/server.{crt,key}`
- User-Lingering aktiv, damit die Dienste ohne Login beim Booten starten:
  `loginctl show-user "$USER" -p Linger` → `Linger=yes`
  (sonst einmalig `sudo loginctl enable-linger "$USER"`)

## Installation

```bash
cd ~/Projekte/OpenNextion_Hermes_Dashboard
git pull --ff-only
python3 -m unittest discover -s tests
# Eine manuell gestartete Bridge (run-local.sh) vorher mit Strg+C beenden.
bash scripts/pi/install-autostart.sh --now
bash scripts/pi/tls-smoke.sh
```

Ohne `--now` werden die Units nur installiert und für den nächsten Boot
aktiviert. Belegt ein manuell gestarteter Prozess Port 8765, verweigert
`--now` den Start, statt eine Neustartschleife zu erzeugen.

## Betrieb

| Aufgabe | Befehl |
|---|---|
| Status | `bash scripts/pi/install-autostart.sh --status` |
| Logs live | `journalctl --user -u hermes-touch-bridge -u hermes-touch-tls -f` |
| Nach `git pull` neu starten | `systemctl --user restart hermes-touch-bridge hermes-touch-tls` |
| Entfernen | `bash scripts/pi/install-autostart.sh --uninstall` |

## Verhalten

- **Neustart:** Beide Dienste starten nach einem Absturz automatisch neu
  (Bridge nach 5 s, TLS nach 10 s). Ist die LAN-IP beim Booten noch nicht
  vergeben, scheitert der TLS-Bind zunächst und wird wiederholt.
- **Fehlkonfiguration:** Verweigert `run-tls.sh` den Start (Exit 2/3, z. B.
  fehlendes Geräte-Token oder Bridge nicht auf Loopback), gibt es **keine**
  Endlosschleife – erst Konfiguration korrigieren, dann neu starten.
- **Pfad:** Die Units enthalten den absoluten Repository-Pfad. Nach einem
  Verschieben des Repos das Installationsskript erneut ausführen.
