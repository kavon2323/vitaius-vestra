#!/usr/bin/env bash
set -euo pipefail

# ENV you can pass at runtime:
# BLENDER_BIN=/usr/bin/blender
# INPUT=/data/input.stl
# CHEST_WALL=/data/chestwall.stl   (optional)
# AXIS=X
# BASE_OFFSET_MM=2.0
# MOLD_PADDING_MM=10.0
# OUT_PROSTHETIC=/data/vitaius_vestra_prosthetic.stl
# OUT_MOLD=/data/vitaius_vestra_mold.stl

BLENDER_BIN="${BLENDER_BIN:-blender}"
AXIS="${AXIS:-X}"
BASE_OFFSET_MM="${BASE_OFFSET_MM:-2.0}"
MOLD_PADDING_MM="${MOLD_PADDING_MM:-10.0}"

if [[ -z "${INPUT:-}" ]]; then
  echo "ERROR: INPUT not set"; exit 1
fi

CMD=( "$BLENDER_BIN" -b -P headless/process_cli.py -- \
      --input "$INPUT" \
      --axis "$AXIS" \
      --base_offset_mm "$BASE_OFFSET_MM" \
      --mold_padding_mm "$MOLD_PADDING_MM" )

if [[ -n "${CHEST_WALL:-}" ]]; then
  CMD+=( --chest_wall "$CHEST_WALL" )
fi
if [[ -n "${OUT_PROSTHETIC:-}" ]]; then
  CMD+=( --out_prosthetic "$OUT_PROSTHETIC" )
fi
if [[ -n "${OUT_MOLD:-}" ]]; then
  CMD+=( --out_mold "$OUT_MOLD" )
fi

echo "Running: ${CMD[*]}"
exec "${CMD[@]}"
