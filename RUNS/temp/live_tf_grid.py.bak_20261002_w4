"""live_tf_grid.py — прогоны других ТФ и slope-EMA-гейта в живой модели (задания 27.09).

Живая модель = как live_filt_abl.py: busy, htf_taken, tp_touched, sweep_valid,
fill по 1m с окном лимитки профиля, выход TP/SL/time(окно позиции профиля),
комиссии Bybit (maker 0.036% / taker 0.10%). Фильтры A/V/D включены, atr=0.40
(единый стандарт, как канон tf7). min_stop — по режиму.

Профили ТФ берутся из CONFIG бота (timeframe, htf_ratio, limit_h, position_h):
  tf1 : 15m→4H, limit 5ч,  pos 16ч      — задание 1
  tf8 : 30m→8H, limit 30м, pos 6ч       — задание 1
  tf2 : 1h→Daily, limit 24ч, pos 24ч    — задание 1
  tf0 : 5m→1H, limit 1ч, pos 6ч         — справочно
  tf7 — канон (5m→4H, limit 10м, pos 12ч) + опциональный slope-EMA гейт (задание 2)

Режимы slope-гейта (tf7e*): гейт считается по рабочему 5m (или иному ТФ):
  pass если (LONG и slope>thr) или (SHORT и slope<thr), NaN — pass (fail-open);
  иначе сигнал скипается (как в скрине ema_span_scan.py).

Запуск:  python live_tf_grid.py tf8            # все 6 пар × 3 года → live_tf/tf8/
         python live_tf_grid.py tf7e8_002      # tf7 + гейт span 8, thr 0.02% → live_tf/tf7e8_002/
         python live_tf_grid.py tf8 smoke      # смоук: ADA, месяц, live_tf/smoke_tf8/
"""
from __future__ import annotations

import logging
import os
import pickle
import sys
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

OUT_ROOT = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf"
PATHS = {
    "SOL": r"D:\databtcusdt\SOLUSDT-1m\SOLUSDT_1m_full_hdr.csv",
    "DOGE": r"D:\databtcusdt\DOGEUSDT-1m\DOGEUSDT_1m_full_hdr.csv",
    "KAS": r"D:\databtcusdt\KASUSDT-1m\KASUSDT_1m_full_hdr.csv",
    "ADA": r"D:\databtcusdt\ADAUSDT-1m-merged.csv",
    "LINK": r"D:\databtcusdt\LINKUSDT-1m-merged.csv",
    "LTC": r"D:\databtcusdt\LTCUSDT-1m-merged.csv",
}
YEARS = [
    (2024, "2024-01-01", "2025-01-01"),
    (2025, "2025-01-01", "2026-01-01"),
    (2026, "2026-01-01", "2026-09-01"),
]
WIN = 300
MAKER, TAKER = 0.00036, 0.0010

