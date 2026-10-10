#!/usr/bin/env bash
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
rm -f stopt7_queue.nohup.log
nohup bash stopt7_run.sh > stopt7_queue.nohup.log 2>&1 &
echo "nohup-stopt7 PID=$!"
