#!/usr/bin/env bash
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
rm -f stopt2_queue.nohup.log
nohup bash stopt2_run.sh > stopt2_queue.nohup.log 2>&1 &
echo "nohup-stopt2 PID=$!"
