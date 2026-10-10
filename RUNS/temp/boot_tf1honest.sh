#!/bin/bash
# boot_tf1honest.sh — запускает tf1honest_sol_run.sh отвязанно (nohup), сам сразу завершается.
cd D:/PYTHON/cisdbotbybit/RUNS/temp || exit 1
nohup bash tf1honest_sol_run.sh >/dev/null 2>&1 &
echo "booted $(date '+%Y-%m-%d %H:%M:%S')" >> boot_tf1honest.log
exit 0
