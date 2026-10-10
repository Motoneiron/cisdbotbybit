#!/bin/bash
# night_queue.sh — ночной планировщик очереди конфигов (28.09.2026, пока юзер в отъезде).
# Запускает конфиги по мере освобождения слотов; ждёт маркеры (18 pkl в папке) с таймаутом.
# Очередь: ТФ-прогоны (задание 1) + EMA-гейты (задание 2) + остаток 1.5-ветки.
cd D:/PYTHON/cisdbotbybit/RUNS/temp || exit 1
LOG=night_queue.log
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> $LOG; }
cnt() { ls "$1"/*.pkl 2>/dev/null | wc -l; }
wait_dir() {  # wait_dir <dir> <n> <maxtime_min>
  local d="$1" n="$2" mx="$3" t=0
  while [ "$(cnt "$d")" -lt "$n" ]; do
    sleep 120; t=$((t+2))
    if [ "$t" -ge "$mx" ]; then say "TIMEOUT wait $d ($(cnt "$d")/$n) — продолжаю"; return 1; fi
  done
  say "OK: $d готов ($(cnt "$d"))"
  return 0
}
run_cfg() {  # run_cfg <logfile> <cmd...>
  local lf="$1"; shift
  say "LAUNCH: $* -> $lf"
  python -u "$@" > "$lf" 2>&1 &
  echo $!
}

say "planner started. snapshot: ms1.5=$(cnt live_final/ms1.5_tp1.25)/18 w30=$(cnt live_final/ms1.0_wait30)/18 h48=$(cnt live_final/ms1.0_hold48)/18"

# --- по завершении ms1.5_tp1.25 → tf8 (задание 1)
wait_dir live_final/ms1.5_tp1.25 18 300
P1=$(run_cfg tf8_out.txt live_tf_grid.py tf8)

# --- по завершении wait30+hold48 → tf2 + tf7e8_002
wait_dir live_final/ms1.0_wait30 18 330
wait_dir live_final/ms1.0_hold48 18 330
P2=$(run_cfg tf2_out.txt live_tf_grid.py tf2)
P3=$(run_cfg tf7e8_002_out.txt live_tf_grid.py tf7e8_002)

# --- по завершении tf7e13 → ms1.5_a0.8
wait_dir live_tf/tf7e13_002 18 330
P4=$(run_cfg fin15_a08_out.txt live_filt_final.py ms1.5_a0.8)

# --- по завершении tf1 → ms1.5_voff
wait_dir live_tf/tf1 18 330
P5=$(run_cfg fin15_voff_out.txt live_filt_final.py ms1.5_voff)

# --- по завершении tf8 → ms1.5_doff
wait_dir live_tf/tf8 18 330
P6=$(run_cfg fin15_doff_out.txt live_filt_final.py ms1.5_doff)

# --- по завершении tf2+tf7e8_002 → ms1.0_voff + ms1.0_doff
wait_dir live_tf/tf2 18 330
wait_dir live_tf/tf7e8_002 18 330
P7=$(run_cfg fin10_voff_out.txt live_filt_final.py ms1.0_voff)
P8=$(run_cfg fin10_doff_out.txt live_filt_final.py ms1.0_doff)

# --- далее: 1.5-ветка добирается, затем EMA-лайт
wait_dir live_final/ms1.5_a0.8 18 330
P9=$(run_cfg fin15_hold6_out.txt live_filt_final.py ms1.5_hold6)

wait_dir live_final/ms1.5_voff 18 330
P10=$(run_cfg tf7e5_out.txt live_tf_grid.py tf7e5_002)

wait_dir live_final/ms1.5_doff 18 330
P11=$(run_cfg tf7e21_out.txt live_tf_grid.py tf7e21_002)

wait_dir live_final/ms1.0_voff 18 330
wait_dir live_final/ms1.0_doff 18 330
P12=$(run_cfg tf7e8_000_out.txt live_tf_grid.py tf7e8_000)

wait_dir live_final/ms1.5_hold6 18 330
P13=$(run_cfg tf7e13_000_out.txt live_tf_grid.py tf7e13_000)

say "все запуски сделаны; жду завершения последних"
for p in $P1 $P2 $P3 $P4 $P5 $P6 $P7 $P8 $P9 $P10 $P11 $P12 $P13; do wait $p 2>/dev/null; done
say "NIGHT_QUEUE_DONE"
