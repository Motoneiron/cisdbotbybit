#!/bin/bash
# lc_queue.sh — честный якорь 'lc' (29.09): slope на последнем ЗАКРЫТОМ 5m-баре
# к моменту решения (i-1). Проверка «ловушки позднего одобрения»: старые якоря
# tb (slope[i]) и cb (slope[jj]) используют бар, закрывающийся на 5 мин ПОЗЖЕ решения.
cd D:/PYTHON/cisdbotbybit/RUNS/temp || exit 1
LOG=lc_queue.log
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> $LOG; }
say "lc queue start (честный якорь, 6 пар x 3 года)"
nohup python -u live_tf_grid.py tf7e13_lc > tf7e13_lc_out.txt 2>&1 &
P1=$!
say "PID=$P1 tf7e13_lc запущен"
wait $P1 2>/dev/null
say "LC_DONE files=$(ls live_tf/tf7e13_lc/*.pkl 2>/dev/null | wc -l)/18"
