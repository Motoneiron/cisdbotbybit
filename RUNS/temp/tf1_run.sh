#!/bin/bash
# tf1_run.sh — tf1-набор (запрос юзера 29.09): ms1.5 + A/V/D-контроли + slope-гейты (5m/15m: честные gtf, якорь cb).
# Этапы по 2 конфига (без сильного перегруза): [ms15+sl5] → [sl15+voff] → [doff].
cd D:/PYTHON/cisdbotbybit/RUNS/temp || exit 1
LOG=tf1_queue.log
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> $LOG; }

python -m py_compile live_tf_grid.py || { say "COMPILE FAIL"; exit 1; }
say "compile ok; смоук ms15..."
python -u live_tf_grid.py tf1ms15 smoke > tf1_smoke_ms15.log 2>&1 || { say "SMOKE ms15 FAIL"; exit 1; }
say "смоук ms15 ok; смоук sl15..."
python -u live_tf_grid.py tf1ms15_sl15 smoke > tf1_smoke_sl15.log 2>&1 || { say "SMOKE sl15 FAIL"; exit 1; }
say "смоук sl15 ok; смоук voff..."
python -u live_tf_grid.py tf1ms15_voff smoke > tf1_smoke_voff.log 2>&1 || { say "SMOKE voff FAIL"; exit 1; }
say "смоуки ok. Этап 1: ms15 + sl5"
python -u live_tf_grid.py tf1ms15 > tf1ms15_out.txt 2>&1 &
P1=$!
python -u live_tf_grid.py tf1ms15_sl5 > tf1sl5_out.txt 2>&1 &
P2=$!
wait $P1 $P2 2>/dev/null
say "этап 1 готов. Этап 2: sl15 + voff"
python -u live_tf_grid.py tf1ms15_sl15 > tf1sl15_out.txt 2>&1 &
P3=$!
python -u live_tf_grid.py tf1ms15_voff > tf1voff_out.txt 2>&1 &
P4=$!
wait $P3 $P4 2>/dev/null
say "этап 2 готов. Этап 3: doff"
python -u live_tf_grid.py tf1ms15_doff > tf1doff_out.txt 2>&1
say "TF1_QUEUE_DONE ms15=$(ls live_tf/tf1ms15/*.pkl 2>/dev/null | wc -l)/18 sl5=$(ls live_tf/tf1ms15_sl5/*.pkl 2>/dev/null | wc -l)/18 sl15=$(ls live_tf/tf1ms15_sl15/*.pkl 2>/dev/null | wc -l)/18 voff=$(ls live_tf/tf1ms15_voff/*.pkl 2>/dev/null | wc -l)/18 doff=$(ls live_tf/tf1ms15_doff/*.pkl 2>/dev/null | wc -l)/18"
