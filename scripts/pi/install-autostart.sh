#!/usr/bin/env bash
# Install Hermes Touch bridge + TLS service as systemd USER units.
# No sudo, no changes to Hermes units, no secrets copied into unit files.
#   bash scripts/pi/install-autostart.sh            install + enable (boot)
#   bash scripts/pi/install-autostart.sh --now      ... and (re)start now
#   bash scripts/pi/install-autostart.sh --status   show unit state
#   bash scripts/pi/install-autostart.sh --uninstall stop, disable, remove
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNITS=(hermes-touch-bridge.service hermes-touch-tls.service)
MODE="${1:-install}"

case "$MODE" in
  install|--now|--status|--uninstall) ;;
  *) printf 'Usage: %s [--now|--status|--uninstall]\n' "$0" >&2; exit 2 ;;
esac
command -v systemctl >/dev/null || { printf 'systemctl not found.\n' >&2; exit 2; }

if [[ "$MODE" == "--status" ]]; then
  systemctl --user --no-pager status "${UNITS[@]}" || true
  exit 0
fi

if [[ "$MODE" == "--uninstall" ]]; then
  systemctl --user disable --now "${UNITS[@]}" 2>/dev/null || true
  for unit in "${UNITS[@]}"; do rm -f -- "$UNIT_DIR/$unit"; done
  systemctl --user daemon-reload
  printf 'Hermes Touch autostart removed. Config and certificates unchanged.\n'
  exit 0
fi

# systemd specifiers (%) and whitespace would change the rendered paths.
if [[ "$ROOT" =~ [[:space:]%\"\\] ]]; then
  printf 'REFUSED: repository path contains whitespace, %%, quotes or backslashes.\n' >&2
  exit 3
fi
for file in config/bridge.env config/tls.env config/pki/server.crt config/pki/server.key; do
  [[ -s "$ROOT/$file" ]] || {
    printf 'Missing %s. Complete docs/TLS-LIVE-SETUP.md first.\n' "$file" >&2; exit 3; }
done

mkdir -p "$UNIT_DIR"
for unit in "${UNITS[@]}"; do
  tmp="$(mktemp "$UNIT_DIR/.$unit.XXXXXX")"
  sed "s|@ROOT@|$ROOT|g" "$ROOT/deploy/systemd/$unit.in" > "$tmp"
  chmod 644 "$tmp"
  mv -f -- "$tmp" "$UNIT_DIR/$unit"
done
systemctl --user daemon-reload
systemctl --user enable "${UNITS[@]}"
printf 'Installed and enabled: %s\n' "${UNITS[*]}"

if [[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null || true)" != "yes" ]]; then
  printf 'NOTE: user lingering is off; services start only after login.\n'
  printf '      For start at boot run once: sudo loginctl enable-linger %s\n' "$USER"
fi

if [[ "$MODE" == "--now" ]]; then
  # A manually started bridge would hold 127.0.0.1:8765 and make the unit loop.
  if ! systemctl --user is-active --quiet hermes-touch-bridge.service &&
     ss -ltnH 'sport = :8765' 2>/dev/null | grep -q .; then
    printf 'REFUSED to start: port 8765 is used by a process outside systemd\n' >&2
    printf '(probably a manually started run-local.sh). Stop it, then rerun with --now.\n' >&2
    exit 4
  fi
  systemctl --user restart "${UNITS[@]}"
  sleep 3
  systemctl --user --no-pager --lines=0 status "${UNITS[@]}" || true
  printf '\nCheck HTTPS path: bash scripts/pi/tls-smoke.sh\n'
else
  printf 'Not started now. Start with: bash scripts/pi/install-autostart.sh --now\n'
fi
printf 'Logs: journalctl --user -u hermes-touch-bridge -u hermes-touch-tls -f\n'
