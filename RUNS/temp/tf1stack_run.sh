#!/bin/bash
# tf1stack_run.sh — СТЭК tf1+ms1.5+честный lc: контроли фильтров A/V/D (запрос юзера 30.09).
# 5 конфигов × 6 пар × 3 года: on / foff / fa / fv / fd. Запуск разом (~30 воркеров).
# "on" = tf1sl15sp21_lc — уже есть SOL (3 файла), остальные пары досчитываются.
cd D:/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
LOG=tf1stack_queue.log
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> $LOG; }

"$PY" -m py_compile live_tf_grid.py || { say "COMPILE FAIL"; exit 1; }
say "compile ok; смоуки foff/fa/fv/fd..."

"$PY" -u live_tf_grid.py tf1lc15_foff smoke > tf1_foff_smoke.log 2>&1 &
S1=$!
"$PY" -u live_tf_grid.py tf1lc15_fa smoke > tf1_fa_smoke.log 2>&1 &
S2=$!
"$PY" -u live_tf_grid.py tf1lc15_fv smoke > tf1_fv_smoke.log 2>&1 &
S3=$!
"$PY" -u live_tf_grid.py tf1lc15_fd smoke > tf1_fd_smoke.log 2>&1 &
S4=$!
wait $S1 $S2 $S3 $S4 2>/dev/null

ok=1
for f in tf1_foff_smoke.log tf1_fa_smoke.log tf1_fv_smoke.log tf1_fd_smoke.log; do
  grep -q "OK ADA" "$f" || { say "SMOKE FAIL: $f"; ok=0; }
done
[ $ok -eq 1 ] || { say "СМОУКИ НЕ ПРОШЛИ — стоп"; exit 1; }
say "смоуки ok; старт 5 конфигов разом"

"$PY" -u live_tf_grid.py tf1sl15sp21_lc > tf1lc15_on_out.txt 2>&1 &
P0=$!
"$PY" -u live_tf_grid.py tf1lc15_foff > tf1lc15_foff_out.txt 2>&1 &
P1=$!
"$PY" -u live_tf_grid.py tf1lc15_fa > tf1lc15_fa_out.txt 2>&1 &
P2=$!
"$PY" -u live_tf_grid.py tf1lc15_fv > tf1lc15_fv_out.txt 2>&1 &
P3=$!
"$PY" -u live_tf_grid.py tf1lc15_fd > tf1lc15_fd_out.txt 2>&1 &
P4=$!
say "запущены: on=$P0 foff=$P1 fa=$P2 fv=$P3 fd=$P4"
wait $P0 $P1 $P2 $P3 $P4 2>/dev/null
say "TF1STACK_DONE on=$(ls live_tf/tf1sl15sp21_lc/*.pkl 2>/dev/null | wc -l)/18 foff=$(ls live_tf/tf1lc15_foff/*.pkl 2>/dev/null | wc -l)/18 fa=$(ls live_tf/tf1lc15_fa/*.pkl 2>/dev/null | wc -l)/18 fv=$(ls live_tf/tf1lc15_fv/*.pkl 2>/dev/null | wc -l)/18 fd=$(ls live_tf/tf1lc15_fd/*.pkl 2>/dev/null | wc -l)/18"
