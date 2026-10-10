#!/bin/bash
# tf1cb_run.sh — CB-ЗЕРКАЛА сеток (запрос юзера 01.10): те же 8 конфигов на лукапном якоре cb.
# База сравнения: честные lc-версии (ночь 30.09/01.10). Запуск разом (~48 воркеров, ~5 ч).
cd D:/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
LOG=tf1cb_queue.log
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> $LOG; }

"$PY" -m py_compile live_tf_grid.py || { say "COMPILE FAIL"; exit 1; }
say "compile ok; смоуки foff/l1h..."

"$PY" -u live_tf_grid.py tf1cb15_foff smoke > tf1_cb_foff_smoke.log 2>&1 &
S1=$!
"$PY" -u live_tf_grid.py tf1cb15_l1h smoke > tf1_cb_l1h_smoke.log 2>&1 &
S2=$!
wait $S1 $S2 2>/dev/null

ok=1
for f in tf1_cb_foff_smoke.log tf1_cb_l1h_smoke.log; do
  grep -q "OK ADA" "$f" || { say "SMOKE FAIL: $f"; ok=0; }
done
[ $ok -eq 1 ] || { say "СМОУКИ НЕ ПРОШЛИ — стоп"; exit 1; }
say "смоуки ok; старт 8 cb-конфигов"

"$PY" -u live_tf_grid.py tf1cb15_foff > tf1cb15_foff_out.txt 2>&1 &
P1=$!
"$PY" -u live_tf_grid.py tf1cb15_foff_h12 > tf1cb15_foff_h12_out.txt 2>&1 &
P2=$!
"$PY" -u live_tf_grid.py tf1cb15_foff_h8 > tf1cb15_foff_h8_out.txt 2>&1 &
P3=$!
"$PY" -u live_tf_grid.py tf1cb15_foff_h6 > tf1cb15_foff_h6_out.txt 2>&1 &
P4=$!
"$PY" -u live_tf_grid.py tf1cb15_l2h > tf1cb15_l2h_out.txt 2>&1 &
P5=$!
"$PY" -u live_tf_grid.py tf1cb15_l1h > tf1cb15_l1h_out.txt 2>&1 &
P6=$!
"$PY" -u live_tf_grid.py tf1cb15_l30m > tf1cb15_l30m_out.txt 2>&1 &
P7=$!
"$PY" -u live_tf_grid.py tf1cb15_l15m > tf1cb15_l15m_out.txt 2>&1 &
P8=$!
say "запущены: foff=$P1 h12=$P2 h8=$P3 h6=$P4 l2h=$P5 l1h=$P6 l30m=$P7 l15m=$P8"
wait $P1 $P2 $P3 $P4 $P5 $P6 $P7 $P8 2>/dev/null
say "TF1CB_DONE foff=$(ls live_tf/tf1cb15_foff/*.pkl 2>/dev/null | wc -l)/18 h12=$(ls live_tf/tf1cb15_foff_h12/*.pkl 2>/dev/null | wc -l)/18 h8=$(ls live_tf/tf1cb15_foff_h8/*.pkl 2>/dev/null | wc -l)/18 h6=$(ls live_tf/tf1cb15_foff_h6/*.pkl 2>/dev/null | wc -l)/18 l2h=$(ls live_tf/tf1cb15_l2h/*.pkl 2>/dev/null | wc -l)/18 l1h=$(ls live_tf/tf1cb15_l1h/*.pkl 2>/dev/null | wc -l)/18 l30m=$(ls live_tf/tf1cb15_l30m/*.pkl 2>/dev/null | wc -l)/18 l15m=$(ls live_tf/tf1cb15_l15m/*.pkl 2>/dev/null | wc -l)/18"
