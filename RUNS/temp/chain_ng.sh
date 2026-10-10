#!/bin/bash
# chain_ng.sh — 05.10: контрольные прогоны к вопросу «нужен ли slope-гейт при dt-фильтре»
# 1) tf1v2_ngate: БЕЗ гейта (dt>=120 остаётся), 10 пар x 3 года -> stopt_tf1v2_ngate/
# 2) tf1lc15_alloff_l1h: догон «гейт без dt» до 10 пар (есть 6: SOL DOGE KAS ADA LINK LTC; догнать XRP BTC AVAX TON)
cd /d/PYTHON/cisdbotbybit/RUNS/temp
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
"$PY" stop_timing_run.py tf1v2_ngate > stopt_ngate.log 2>&1
echo "PART1_DONE $(date +%F_%H:%M:%S)" >> stopt_ngate.log
"$PY" stop_timing_run.py tf1lc15_alloff_l1h > stopt_alloff_dogon.log 2>&1
echo "CHAIN_NG_ALLDONE $(date +%F_%H:%M:%S)" >> stopt_ngate.log
