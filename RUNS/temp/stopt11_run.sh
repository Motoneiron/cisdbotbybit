#!/usr/bin/env bash
# STOP-TIMING-11 (04.10): TZ-сетка — «стоп в БУ» после 90/120/180 мин суммарно в зоне.
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
LOG=stopt11_queue.log
echo "START_STOPT11 $(date +%F_%H:%M:%S)" >> "$LOG"
for tz in 90 120 180; do
  echo "TZ${tz}_START $(date +%F_%H:%M:%S)" >> "$LOG"
  "$PY" stop_timing_run.py tf1v2_tz${tz} >> stopt11_run.log 2>&1
  echo "TZ${tz}_DONE $(date +%F_%H:%M:%S)" >> "$LOG"
done
echo "STOPT11_ALLDONE $(date +%F_%H:%M:%S)" >> "$LOG"
