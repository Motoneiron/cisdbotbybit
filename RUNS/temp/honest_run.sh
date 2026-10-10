#!/bin/bash
# honest_run.sh — последние ЧЕСТНЫЕ якоря для tf7: cc (наклон на баре конфирма) и lc-span21 (проверка длинного span честно).
cd D:/PYTHON/cisdbotbybit/RUNS/temp || exit 1
LOG=honest_queue.log
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> $LOG; }

python -m py_compile live_tf_grid.py || { say "COMPILE FAIL"; exit 1; }
say "compile ok; смоук cc..."
python -u live_tf_grid.py tf7e13_cc smoke > tf7_cc_smoke.log 2>&1 || { say "SMOKE cc FAIL"; exit 1; }
say "смоук cc ok; смоук e21_lc..."
python -u live_tf_grid.py tf7e21_lc smoke > tf7_e21lc_smoke.log 2>&1 || { say "SMOKE e21lc FAIL"; exit 1; }
say "смоуки ok; старт cc + e21_lc (2 пула)"
python -u live_tf_grid.py tf7e13_cc > tf7e13cc_out.txt 2>&1 &
P1=$!
python -u live_tf_grid.py tf7e21_lc > tf7e21lc_out.txt 2>&1 &
P2=$!
wait $P1 $P2 2>/dev/null
say "HONEST_DONE cc=$(ls live_tf/tf7e13_cc/*.pkl 2>/dev/null | wc -l)/18 e21lc=$(ls live_tf/tf7e21_lc/*.pkl 2>/dev/null | wc -l)/18"
