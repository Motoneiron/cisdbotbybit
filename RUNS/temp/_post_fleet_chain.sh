#!/usr/bin/env bash
# Автоцепочка после флита: снапшот 7 лет -> вектор -> фандинг -> kNN -> eval -> Эллиотт -> кластеры.
cd /d/PYTHON/cisdbotbybit || exit 9
export PYTHONPATH="D:/PYTHON;D:/PYTHON/CISDBOT"
L=RUNS/temp/_post_fleet_log.txt
: > "$L"
echo "[chain] ждём DONE во флите... $(date +%H:%M:%S)" >> "$L"
while ! grep -q "DONE in" RUNS/temp/_rebuild_log.txt; do sleep 60; done
echo "[chain] флит завершён: $(date +%H:%M:%S)" >> "$L"
python RUNS/temp/_stream_snapshot_v1.py --dir "D:/PYTHON/CISDBOT/RUNS/filters_off_full" >> "$L" 2>&1; echo "SNAP_EXIT=$?" >> "$L"
python RUNS/temp/_stream_vector_v2.py RUNS/temp/stream_off_v1.pkl >> "$L" 2>&1; echo "VEC_EXIT=$?" >> "$L"
python RUNS/temp/_funding_merge_v1.py RUNS/temp/stream_off_v1_v2.pkl >> "$L" 2>&1; echo "FUND_EXIT=$?" >> "$L"
python RUNS/temp/_knn18_v1.py RUNS/temp/stream_off_v1_v2.pkl --tag full >> "$L" 2>&1; echo "KNN_EXIT=$?" >> "$L"
python RUNS/temp/_rule_eval_v1.py RUNS/temp/stream_off_v1_v2_funded.pkl >> "$L" 2>&1; echo "EVAL_EXIT=$?" >> "$L"
python RUNS/temp/_elliott_proxy_v1.py RUNS/temp/stream_off_v1_v2.pkl --tag full >> "$L" 2>&1; echo "EL_EXIT=$?" >> "$L"
python RUNS/temp/_cluster_probe.py RUNS/temp/stream_off_v1_v2.pkl >> "$L" 2>&1; echo "CLU_EXIT=$?" >> "$L"
echo "CHAIN_DONE $(date +%H:%M:%S)" >> "$L"
