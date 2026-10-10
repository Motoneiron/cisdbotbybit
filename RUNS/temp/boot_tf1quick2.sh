#!/usr/bin/env bash
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
rm -f tf1quick2_queue.nohup.log
nohup bash tf1quick2_run.sh > tf1quick2_queue.nohup.log 2>&1 &
echo "nohup2 PID=$!"