# mode: dict(profile=..., min_stop=%..., sl_gate=(span, thr, gtf|None) | None)
MODES: dict[str, dict] = {
    "tf1": {"profile": "tf1", "min_stop": 1.0},
    "tf8": {"profile": "tf8", "min_stop": 1.0},
    "tf2": {"profile": "tf2", "min_stop": 1.0},
    "tf0": {"profile": "tf0", "min_stop": 1.0},
    # tf7 + slope gate по рабочему 5m: span_thr в имени
    "tf7e5_002": {"profile": "tf7", "min_stop": 1.0, "sl_gate": (5, 0.0002, None)},
    "tf7e8_000": {"profile": "tf7", "min_stop": 1.0, "sl_gate": (8, 0.0, None)},
    "tf7e8_002": {"profile": "tf7", "min_stop": 1.0, "sl_gate": (8, 0.0002, None)},
    "tf7e13_002": {"profile": "tf7", "min_stop": 1.0, "sl_gate": (13, 0.0002, None)},
    "tf7e21_002": {"profile": "tf7", "min_stop": 1.0, "sl_gate": (21, 0.0002, None)},
    "tf7e8_002_ms15": {"profile": "tf7", "min_stop": 1.5, "sl_gate": (8, 0.0002, None)},
    # ЯКОРЬ гейта (сравнение): tb=триггер-бар (все выше), cb=конфирм-бар,
    # f1h/f4h=«первый бар часа/4ч» (наклон квантован к началу часа/4ч блока)
    "tf7e13_cb": {"profile": "tf7", "min_stop": 1.0, "sl_gate": (13, 0.0002, None, "cb")},
    "tf7e8_cb": {"profile": "tf7", "min_stop": 1.0, "sl_gate": (8, 0.0002, None, "cb")},
    "tf7e13_f1h": {"profile": "tf7", "min_stop": 1.0, "sl_gate": (13, 0.0002, None, "f1h")},
    "tf7e13_f4h": {"profile": "tf7", "min_stop": 1.0, "sl_gate": (13, 0.0002, None, "f4h")},
    # КОМБО: лучший гейт (cb) + лучший рычаг (min_stop 1.5)
    "tf7e13_cb_ms15": {"profile": "tf7", "min_stop": 1.5, "sl_gate": (13, 0.0002, None, "cb")},
    # КОМБО-2: EMA13_cb + DI-гейт (книга: pass&pass +0.325; DI независим от EMA, corr~0)
    "tf7e13_cb_di": {"profile": "tf7", "min_stop": 1.0, "sl_gate": (13, 0.0002, None, "cb"), "di_gate": True},
    # DI-гейт в одиночку (проверка самостоятельности)
    "tf7di_cb": {"profile": "tf7", "min_stop": 1.0, "di_gate": True, "gate_anchor": "cb"},
    # ФИНАЛЬНЫЕ ТОЧКИ: лайт thr=0 (span13 — забытый) + cb-якорь на краях сетки span (5/21)
    "tf7e13_000": {"profile": "tf7", "min_stop": 1.0, "sl_gate": (13, 0.0, None)},
    "tf7e21_cb": {"profile": "tf7", "min_stop": 1.0, "sl_gate": (21, 0.0002, None, "cb")},
    "tf7e5_cb": {"profile": "tf7", "min_stop": 1.0, "sl_gate": (5, 0.0002, None, "cb")},
    # ЧЕСТНЫЕ якоря (проверка «ловушки позднего одобрения», 29.09):
    #   lc — slope на последнем ЗАКРЫТОМ 5m-баре к моменту решения (i-1), без 5-мин загляда
    #   cc — slope на баре конфирма (jj-1)
    "tf7e13_lc": {"profile": "tf7", "min_stop": 1.0, "sl_gate": (13, 0.0002, None, "lc")},
    "tf7e13_cc": {"profile": "tf7", "min_stop": 1.0, "sl_gate": (13, 0.0002, None, "cc")},
    "tf7e21_lc": {"profile": "tf7", "min_stop": 1.0, "sl_gate": (21, 0.0002, None, "lc")},
    # TF8-НАБОР (вопрос юзера 29.09): ms1.5 + контроли A/V/D + slope-гейт на tf8
    "tf8_ms15_voff": {"profile": "tf8", "min_stop": 1.5, "det_filters": {"atr_enabled": True, "vol_enabled": False, "d_enabled": True}},
    "tf8_ms15_doff": {"profile": "tf8", "min_stop": 1.5, "det_filters": {"atr_enabled": True, "vol_enabled": True, "d_enabled": False}},
    "tf8_ms15_sl30": {"profile": "tf8", "min_stop": 1.5, "sl_gate": (13, 0.0002, "30m", "cb")},
    "tf8_ms15_sl5": {"profile": "tf8", "min_stop": 1.5, "sl_gate": (13, 0.0002, "5m", "cb")},
    # ТФ × ms1.5 и ТФ × slope-гейт (5m-гейт на чужих профилях: gtf="5m")
    "tf8_ms15": {"profile": "tf8", "min_stop": 1.5},
    "tf2_ms15": {"profile": "tf2", "min_stop": 1.5},
    "tf8e8_002": {"profile": "tf8", "min_stop": 1.0, "sl_gate": (8, 0.0002, "5m")},
    "tf2e8_002": {"profile": "tf2", "min_stop": 1.0, "sl_gate": (8, 0.0002, "5m")},
    # TF1-НАБОР (запрос юзера 29.09: «ещё один ТФ — 15м→4ч»): ms1.5 + A/V/D-контроли + slope-гейты (5m/15m: честные gtf-крепления к закрытым барам, якорь cb)
    "tf1ms15": {"profile": "tf1", "min_stop": 1.5},
    "tf1ms15_voff": {"profile": "tf1", "min_stop": 1.5, "det_filters": {"atr_enabled": True, "vol_enabled": False, "d_enabled": True}},
    "tf1ms15_doff": {"profile": "tf1", "min_stop": 1.5, "det_filters": {"atr_enabled": True, "vol_enabled": True, "d_enabled": False}},
    "tf1ms15_sl5": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (13, 0.0002, "5m", "cb")},
    "tf1ms15_sl15": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (13, 0.0002, "15m", "cb")},
    # TF1-расширение (запрос юзера 29.09: «помимо базы — мс, гейты разные, фильтры»)
    "tf1ms125": {"profile": "tf1", "min_stop": 1.25},
    "tf1ms15a08": {"profile": "tf1", "min_stop": 1.5, "min_sweep_atr": 0.8},
    "tf1sl5sp8": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (8, 0.0002, "5m", "cb")},
    "tf1sl5sp21": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "5m", "cb")},
    "tf1sl15sp8": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (8, 0.0002, "15m", "cb")},
    "tf1sl15sp21": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "cb")},
    "tf1sl5ms10": {"profile": "tf1", "min_stop": 1.0, "sl_gate": (13, 0.0002, "5m", "cb")},
    # СТЭК tf1+ms1.5+честный lc (запрос юзера 30.09): контроли фильтров A/V/D
    #   on (имя = папка честного SOL-прогона) / foff (все off) / fa / fv / fd (по одному)
    "tf1sl15sp21_lc": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "lc"),
                       "det_filters": {"atr_enabled": True, "vol_enabled": True, "d_enabled": True}},
    "tf1lc15_foff": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "lc"),
                     "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "tf1lc15_fa": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "lc"),
                   "det_filters": {"atr_enabled": True, "vol_enabled": False, "d_enabled": False}},
    "tf1lc15_fv": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "lc"),
                   "det_filters": {"atr_enabled": False, "vol_enabled": True, "d_enabled": False}},
    "tf1lc15_fd": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "lc"),
                   "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": True}},
    # alloff — ПОЛНОЕ выключение фильтров (вкл. свип A: min_sweep_atr=0; в foff свип оставался 0.40)
    "tf1lc15_alloff": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "lc"),
                       "min_sweep_atr": 0.0,
                       "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    # hold-сетка (запрос юзера 30.09): таймаут ВЫХОДА 12/8/6ч на базе строки 1 (без V/D, свип 0.4)
    "tf1lc15_foff_h12": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "lc"),
                         "position_h": 12,
                         "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "tf1lc15_foff_h8": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "lc"),
                        "position_h": 8,
                        "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "tf1lc15_foff_h6": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "lc"),
                        "position_h": 6,
                        "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    # limit-сетка (запрос юзера 30.09): ожидание ВХОДА 15м/30м/1ч/2ч на базе строки 1 (без V/D; база 5ч уже есть)
    "tf1lc15_l15m": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "lc"),
                     "limit_h": 0.25,
                     "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "tf1lc15_l30m": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "lc"),
                     "limit_h": 0.5,
                     "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "tf1lc15_l1h": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "lc"),
                    "limit_h": 1,
                    "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "tf1lc15_l2h": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "lc"),
                    "limit_h": 2,
                    "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    # CB-ЗЕРКАЛА сеток (запрос юзера 01.10): те же конфиги на лукапном якоре cb — сравнение с честным lc
    "tf1cb15_foff": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "cb"),
                     "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "tf1cb15_foff_h12": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "cb"),
                         "position_h": 12,
                         "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "tf1cb15_foff_h8": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "cb"),
                        "position_h": 8,
                        "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "tf1cb15_foff_h6": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "cb"),
                        "position_h": 6,
                        "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "tf1cb15_l2h": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "cb"),
                    "limit_h": 2,
                    "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "tf1cb15_l1h": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "cb"),
                    "limit_h": 1,
                    "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "tf1cb15_l30m": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "cb"),
                     "limit_h": 0.5,
                     "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "tf1cb15_l15m": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "cb"),
                     "limit_h": 0.25,
                     "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    # БЕЗ ЯКОРЯ (запрос юзера 01.10): те же 8 конфигов, но slope-гейт выключен ПОЛНОСТЬЮ
    "tf1ng15_foff": {"profile": "tf1", "min_stop": 1.5,
                     "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "tf1ng15_foff_h12": {"profile": "tf1", "min_stop": 1.5, "position_h": 12,
                         "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "tf1ng15_foff_h8": {"profile": "tf1", "min_stop": 1.5, "position_h": 8,
                        "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "tf1ng15_foff_h6": {"profile": "tf1", "min_stop": 1.5, "position_h": 6,
                        "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "tf1ng15_l2h": {"profile": "tf1", "min_stop": 1.5, "limit_h": 2,
                    "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "tf1ng15_l1h": {"profile": "tf1", "min_stop": 1.5, "limit_h": 1,
                    "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "tf1ng15_l30m": {"profile": "tf1", "min_stop": 1.5, "limit_h": 0.5,
                     "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "tf1ng15_l15m": {"profile": "tf1", "min_stop": 1.5, "limit_h": 0.25,
                     "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    # ===== QUICK-СЕРИЯ 01.10 (тюнинг гейта на SOL/2025): спаны, пороги, якорь свипа, сглаживание, старшие ТФ =====
    # Все: tf1 + ms1.5 + foff (без V/D), база 5ч/16ч, источник 15m. lc/cc/sw — честные, cb — лукап-контроль.
    "q_sp8_lc": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (8, 0.0002, "15m", "lc"),
                 "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q_sp8_cb": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (8, 0.0002, "15m", "cb"),
                 "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q_sp13_lc": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (13, 0.0002, "15m", "lc"),
                  "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q_sp13_cb": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (13, 0.0002, "15m", "cb"),
                  "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q_sp21_cb": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "cb"),
                  "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q_sp34_lc": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (34, 0.0002, "15m", "lc"),
                  "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q_sp34_cb": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (34, 0.0002, "15m", "cb"),
                  "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q_cc21": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "cc"),
               "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q_sw21": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "sw"),
               "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q_sw13": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (13, 0.0002, "15m", "sw"),
               "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q_th001": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0001, "15m", "lc"),
                "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q_th003": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0003, "15m", "lc"),
                "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q_th005": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0005, "15m", "lc"),
                "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q_th010": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0010, "15m", "lc"),
                "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q_th005_cb": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0005, "15m", "cb"),
                   "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q_ss3": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "lc"), "slope_smooth": 3,
              "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q_ss5": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "lc"), "slope_smooth": 5,
              "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q_ss3_cb": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "cb"), "slope_smooth": 3,
                 "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q_1d13": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (13, 0.0002, "1D", "lc"),
               "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q_8h13": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (13, 0.0002, "8h", "lc"),
               "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    # QUICK-ВОЛНА-2 (01.10): комбо спан×порог на лучших осях (sp13/34 × th0.03/0.05)
    "q_c13_003": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (13, 0.0003, "15m", "lc"),
                  "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q_c34_003": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (34, 0.0003, "15m", "lc"),
                  "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q_c13_005": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (13, 0.0005, "15m", "lc"),
                  "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q_c34_005": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (34, 0.0005, "15m", "lc"),
                  "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    # QUICK-ВОЛНА-3 (02.10): финалисты × окна входа/выхода 1ч/16ч и 1ч/12ч (vs 5ч/16ч волн 1-2)
    "q1h16_sp13": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (13, 0.0002, "15m", "lc"), "limit_h": 1,
                   "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q1h16_sp13x05": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (13, 0.0005, "15m", "lc"), "limit_h": 1,
                      "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q1h16_th003": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0003, "15m", "lc"), "limit_h": 1,
                    "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q1h16_sp34": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (34, 0.0002, "15m", "lc"), "limit_h": 1,
                   "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q1h16_sp34x03": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (34, 0.0003, "15m", "lc"), "limit_h": 1,
                      "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q1h12_sp21": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "lc"), "limit_h": 1, "position_h": 12,
                   "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q1h12_sp13": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (13, 0.0002, "15m", "lc"), "limit_h": 1, "position_h": 12,
                   "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q1h12_sp13x05": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (13, 0.0005, "15m", "lc"), "limit_h": 1, "position_h": 12,
                      "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q1h12_th003": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0003, "15m", "lc"), "limit_h": 1, "position_h": 12,
                    "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q1h12_sp34": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (34, 0.0002, "15m", "lc"), "limit_h": 1, "position_h": 12,
                   "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q1h12_sp34x03": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (34, 0.0003, "15m", "lc"), "limit_h": 1, "position_h": 12,
                      "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    # QUICK-ВОЛНА-4 (02.10): вход меньше часа — 15м/30м/45м (база, sp13, th0.03), выход 16ч
    "q15m_sp21": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "lc"), "limit_h": 0.25,
                  "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q30m_sp21": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "lc"), "limit_h": 0.5,
                  "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q45m_sp21": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0002, "15m", "lc"), "limit_h": 0.75,
                  "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q15m_sp13": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (13, 0.0002, "15m", "lc"), "limit_h": 0.25,
                  "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q30m_sp13": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (13, 0.0002, "15m", "lc"), "limit_h": 0.5,
                  "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q45m_sp13": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (13, 0.0002, "15m", "lc"), "limit_h": 0.75,
                  "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q15m_th003": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0003, "15m", "lc"), "limit_h": 0.25,
                   "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q30m_th003": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0003, "15m", "lc"), "limit_h": 0.5,
                   "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
    "q45m_th003": {"profile": "tf1", "min_stop": 1.5, "sl_gate": (21, 0.0003, "15m", "lc"), "limit_h": 0.75,
                   "det_filters": {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}},
}
MODE = "tf8"
SMOKE = False
OUT_DIR = ""


