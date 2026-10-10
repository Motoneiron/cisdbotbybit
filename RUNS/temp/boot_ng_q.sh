#!/usr/bin/env bash
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
rm -f ng_q_queue.nohup.log
nohup bash run_ng_q.sh > ng_q_queue.nohup.log 2>&1 &
echo "nohup-ngq PID=$!"
