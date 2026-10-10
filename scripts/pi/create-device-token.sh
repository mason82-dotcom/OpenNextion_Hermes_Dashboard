#!/usr/bin/env bash
# Add a distinct HTTPS DEVICE token to existing local config/tls.env.
# Does not alter existing certificates, Bridge token or Hermes configuration.
# Never prints tokens, refuses accidental replacement.
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$ROOT/config/tls.env"
if [[ ! -f "$ENV_FILE" ]]; then
  printf 'Missing config/tls.env. Create the local TLS certificates first.\n' >&2
  exit 2
fi
if grep -Eq '^HERMES_TOUCH_DEVICE_TOKEN=' "$ENV_FILE"; then
  printf 'Device token already exists; not changing it.\n'
  exit 0
fi
if [[ -L "$ENV_FILE" ]]; then
  printf 'REFUSED: TLS config is a symlink.\n' >&2
  exit 3
fi
chmod 600 "$ENV_FILE"
python3 - "$ENV_FILE" <<'PY'
import os
import secrets
import sys
from pathlib import Path

path = Path(sys.argv[1])
fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
try:
    # The token is random, URL-safe and contains no shell metacharacters.
    token = secrets.token_urlsafe(36)
    with os.fdopen(fd, "a", encoding="ascii") as file:
        file.write("HERMES_TOUCH_DEVICE_TOKEN=" + token + "\n")
except BaseException:
    raise
print("Created distinct HTTPS device token (not printed) in ignored config/tls.env.")
print("Existing Bridge token and TLS certificates remain unchanged.")
PY