def load_1m(path: str, since: str, until: str) -> pd.DataFrame:
    t0 = pd.Timestamp(since) - pd.Timedelta(days=4)
    t1 = pd.Timestamp(until) + pd.Timedelta(days=1)
    parts = []
    cols = ["open_time", "open", "high", "low", "close", "volume"]
    for chunk in pd.read_csv(path, usecols=cols, chunksize=500_000):
        ot = pd.to_datetime(chunk["open_time"], unit="ms")
        m = (ot >= t0) & (ot < t1)
        if not m.any():
            if len(ot) and ot.iloc[-1] < t0:
                continue
            if len(ot) and ot.iloc[0] >= t1:
                break
            continue
        sub = chunk.loc[m, ["open", "high", "low", "close", "volume"]].astype(float)
        sub.index = ot[m]
        parts.append(sub)
    if not parts:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.concat(parts)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def _outcome(df1, scan, direction, entry, stop, tp, limit_min, pos_h):
    t0 = pd.Timestamp(scan)
    window = df1[(df1.index >= t0) & (df1.index < t0 + pd.Timedelta(minutes=limit_min))]
    fill_ts = None
    for ts, bar in window.iterrows():
        hit = float(bar.low) <= entry if direction == "LONG" else float(bar.high) >= entry
        if hit:
            fill_ts = ts
            break
    if fill_ts is None:
        return None
    end = fill_ts + pd.Timedelta(hours=pos_h)
    path = df1[(df1.index >= fill_ts) & (df1.index <= end)]
    if path.empty:
        return None
    sp = abs(entry - stop) / entry
    exit_ts = path.index[-1]
    kind = "time"
    gross = None
    for ts, bar in path.iterrows():
        if direction == "LONG":
            sl_hit = float(bar.low) <= stop
            tp_hit = float(bar.high) >= tp
        else:
            sl_hit = float(bar.high) >= stop
            tp_hit = float(bar.low) <= tp
        if sl_hit:
            kind, gross, exit_ts = "sl", -1.0, ts
            break
        if tp_hit:
            kind, gross, exit_ts = "tp", 1.0, ts
            break
    if gross is None:
        last = float(path.iloc[-1].close)
        risk = (entry - stop) if direction == "LONG" else (stop - entry)
        gross = ((last - entry) if direction == "LONG" else (entry - last)) / risk
    fee_x = MAKER if kind == "tp" else TAKER
    r = float(gross) - MAKER / sp - fee_x / sp
    return kind, r, exit_ts


