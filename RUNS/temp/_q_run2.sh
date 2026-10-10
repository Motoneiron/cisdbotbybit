#!/bin/bash
# Автоцепочка волны-2: ждёт pf-фичи и OI-загрузку, затем мета-LR и OI-фичи и индикаторный скрин.
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
export PYTHONPATH="D:/PYTHON;D:/PYTHON/CISDBOT"
echo "QUEUE2 START $(date +%H:%M:%S)"

# 1) ждём pf-фичи (до 90 мин)
for i in $(seq 1 540); do [ -f stream_off_v1_lv0_v2_pf.pkl ] && break; sleep 10; done
if [ -f stream_off_v1_lv0_v2_pf.pkl ]; then
  python _q_meta_lr.py > _q_meta.log 2>&1; echo "META=$?" >> _q_meta.log
else
  echo "PF НЕ ПОЯВИЛСЯ — пропуск META" > _q_meta.log
fi

# 2) ждём OI-файлы (до 90 мин; 10 oi + 10 ls)
for i in $(seq 1 540); do
  c1=$(ls q_oi/*_oi.pkl 2>/dev/null | wc -l); c2=$(ls q_oi/*_ls.pkl 2>/dev/null | wc -l)
  [ "$c1" -ge 10 ] && [ "$c2" -ge 10 ] && break; sleep 10
done
c1=$(ls q_oi/*_oi.pkl 2>/dev/null | wc -l); c2=$(ls q_oi/*_ls.pkl 2>/dev/null | wc -l)
if [ "$c1" -ge 1 ]; then
  python _q_oi_features.py > _q_oif.log 2>&1; echo "OIF=$?" >> _q_oif.log
else
  echo "OI ФАЙЛОВ НЕТ — пропуск" > _q_oif.log
fi

# 3) индикаторный скрин (не зависит от 1-2)
python _q_ind_screen.py > _q_ind.log 2>&1; echo "IND=$?" >> _q_ind.log

echo "QUEUE2 DONE $(date +%H:%M:%S)"
echo "== meta ==";   tail -4 _q_meta.log 2>/dev/null
echo "== oif ==";    tail -4 _q_oif.log 2>/dev/null
echo "== ind ==";    tail -4 _q_ind.log 2>/dev/null
