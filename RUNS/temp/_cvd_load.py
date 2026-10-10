"""Загрузчик CVD-кэша: обходит несовместимость StringDtype в пикле.

Кэш cvd/<SYM>USDT_minute.pkl писался пандой, у которой StringArray пиклился
состоянием-двойкой (dtype, values). Текущая панда ждёт тройку и падает
NotImplementedError. Нормализуем состояние в dict — его cython-реализация
NDArrayBacked.__setstate__ понимает.

Использование:
    from _cvd_load import load_cvd_minute
    m = load_cvd_minute("SOL")      # ts_ms, delta, buy, sell, n
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pandas._libs.arrays import NDArrayBacked

BASE = "D:/PYTHON/cisdbotbybit/RUNS/temp"
_patched = False


def _patch() -> None:
    global _patched
    if _patched:
        return
    from pandas.core.arrays.masked import BaseMaskedArray
    from pandas.core.arrays.string_ import StringArray

    def _setstate(self, state):
        if isinstance(state, tuple) and len(state) == 2:
            a, b = state
            values, dtype = (a, b) if isinstance(a, np.ndarray) else (b, a)
            NDArrayBacked.__setstate__(self, {"_ndarray": values, "_dtype": dtype})
            return
        NDArrayBacked.__setstate__(self, state)

    StringArray.__setstate__ = _setstate
    for cls in (BaseMaskedArray,):
        if not hasattr(cls, "__setstate__"):
            continue
    _patched = True


def load_cvd_minute(sym: str) -> pd.DataFrame:
    """Минутный CVD пары: ts_ms (int64, UTC ms), delta, buy, sell, n."""
    _patch()
    sym = sym.upper().replace("USDT", "")
    m = pd.read_pickle(f"{BASE}/cvd/{sym}USDT_minute.pkl")
    m.columns = [str(c) for c in m.columns]
    return m.sort_values("ts_ms").reset_index(drop=True)


if __name__ == "__main__":
    for s in ("SOL", "BTC", "KAS"):
        m = load_cvd_minute(s)
        t0 = pd.to_datetime(m.ts_ms.iloc[0], unit="ms")
        t1 = pd.to_datetime(m.ts_ms.iloc[-1], unit="ms")
        print(f"{s}: {len(m)} минут  {t0} .. {t1}  cols={list(m.columns)}")
        print(m.head(2).to_string())
