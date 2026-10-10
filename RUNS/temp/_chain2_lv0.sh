#!/usr/bin/env bash
# Цепочка v2: после снапшота lv0 (LONG vd>=0) — вектор, фандинг, kNN, eval, Эллиотт, кластеры.
cd /d/PYTHON/cisdbotbybit || exit 9
export PYTHONPATH="D:/PYTHON;D:/PYTHON/CISDBOT"
L=RUNS/temp/_chain2_lv0.log
: > "$L"
echo "[chain2] ждём снапшот lv0... $(date +%H:%M:%S)" >> "$L"
while ! grep -q "ИТОГО" RUNS/temp/_snap_lv0_log.txt; do sleep 60; done
echo "[chain2] снапшот готов $(date +%H:%M:%S)" >> "$L"
python RUNS/temp/_stream_vector_v2.py RUNS/temp/stream_off_v1_lv0.pkl >> "$L" 2>&1; echo "VEC=$?" >> "$L"
python RUNS/temp/_funding_merge_v1.py RUNS/temp/stream_off_v1_lv0_v2.pkl >> "$L" 2>&1; echo "FUND=$?" >> "$L"
python RUNS/temp/_knn18_v1.py RUNS/temp/stream_off_v1_lv0_v2.pkl --tag lv0 >> "$L" 2>&1; echo "KNN=$?" >> "$L"
python RUNS/temp/_rule_eval_v1.py RUNS/temp/stream_off_v1_lv0_v2_funded.pkl >> "$L" 2>&1; echo "EVAL=$?" >> "$L"
python RUNS/temp/_elliott_proxy_v1.py RUNS/temp/stream_off_v1_lv0_v2.pkl --tag lv0 >> "$L" 2>&1; echo "EL=$?" >> "$L"
python RUNS/temp/_cluster_probe.py RUNS/temp/stream_off_v1_lv0_v2.pkl >> "$L" 2>&1; echo "CLU=$?" >> "$L"
echo "CHAIN2_DONE $(date +%H:%M:%S)" >> "$L"
