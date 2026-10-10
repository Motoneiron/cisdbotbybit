#!/usr/bin/env bash
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
rm -f quick_tp_queue.nohup.log
nohup bash quick_tp_run.sh > quick_tp_queue.nohup.log 2>&1 &
echo "nohup-quicktp PID=$!"
