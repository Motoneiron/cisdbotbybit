#!/bin/bash
# anchor_queue.sh — очередь EMA-якорей (cb=конфирм-бар, f1h/f4h=начало часа/4ч).
# Запуск: bash anchor_queue.sh   (фоново; пишет anchor_queue.log)
# Логика: ждём завершения tb-прогонов, затем добавляем якорные — по 1-2 конфига,
# чтобы не перегружать машину (юзер просил «проц не перегружай сильно»).
cd D:/PYTHON/cisdbotbybit/RUNS/temp || exit 1
LOG=anchor_queue.log
say(){ echo "$(date '+%H:%M:%S') $*" >> $LOG; }
count(){ ls live_tf/$1/*.pkl 2>/dev/null | wc -l | tr -d ' '; }
wait_dir(){  # $1=dir $2=need $3=max_minutes
  local t=0
  while [ "$t" -lt "$3" ]; do
    if [ "$(count $1)" -ge "$2" ]; then say "OK live_tf/$1 ($(count $1)/$2)"; return 0; fi
    sleep 120; t=$((t+2))
  done
  say "TIMEOUT live_tf/$1 ($(count $1)/$2) — продолжаю"; return 1
}
say "=== START anchor_queue (pid $$) ==="

# Шаг 1: tb-прогон tf7e13_002 готов → запускаем cb + f1h (2 конфига)
wait_dir tf7e13_002 18 1440
say "LAUNCH tf7e13_cb + tf7e13_f1h"
python -u live_tf_grid.py tf7e13_cb > tf7e13cb_out.txt 2>&1 &
python -u live_tf_grid.py tf7e13_f1h > tf7e13f1h_out.txt 2>&1 &
sleep 90
say "  после старта: tf7e13_cb=$(count tf7e13_cb)/18 tf7e13_f1h=$(count tf7e13_f1h)/18"

# Шаг 2: tb-прогон tf7e8_002 готов → tf7e8_cb
wait_dir tf7e8_002 18 1440
say "LAUNCH tf7e8_cb"
python -u live_tf_grid.py tf7e8_cb > tf7e8cb_out.txt 2>&1 &
sleep 90
say "  после старта: tf7e8_cb=$(count tf7e8_cb)/18"

# Шаг 3: f1h готов → tf7e13_f4h
wait_dir tf7e13_f1h 18 1440
say "LAUNCH tf7e13_f4h"
python -u live_tf_grid.py tf7e13_f4h > tf7e13f4h_out.txt 2>&1 &

# Шаг 4: финальное ожидание всех якорных
wait_dir tf7e13_cb 18 1440
wait_dir tf7e8_cb 18 1440
wait_dir tf7e13_f4h 18 1440
say "=== ANCHOR_QUEUE_DONE ==="
