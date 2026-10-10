#!/usr/bin/env bash
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
rm -f stopt10_queue.nohup.log
nohup bash stopt10_run.sh > stopt10_queue.nohup.log 2>&1 &
echo "nohup-stopt10 PID=$!"
