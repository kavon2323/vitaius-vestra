#!/usr/bin/env bash
set -euo pipefail

# If INPUT is provided, run one-shot (useful for manual tests)
if [[ -n "${INPUT:-}" ]]; then
  echo "[oneshot] Running single job with INPUT=$INPUT"
  exec blender -b -P headless/process_cli.py -- \
    --input "${INPUT}" \
    ${CHEST_WALL:+--chest_wall "${CHEST_WALL}"} \
    --axis "${AXIS:-X}" \
    --base_offset_mm "${BASE_OFFSET_MM:-2.0}" \
    --mold_padding_mm "${MOLD_PADDING_MM:-10.0}" \
    ${OUT_PROSTHETIC:+--out_prosthetic "${OUT_PROSTHETIC}"} \
    ${OUT_MOLD:+--out_mold "${OUT_MOLD}"}
fi

# Otherwise run the Redis loop
echo "[loop] Starting Vitaius worker loop"
exec python3 /app/worker/runner.py
