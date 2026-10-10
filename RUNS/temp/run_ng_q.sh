#!/usr/bin/env bash
# NG-дублирование тест (03.10): без гейта, SOL/2025, с tbt.
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
LOG=ng_q_queue.log
echo "START_NGQ $(date +%F_%H:%M:%S)" >> "$LOG"
"$PY" quick_tp.py tf1ng_q > quick_ng_q.log 2>&1
echo "NGQ_DONE $(date +%F_%H:%M:%S)" >> "$LOG"
