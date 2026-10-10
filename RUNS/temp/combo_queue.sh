#!/bin/bash
# combo_queue.sh — live-проверка DI-комбо (28.09, ждёт слоты от night_queue).
# tf7e13_cb_di (EMA13_cb + DI) и tf7di_cb (DI в одиночку) — по мере освобождения слотов.
cd D:/PYTHON/cisdbotbybit/RUNS/temp || exit 1
LOG=combo_queue.log
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

say "combo planner started (слот-правило: не более ~6 конфигов)"

# Слот 1: ждём финиша ms1.0-ветки (освобождает 2 процесса-конфига)
wait_dir live_final/ms1.0_voff 18 480
wait_dir live_final/ms1.0_doff 18 480
sleep 90
say "LAUNCH: tf7e13_cb_di"
python -u live_tf_grid.py tf7e13_cb_di > tf7e13cbdi_out.txt 2>&1 &
PD1=$!

# Слот 2: после финиша hold6 (или любого следующего)
wait_dir live_final/ms1.5_hold6 18 480
sleep 60
say "LAUNCH: tf7di_cb"
python -u live_tf_grid.py tf7di_cb > tf7di_out.txt 2>&1 &
PD2=$!

wait $PD1 2>/dev/null; say "cb_di завершён ($(cnt live_tf/tf7e13_cb_di)/18)"
wait $PD2 2>/dev/null; say "di завершён ($(cnt live_tf/tf7di_cb)/18)"
say "COMBO_QUEUE_DONE"
