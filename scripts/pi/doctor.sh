#!/usr/bin/env bash
# Read-only report: no configuration changes.
set -euo pipefail
printf '\n== Hermes Touch / Pi diagnostic (read-only) ==\n'
printf 'Host: '; hostname
printf 'Kernel: '; uname -sr
printf 'Architecture: '; uname -m
printf 'Python: '; python3 --version
printf 'Git: '; git --version
printf '\n== Hermes paths (existence only) ==\n'
for path in "$HOME/.hermes" "$HOME/.hermes/hermes-agent" "$HOME/Projekte"; do
  if [[ -e "$path" ]]; then printf 'OK  %s\n' "$path"; else printf '--- %s\n' "$path"; fi
done
printf '\n== Listening ports (local check) ==\n'
if command -v ss >/dev/null; then
  ss -ltn | grep -E '(:8642|:9119|:8765)([[:space:]]|$)' || true
else
  printf 'ss not available\n'
fi
printf '\n== Local bridge config present? ==\n'
if [[ -f "$(dirname "$0")/../../config/bridge.env" ]]; then
  printf 'config/bridge.env exists (secrets not displayed)\n'
else
  printf 'config/bridge.env missing; use create-local-config.sh\n'
fi
printf '\nCheck complete; no services modified.\n'
