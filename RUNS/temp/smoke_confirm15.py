"""Смоук: 15m-подтверждение внутри 30m-бара. Что даёт профиль confirm_timeframe=15m?"""
import logging
import sys

import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

import backtest.config as cfg  # noqa: E402

_tf8 = dict(cfg.BOT_TF_PROFILES["tf8"])
_tf8["confirm_timeframe"] = "15m"
cfg.BOT_TF_PROFILES["tf8_mss15"] = _tf8

from backtest.bot_aligned import run_bot_aligned_backtest  # noqa: E402
from backtest.data import load_ltf  # noqa: E402

logging.disable(logging.INFO)
res = run_bot_aligned_backtest(
    since="2024-01-01", until="2024-12-31", profile="tf8_mss15", symbol="BTC",
    limit_bars=1, pos_bars=12, save=False, quiet=True,
    detect_filters={"atr_enabled": False, "vol_enabled": False, "d_enabled": False},
    mss_on_ltf=False,
)
sg = res.get("signals") or []
tr = res.get("trades") or []
print(f"BTC 2024 (confirm 15m): сигналов {len(sg)} | сделок {len(tr)}")
if sg:
    s = sg[0]
    for k in ("confirm_bar_time", "confirm_timeframe", "cisd_level", "direction", "htf_time", "sweep_close_bar_time"):
        print(f"   {k} = {s.get(k)}")
    # на какой 15m-бар внутри 30m пришлось подтверждение и закрылась ли 30m за уровнем
    d30, _ = load_ltf(tf="30m", since="2024-01-01", until="2024-12-31", symbol="BTC")
    idx30 = pd.DatetimeIndex(d30.index)
    cl30 = d30["close"].to_numpy(dtype=float)
    from collections import Counter
    cnt = Counter()
    for s in sg:
        cbt = pd.Timestamp(s.get("confirm_bar_time") or "")
        lvl = float(s.get("cisd_level") or 0)
        long_ = s.get("direction") == "LONG"
        j = int(idx30.searchsorted(cbt, side="right")) - 1
        if j < 0 or lvl <= 0:
            cnt["no_data"] += 1
            continue
        beyond = (cl30[j] > lvl) if long_ else (cl30[j] < lvl)
        cnt["30m_close_beyond" if beyond else "30m_wick"] += 1
        cnt[f"minute_{cbt.minute:02d}"] += 1
    print("   классификация:", dict(cnt))
