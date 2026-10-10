#!/bin/bash
# tf1_run2.sh — tf1-расширение (запрос юзера 29.09): span-вариации гейтов (8/21 x 5m/15m), мс 1.25, a0.8, гейт на базовом мс1.0.
# Волны по 2 конфига: [sl5sp8+sl5sp21] → [sl15sp8+sl15sp21] → [sl5ms10+ms125] → [ms15a08].
cd D:/PYTHON/cisdbotbybit/RUNS/temp || exit 1
LOG=tf1_queue2.log
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> $LOG; }

python -m py_compile live_tf_grid.py || { say "COMPILE FAIL"; exit 1; }
say "compile ok; смоук sl5sp8..."
python -u live_tf_grid.py tf1sl5sp8 smoke > tf1_smoke_sl5sp8.log 2>&1 || { say "SMOKE sl5sp8 FAIL"; exit 1; }
say "смоук sl5sp8 ok; смоук sl15sp21..."
python -u live_tf_grid.py tf1sl15sp21 smoke > tf1_smoke_sl15sp21.log 2>&1 || { say "SMOKE sl15sp21 FAIL"; exit 1; }
say "смоук sl15sp21 ok; смоук ms15a08..."
python -u live_tf_grid.py tf1ms15a08 smoke > tf1_smoke_a08.log 2>&1 || { say "SMOKE ms15a08 FAIL"; exit 1; }
say "смоуки ok. Волна 1: sl5sp8 + sl5sp21"
python -u live_tf_grid.py tf1sl5sp8 > tf1sl5sp8_out.txt 2>&1 &
P1=$!
python -u live_tf_grid.py tf1sl5sp21 > tf1sl5sp21_out.txt 2>&1 &
P2=$!
wait $P1 $P2 2>/dev/null
say "волна 1 готова. Волна 2: sl15sp8 + sl15sp21"
python -u live_tf_grid.py tf1sl15sp8 > tf1sl15sp8_out.txt 2>&1 &
P3=$!
python -u live_tf_grid.py tf1sl15sp21 > tf1sl15sp21_out.txt 2>&1 &
P4=$!
wait $P3 $P4 2>/dev/null
say "волна 2 готова. Волна 3: sl5ms10 + ms125"
python -u live_tf_grid.py tf1sl5ms10 > tf1sl5ms10_out.txt 2>&1 &
P5=$!
python -u live_tf_grid.py tf1ms125 > tf1ms125_out.txt 2>&1 &
P6=$!
wait $P5 $P6 2>/dev/null
say "волна 3 готова. Волна 4: ms15a08"
python -u live_tf_grid.py tf1ms15a08 > tf1ms15a08_out.txt 2>&1
say "TF1_RUN2_DONE sl5sp8=$(ls live_tf/tf1sl5sp8/*.pkl 2>/dev/null | wc -l)/18 sl5sp21=$(ls live_tf/tf1sl5sp21/*.pkl 2>/dev/null | wc -l)/18 sl15sp8=$(ls live_tf/tf1sl15sp8/*.pkl 2>/dev/null | wc -l)/18 sl15sp21=$(ls live_tf/tf1sl15sp21/*.pkl 2>/dev/null | wc -l)/18 sl5ms10=$(ls live_tf/tf1sl5ms10/*.pkl 2>/dev/null | wc -l)/18 ms125=$(ls live_tf/tf1ms125/*.pkl 2>/dev/null | wc -l)/18 a08=$(ls live_tf/tf1ms15a08/*.pkl 2>/dev/null | wc -l)/18"
