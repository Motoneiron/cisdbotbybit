#!/bin/bash
# tf1hold_run.sh — hold-сетка по времени выхода (запрос юзера 30.09):
# база = строка 1 (tf1 + ms1.5 + lc-гейт, без V/D). Точки: 12 / 8 / 6 ч (базовые 16ч уже есть).
cd D:/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
LOG=tf1hold_queue.log
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> $LOG; }

"$PY" -m py_compile live_tf_grid.py || { say "COMPILE FAIL"; exit 1; }
say "compile ok; смоуки h6/h8/h12..."

"$PY" -u live_tf_grid.py tf1lc15_foff_h6 smoke > tf1_h6_smoke.log 2>&1 &
S1=$!
"$PY" -u live_tf_grid.py tf1lc15_foff_h8 smoke > tf1_h8_smoke.log 2>&1 &
S2=$!
"$PY" -u live_tf_grid.py tf1lc15_foff_h12 smoke > tf1_h12_smoke.log 2>&1 &
S3=$!
wait $S1 $S2 $S3 2>/dev/null

ok=1
for f in tf1_h6_smoke.log tf1_h8_smoke.log tf1_h12_smoke.log; do
  grep -q "OK ADA" "$f" || { say "SMOKE FAIL: $f"; ok=0; }
done
[ $ok -eq 1 ] || { say "СМОУКИ НЕ ПРОШЛИ — стоп"; exit 1; }
say "смоуки ok; старт 3 конфигов (h12/h8/h6)"

"$PY" -u live_tf_grid.py tf1lc15_foff_h12 > tf1lc15_foff_h12_out.txt 2>&1 &
P1=$!
"$PY" -u live_tf_grid.py tf1lc15_foff_h8 > tf1lc15_foff_h8_out.txt 2>&1 &
P2=$!
"$PY" -u live_tf_grid.py tf1lc15_foff_h6 > tf1lc15_foff_h6_out.txt 2>&1 &
P3=$!
say "запущены: h12=$P1 h8=$P2 h6=$P3"
wait $P1 $P2 $P3 2>/dev/null
say "TF1HOLD_DONE h12=$(ls live_tf/tf1lc15_foff_h12/*.pkl 2>/dev/null | wc -l)/18 h8=$(ls live_tf/tf1lc15_foff_h8/*.pkl 2>/dev/null | wc -l)/18 h6=$(ls live_tf/tf1lc15_foff_h6/*.pkl 2>/dev/null | wc -l)/18"
