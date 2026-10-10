#!/usr/bin/env bash
# Смоуки новых механик гейта (ADA/июнь-2024 по built-in smoke) + отладка sw на SOL.
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
rm -f smoke_all.done
"$PY" live_tf_grid.py q_sw21 smoke > smoke_q_sw21.log 2>&1 &
"$PY" live_tf_grid.py q_ss3 smoke > smoke_q_ss3.log 2>&1 &
"$PY" live_tf_grid.py q_1d13 smoke > smoke_q_1d13.log 2>&1 &
"$PY" live_tf_grid.py q_8h13 smoke > smoke_q_8h13.log 2>&1 &
"$PY" dbg_sw.py > dbg_sw.log 2>&1 &
wait
echo "SMOKES_DONE $(date +%F_%H:%M:%S)" > smoke_all.done
