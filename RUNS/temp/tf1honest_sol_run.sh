#!/bin/bash
# tf1honest_sol_run.sh — ЧЕСТНЫЙ tf1 sl15(sp21) на SOL: якоря lc и cc (2 процесса параллельно).
# Время: ~1 ч 45 мин (SOL = 2024 ~42м + 2025 ~41м + 2026 ~20м; оценки из логов волн run2).
# Смоуки проверены отдельно (tf1_lc_SOL_smoke.log / tf1_cc_SOL_smoke.log).
# Запуск: nohup bash tf1honest_sol_run.sh >/dev/null 2>&1 &
cd D:/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
LOG=tf1honest_sol_queue.log
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> $LOG; }

say "старт: lc + cc на SOL (3 года)"
"$PY" -u tf1_honest_pair.py lc SOL > tf1sl15sp21_lc_SOL_out.txt 2>&1 &
P1=$!
"$PY" -u tf1_honest_pair.py cc SOL > tf1sl15sp21_cc_SOL_out.txt 2>&1 &
P2=$!
say "запущены: lc pid=$P1, cc pid=$P2"
wait $P1 $P2 2>/dev/null
say "TF1HONEST_SOL_DONE lc=$(ls live_tf/tf1sl15sp21_lc/*.pkl 2>/dev/null | wc -l)/3 cc=$(ls live_tf/tf1sl15sp21_cc/*.pkl 2>/dev/null | wc -l)/3"
