#!/bin/bash
# finals3_run.sh — перезапуск доборов (29.09): e13_000 (лайт), e21_cb, e5_cb.
# Прошлый запуск умер на 6/18 (2024 готов); 2024-е файлы будут пропущены (skip).
# Запускать через nohup — переживает рестарты Hermes.
cd D:/PYTHON/cisdbotbybit/RUNS/temp || exit 1
LOG=finals3.log
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> $LOG; }
say "restart finals3 (обрыв был на 6/18; пропускаю готовые годы)"
python -u live_tf_grid.py tf7e13_000 > tf7e13_000_out2.txt 2>&1 &
P1=$!
python -u live_tf_grid.py tf7e21_cb > tf7e21cb_out2.txt 2>&1 &
P2=$!
python -u live_tf_grid.py tf7e5_cb > tf7e5cb_out2.txt 2>&1 &
P3=$!
wait $P1 $P2 $P3 2>/dev/null
say "FINALS3_DONE e13_000=$(ls live_tf/tf7e13_000/*.pkl 2>/dev/null | wc -l)/18 e21cb=$(ls live_tf/tf7e21_cb/*.pkl 2>/dev/null | wc -l)/18 e5cb=$(ls live_tf/tf7e5_cb/*.pkl 2>/dev/null | wc -l)/18"
