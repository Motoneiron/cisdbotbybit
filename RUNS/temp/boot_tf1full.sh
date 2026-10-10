#!/usr/bin/env bash
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
rm -f tf1full_queue.nohup.log
nohup bash tf1full_run.sh > tf1full_queue.nohup.log 2>&1 &
echo "nohup_full PID=$!"
