#!/usr/bin/env bash
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
rm -f stopt5_queue.nohup.log
nohup bash stopt5_run.sh > stopt5_queue.nohup.log 2>&1 &
echo "nohup-stopt5 PID=$!"
