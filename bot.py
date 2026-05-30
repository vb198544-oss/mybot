import os
import time
import logging
import requests
import pandas as pd
from datetime import datetime
from pybit.unified_trading import HTTP

# import os
BYBIT_API_KEY    = os.environ["BYBIT_API_KEY"]
BYBIT_API_SECRET = os.environ["BYBIT_API_SECRET"]
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

SYMBOL    = "SOLUSDT"
INTERVAL  = "15"
LIMIT     = 200
CHECK_SEC = 60 * 15

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger(__name__)

session = HTTP(
    testnet=False,
    api_key=BYBIT_API_KEY,
    api_secret=BYBIT_API_SECRET,
)

def get_klines():
    resp = session.get_kline(
        category="linear",
        symbol=SYMBOL,
        interval=INTERVAL,
        limit=LIMIT,
    )
    raw = resp["result"]["list"]
    df = pd.DataFrame(raw, columns=["ts","open","high","low","close","volume","turnover"])
    df = df.astype({"ts":"int64","open":"float","high":"float",
                    "low":"float","close":"float","volume":"float"})
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    df.sort_values("ts", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df

def calc_rsi(series, period=14):
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss
    return 100 - (100 / (1 + rs))

def calc_macd(series, fast=12, slow=26, signal=9):
    ema_fast    = series.ewm(span=fast, adjust=False).mean()
    ema_slow    = series.ewm(span=slow, adjust=False).mean()
    macd_line   = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram

def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def add_indicators(df):
    df["rsi"]         = calc_rsi(df["close"])
    macd, sig, hist   = calc_macd(df["close"])
    df["macd"]        = macd
    df["macd_signal"] = sig
    df["macd_hist"]   = hist
    df["ema50"]       = calc_ema(df["close"], 50)
    df["ema200"]      = calc_ema(df["close"], 200)
    return df

def fibonacci_levels(df, lookback=50):
    recent = df.tail(lookback)
    high   = recent["high"].max()
    low    = recent["low"].min()
    diff   = high - low
    return {
        "swing_high": round(high, 4),
        "fib_23":     round(high - diff * 0.236, 4),
        "fib_38":     round(high - diff * 0.382, 4),
        "fib_50":     round(high - diff * 0.500, 4),
        "fib_61":     round(high - diff * 0.618, 4),
        "fib_78":     round(high - diff * 0.786, 4),
        "swing_low":  round(low, 4),
    }

def detect_elliott(df, lookback=60):
    closes = df["close"].tail(lookback).values
    pivots = []
    for i in range(1, len(closes) - 1):
        if closes[i] > closes[i-1] and closes[i] > closes[i+1]:
            pivots.append(("H", closes[i]))
        elif closes[i] < closes[i-1] and closes[i] < closes[i+1]:
            pivots.append(("L", closes[i]))

    if len(pivots) < 5:
        return "Qeyri-mueyyen"

    last5 = pivots[-5:]
    types = [p[0] for p in last5]
    vals  = [p[1] for p in last5]

    if types == ["L","H","L","H","L"] and vals[1] > vals[0] and vals[3] > vals[1]:
        return "Impuls Dalgasi (Yukselen) - 5-ci dalga gozelenir"
    if types == ["H","L","H","L","H"] and vals[1] < vals[0] and vals[3] < vals[1]:
        return "Impuls Dalgasi (Enen) - 5-ci dalga gozelenir"

    last3 = pivots[-3:]
    t3    = [p[0] for p in last3]
    if t3 == ["H","L","H"]:
        return "Korreksiya (A-B-C) - C enisi gozelenir"
    if t3 == ["L","H","L"]:
        return "Korreksiya (A-B-C) - C yukselist gozelenir"

    return "Konsolidasiya fazasi"

def generate_signal(df):
    last  = df.iloc[-1]
    prev  = df.iloc[-2]
    price = last["close"]

    rsi             = last["rsi"]
    macd_cross_up   = prev["macd"] < prev["macd_signal"] and last["macd"] > last["macd_signal"]
    macd_cross_down = prev["macd"] > prev["macd_signal"] and last["macd"] < last["macd_signal"]
    ema_bull        = last["ema50"] > last["ema200"]
    ema_bear        = last["ema50"] < last["ema200"]

    fib     = fibonacci_levels(df)
    elliott = detect_elliott(df)
    atr     = df["close"].diff().abs().tail(14).mean()

    if 30 <= rsi <= 55 and macd_cross_up and ema_bull:
        return {
            "direction": "LONG",
            "emoji": "LONG",
            "price": price,
            "sl":  round(price - atr * 1.5, 4),
            "tp1": round(price + atr * 2,   4),
            "tp2": round(price + atr * 3.5, 4),
            "leverage": 10 if rsi < 45 else 7,
            "rsi": round(rsi, 2),
            "macd": round(last["macd"], 4),
            "ema50": round(last["ema50"], 4),
            "ema200": round(last["ema200"], 4),
            "fib": fib,
            "elliott": elliott,
        }

    if 45 <= rsi <= 70 and macd_cross_down and ema_bear:
        return {
            "direction": "SHORT",
            "emoji": "SHORT",
            "price": price,
            "sl":  round(price + atr * 1.5, 4),
            "tp1": round(price - atr * 2,   4),
            "tp2": round(price - atr * 3.5, 4),
            "leverage": 10 if rsi > 55 else 7,
            "rsi": round(rsi, 2),
            "macd": round(last["macd"], 4),
            "ema50": round(last["ema50"], 4),
            "ema200": round(last["ema200"], 4),
            "fib": fib,
            "elliott": elliott,
        }

    return None

def send_telegram(signal):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    d   = signal
    fib = d["fib"]

    if d["direction"] == "LONG":
        yon = "LONG - AL"
    else:
        yon = "SHORT - SAT"

    msg = (
        "SOL/USDT SIQNALI\n"
        "\n"
        "Tarix: " + now + "\n"
        "Istiqamet: " + yon + "\n"
        "Giris: " + str(d["price"]) + " USDT\n"
        "Stop Loss: " + str(d["sl"]) + " USDT\n"
        "TP1: " + str(d["tp1"]) + " USDT\n"
        "TP2: " + str(d["tp2"]) + " USDT\n"
        "Leverage: " + str(d["leverage"]) + "x\n"
        "\n"
        "INDIKATORLAR\n"
        "RSI: " + str(d["rsi"]) + "\n"
        "MACD: " + str(d["macd"]) + "\n"
        "EMA50: " + str(d["ema50"]) + "\n"
        "EMA200: " + str(d["ema200"]) + "\n"
        "\n"
        "ELLIOTT DALGASI\n"
        + d["elliott"] + "\n"
        "\n"
        "FIBONACCI\n"
        "Swing High: " + str(fib["swing_high"]) + "\n"
        "Fib 23.6%: " + str(fib["fib_23"]) + "\n"
        "Fib 38.2%: " + str(fib["fib_38"]) + "\n"
        "Fib 50.0%: " + str(fib["fib_50"]) + "\n"
        "Fib 61.8%: " + str(fib["fib_61"]) + "\n"
        "Fib 78.6%: " + str(fib["fib_78"]) + "\n"
        "Swing Low: " + str(fib["swing_low"]) + "\n"
        "\n"
        "Risk idareetme qaidalerina emel edin!"
    )

    url  = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
    r    = requests.post(url, data=data, timeout=10)
    if r.status_code == 200:
        log.info("Telegram siqnali gonderildi")
    else:
        log.error("Telegram xetasi: " + r.text)

def main():
    log.info("SOL/USDT Signal Bot iwle bashladi")
    last_signal_dir = None

    while True:
        try:
            df     = get_klines()
            df     = add_indicators(df)
            signal = generate_signal(df)

            if signal:
                if signal["direction"] != last_signal_dir:
                    send_telegram(signal)
                    last_signal_dir = signal["direction"]
                    log.info("Siqnal: " + signal["direction"] + " @ " + str(signal["price"]))
                else:
                    log.info("Eyni istiqamet - siqnal saxlanildi")
            else:
                log.info("Siqnal yoxdur | Qiymet: " + str(df.iloc[-1]["close"]) + " | RSI: " + str(round(df.iloc[-1]["rsi"], 2)))

        except Exception as e:
            log.error("Xeta: " + str(e))

        time.sleep(CHECK_SEC)

if __name__ == "__main__":
    main()
