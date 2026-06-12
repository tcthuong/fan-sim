#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/zip_split.sh [source_dir] [output_dir] [archive_name] [part_size]

Defaults:
  source_dir    proj
  output_dir    split_zip
  archive_name  basename of source_dir
  part_size     90M

Password:
  Set SPLIT_ZIP_PASSWORD before running, or type it when prompted.
  The password is not written to the generated README.

Example:
  scripts/zip_split.sh proj split_zip proj 90M
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

source_dir="${1:-proj}"
output_dir="${2:-split_zip}"
archive_name="${3:-$(basename "$source_dir")}"
part_size="${4:-90M}"

if [[ ! -d "$source_dir" ]]; then
  echo "Source directory not found: $source_dir" >&2
  exit 1
fi

require_cmd python3
require_cmd openssl
require_cmd split
require_cmd realpath

source_abs="$(realpath "$source_dir")"
output_abs="$(realpath -m "$output_dir")"
parent_dir="$(dirname "$source_abs")"
source_base="$(basename "$source_abs")"

mkdir -p "$output_abs"
rm -f "$output_abs/$archive_name.zip" "$output_abs/$archive_name.zip.enc" "$output_abs/$archive_name.zip.part-"* "$output_abs/$archive_name.zip.enc.part-"*

tmp_zip="$(mktemp --suffix=.zip)"
tmp_enc="$(mktemp --suffix=.zip.enc)"
trap 'rm -f "$tmp_zip" "$tmp_enc"' EXIT

if [[ -z "${SPLIT_ZIP_PASSWORD:-}" ]]; then
  read -r -s -p "Password: " SPLIT_ZIP_PASSWORD
  echo
  read -r -s -p "Confirm password: " confirm_password
  echo
  if [[ "$SPLIT_ZIP_PASSWORD" != "$confirm_password" ]]; then
    echo "Passwords do not match." >&2
    exit 1
  fi
  unset confirm_password
fi

if [[ -z "$SPLIT_ZIP_PASSWORD" ]]; then
  echo "Password cannot be empty." >&2
  exit 1
fi
export SPLIT_ZIP_PASSWORD

(
  cd "$parent_dir"
  python3 - "$source_base" "$tmp_zip" <<'PY'
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])

with ZipFile(target, "w", ZIP_DEFLATED) as archive:
    for path in sorted(source.rglob("*")):
        archive.write(path, path.as_posix())
PY
)

openssl enc -aes-256-cbc -salt -pbkdf2 -in "$tmp_zip" -out "$tmp_enc" -pass env:SPLIT_ZIP_PASSWORD
unset SPLIT_ZIP_PASSWORD

split -b "$part_size" -d -a 3 "$tmp_enc" "$output_abs/$archive_name.zip.enc.part-"

cat > "$output_abs/$archive_name.README.txt" <<EOF
Created from: $source_abs
Part size: $part_size
Encrypted: yes, OpenSSL AES-256-CBC with PBKDF2

Restore on Ubuntu:
  bash scripts/unzip_split.sh "$output_dir" restored "$archive_name"

Or manually:
  cat "$archive_name.zip.enc.part-"* > "$archive_name.zip.enc"
  openssl enc -d -aes-256-cbc -pbkdf2 -in "$archive_name.zip.enc" -out "$archive_name.zip"
  python3 -m zipfile -e "$archive_name.zip" restored
EOF

echo "Created split zip parts:"
find "$output_abs" -maxdepth 1 -type f -name "$archive_name.zip.enc.part-*" -printf '%f %s bytes\n' | sort -V
echo "Output directory: $output_abs"
