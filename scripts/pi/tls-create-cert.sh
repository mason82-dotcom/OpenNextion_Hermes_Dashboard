#!/usr/bin/env bash
# Provision an isolated local CA and IP-SAN TLS server certificate.
# Does not touch existing bridge.env, Hermes services, or system trust.
# Never overwrites an existing PKI or tls.env.
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PKI="$ROOT/config/pki"
TLS_ENV="$ROOT/config/tls.env"

if [[ $# -ne 1 ]]; then
  printf 'Usage: bash scripts/pi/tls-create-cert.sh <PI_PRIVATE_IPV4>\n' >&2
  exit 2
fi
IP="$1"
python3 - "$IP" <<'PY'
import ipaddress, sys
try:
    ip = ipaddress.ip_address(sys.argv[1])
except ValueError:
    raise SystemExit("ERROR: Invalid IPv4 LAN address")
allowed = tuple(ipaddress.ip_network(x) for x in
    ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
if ip.version != 4 or not any(ip in n for n in allowed):
    raise SystemExit("ERROR: Supply the Raspberry Pi's RFC1918 IPv4 LAN address")
PY
for bin in openssl python3; do
  command -v "$bin" >/dev/null || { printf '%s not installed\n' "$bin" >&2; exit 2; }
done
if [[ -e "$TLS_ENV" || -e "$PKI/ca.key" || -e "$PKI/server.key" || -e "$PKI/server.crt" ]]; then
  printf 'REFUSED: existing TLS configuration/certificates. No files overwritten.\n' >&2
  exit 3
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
printf 'Creating a private project-specific CA and server certificate for %s...\n' "$IP"
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -sha256 \
  -days 1095 -keyout "$TMP/ca.key" -out "$TMP/ca.crt" \
  -subj "/CN=HermesTouch Local CA" \
  -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" >/dev/null 2>&1
openssl req -new -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -sha256 \
  -keyout "$TMP/server.key" -out "$TMP/server.csr" \
  -subj "/CN=HermesTouch-Pi" >/dev/null 2>&1
cat > "$TMP/server.ext" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature
extendedKeyUsage=serverAuth
subjectAltName=IP:$IP
EOF
openssl x509 -req -sha256 -days 365 \
  -in "$TMP/server.csr" -CA "$TMP/ca.crt" -CAkey "$TMP/ca.key" \
  -CAcreateserial -extfile "$TMP/server.ext" \
  -out "$TMP/server.crt" >/dev/null 2>&1
# OpenSSL validates BOTH the signed chain and the IP subjectAltName.
# Python 3.13 no longer exposes ssl.match_hostname.
openssl verify -verify_ip "$IP" -CAfile "$TMP/ca.crt" "$TMP/server.crt" >/dev/null

mkdir -p "$PKI"
install -m 600 "$TMP/ca.key" "$PKI/ca.key"
install -m 644 "$TMP/ca.crt" "$PKI/ca.crt"
install -m 600 "$TMP/server.key" "$PKI/server.key"
install -m 644 "$TMP/server.crt" "$PKI/server.crt"
printf 'HERMES_TOUCH_TLS_BIND=%s\nHERMES_TOUCH_TLS_PORT=8766\n' "$IP" > "$TLS_ENV"
printf 'HERMES_TOUCH_TLS_CERT=%s\nHERMES_TOUCH_TLS_KEY=%s\n' \
  "$PKI/server.crt" "$PKI/server.key" >> "$TLS_ENV"
chmod 600 "$TLS_ENV"
printf 'TLS materials ready in config/pki/. CA and server PRIVATE keys: 0600.\n'
printf 'Server certificate: IP SAN %s, ~365 days. Config: %s\n' "$IP" "$TLS_ENV"
printf 'IMPORTANT: do not publish config/pki or config/tls.env.\n'
