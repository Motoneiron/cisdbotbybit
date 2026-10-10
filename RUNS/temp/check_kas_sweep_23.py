"""KAS 13.09: 4H свечи 08/12/16/20 UTC + окно 16-20: где минимум, свип по Pine-критерию."""
import pandas as pd

df = pd.read_csv(r"D:/databtcusdt/KASUSDT-1m-merged.csv")
tc = "open_time" if "open_time" in df.columns else df.columns[0]
df[tc] = pd.to_datetime(df[tc], unit="ms", utc=True).dt.tz_localize(None)
sel = df[(df[tc] >= "2026-09-13 04:00") & (df[tc] < "2026-09-13 21:00")].set_index(tc)

h4 = sel.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last"})
print("=== KAS 4H свечи (UTC) ===")
print(h4[["open", "high", "low", "close"]].to_string())

print("\n=== окно 16:00-20:00 UTC (5m) ===")
w = sel["2026-09-13 16:00":"2026-09-13 19:59"]
print(f"low(16:00 4H) = {w.low.min()}  в {w.low.idxmin()}")
print(f"high(16:00 4H) = {w.high.max()}  в {w.high.idxmax()}")
print(f"close 19:59 = {w.close.iloc[-1]}")

print("\n=== Pine-критерий (c2=16:00, c3=12:00) ===")
c2, c3 = h4.loc[pd.Timestamp("2026-09-13 16:00")], h4.loc[pd.Timestamp("2026-09-13 12:00")]
high_sw = c2.high > c3.high and c2.close < c3.high
low_sw = c2.low < c3.low and c2.close > c3.low
print(f"high-свип (SHORT): {high_sw}   (c2.high={c2.high} c3.high={c3.high} c2.close={c2.close})")
print(f"low-свип (LONG):   {low_sw}   (c2.low={c2.low} c3.low={c3.low} c2.close={c2.close})")

# заодно окно 12:00 (c1=08:00, c2=12:00)
c2b, c3b = h4.loc[pd.Timestamp("2026-09-13 12:00")], h4.loc[pd.Timestamp("2026-09-13 08:00")]
print("\n(для справки окно 12:00 vs 08:00):")
print(f"high-свип: {c2b.high > c3b.high and c2b.close < c3b.high}  low-свип: {c2b.low < c3b.low and c2b.close > c3b.low}")
