#!/bin/bash
# tf1alloff_run.sh — догон: конфиг tf1lc15_alloff (все фильтры выключены ПО-НАСТОЯЩЕМУ,
# включая свип A: min_sweep_atr=0). В пятёрке foff свип оставался 0.40 (нюанс обвязки).
cd D:/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
LOG=tf1alloff_queue.log
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> $LOG; }

"$PY" -m py_compile live_tf_grid.py || { say "COMPILE FAIL"; exit 1; }
say "смоук alloff..."
"$PY" -u live_tf_grid.py tf1lc15_alloff smoke > tf1_alloff_smoke.log 2>&1
grep -q "OK ADA" tf1_alloff_smoke.log || { say "SMOKE FAIL: нет OK ADA"; exit 1; }
say "смоук ok; старт alloff (6 пар × 3 года)"

"$PY" -u live_tf_grid.py tf1lc15_alloff > tf1lc15_alloff_out.txt 2>&1 &
P=$!
say "запущен pid=$P"
wait $P 2>/dev/null
say "TF1ALLOFF_DONE $(ls live_tf/tf1lc15_alloff/*.pkl 2>/dev/null | wc -l)/18"
