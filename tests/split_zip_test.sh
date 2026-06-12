#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_root="$(mktemp -d)"
trap 'rm -rf "$tmp_root"' EXIT

src="$tmp_root/src"
mkdir -p "$src/nested"
python3 - "$src" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
(root / "a.txt").write_text("alpha\n" * 100, encoding="utf-8")
(root / "nested" / "b.bin").write_bytes(bytes(i % 251 for i in range(2500)))
PY

out="$tmp_root/out"
export SPLIT_ZIP_PASSWORD="test-password"
bash "$repo_root/scripts/zip_split.sh" "$src" "$out" "sample" "512"
unset SPLIT_ZIP_PASSWORD

part_count="$(find "$out" -maxdepth 1 -type f -name 'sample.zip.enc.part-*' | wc -l | tr -d ' ')"
if [[ "$part_count" -lt 2 ]]; then
  echo "Expected at least 2 split parts, got $part_count" >&2
  exit 1
fi

while IFS= read -r -d '' part; do
  size="$(stat -c%s "$part")"
  if (( size > 512 )); then
    echo "Part exceeds 512 bytes: $part is $size bytes" >&2
    exit 1
  fi
done < <(find "$out" -maxdepth 1 -type f -name 'sample.zip.enc.part-*' -print0)

restore="$tmp_root/restore"
export SPLIT_ZIP_PASSWORD="test-password"
bash "$repo_root/scripts/unzip_split.sh" "$out" "$restore" "sample"
unset SPLIT_ZIP_PASSWORD

diff -r "$src" "$restore/src"

wrong_restore="$tmp_root/wrong-restore"
export SPLIT_ZIP_PASSWORD="wrong-password"
if bash "$repo_root/scripts/unzip_split.sh" "$out" "$wrong_restore" "sample" >/dev/null 2>&1; then
  echo "Expected restore with wrong password to fail" >&2
  exit 1
fi
unset SPLIT_ZIP_PASSWORD

echo "split zip test passed"

prompt_src="$tmp_root/prompt-src"
prompt_out="$tmp_root/prompt-out"
mkdir -p "$prompt_src"
printf 'prompt password path\n' > "$prompt_src/file.txt"
printf 'prompt-password\nprompt-password\n' | bash "$repo_root/scripts/zip_split.sh" "$prompt_src" "$prompt_out" "prompt" "512"

prompt_restore="$tmp_root/prompt-restore"
printf 'prompt-password\n' | bash "$repo_root/scripts/unzip_split.sh" "$prompt_out" "$prompt_restore" "prompt"

diff -r "$prompt_src" "$prompt_restore/prompt-src"
echo "interactive password test passed"
