"""BTC 1m: собрать единый файл в формате движка:
- база: pattern-detection BTCUSDT_1m_2020_2026.csv (2020-01-01..2026-05-22)
- доп: databtcusdt/BTCUSDT-1m/BTCUSDT_1m_full_hdr.csv (2026-06-18..2026-08-22)
→ databtcusdt/BTCUSDT-1m/BTCUSDT_1m_2020_2026_conv.csv
"""
import pandas as pd

SRC1 = r"D:\hermes-agent\pattern-detection\data\raw\BTCUSDT_1m_2020_2026.csv"
SRC2 = r"D:\databtcusdt\BTCUSDT-1m\BTCUSDT_1m_full_hdr.csv"
DST = r"D:\databtcusdt\BTCUSDT-1m\BTCUSDT_1m_2020_2026_conv.csv"

d1 = pd.read_csv(SRC1)
ts1 = pd.to_datetime(d1["timestamp"])
last1 = ts1.max()
print("SRC1 rows:", len(d1), "->", str(last1))

d2 = pd.read_csv(SRC2)
ts2_all = pd.to_datetime(d2["open_time"], unit="ms")
mask2 = ts2_all > last1
d2 = d2[mask2].copy()
ts2 = ts2_all[mask2]
print("SRC2 доп. rows:", len(d2), "->", str(ts2.max()) if len(ts2) else "-")

def to_ms(ts):
    return ((ts - pd.Timestamp("1970-01-01")) // pd.Timedelta("1ms")).astype("int64")


base = pd.DataFrame({
    "open_time": to_ms(ts1),
    "open": d1["open"], "high": d1["high"], "low": d1["low"], "close": d1["close"], "volume": d1["volume"],
})
tail = pd.DataFrame({
    "open_time": to_ms(ts2),
    "open": d2["open"].values, "high": d2["high"].values, "low": d2["low"].values,
    "close": d2["close"].values, "volume": d2["volume"].values,
})
out = pd.concat([base, tail]).drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
out.to_csv(DST, index=False)
print("saved:", DST, "rows:", len(out))
ott = pd.to_datetime(out["open_time"], unit="ms")
print("period:", ott.min(), "->", ott.max())
gaps = ott.diff() > pd.Timedelta(minutes=5)
print("gaps>5m:", int(gaps.sum()), "| дубликаты:", int(out["open_time"].duplicated().sum()))
for i in ott[gaps].head(12):
    print("   gap at", i)
