#!/usr/bin/env bash
# NOFILTER-прогон кандидата v2 (10 пар x 3 года) → RUNS/temp/live_tf_htfctx_nf/rows_tf1v2_nofilter/
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
rm -f htfctx_nf_run.log
nohup D:/PYTHON/CISDBOT/.venv/Scripts/python.exe -u htfctx_nofilter_run.py tf1v2_nofilter > htfctx_nf_run.log 2>&1 &
echo "nohup-htfctx-nf PID=$!"
