#!/usr/bin/env bash
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
rm -f chain.nohup.log
nohup bash chain_run.sh > chain.nohup.log 2>&1 &
echo "nohup-chain PID=$!"
