#!/bin/bash
# tf1limit_run.sh — limit-сетка (запрос юзера 30.09): ожидание ВХОДА 15м/30м/1ч/2ч
# на базе строки 1 (без V/D). База для сравнения: foff с лимиткой 5ч (+17.1R).
cd D:/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
LOG=tf1limit_queue.log
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> $LOG; }

"$PY" -m py_compile live_tf_grid.py || { say "COMPILE FAIL"; exit 1; }
say "compile ok; смоуки l15m/l30m/l1h/l2h..."

"$PY" -u live_tf_grid.py tf1lc15_l15m smoke > tf1_l15m_smoke.log 2>&1 &
S1=$!
"$PY" -u live_tf_grid.py tf1lc15_l30m smoke > tf1_l30m_smoke.log 2>&1 &
S2=$!
"$PY" -u live_tf_grid.py tf1lc15_l1h smoke > tf1_l1h_smoke.log 2>&1 &
S3=$!
"$PY" -u live_tf_grid.py tf1lc15_l2h smoke > tf1_l2h_smoke.log 2>&1 &
S4=$!
wait $S1 $S2 $S3 $S4 2>/dev/null

ok=1
for f in tf1_l15m_smoke.log tf1_l30m_smoke.log tf1_l1h_smoke.log tf1_l2h_smoke.log; do
  grep -q "OK ADA" "$f" || { say "SMOKE FAIL: $f"; ok=0; }
done
[ $ok -eq 1 ] || { say "СМОУКИ НЕ ПРОШЛИ — стоп"; exit 1; }
say "смоуки ok; старт 4 конфигов (l15m/l30m/l1h/l2h)"

"$PY" -u live_tf_grid.py tf1lc15_l15m > tf1lc15_l15m_out.txt 2>&1 &
P1=$!
"$PY" -u live_tf_grid.py tf1lc15_l30m > tf1lc15_l30m_out.txt 2>&1 &
P2=$!
"$PY" -u live_tf_grid.py tf1lc15_l1h > tf1lc15_l1h_out.txt 2>&1 &
P3=$!
"$PY" -u live_tf_grid.py tf1lc15_l2h > tf1lc15_l2h_out.txt 2>&1 &
P4=$!
say "запущены: l15m=$P1 l30m=$P2 l1h=$P3 l2h=$P4"
wait $P1 $P2 $P3 $P4 2>/dev/null
say "TF1LIMIT_DONE l15m=$(ls live_tf/tf1lc15_l15m/*.pkl 2>/dev/null | wc -l)/18 l30m=$(ls live_tf/tf1lc15_l30m/*.pkl 2>/dev/null | wc -l)/18 l1h=$(ls live_tf/tf1lc15_l1h/*.pkl 2>/dev/null | wc -l)/18 l2h=$(ls live_tf/tf1lc15_l2h/*.pkl 2>/dev/null | wc -l)/18"
