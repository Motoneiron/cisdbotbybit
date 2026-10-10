#!/usr/bin/env bash
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
rm -f stopt4_queue.nohup.log
nohup bash stopt4_run.sh > stopt4_queue.nohup.log 2>&1 &
echo "nohup-stopt4 PID=$!"
