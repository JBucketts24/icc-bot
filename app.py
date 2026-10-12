import os
import time
import threading
from datetime import datetime
from flask import Flask, render_template_string
import yfinance as yf
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# --- CONFIG FROM ENV (Render) ---
API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
TICKERS = ["AAPL", "TSLA", "NVDA", "SPY", "MSFT", "AMD"]

app = Flask(__name__)

# Shared state for website
state = {
    "buying_power": "$400,000.00",
    "connected": False,
    "last_check": "Never",
    "next_check": "Waiting...",
    "stocks": {t: {"price": 0.0, "status": "Waiting..."} for t in TICKERS},
    "logs": [],
    "running": True
}

def log(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = f"[{timestamp}] {msg}"
    print(entry)
    state["logs"].append(entry)
    if len(state["logs"]) > 100:
        state["logs"] = state["logs"][-100:]

def get_client():
    if not API_KEY or not SECRET_KEY:
        return None
    try:
        client = TradingClient(API_KEY, SECRET_KEY, paper=True)
        account = client.get_account()
        state["buying_power"] = f"${float(account.buying_power):,.2f}"
        state["connected"] = True
        return client
    except Exception as e:
        log(f"⚠️ Can't connect: {e}")
        state["connected"] = False
        return None

def is_good_trade(ticker):
    try:
        stock = yf.Ticker(ticker)
        daily = stock.history(period="6mo", interval="1d")
        if daily is None or len(daily) < 50:
            return False, 0.0
        
        price = float(daily['Close'].iloc[-1])
        
        # ICC logic simplified for web
        # Uptrend: price > EMA50
        ema50 = daily['Close'].ewm(span=50).mean().iloc[-1]
        if price < ema50:
            return False, price
            
        # Pullback: last close < recent high
        recent_high = daily['Close'].tail(20).max()
        if price > recent_high * 0.97:  # not pulled back enough
            return False, price
            
        return True, price
    except Exception as e:
        log(f"Error checking {ticker}: {e}")
        return False, 0.0

def bot_loop():
    log("🤖 ICC Bot started - checks every 60 minutes")
    while state["running"]:
        try:
            client = get_client()
            state["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            state["next_check"] = datetime.now().timestamp() + 3600
            
            for ticker in TICKERS:
                good, price = is_good_trade(ticker)
                state["stocks"][ticker]["price"] = price
                
                if good:
                    state["stocks"][ticker]["status"] = "🚀 SIGNAL - Buying!"
                    log(f"🚀 SIGNAL {ticker} ${price:.2f}")
                    if client:
                        try:
                            order = MarketOrderRequest(
                                symbol=ticker,
                                qty=1,
                                side=OrderSide.BUY,
                                time_in_force=TimeInForce.DAY
                            )
                            client.submit_order(order)
                            log(f"✅ BOUGHT {ticker} @ ${price:.2f}")
                            state["stocks"][ticker]["status"] = f"✅ BOUGHT @ ${price:.2f}"
                        except Exception as e:
                            log(f"❌ Order failed {ticker}: {e}")
                else:
                    state["stocks"][ticker]["status"] = f"No trade (${price:.2f})"
                    log(f"No trade for {ticker} (${price:.2f})")
            
            # sleep 60 min but update countdown
            log(f"💤 Sleeping 60 min... next at {datetime.fromtimestamp(state['next_check'])}")
            time.sleep(3600)
            
        except Exception as e:
            log(f"Bot error: {e}")
            time.sleep(60)

# Start bot in background thread
threading.Thread(target=bot_loop, daemon=True).start()

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
<title>ICC Bot Live</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { background:#0a0a0f; color:#e0e0e0; font-family: monospace; margin:0; padding:20px; }
.header { display:flex; justify-content:space-between; align-items:center; border:1px solid #222; padding:15px; border-radius:12px; background:#111; }
.live { display:flex; align-items:center; gap:8px; color:#00ff88; }
.dot { width:10px; height:10px; background:#00ff88; border-radius:50%; animation:pulse 2s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:15px; margin-top:20px; }
.card { background:#15151a; border:1px solid #222; border-radius:12px; padding:15px; }
.card h3 { margin:0; color:#00ff88; }
.price { font-size:20px; margin:8px 0; }
.status { font-size:12px; color:#888; }
.log { background:#000; border:1px solid #222; border-radius:12px; padding:15px; margin-top:20px; height:300px; overflow:auto; font-size:12px; white-space:pre-wrap; }
.buying { color:#00ff88; font-size:18px; }
</style>
<meta http-equiv="refresh" content="30">
</head>
<body>
<div class="header">
  <div>
    <div class="live"><div class="dot"></div> ICC BOT LIVE - {{ 'CONNECTED' if connected else 'DISCONNECTED' }}</div>
    <div class="buying">{{ buying_power }}</div>
  </div>
  <div>Last: {{ last_check }}<br>Next in ~60 min</div>
</div>
<div class="grid">
{% for ticker, data in stocks.items() %}
<div class="card">
<h3>{{ ticker }}</h3>
<div class="price">${{ "%.2f"|format(data.price) }}</div>
<div class="status">{{ data.status }}</div>
</div>
{% endfor %}
</div>
<div class="log">{{ logs|join('\\n') }}</div>
</body>
</html>
"""

@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD_HTML, 
        buying_power=state["buying_power"],
        connected=state["connected"],
        last_check=state["last_check"],
        stocks=state["stocks"],
        logs=list(reversed(state["logs"][-50:]))
    )

@app.route("/health")
def health():
    return "ok"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
