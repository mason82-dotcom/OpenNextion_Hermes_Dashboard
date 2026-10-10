#!/usr/bin/env bash
# Install a pinned, checksum-verified Arduino CLI for Linux ARM64 to ~/.local/bin.
# No sudo, apt, system services or Hermes changes.
set -euo pipefail

if [[ "$(uname -s)" != "Linux" || ! "$(uname -m)" =~ ^(aarch64|arm64)$ ]]; then
  printf 'Unsupported host. Expected Linux aarch64/arm64.\n' >&2
  exit 2
fi
if command -v arduino-cli >/dev/null 2>&1; then
  printf 'Already installed: %s\n' "$(command -v arduino-cli)"
  arduino-cli version
  exit 0
fi

VERSION="1.5.1"
FILENAME="arduino-cli_${VERSION}_Linux_ARM64.tar.gz"
URL="https://github.com/arduino/arduino-cli/releases/download/v${VERSION}/${FILENAME}"
# Published upstream SHA-256 for Arduino CLI v1.5.1 Linux ARM64 tarball.
EXPECTED_SHA256="1e69e077479f300614d4551334e0a33f08ee40b04315d83b8e7e0e94f0d0ee62"
TARGET_DIR="$HOME/.local/bin"
TARGET="$TARGET_DIR/arduino-cli"

if [[ -e "$TARGET" ]]; then
  printf 'Refusing to overwrite existing binary: %s\n' "$TARGET" >&2
  "$TARGET" version
  exit 2
fi
if ! command -v curl >/dev/null 2>&1; then
  printf 'curl is required to download the official Arduino CLI archive.\n' >&2
  exit 2
fi
if ! command -v sha256sum >/dev/null 2>&1; then
  printf 'sha256sum is needed to validate the upstream release archive.\n' >&2
  exit 2
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
printf 'Downloading Arduino CLI %s for Linux ARM64 from GitHub Releases...\n' "$VERSION"
curl --fail --location --retry 3 --connect-timeout 20 \
  "$URL" --output "$WORK/$FILENAME"
printf '%s  %s\n' "$EXPECTED_SHA256" "$WORK/$FILENAME" | sha256sum --check --status || {
  printf 'ERROR: SHA256 verification failed, installation aborted.\n' >&2
  exit 1
}
printf 'SHA256 verified against Arduino CLI v%s published release.\n' "$VERSION"
tar -xzf "$WORK/$FILENAME" -C "$WORK" arduino-cli
mkdir -p "$TARGET_DIR"
install -m 0755 "$WORK/arduino-cli" "$TARGET"
"$TARGET" version
printf '\nInstalled: %s\n' "$TARGET"
printf 'For this shell: export PATH="$HOME/.local/bin:$PATH"\n'
printf 'No system packages, services or Hermes files changed.\n'
