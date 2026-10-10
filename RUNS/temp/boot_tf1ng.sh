#!/bin/bash
# boot_tf1ng.sh — запускает tf1ng_run.sh отвязанно (nohup), сам сразу завершается.
cd D:/PYTHON/cisdbotbybit/RUNS/temp || exit 1
nohup bash tf1ng_run.sh >/dev/null 2>&1 &
echo "booted $(date '+%Y-%m-%d %H:%M:%S')" >> boot_tf1ng.log
exit 0