def _tp_touched(sl, direction, tp, since) -> bool:
    if tp <= 0 or not since:
        return False
    try:
        t = pd.Timestamp(since)
    except Exception:
        return False
    sub = sl[sl.index >= t]
    if len(sub) < 2:
        sub = sub.iloc[:-1] if len(sub) else sub
    else:
        sub = sub.iloc[:-1]
    if sub.empty:
        return False
    if direction == "LONG":
        return float(sub["high"].max()) >= tp
    return float(sub["low"].min()) <= tp


def _tf_min_local(bot, gtf: str) -> int:
    # как bot._tf_to_minutes, но с поддержкой дневок ("1D"/"2D") — бот их не умеет
    g = str(gtf).strip().lower()
    if g.endswith("d"):
        return max(1, int(g[:-1] or 1)) * 1440
    return bot._tf_to_minutes(g)


def _resample_local(bot, df: pd.DataFrame, gtf: str) -> pd.DataFrame:
    g = str(gtf).strip().lower()
    if g.endswith("d"):
        rule = f"{_tf_min_local(bot, gtf)}min"
        out = pd.DataFrame({
            "open":   df["open"].resample(rule, label="left", closed="left").first(),
            "high":   df["high"].resample(rule, label="left", closed="left").max(),
            "low":    df["low"].resample(rule, label="left", closed="left").min(),
            "close":  df["close"].resample(rule, label="left", closed="left").last(),
            "volume": df["volume"].resample(rule, label="left", closed="left").sum(),
        })
        return out.dropna(subset=["close"])
    return bot._resample_ohlcv(df, gtf)


