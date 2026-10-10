#!/usr/bin/env bash
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
rm -f chain12.nohup.log
nohup bash chain12_run.sh > chain12.nohup.log 2>&1 &
echo "nohup-chain12 PID=$!"
