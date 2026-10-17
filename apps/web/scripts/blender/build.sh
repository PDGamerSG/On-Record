#!/usr/bin/env bash
# Rebuilds the landing page's 3D assets from scratch.
#   scripts/blender/build.sh            GLB + contact shadow only (seconds)
#   scripts/blender/build.sh --render   also the Cycles stills (minutes on a laptop GPU)
# Needs: blender (5.x) on PATH, Node (for npx @gltf-transform/cli), cwebp.
set -euo pipefail
cd "$(dirname "$0")/../.."

OUT=public/landing
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$OUT"

blender -b --factory-startup -P scripts/blender/build_turntable.py -- --out "$TMP" "$@"

# meshopt + quantised geometry; keep the record's UVs (the hero paints the grooves and label at runtime)
# and the node tree (the hero turns ArmPivot, ArmLift and Platter)
npx -y @gltf-transform/cli@4 optimize "$TMP/turntable.glb" "$OUT/turntable.glb" \
  --compress meshopt --texture-compress webp --texture-size 1024 \
  --simplify false --flatten false --join false --palette false --instance false --prune-attributes false

cwebp -quiet -q 82 "$TMP/turntable-shadow.png" -o "$OUT/turntable-shadow.webp"

if [ -f "$TMP/_hero.png" ]; then
  blender -b --factory-startup -P scripts/blender/build_mic.py -- --out "$TMP/_mic.png"
  # the mic stands in the middle of a tall frame; keep just the mic
  cwebp -quiet -q 86 -alpha_q 90 -crop 420 160 460 1220 "$TMP/_mic.png" -o "$OUT/mic.webp"
  cwebp -quiet -q 86 -alpha_q 90 "$TMP/_hero.png" -o "$OUT/turntable-still.webp"
  cwebp -quiet -q 84 "$TMP/_macro.png" -o "$OUT/stylus.webp"
  cwebp -quiet -q 86 -alpha_q 90 "$TMP/_record.png" -o "$OUT/record.webp"
fi
ls -la "$OUT"
