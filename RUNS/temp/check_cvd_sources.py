"""Проверка: что даёт Bybit для CVD-фичи vs Binance."""
import json
import urllib.request

def get(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.load(r)

print("=== 1) Bybit kline (1m): поля ответа ===")
k = get("https://api.bybit.com/v5/market/kline?category=linear&symbol=BNBUSDT&interval=1&limit=2")["result"]["list"][0]
print("полей:", len(k), "->", k)

print()
print("=== 2) Bybit recent-trade limit=1000: временной охват ===")
rt = get("https://api.bybit.com/v5/market/recent-trade?category=linear&symbol=BNBUSDT&limit=1000")["result"]["list"]
t0 = int(rt[-1]["time"]); t1 = int(rt[0]["time"])
print(f"сделок: {len(rt)} | охват: {(t1 - t0)/60000:.1f} минут")
print("поля сделки:", list(rt[0].keys()))

print()
print("=== 3) Binance fapi kline 1m: поля ===")
b = get("https://fapi.binance.com/fapi/v1/klines?symbol=BNBUSDT&interval=1m&limit=2")[0]
print("полей:", len(b))
print("time:", b[0], "| volume:", b[5], "| takerBuyBase:", b[9])

print()
print("=== 4) Bybit pуblикче: есть ли у kline taker-разбивка в любом варианте? ===")
for name, url in [
    ("spot kline", "https://api.bybit.com/v5/market/kline?category=spot&symbol=BNBUSDT&interval=1&limit=1"),
]:
    try:
        kk = get(url)["result"]["list"][0]
        print(name, "->", len(kk), "полей:", kk)
    except Exception as e:
        print(name, "ошибка:", e)
