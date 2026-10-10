#!/usr/bin/env bash
# CHAIN-12 (04.10): после финиша TZ-серии (stopt11) -> TZB-серия (90/120/180).
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"

i=0
while ! grep -q "STOPT11_ALLDONE" stopt11_queue.log 2>/dev/null; do
  sleep 60; i=$((i+1))
  if [ $i -gt 1200 ]; then echo "CHAIN12_TIMEOUT $(date +%F_%H:%M:%S)" >> chain12.log; exit 1; fi
done

echo "CHAIN12_START $(date +%F_%H:%M:%S)" >> chain12.log
for tz in 90 120 180; do
  echo "TZB${tz}_START $(date +%F_%H:%M:%S)" >> stopt12_queue.log
  "$PY" stop_timing_run.py tf1v2_tzb${tz} >> stopt12_run.log 2>&1
  echo "TZB${tz}_DONE $(date +%F_%H:%M:%S)" >> stopt12_queue.log
done
echo "STOPT12_ALLDONE $(date +%F_%H:%M:%S)" >> stopt12_queue.log
