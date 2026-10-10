#!/usr/bin/env bash
# Export PUBLIC CA certificate to ignored C++ header; never export keys.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CERT="$ROOT/config/pki/ca.crt"
OUT="$ROOT/firmware/HermesTouch/LocalCa.h"
if [[ ! -s "$CERT" ]]; then
  printf 'CA certificate missing; run tls-create-cert.sh first.\n' >&2
  exit 2
fi
if [[ -e "$OUT" ]]; then
  printf 'REFUSED: %s already exists. Review it before intentional rotation.\n' "$OUT" >&2
  exit 3
fi
python3 - "$CERT" "$OUT" <<'PY'
from pathlib import Path
import os, sys
cert = Path(sys.argv[1]).read_text(encoding="ascii")
if "-----BEGIN CERTIFICATE-----" not in cert or "-----END CERTIFICATE-----" not in cert:
    raise SystemExit("Invalid PEM certificate")
out = Path(sys.argv[2])
header = ('#pragma once\n// PUBLIC trust anchor. Generated locally; NEVER put CA private key here.\n'
          'static const char HT_CA_CERT[] = R"HTCA(' + cert.rstrip() + '\n)HTCA";\n')
fd = os.open(str(out), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="ascii") as handle:
    handle.write(header)
print("Wrote firmware/HermesTouch/LocalCa.h (public CA only).")
print("Private CA key and server key were never opened by this script.")
PY
