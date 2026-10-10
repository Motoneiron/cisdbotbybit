#!/usr/bin/env bash
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
rm -f tf1quick_queue.nohup.log
nohup bash tf1quick_run.sh > tf1quick_queue.nohup.log 2>&1 &
echo "nohup PID=$!"
