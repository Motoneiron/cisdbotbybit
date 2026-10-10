#!/usr/bin/env bash
# Полный прогон htfctx_run tf1v2 (10 пар x 3 года) → RUNS/temp/live_tf_htfctx/rows_tf1v2/
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
rm -f htfctx_run.log
nohup D:/PYTHON/CISDBOT/.venv/Scripts/python.exe -u htfctx_run.py tf1v2 > htfctx_run.log 2>&1 &
echo "nohup-htfctx PID=$!"
