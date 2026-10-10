#!/bin/bash
# tf8_run.sh — tf8-набор (вопрос юзера 29.09): ms1.5 + A/V/D-контроли + slope-гейты (30m/5m, cb).
# Сначала смоуки двух новых типов, затем очередь этапами (по 2 конфига, без перегруза).
cd D:/PYTHON/cisdbotbybit/RUNS/temp || exit 1
LOG=tf8_queue.log
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> $LOG; }

python -m py_compile live_tf_grid.py || { say "COMPILE FAIL"; exit 1; }
say "compile ok; смоук voff..."
python -u live_tf_grid.py tf8_ms15_voff smoke > tf8_smoke_voff.log 2>&1 || { say "SMOKE voff FAIL"; exit 1; }
say "смоук voff ok; смоук sl30..."
python -u live_tf_grid.py tf8_ms15_sl30 smoke > tf8_smoke_sl30.log 2>&1 || { say "SMOKE sl30 FAIL"; exit 1; }
say "смоуки ok. Этап 1: voff + sl30"
python -u live_tf_grid.py tf8_ms15_voff > tf8voff_out.txt 2>&1 &
P1=$!
python -u live_tf_grid.py tf8_ms15_sl30 > tf8sl30_out.txt 2>&1 &
P2=$!
wait $P1 $P2 2>/dev/null
say "этап 1 готов. Этап 2: doff + sl5"
python -u live_tf_grid.py tf8_ms15_doff > tf8doff_out.txt 2>&1 &
P3=$!
python -u live_tf_grid.py tf8_ms15_sl5 > tf8sl5_out.txt 2>&1 &
P4=$!
wait $P3 $P4 2>/dev/null
say "TF8_QUEUE_DONE voff=$(ls live_tf/tf8_ms15_voff/*.pkl 2>/dev/null | wc -l)/18 doff=$(ls live_tf/tf8_ms15_doff/*.pkl 2>/dev/null | wc -l)/18 sl30=$(ls live_tf/tf8_ms15_sl30/*.pkl 2>/dev/null | wc -l)/18 sl5=$(ls live_tf/tf8_ms15_sl5/*.pkl 2>/dev/null | wc -l)/18"