def walk(bot, sym, df_tf, df1, since, until) -> list[dict]:
    conf = MODES[MODE]
    prof = conf["profile"]
    min_stop = float(conf["min_stop"])
    sl_gate = conf.get("sl_gate")
    C = bot.CONFIG[prof]
    htf = int(C["htf_ratio"])
    limit_min = int(round(float(conf.get("limit_h") or C["limit_h"]) * 60))  # override для limit-сеток (30.09)
    pos_h = float(conf.get("position_h") or C["position_h"])  # override для hold-сеток (30.09)
    tf_rule = str(C["timeframe"])

    slope_arr = None
    gate_anchor = conf.get("gate_anchor", "tb")
    if sl_gate:
        span, thr, gtf = sl_gate[0], sl_gate[1], sl_gate[2]
        gate_anchor = sl_gate[3] if len(sl_gate) > 3 else gate_anchor
        if gtf:
            src = _resample_local(bot, df1, gtf)
            ema = src["close"].ewm(span=span, adjust=False, min_periods=span).mean()
            slope_full = (ema / ema.shift(1) - 1.0).to_numpy(dtype=float)
            ct_arr = (src.index + pd.Timedelta(minutes=_tf_min_local(bot, gtf))).to_numpy()
            scan_ns = df_tf.index.to_numpy()
            ii = np.searchsorted(ct_arr, scan_ns, side="right") - 1
            n = len(slope_full)
            slope_arr = np.where((ii >= 0) & (ii < n) & (n > 0), slope_full[np.clip(ii, 0, max(0, n - 1))], np.nan)
        else:
            ema = df_tf["close"].ewm(span=span, adjust=False, min_periods=span).mean()
            slope_arr = (ema / ema.shift(1) - 1.0).to_numpy(dtype=float)
        g_thr = float(thr)
        ss_k = int(conf.get("slope_smooth") or 0)
        if ss_k > 1 and slope_arr is not None:
            # сглаживание ряда наклона (SMA по последним ss_k барам) — только прошлое, без загляда
            slope_arr = pd.Series(slope_arr).rolling(ss_k, min_periods=ss_k).mean().to_numpy()

    di_arr = None
    if conf.get("di_gate"):
        src5 = bot._resample_ohlcv(df1, "5m")
        _h, _l, _c = src5["high"], src5["low"], src5["close"]
        _tr = pd.concat([(_h - _l), (_h - _c.shift()).abs(), (_l - _c.shift()).abs()], axis=1).max(axis=1)
        _atr = _tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        _up = _h.diff()
        _dn = -_l.diff()
        _pdm = pd.Series(np.where((_up > _dn) & (_up > 0), _up, 0.0), index=src5.index)
        _mdm = pd.Series(np.where((_dn > _up) & (_dn > 0), _dn, 0.0), index=src5.index)
        _pdi = 100 * _pdm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / _atr
        _mdi = 100 * _mdm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / _atr
        spread_full = (_pdi - _mdi).to_numpy(dtype=float)
        ct5 = (src5.index + pd.Timedelta(minutes=5)).to_numpy()
        scan_ns5 = df_tf.index.to_numpy()
        ii5 = np.searchsorted(ct5, scan_ns5, side="right") - 1
        n5 = len(spread_full)
        di_arr = np.where((ii5 >= 0) & (ii5 < n5) & (n5 > 0), spread_full[np.clip(ii5, 0, max(0, n5 - 1))], np.nan)

    def _anchor_val(arr, s, i, scan_ts):
        # значение arr на якоре gate_anchor (tb/cb/f1h/f4h); для DI-гейта
        if arr is None:
            return np.nan
        if gate_anchor == "tb":
            return arr[i] if i < len(arr) else np.nan
        if gate_anchor == "cb":
            cb_s = str(s.get("confirm_bar_time") or "")
            if cb_s:
                try:
                    jj = int(np.searchsorted(df_tf.index.to_numpy(), np.datetime64(pd.Timestamp(cb_s)), side="right"))
                    if 0 <= jj < len(arr):
                        return arr[jj]
                except Exception:
                    return np.nan
            return np.nan
        if gate_anchor == "lc":
            return arr[i - 1] if 0 <= i - 1 < len(arr) else np.nan
        if gate_anchor == "cc":
            cb_s2 = str(s.get("confirm_bar_time") or "")
            if cb_s2:
                try:
                    jj2 = int(np.searchsorted(df_tf.index.to_numpy(), np.datetime64(pd.Timestamp(cb_s2)), side="right"))
                    if 1 <= jj2 <= len(arr):
                        return arr[jj2 - 1]
                except Exception:
                    return np.nan
            return np.nan
        if gate_anchor == "sw":
            tr_s = str(s.get("trigger_bar_time") or s.get("trigger_bar_at") or "")
            if tr_s:
                try:
                    kk = int(np.searchsorted(df_tf.index.to_numpy(),
                                             np.datetime64(pd.Timestamp(tr_s)), side="right"))
                    if 1 <= kk <= len(arr):
                        return arr[kk - 1]
                except Exception:
                    return np.nan
            return np.nan
        an = scan_ts.floor("1h") if gate_anchor == "f1h" else scan_ts.floor("4h")
        kk = int(np.searchsorted(df_tf.index.to_numpy(), np.datetime64(an), side="left"))
        return arr[kk] if kk < len(arr) else np.nan

    bot.state.paper = True
    bot.state.sweep_candidates.clear()
    bot.state.htf_sweep_lock.clear()
    if hasattr(bot.state, "htf_sweep_validated"):
        bot.state.htf_sweep_validated.clear()
    seen: set = set()
    htf_taken: set = set()
    busy_until = None
    t_since = pd.Timestamp(since)
    t_until = pd.Timestamp(until)
    rows = []
    n_bars = len(df_tf)
    t0 = time.time()
    n_skip_gate = 0
    for i in range(WIN, n_bars):
        scan_ts = pd.Timestamp(df_tf.index[i])
        if scan_ts < t_since:
            continue
        if scan_ts >= t_until:
            break
        if i % 8000 == 0:
            print(f"  [{MODE}] {sym} {scan_ts.date()} trades={len(rows)} skip_gate={n_skip_gate} sec={time.time()-t0:.0f}", flush=True)
        sl = df_tf.iloc[i - (WIN - 1): i + 1]
        sigs = bot.detect_signals(
            sl, seen, htf_ratio=htf, tf_name=prof,
            df_confirm=None, min_sweep_atr=conf.get("min_sweep_atr", 0.40),
        ) or []
        sigs.sort(key=lambda s: str(s.get("timestamp") or ""), reverse=True)
        scan_s = str(scan_ts)[:19]
        for s in sigs:
            h = str(s.get("hash") or "")
            if h and h not in seen:
                seen.add(h)
            direction = str(s.get("direction") or "")
            try:
                entry = float(s.get("entry") or 0)
                stop = float(s.get("stop") or 0)
                tp = float(s.get("tp") or 0)
            except (TypeError, ValueError):
                continue
            if entry <= 0 or stop <= 0 or entry == stop:
                continue
            if slope_arr is not None:
                if gate_anchor == "tb":
                    sv = slope_arr[i] if i < len(slope_arr) else np.nan
                elif gate_anchor == "cb":
                    # slope на баре сразу ПОСЛЕ конфирм-бара (историческая реализация)
                    sv = np.nan
                    cb_s = str(s.get("confirm_bar_time") or "")
                    if cb_s:
                        try:
                            jj = int(np.searchsorted(df_tf.index.to_numpy(),
                                                     np.datetime64(pd.Timestamp(cb_s)), side="right"))
                            if 0 <= jj < len(slope_arr):
                                sv = slope_arr[jj]
                        except Exception:
                            sv = np.nan
                elif gate_anchor == "lc":
                    # ЧЕСТНЫЙ якорь: slope на последнем ЗАКРЫТОМ 5m-баре к моменту решения (i-1)
                    sv = slope_arr[i - 1] if 0 <= i - 1 < len(slope_arr) else np.nan
                elif gate_anchor == "cc":
                    # ЧЕСТНЫЙ якорь: slope на баре конфирма (первый после cb минус 1 бар)
                    sv = np.nan
                    cb_s = str(s.get("confirm_bar_time") or "")
                    if cb_s:
                        try:
                            jj = int(np.searchsorted(df_tf.index.to_numpy(),
                                                     np.datetime64(pd.Timestamp(cb_s)), side="right"))
                            if 1 <= jj <= len(slope_arr):
                                sv = slope_arr[jj - 1]
                        except Exception:
                            sv = np.nan
                elif gate_anchor == "sw":
                    # ЧЕСТНЫЙ якорь: slope на баре СВИПА (trigger_bar_time) — бар давно закрыт к скану
                    sv = np.nan
                    tr_s = str(s.get("trigger_bar_time") or s.get("trigger_bar_at") or "")
                    if tr_s:
                        try:
                            kk = int(np.searchsorted(df_tf.index.to_numpy(),
                                                     np.datetime64(pd.Timestamp(tr_s)), side="right"))
                            if 1 <= kk <= len(slope_arr):
                                sv = slope_arr[kk - 1]
                        except Exception:
                            sv = np.nan
                else:  # f1h / f4h — якорь квантован к началу часа/4ч-блока
                    an = scan_ts.floor("1h") if gate_anchor == "f1h" else scan_ts.floor("4h")
                    kk = int(np.searchsorted(df_tf.index.to_numpy(), np.datetime64(an), side="left"))
                    sv = slope_arr[kk] if kk < len(slope_arr) else np.nan
                if sv == sv:  # not NaN → гейт активен
                    if (direction == "LONG" and sv <= g_thr) or (direction == "SHORT" and sv >= -g_thr):
                        n_skip_gate += 1
                        continue
            if di_arr is not None:
                dv = _anchor_val(di_arr, s, i, scan_ts)
                if dv == dv:  # not NaN
                    if (direction == "LONG" and dv <= 0.0) or (direction == "SHORT" and dv >= 0.0):
                        n_skip_gate += 1
                        continue
            if abs(stop - entry) / entry * 100.0 < min_stop:
                continue
            htf_s = str(s.get("htf_time") or "")[:19]
            ok_sw, _why = bot._sweep_valid_for_setup(
                sl, htf, htf_s,
                str(s.get("trigger_bar_time") or s.get("trigger_bar_at") or ""),
                float(s.get("htf_sweep_level") or s.get("sweep_level") or 0),
                direction,
            )
            if not ok_sw:
                continue
            since_tp = str(s.get("confirm_bar_time") or s.get("trigger_bar_time") or "")
            if _tp_touched(sl, direction, tp, since_tp):
                if htf_s:
                    htf_taken.add(htf_s)
                continue
            if htf_s and htf_s in htf_taken:
                continue
            if busy_until is not None and scan_ts < busy_until:
                seen.add(h)
                continue
            if htf_s:
                htf_taken.add(htf_s)
            got = _outcome(df1, scan_s, direction, entry, stop, tp, limit_min, pos_h)
            if got is None:
                continue
            kind, r, exit_ts = got
            busy_until = pd.Timestamp(exit_ts)
            rows.append({
                "sym": sym,
                "direction": direction,
                "outcome": kind,
                "r": r,
                "scan": scan_s,
                "cbt": str(s.get("confirm_bar_time") or "")[:19],
                "entry": entry,
                "stop": stop,
                "tp": tp,
                "sp": abs(entry - stop) / entry,
            })
    return rows


