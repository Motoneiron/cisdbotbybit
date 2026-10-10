#!/usr/bin/env bash
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
rm -f stopt_queue.nohup.log
nohup bash stopt_run.sh > stopt_queue.nohup.log 2>&1 &
echo "nohup-stopt PID=$!"
