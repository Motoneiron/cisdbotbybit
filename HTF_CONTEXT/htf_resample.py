# -*- coding: utf-8 -*-
"""HTF Context Engine — загрузка 1m и ресемпл в старшие ТФ (4H/1D/1W).

Семантика времени (проверено для датасета D:\\databtcusdt):
  * timestamp в CSV — OPEN TIME бара (1m-сетка строго 60 c, дублей нет);
  * close_time бара = open_time + tf_minutes (lab=left / closed=left во всех ресемплах);
  * решение бота (scan) приходит через 15 минут после закрытия конфирм-бара:
    scan == cbt + 15м — это и есть decision_time.

Модуль намеренно НЕ импортирует бота: HTF-карта строится независимо, из тех же
1m-данных, с явными правилами causal availability.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

#: Допустимые старшие ТФ и их длина в минутах.
TF_MINUTES: dict[str, int] = {"4H": 240, "1D": 1440, "1W": 10080}

#: Правила ресемпла. W-MON c label/closed=left даёт недели Пн..Вс с меткой-понедельником.
TF_RULES: dict[str, str] = {"4H": "240min", "1D": "1440min", "1W": "W-MON"}

OHLCV_COLS = ("open", "high", "low", "close", "volume")


def load_1m(path: str, since: str, until: str) -> pd.DataFrame:
    """Чанковая загрузка 1m OHLCV как в движке прогонов (index = open_time, naive UTC)."""
    t0 = pd.Timestamp(since)
    t1 = pd.Timestamp(until)
    parts: list[pd.DataFrame] = []
    cols = ["open_time", "open", "high", "low", "close", "volume"]
    for chunk in pd.read_csv(path, usecols=cols, chunksize=500_000):
        ot = pd.to_datetime(chunk["open_time"], unit="ms")
        m = (ot >= t0) & (ot < t1)
        if not m.any():
            continue
        sub = chunk.loc[m, ["open", "high", "low", "close", "volume"]].astype(float)
        sub.index = ot[m]
        parts.append(sub)
    if not parts:
        return pd.DataFrame(columns=list(OHLCV_COLS))
    df = pd.concat(parts)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def resample_ohlcv(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Ресемпл 1m → tf (label=left, closed=left; W-MON для недель)."""
    rule = TF_RULES[tf]
    out = pd.DataFrame(
        {
            "open": df["open"].resample(rule, label="left", closed="left").first(),
            "high": df["high"].resample(rule, label="left", closed="left").max(),
            "low": df["low"].resample(rule, label="left", closed="left").min(),
            "close": df["close"].resample(rule, label="left", closed="left").last(),
            "volume": df["volume"].resample(rule, label="left", closed="left").sum(),
        }
    )
    return out.dropna(subset=["open"])


def make_frames(df1: pd.DataFrame, tfs: tuple[str, ...] = ("4H", "1D", "1W")) -> dict[str, pd.DataFrame]:
    """Собрать словарь старших ТФ-фреймов из 1m."""
    return {tf: resample_ohlcv(df1, tf) for tf in tfs}


def bar_close_ns(df: pd.DataFrame, tf: str) -> np.ndarray:
    """Массив close_time (datetime64[ns]) для баров фрейма."""
    return (df.index.to_numpy(dtype="datetime64[ns]")
            + np.timedelta64(TF_MINUTES[tf], "m"))


def last_closed_index(close_ns: np.ndarray, t: pd.Timestamp | str) -> int:
    """Индекс последнего ЗАКРЫТОГО на момент t бара (close_time <= t); -1 если нет."""
    tns = np.datetime64(pd.Timestamp(t))
    return int(np.searchsorted(close_ns, tns, side="right")) - 1
