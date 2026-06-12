#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/unzip_split.sh [parts_dir] [destination_dir] [archive_name]

Defaults:
  parts_dir        split_zip
  destination_dir  restored
  archive_name     proj

Example:
  scripts/unzip_split.sh split_zip restored proj

Password:
  Set SPLIT_ZIP_PASSWORD before running, or type it when prompted.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    echo "Ubuntu install: sudo apt update && sudo apt install -y python3 openssl coreutils" >&2
    exit 1
  fi
}

parts_dir="${1:-split_zip}"
destination_dir="${2:-restored}"
archive_name="${3:-proj}"

if [[ ! -d "$parts_dir" ]]; then
  echo "Parts directory not found: $parts_dir" >&2
  exit 1
fi

require_cmd python3
require_cmd openssl
require_cmd realpath
require_cmd sort

mapfile -t parts < <(find "$parts_dir" -maxdepth 1 -type f -name "$archive_name.zip.enc.part-*" | sort -V)
if [[ "${#parts[@]}" -eq 0 ]]; then
  echo "No parts found matching: $parts_dir/$archive_name.zip.enc.part-*" >&2
  exit 1
fi

mkdir -p "$destination_dir"
tmp_zip="$(mktemp --suffix=.zip)"
tmp_enc="$(mktemp --suffix=.zip.enc)"
trap 'rm -f "$tmp_zip" "$tmp_enc"' EXIT

if [[ -z "${SPLIT_ZIP_PASSWORD:-}" ]]; then
  read -r -s -p "Password: " SPLIT_ZIP_PASSWORD
  echo
fi

if [[ -z "$SPLIT_ZIP_PASSWORD" ]]; then
  echo "Password cannot be empty." >&2
  exit 1
fi
export SPLIT_ZIP_PASSWORD

cat "${parts[@]}" > "$tmp_enc"
if ! openssl enc -d -aes-256-cbc -pbkdf2 -in "$tmp_enc" -out "$tmp_zip" -pass env:SPLIT_ZIP_PASSWORD; then
  unset SPLIT_ZIP_PASSWORD
  echo "Failed to decrypt. Check the password or split parts." >&2
  exit 1
fi
unset SPLIT_ZIP_PASSWORD

python3 - "$tmp_zip" "$destination_dir" <<'PY'
from pathlib import Path
from zipfile import ZipFile
import sys

zip_path = Path(sys.argv[1])
destination = Path(sys.argv[2])

with ZipFile(zip_path) as archive:
    archive.extractall(destination)
PY

echo "Restored archive into: $(realpath -m "$destination_dir")"