def run_symbol(sym: str) -> str:
    sys.path.insert(0, r"D:\PYTHON\cisdbotbybit")
    logging.disable(logging.CRITICAL)
    import cisdbot as bot

    conf = MODES[MODE]
    prof = conf["profile"]
    bot.CONFIG[prof]["detect_filters"] = conf.get("det_filters") or {"atr_enabled": True, "vol_enabled": True, "d_enabled": True}
    out = os.path.join(OUT_ROOT, OUT_DIR)
    os.makedirs(out, exist_ok=True)
    msgs = []
    years = [(2024, "2024-06-01", "2024-07-01")] if SMOKE else YEARS
    for year, since, until in years:
        dst = os.path.join(out, f"{sym}_{year}.pkl")
        if os.path.exists(dst) and not SMOKE:
            msgs.append(f"skip {sym} {year}")
            continue
        t0 = time.time()
        df1 = load_1m(PATHS[sym], since, until)
        if df1.empty:
            msgs.append(f"EMPTY {sym} {year}")
            continue
        df_tf = bot._resample_ohlcv(df1, str(bot.CONFIG[prof]["timeframe"]))
        rows = walk(bot, sym, df_tf, df1, since, until)
        with open(dst + ".tmp", "wb") as f:
            pickle.dump(rows, f)
        os.replace(dst + ".tmp", dst)
        msgs.append(f"OK {sym} {year} n={len(rows)} sec={time.time()-t0:.0f}")
        print(msgs[-1], flush=True)
    return " | ".join(msgs)


