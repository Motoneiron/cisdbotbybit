#!/usr/bin/env bash
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
rm -f stopt11_queue.nohup.log
nohup bash stopt11_run.sh > stopt11_queue.nohup.log 2>&1 &
echo "nohup-stopt11 PID=$!"
