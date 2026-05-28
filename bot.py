import time
import hmac
import hashlib
import requests
import os
from datetime import datetime

# --- Konfiqurasiya ---
API_KEY = os.environ.get("BYBIT_API_KEY", "")
API_SECRET = os.environ.get("BYBIT_API_SECRET", "")
SYMBOL = "BTCUSDT"
TRADE_AMOUNT = 10  # USDT - hər əməliyyatda istifadə ediləcək məbləğ
CHECK_INTERVAL = 60  # saniyə - neçə saniyədən bir yoxlasın

BASE_URL = "https://api.bybit.com"

def log(msg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}")

def sign(params, secret):
    query = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()

def get_klines(symbol, interval="5", limit=50):
    url = f"{BASE_URL}/v5/market/kline"
    params = {"category": "spot", "symbol": symbol, "interval": interval, "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    data = r.json()
    if data["retCode"] != 0:
        log(f"Kline xətası: {data['retMsg']}")
        return []
    closes = [float(item[4]) for item in data["result"]["list"]]
    closes.reverse()
    return closes

def calc_ma(prices, period):
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period

def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
    gains, losses = 0, 0
    for i in range(len(prices) - period, len(prices)):
        diff = prices[i] - prices[i-1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    if losses == 0:
        return 100
    rs = gains / losses
    return 100 - (100 / (1 + rs))

def get_balance(coin="USDT"):
    ts = str(int(time.time() * 1000))
    params = {"accountType": "UNIFIED", "coin": coin}
    sign_str = ts + API_KEY + "5000" + "&".join([f"{k}={v}" for k, v in sorted(params.items())])
    sig = hmac.new(API_SECRET.encode(), sign_str.encode(), hashlib.sha256).hexdigest()
    headers = {"X-BAPI-API-KEY": API_KEY, "X-BAPI-TIMESTAMP": ts,
               "X-BAPI-SIGN": sig, "X-BAPI-RECV-WINDOW": "5000"}
    r = requests.get(f"{BASE_URL}/v5/account/wallet-balance", params=params, headers=headers, timeout=10)
    data = r.json()
    if data["retCode"] != 0:
        log(f"Balans xətası: {data['retMsg']}")
        return 0
    coins = data["result"]["list"][0]["coin"]
    for c in coins:
        if c["coin"] == coin:
            return float(c["availableToWithdraw"])
    return 0

def place_order(side, qty):
    ts = str(int(time.time() * 1000))
    params = {
        "category": "spot",
        "symbol": SYMBOL,
        "side": side,
        "orderType": "Market",
        "qty": str(qty),
    }
    sign_str = ts + API_KEY + "5000" + str(params).replace("'", '"').replace(": ", ":").replace(", ", ",")
    
    import json
    body = json.dumps(params)
    sign_str2 = ts + API_KEY + "5000" + body
    sig = hmac.new(API_SECRET.encode(), sign_str2.encode(), hashlib.sha256).hexdigest()
    headers = {
        "X-BAPI-API-KEY": API_KEY,
        "X-BAPI-TIMESTAMP": ts,
        "X-BAPI-SIGN": sig,
        "X-BAPI-RECV-WINDOW": "5000",
        "Content-Type": "application/json"
    }
    r = requests.post(f"{BASE_URL}/v5/order/create", data=body, headers=headers, timeout=10)
    data = r.json()
    if data["retCode"] != 0:
        log(f"Order xətası: {data['retMsg']}")
        return False
    log(f"✅ {side} ordera verildi! OrderId: {data['result']['orderId']}")
    return True

def get_price(symbol):
    url = f"{BASE_URL}/v5/market/tickers"
    params = {"category": "spot", "symbol": symbol}
    r = requests.get(url, params=params, timeout=10)
    data = r.json()
    if data["retCode"] != 0:
        return 0
    return float(data["result"]["list"][0]["lastPrice"])

def main():
    log("🤖 Bot başladı!")
    log(f"📊 Cüt: {SYMBOL} | Məbləğ: {TRADE_AMOUNT} USDT")

    if not API_KEY or not API_SECRET:
        log("❌ API açarları tapılmadı! BYBIT_API_KEY və BYBIT_API_SECRET environment variable-larını yoxlayın.")
        return

    last_signal = None

    while True:
        try:
            prices = get_klines(SYMBOL, interval="5", limit=50)
            if not prices:
                time.sleep(CHECK_INTERVAL)
                continue

            price = get_price(SYMBOL)
            ma20 = calc_ma(prices, 20)
            rsi = calc_rsi(prices, 14)

            if not ma20 or not rsi:
                log("⏳ Kifayət qədər data yoxdur, gözlənilir...")
                time.sleep(CHECK_INTERVAL)
                continue

            log(f"💰 Qiymət: ${price:.2f} | MA20: ${ma20:.2f} | RSI: {rsi:.1f}")

            # Siqnal məntiqi
            if price > ma20 and rsi < 35:
                signal = "BUY"
            elif price < ma20 and rsi > 65:
                signal = "SELL"
            else:
                signal = "WAIT"

            log(f"🎯 Siqnal: {signal}")

            if signal == "BUY" and last_signal != "BUY":
                usdt_balance = get_balance("USDT")
                log(f"💵 USDT Balans: ${usdt_balance:.2f}")
                if usdt_balance >= TRADE_AMOUNT:
                    qty = round(TRADE_AMOUNT / price, 6)
                    log(f"📈 AL əməliyyatı: {qty} BTC")
                    if place_order("Buy", qty):
                        last_signal = "BUY"
                else:
                    log(f"⚠️ Kifayət qədər USDT yoxdur: ${usdt_balance:.2f}")

            elif signal == "SELL" and last_signal != "SELL":
                btc_balance = get_balance("BTC")
                log(f"₿ BTC Balans: {btc_balance:.6f}")
                if btc_balance * price >= 10:
                    qty = round(btc_balance * 0.99, 6)
                    log(f"📉 SAT əməliyyatı: {qty} BTC")
                    if place_order("Sell", qty):
                        last_signal = "SELL"
                else:
                    log(f"⚠️ Kifayət qədər BTC yoxdur")

        except Exception as e:
            log(f"❌ Xəta: {e}")

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