def _init(m: str) -> None:
    # ВАЖНО: в spawn-воркерах Windows main() не выполняется, поэтому OUT_DIR
    # надо задать и здесь — иначе воркеры пишут все файлы в корень live_tf/.
    global MODE, OUT_DIR
    MODE = m
    OUT_DIR = m


def _run(sym: str) -> str:
    return run_symbol(sym)


def main() -> None:
    global MODE, SMOKE, OUT_DIR
    mode = (sys.argv[1] if len(sys.argv) > 1 else "tf8").lower()
    if mode not in MODES:
        print(f"неизвестный режим {mode}; есть: {', '.join(MODES)}")
        sys.exit(2)
    SMOKE = len(sys.argv) > 2 and sys.argv[2].lower() == "smoke"
    MODE = mode
    OUT_DIR = ("smoke_" + mode) if SMOKE else mode
    conf = MODES[mode]
    print(f"===== MODE={mode} profile={conf['profile']} min_stop={conf['min_stop']} sl_gate={conf.get('sl_gate')} di_gate={conf.get('di_gate')} anchor={conf.get('gate_anchor')} smoke={SMOKE} =====", flush=True)
    if SMOKE:
        print(run_symbol("ADA"), flush=True)
        return
    with Pool(6, initializer=_init, initargs=(mode,)) as pool:
        for msg in pool.imap_unordered(_run, list(PATHS)):
            print(msg, flush=True)


if __name__ == "__main__":
    main()
