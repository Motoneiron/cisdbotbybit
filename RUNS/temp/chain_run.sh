#!/usr/bin/env bash
# CHAIN (03.10): после финиша stopt7 -> трекинг-прогон -> BE-сетка 1..12ч
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"

# ждём финиша сетки выходов (макс ~20ч)
i=0
while ! grep -q "STOPT7_ALLDONE" stopt7_queue.log 2>/dev/null; do
  sleep 60; i=$((i+1))
  if [ $i -gt 1200 ]; then echo "CHAIN_TIMEOUT $(date +%F_%H:%M:%S)" >> chain.log; exit 1; fi
done

echo "CHAIN_START $(date +%F_%H:%M:%S)" >> chain.log
"$PY" stop_timing_run.py tf1v2_track > stopt8_run.log 2>&1
echo "TRACK_DONE $(date +%F_%H:%M:%S)" >> stopt8_queue.log

for n in 1 2 3 4 6 8 12; do
  echo "BE${n}_START $(date +%F_%H:%M:%S)" >> stopt9_queue.log
  "$PY" stop_timing_run.py tf1v2_be${n} >> stopt9_run.log 2>&1
  echo "BE${n}_DONE $(date +%F_%H:%M:%S)" >> stopt9_queue.log
done
echo "STOPT9_ALLDONE $(date +%F_%H:%M:%S)" >> stopt9_queue.log
