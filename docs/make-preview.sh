#!/bin/bash
# Regenerate docs/before-after.png from assets/ and the current renderer.
# Run from anywhere: ./docs/make-preview.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# "After": run the real pipeline (renderer + encoder) at 512 px for a crisp preview.
swiftc -O "$ROOT/lib/round.swift" -o "$TMP/round"
# The source art is 256 px; upscale it first so the 512 px render keeps the same proportions.
sips -z 512 512 "$ROOT/assets/orig256.png" --out "$TMP/orig512.png" >/dev/null
"$TMP/round" "$TMP/orig512.png" "$TMP/after.rgba" 512
python3 -I - "$ROOT" "$TMP" <<'PY'
import sys; sys.path.insert(0, sys.argv[1] + "/lib")
import encode
open(sys.argv[2] + "/after.png", "wb").write(encode.encode(open(sys.argv[2] + "/after.rgba", "rb").read(), 512))
PY

swiftc -O "$ROOT/docs/make-preview.swift" -o "$TMP/preview"
"$TMP/preview" "$ROOT/assets/orig256.png" "$TMP/after.png" "$ROOT/docs/before-after.png"
echo "wrote $ROOT/docs/before-after.png"
