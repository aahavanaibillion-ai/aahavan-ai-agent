import os
import sys
import json
import sqlite3
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import uvicorn
import requests

# Configuration
PORT = int(os.environ.get("PORT", 8000))
DB_PATH = os.environ.get("DATABASE_PATH", "./aahavan_data.db")

# Database Setup
def init_database():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT,
            email TEXT,
            risk_profile TEXT DEFAULT 'moderate',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS portfolios (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            name TEXT DEFAULT 'My Portfolio',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS holdings (
            id INTEGER PRIMARY KEY,
            portfolio_id INTEGER,
            symbol TEXT,
            name TEXT,
            type TEXT,
            quantity REAL,
            avg_buy_price REAL,
            current_price REAL DEFAULT 0,
            invested_value REAL DEFAULT 0,
            current_value REAL DEFAULT 0,
            pnl REAL DEFAULT 0,
            pnl_percent REAL DEFAULT 0,
            sector TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO users (name, email, risk_profile) VALUES (?, ?, ?)",
                 ("Demo User", "demo@aahavan.ai", "moderate"))
        c.execute("INSERT INTO portfolios (user_id, name) VALUES (?, ?)", (1, "My Portfolio"))

        demo_holdings = [
            ("RELIANCE", "Reliance Industries", "stock", 50, 2400, "Energy"),
            ("TCS", "Tata Consultancy Services", "stock", 25, 3500, "IT"),
            ("HDFCBANK", "HDFC Bank", "stock", 100, 1500, "Banking"),
            ("INFY", "Infosys", "stock", 75, 1400, "IT"),
            ("SBIN", "State Bank of India", "stock", 200, 600, "Banking"),
        ]
        for h in demo_holdings:
            c.execute("""
                INSERT INTO holdings (portfolio_id, symbol, name, type, quantity, avg_buy_price, sector)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (1,) + h)

    conn.commit()
    conn.close()

init_database()

# NSE Data Service (No pandas, no yfinance)
class StockService:
    def __init__(self):
        self.cache = {}
        self.cache_time = {}

    def _get_nse_data(self, symbol):
        """Fetch stock data from Yahoo Finance API (JSON, no pandas)"""
        try:
            fallback_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.NS"
            headers = {"User-Agent": "Mozilla/5.0"}
            
            r = requests.get(fallback_url, headers=headers, timeout=10)
            data = r.json()
            
            if "chart" in data and "result" in data["chart"] and data["chart"]["result"]:
                result = data["chart"]["result"][0]
                meta = result["meta"]
                
                current_price = meta.get("regularMarketPrice", meta.get("previousClose", 0))
                previous_close = meta.get("previousClose", 0)
                
                return {
                    "symbol": symbol,
                    "name": symbol,
                    "price": round(current_price, 2) if current_price else previous_close,
                    "previous_close": round(previous_close, 2),
                    "day_high": round(meta.get("regularMarketDayHigh", previous_close), 2),
                    "day_low": round(meta.get("regularMarketDayLow", previous_close), 2),
                    "volume": meta.get("regularMarketVolume", 0),
                    "market_cap": 0,
                    "pe": 0,
                    "pb": 0,
                    "dividend_yield": 0,
                    "sector": "Unknown",
                    "52w_high": round(meta.get("fiftyTwoWeekHigh", previous_close * 1.2), 2),
                    "52w_low": round(meta.get("fiftyTwoWeekLow", previous_close * 0.8), 2),
                }
        except:
            pass
        
        return self._get_fallback_data(symbol)

    def _get_fallback_data(self, symbol):
        """Fallback data when API fails"""
        fallback_prices = {
            "RELIANCE": 2845.50,
            "TCS": 3987.25,
            "HDFCBANK": 1678.90,
            "INFY": 1523.40,
            "SBIN": 765.30,
            "ICICIBANK": 1124.60,
            "HINDUNILVR": 2456.80,
            "ITC": 432.15,
            "KOTAKBANK": 1876.45,
            "LT": 3421.70,
            "BHARTIARTL": 978.50,
            "AXISBANK": 1045.30,
            "ASIANPAINT": 3124.80,
            "MARUTI": 11234.50,
            "TATAMOTORS": 876.40,
        }
        
        price = fallback_prices.get(symbol, 1500.00)
        
        return {
            "symbol": symbol,
            "name": symbol,
            "price": price,
            "previous_close": round(price * 0.995, 2),
            "day_high": round(price * 1.02, 2),
            "day_low": round(price * 0.98, 2),
            "volume": 5000000,
            "market_cap": 0,
            "pe": 22.5,
            "pb": 3.2,
            "dividend_yield": 1.5,
            "sector": "Unknown",
            "52w_high": round(price * 1.25, 2),
            "52w_low": round(price * 0.75, 2),
        }

    def get_info(self, symbol, exchange="NSE"):
        symbol = symbol.upper()
        
        now = datetime.now()
        if symbol in self.cache and (now - self.cache_time.get(symbol, datetime.min)).seconds < 120:
            return self.cache[symbol]
        
        data = self._get_nse_data(symbol)
        self.cache[symbol] = data
        self.cache_time[symbol] = now
        return data

    def get_history(self, symbol, period="1y"):
        """Get historical data using Yahoo Finance chart API (no pandas needed)"""
        try:
            symbol = symbol.upper()
            interval = "1d"
            
            period_days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825}
            days = period_days.get(period, 365)
            
            end = int(datetime.now().timestamp())
            start = end - (days * 86400)
            
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.NS?period1={start}&period2={end}&interval={interval}"
            headers = {"User-Agent": "Mozilla/5.0"}
            
            r = requests.get(url, headers=headers, timeout=15)
            data = r.json()
            
            if "chart" not in data or "result" not in data["chart"] or not data["chart"]["result"]:
                return []
            
            result = data["chart"]["result"][0]
            timestamps = result.get("timestamp", [])
            quotes = result["indicators"]["quote"][0]
            closes = quotes.get("close", [])
            
            history = []
            for i, ts in enumerate(timestamps):
                if i < len(closes) and closes[i] is not None:
                    date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                    history.append({"date": date_str, "close": round(closes[i], 2)})
            
            return history
            
        except Exception as e:
            return self._generate_synthetic_history(symbol, period)

    def _generate_synthetic_history(self, symbol, period):
        """Generate realistic synthetic price history"""
        import random
        base_price = 1500
        period_days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825}
        days = period_days.get(period, 365)
        
        history = []
        price = base_price
        end_date = datetime.now()
        
        for i in range(days, 0, -1):
            date = end_date - timedelta(days=i)
            change = random.uniform(-0.02, 0.025)
            price = price * (1 + change)
            history.append({
                "date": date.strftime("%Y-%m-%d"),
                "close": round(price, 2)
            })
        
        return history

class MFService:
    def __init__(self):
        self.nav_data = None
        self.last_fetch = None

    def fetch_navs(self):
        try:
            url = "https://www.amfiindia.com/spages/NAVAll.txt"
            r = requests.get(url, timeout=30)
            data = []
            fund_house = ""
            for line in r.text.strip().split("\n"):
                parts = line.strip().split(";")
                if len(parts) == 1:
                    fund_house = parts[0]
                elif len(parts) >= 5:
                    try:
                        nav = float(parts[4]) if parts[4].strip() else 0
                    except:
                        nav = 0
                    data.append({
                        "code": parts[0].strip(),
                        "name": parts[3].strip(),
                        "nav": nav,
                        "date": parts[7].strip() if len(parts) > 7 else "",
                        "fund_house": fund_house
                    })
            self.nav_data = data
            self.last_fetch = datetime.now()
            return data
        except:
            return []

    def search(self, query):
        if self.nav_data is None or (datetime.now() - self.last_fetch).days > 0:
            self.fetch_navs()
        matches = [d for d in self.nav_data if query.lower() in d["name"].lower()]
        return matches[:10]

stock_service = StockService()
mf_service = MFService()

# FastAPI App
app = FastAPI(title="Aahavan AI Agent - Cloud")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.get("/")
def root():
    return {"message": "Aahavan AI Agent is running on cloud!", "status": "live"}

@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/api/portfolio/{pid}/summary")
def portfolio_summary(pid: int):
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT id, symbol, type, quantity, avg_buy_price FROM holdings WHERE portfolio_id=?", (pid,))
    holdings = c.fetchall()

    total_invested = 0
    total_current = 0

    for h in holdings:
        symbol = h["symbol"]
        qty = h["quantity"]
        avg = h["avg_buy_price"]

        if h["type"] == "stock":
            info = stock_service.get_info(symbol)
            current = info.get("price", avg)
        else:
            current = avg

        invested = qty * avg
        current_val = qty * current
        pnl = current_val - invested
        pnl_pct = (pnl / invested * 100) if invested > 0 else 0

        c.execute("""
            UPDATE holdings SET current_price=?, invested_value=?, current_value=?, pnl=?, pnl_percent=?
            WHERE id=?
        """, (current, invested, current_val, pnl, pnl_pct, h["id"]))

        total_invested += invested
        total_current += current_val

    conn.commit()

    c.execute("SELECT * FROM holdings WHERE portfolio_id=?", (pid,))
    all_holdings = [dict(h) for h in c.fetchall()]

    conn.close()

    pnl = total_current - total_invested
    pnl_pct = (pnl / total_invested * 100) if total_invested > 0 else 0

    return {
        "total_invested": round(total_invested, 2),
        "total_current": round(total_current, 2),
        "pnl": round(pnl, 2),
        "pnl_percent": round(pnl_pct, 2),
        "holdings": all_holdings
    }

@app.get("/api/portfolio/{pid}/review")
def portfolio_review(pid: int):
    summary = portfolio_summary(pid)

    insights = []
    warnings = []

    for h in summary["holdings"]:
        weight = (h["current_value"] / summary["total_current"] * 100) if summary["total_current"] > 0 else 0
        if weight > 25:
            warnings.append(f"⚠️ High concentration in {h['name']} ({weight:.1f}%)")
        if h["pnl_percent"] < -15:
            warnings.append(f"📉 {h['name']} is down {h['pnl_percent']:.1f}%")
        if h["pnl_percent"] > 30:
            insights.append(f"🚀 {h['name']} gained {h['pnl_percent']:.1f}%")

    if summary["pnl_percent"] > 15:
        insights.append(f"📈 Portfolio up {summary['pnl_percent']:.1f}% - Great performance!")
    elif summary["pnl_percent"] < -10:
        warnings.append(f"📉 Portfolio down {summary['pnl_percent']:.1f}% - Review needed")

    return {**summary, "insights": insights, "warnings": warnings}

@app.post("/api/portfolio/{pid}/holdings")
def add_holding(pid: int, symbol: str, name: str, htype: str, qty: float, price: float, sector: str = ""):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO holdings (portfolio_id, symbol, name, type, quantity, avg_buy_price, sector)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (pid, symbol.upper(), name, htype, qty, price, sector))
    conn.commit()
    conn.close()
    return {"message": "Holding added", "symbol": symbol.upper()}

@app.get("/api/stocks/{symbol}")
def stock_info(symbol: str):
    return stock_service.get_info(symbol.upper())

@app.get("/api/stocks/{symbol}/history")
def stock_history(symbol: str, period: str = "1y"):
    history = stock_service.get_history(symbol.upper(), period)
    return {"symbol": symbol.upper(), "data": history}

@app.get("/api/mf/search/{query}")
def search_mf(query: str):
    return {"results": mf_service.search(query)}

@app.post("/api/goals/sip")
def sip_calculator(target: float, years: int, return_rate: float = 12):
    r = return_rate / 100 / 12
    n = years * 12
    sip = target * r / ((1 + r) ** n - 1) if r > 0 else target / n
    total = sip * n
    return {
        "target": target,
        "years": years,
        "monthly_sip": round(sip, 2),
        "total_invested": round(total, 2),
        "wealth_gained": round(target - total, 2)
    }

@app.get("/api/market/overview")
def market_overview():
    indices = {
        "^NSEI": "Nifty 50",
        "^BSESN": "Sensex"
    }
    result = {}
    for idx, name in indices.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{idx}?interval=1d&range=1d"
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            data = r.json()
            
            if "chart" in data and "result" in data["chart"] and data["chart"]["result"]:
                meta = data["chart"]["result"][0]["meta"]
                price = meta.get("regularMarketPrice", 0)
                prev = meta.get("previousClose", 0)
                change = price - prev
                change_pct = (change / prev * 100) if prev else 0
                
                result[idx] = {
                    "name": name,
                    "price": round(price, 2),
                    "change": round(change, 2),
                    "change_percent": round(change_pct, 2)
                }
            else:
                raise Exception("No data")
        except:
            fallback = {"^NSEI": 24500, "^BSESN": 80500}
            base = fallback.get(idx, 24000)
            result[idx] = {
                "name": name,
                "price": base,
                "change": round(base * 0.005, 2),
                "change_percent": 0.5
            }
    return result

@app.get("/api/news")
def get_news():
    return {
        "news": [
            {"title": "Nifty 50 hits new high", "source": "Economic Times", "time": "2 hours ago"},
            {"title": "RBI keeps repo rate unchanged", "source": "Business Standard", "time": "5 hours ago"},
            {"title": "IT sector Q3 earnings strong", "source": "Money Control", "time": "8 hours ago"},
        ]
    }

@app.post("/api/chat")
async def chat(request: Request):
    data = await request.json()
    message = data.get("message", "").lower()
    portfolio_id = data.get("portfolio_id", 1)

    if any(w in message for w in ["portfolio", "my holdings", "how am i doing", "pnl", "returns"]):
        summary = portfolio_summary(portfolio_id)
        text = f"📊 Portfolio Overview\n\n"
        text += f"💰 Invested: ₹{summary['total_invested']:,.2f}\n"
        text += f"📈 Current: ₹{summary['total_current']:,.2f}\n"
        text += f"{'🟢' if summary['pnl'] >= 0 else '🔴'} P&L: ₹{summary['pnl']:,.2f} ({summary['pnl_percent']:.2f}%)\n\n"
        if summary.get("insights"):
            text += "✨ " + "\n✨ ".join(summary["insights"][:2])
        if summary.get("warnings"):
            text += "\n\n⚠️ " + "\n⚠️ ".join(summary["warnings"][:2])
        return {"text": text, "type": "portfolio"}

    if any(w in message for w in ["price of", "stock price", "current price", "how much is", "rate of"]):
        words = message.upper().split()
        symbols = [w for w in words if w in ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "SBIN", "ITC", "KOTAKBANK", "LT"]]
        if symbols:
            info = stock_service.get_info(symbols[0])
            change = info["price"] - info["previous_close"]
            change_pct = (change / info["previous_close"] * 100) if info["previous_close"] else 0
            return {"text": f"📈 {info['name']} ({symbols[0]})\n💰 Price: ₹{info['price']:.2f}\n{'🟢' if change >= 0 else '🔴'} Change: ₹{change:.2f} ({change_pct:+.2f}%)\n📊 Day Range: ₹{info['day_low']:.2f} - ₹{info['day_high']:.2f}", "type": "stock"}
        return {"text": "Which stock? Try: RELIANCE, TCS, HDFCBANK, INFY", "type": "text"}

    if any(w in message for w in ["sip", "monthly investment", "calculate sip"]):
        import re
        nums = [float(n.replace(",", "")) for n in re.findall(r'[\d,]+(?:\.\d+)?', message.replace(",", ""))]
        if len(nums) >= 2:
            result = sip_calculator(nums[0], int(nums[1]))
            return {"text": f"🎯 SIP Calculation\n\n💰 Target: ₹{result['target']:,.0f}\n📅 Years: {result['years']}\n💵 Monthly SIP: ₹{result['monthly_sip']:,.2f}\n💳 Total Invested: ₹{result['total_invested']:,.2f}\n✨ Wealth Gained: ₹{result['wealth_gained']:,.2f}", "type": "sip"}
        return {"text": "Tell me: target amount and years. Example: 'SIP for 50 lakh in 15 years'", "type": "text"}

    if any(w in message for w in ["market today", "nifty", "sensex", "market update"]):
        overview = market_overview()
        text = "🇮🇳 Market Overview\n\n"
        for k, v in overview.items():
            text += f"📊 {v['name']}: {v['price']:.2f} ({v['change_percent']:+.2f}%)\n"
        return {"text": text, "type": "market"}

    if any(w in message for w in ["news", "latest", "happening"]):
        news = get_news()
        text = "📰 Latest News\n\n"
        for n in news["news"]:
            text += f"• {n['title']} - {n['source']}\n"
        return {"text": text, "type": "news"}

    if any(w in message for w in ["tax", "harvesting", "save tax"]):
        summary = portfolio_summary(portfolio_id)
        losses = [h for h in summary["holdings"] if h["pnl"] < 0]
        if losses:
            total_loss = sum(abs(h["pnl"]) for h in losses)
            text = f"💰 Tax Loss Harvesting\n\n📉 Loss-making positions:\n"
            for h in losses:
                text += f"• {h['name']}: ₹{abs(h['pnl']):,.2f}\n"
            text += f"\n💵 Total Losses: ₹{total_loss:,.2f}\n"
            text += f"💡 Tax Saving Potential: ₹{total_loss * 0.3:,.2f} (at 30% slab)"
        else:
            text = "✅ No loss-making positions found. Great job!"
        return {"text": text, "type": "tax"}

    if any(w in message for w in ["hello", "hi", "hey", "namaste"]):
        return {"text": "👋 Hello! I'm Aahavan AI.\n\nI can help you with:\n📊 Portfolio tracking\n📈 Stock prices\n🏦 Mutual funds\n🎯 SIP planning\n💰 Tax harvesting\n📰 Market news\n\nWhat would you like to know?", "type": "greeting"}

    if any(w in message for w in ["help", "what can you do", "features"]):
        return {"text": "🤖 Aahavan AI Features:\n\n1. 📊 Portfolio Review - 'How is my portfolio?'\n2. 📈 Stock Prices - 'Price of RELIANCE'\n3. 🏦 Mutual Funds - 'Search SBI Bluechip'\n4. 🎯 SIP Calculator - 'SIP for 1 Cr in 20 years'\n5. 💰 Tax Harvesting - 'Tax loss analysis'\n6. 📰 Market News - 'Latest news'\n7. 📊 Market Overview - 'Market today'\n\nJust ask naturally!", "type": "help"}

    return {"text": "🤔 I didn't quite get that. Try asking about:\n• Your portfolio\n• Stock prices\n• SIP calculator\n• Market news\n• Tax harvesting\n\nOr type 'help' for all features!", "type": "text"}

# Web Interface
HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Aahavan AI - Cloud Portfolio Manager</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Inter', sans-serif; background: #0f172a; color: #e2e8f0; }
        .glass { background: rgba(30, 41, 59, 0.8); backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.1); }
        .gradient-text { background: linear-gradient(135deg, #60a5fa, #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .chat-message { animation: fadeIn 0.3s ease; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        .scroll-hide::-webkit-scrollbar { display: none; }
        .scroll-hide { -ms-overflow-style: none; scrollbar-width: none; }
    </style>
</head>
<body class="min-h-screen">
    <nav class="glass sticky top-0 z-50 px-6 py-4">
        <div class="max-w-7xl mx-auto flex items-center justify-between">
            <div class="flex items-center gap-3">
                <div class="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl flex items-center justify-center">
                    <span class="text-xl">🤖</span>
                </div>
                <div>
                    <h1 class="text-xl font-bold gradient-text">Aahavan AI</h1>
                    <p class="text-xs text-slate-400">Cloud Portfolio Manager</p>
                </div>
            </div>
            <div class="flex items-center gap-4">
                <span class="text-sm text-green-400 flex items-center gap-1">
                    <span class="w-2 h-2 bg-green-400 rounded-full animate-pulse"></span>
                    Live
                </span>
            </div>
        </div>
    </nav>

    <div class="max-w-7xl mx-auto p-6 grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div class="lg:col-span-2 space-y-6">
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div class="glass rounded-2xl p-4">
                    <p class="text-slate-400 text-sm">Total Invested</p>
                    <p class="text-2xl font-bold mt-1" id="total-invested">Loading...</p>
                </div>
                <div class="glass rounded-2xl p-4">
                    <p class="text-slate-400 text-sm">Current Value</p>
                    <p class="text-2xl font-bold mt-1 text-blue-400" id="total-current">Loading...</p>
                </div>
                <div class="glass rounded-2xl p-4">
                    <p class="text-slate-400 text-sm">P&L</p>
                    <p class="text-2xl font-bold mt-1" id="total-pnl">Loading...</p>
                </div>
                <div class="glass rounded-2xl p-4">
                    <p class="text-slate-400 text-sm">Holdings</p>
                    <p class="text-2xl font-bold mt-1" id="holdings-count">Loading...</p>
                </div>
            </div>

            <div class="glass rounded-2xl p-6">
                <h2 class="text-xl font-bold mb-4 flex items-center gap-2">📊 Your Holdings</h2>
                <div class="overflow-x-auto">
                    <table class="w-full text-sm">
                        <thead>
                            <tr class="text-slate-400 border-b border-slate-700">
                                <th class="text-left py-3">Stock</th>
                                <th class="text-right py-3">Qty</th>
                                <th class="text-right py-3">Avg Price</th>
                                <th class="text-right py-3">Current</th>
                                <th class="text-right py-3">P&L</th>
                            </tr>
                        </thead>
                        <tbody id="holdings-table"></tbody>
                    </table>
                </div>
            </div>

            <div class="glass rounded-2xl p-6" id="insights-section" style="display:none;">
                <h2 class="text-xl font-bold mb-4 flex items-center gap-2">✨ AI Insights</h2>
                <div id="insights-content" class="space-y-2"></div>
            </div>

            <div class="glass rounded-2xl p-6">
                <h2 class="text-xl font-bold mb-4 flex items-center gap-2">🌏 Market Overview</h2>
                <div id="market-data" class="grid grid-cols-3 gap-4"></div>
            </div>
        </div>

        <div class="lg:col-span-1">
            <div class="glass rounded-2xl h-[calc(100vh-120px)] flex flex-col">
                <div class="p-4 border-b border-slate-700">
                    <h2 class="font-bold flex items-center gap-2">
                        <span class="text-xl">💬</span> AI Assistant
                    </h2>
                    <p class="text-xs text-slate-400">Ask me anything about markets</p>
                </div>

                <div id="chat-messages" class="flex-1 overflow-y-auto p-4 space-y-4 scroll-hide">
                    <div class="chat-message">
                        <div class="bg-slate-800 rounded-2xl p-3 text-sm">
                            <p class="text-blue-400 font-medium mb-1">🤖 Aahavan AI</p>
                            <p>Hello! I'm your investment assistant. Ask me about:</p>
                            <ul class="mt-2 space-y-1 text-slate-300">
                                <li>• Your portfolio</li>
                                <li>• Stock prices</li>
                                <li>• SIP calculator</li>
                                <li>• Market news</li>
                                <li>• Tax harvesting</li>
                            </ul>
                        </div>
                    </div>
                </div>

                <div class="px-4 py-2 border-t border-slate-700">
                    <div class="flex gap-2 overflow-x-auto scroll-hide">
                        <button onclick="quickAsk('How is my portfolio?')" class="whitespace-nowrap text-xs bg-slate-700 hover:bg-slate-600 px-3 py-1.5 rounded-full transition">📊 Portfolio</button>
                        <button onclick="quickAsk('Price of RELIANCE')" class="whitespace-nowrap text-xs bg-slate-700 hover:bg-slate-600 px-3 py-1.5 rounded-full transition">📈 RELIANCE</button>
                        <button onclick="quickAsk('Market today')" class="whitespace-nowrap text-xs bg-slate-700 hover:bg-slate-600 px-3 py-1.5 rounded-full transition">🌏 Market</button>
                        <button onclick="quickAsk('SIP for 1 crore in 20 years')" class="whitespace-nowrap text-xs bg-slate-700 hover:bg-slate-600 px-3 py-1.5 rounded-full transition">🎯 SIP</button>
                    </div>
                </div>

                <div class="p-4 border-t border-slate-700">
                    <div class="flex gap-2">
                        <input type="text" id="chat-input" placeholder="Ask about stocks, mutual funds, your portfolio..."
                            class="flex-1 bg-slate-900 border border-slate-600 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-blue-500"
                            onkeypress="if(event.key==='Enter') sendMessage()">
                        <button onclick="sendMessage()" class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2.5 rounded-xl transition">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
                        </button>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const API_BASE = window.location.origin;

        async function loadPortfolio() {
            try {
                const res = await fetch(`${API_BASE}/api/portfolio/1/review`);
                const data = await res.json();

                document.getElementById('total-invested').textContent = '₹' + data.total_invested.toLocaleString();
                document.getElementById('total-current').textContent = '₹' + data.total_current.toLocaleString();
                document.getElementById('total-pnl').textContent = (data.pnl >= 0 ? '+' : '') + '₹' + data.pnl.toLocaleString();
                document.getElementById('total-pnl').className = 'text-2xl font-bold mt-1 ' + (data.pnl >= 0 ? 'text-green-400' : 'text-red-400');
                document.getElementById('holdings-count').textContent = data.holdings.length;

                const tbody = document.getElementById('holdings-table');
                tbody.innerHTML = data.holdings.map(h => `
                    <tr class="border-b border-slate-700/50 hover:bg-slate-800/50">
                        <td class="py-3">
                            <div class="font-medium">${h.symbol}</div>
                            <div class="text-xs text-slate-400">${h.name}</div>
                        </td>
                        <td class="text-right py-3">${h.quantity}</td>
                        <td class="text-right py-3">₹${h.avg_buy_price.toFixed(2)}</td>
                        <td class="text-right py-3">₹${h.current_price.toFixed(2)}</td>
                        <td class="text-right py-3 ${h.pnl >= 0 ? 'text-green-400' : 'text-red-400'}">
                            ${h.pnl >= 0 ? '+' : ''}₹${h.pnl.toFixed(2)}<br>
                            <span class="text-xs">${h.pnl_percent.toFixed(1)}%</span>
                        </td>
                    </tr>
                `).join('');

                if (data.insights?.length || data.warnings?.length) {
                    document.getElementById('insights-section').style.display = 'block';
                    const content = document.getElementById('insights-content');
                    content.innerHTML = '';
                    data.insights?.forEach(i => {
                        content.innerHTML += `<div class="bg-green-900/30 border border-green-700/50 rounded-lg p-3 text-green-300 text-sm">✨ ${i}</div>`;
                    });
                    data.warnings?.forEach(w => {
                        content.innerHTML += `<div class="bg-red-900/30 border border-red-700/50 rounded-lg p-3 text-red-300 text-sm">⚠️ ${w}</div>`;
                    });
                }
            } catch (e) {
                console.log('Portfolio load error:', e);
            }
        }

        async function loadMarket() {
            try {
                const res = await fetch(`${API_BASE}/api/market/overview`);
                const data = await res.json();
                const container = document.getElementById('market-data');
                container.innerHTML = Object.values(data).map(m => `
                    <div class="bg-slate-800/50 rounded-xl p-3 text-center">
                        <p class="text-xs text-slate-400">${m.name}</p>
                        <p class="text-lg font-bold">${m.price.toFixed(2)}</p>
                        <p class="text-xs ${m.change_percent >= 0 ? 'text-green-400' : 'text-red-400'}">${m.change_percent >= 0 ? '+' : ''}${m.change_percent.toFixed(2)}%</p>
                    </div>
                `).join('');
            } catch (e) {
                console.log('Market load error:', e);
            }
        }

        async function sendMessage() {
            const input = document.getElementById('chat-input');
            const message = input.value.trim();
            if (!message) return;

            addMessage(message, 'user');
            input.value = '';

            try {
                const res = await fetch(`${API_BASE}/api/chat`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: message})
                });
                const data = await res.json();
                addMessage(data.text, 'ai', true);
            } catch (e) {
                addMessage('❌ Sorry, I encountered an error. Please try again.', 'ai', true);
            }
        }

        function quickAsk(text) {
            document.getElementById('chat-input').value = text;
            sendMessage();
        }

        function addMessage(text, sender, isHTML = false) {
            const container = document.getElementById('chat-messages');
            const div = document.createElement('div');
            div.className = 'chat-message';

            const isUser = sender === 'user';
            div.innerHTML = `
                <div class="${isUser ? 'ml-auto bg-blue-600' : 'bg-slate-800'} rounded-2xl p-3 text-sm max-w-[85%] ${isUser ? 'text-white' : ''}">
                    ${!isUser ? '<p class="text-blue-400 font-medium mb-1">🤖 Aahavan AI</p>' : ''}
                    <div class="whitespace-pre-line">${text}</div>
                </div>
            `;
            container.appendChild(div);
            container.scrollTop = container.scrollHeight;
        }

        loadPortfolio();
        loadMarket();
        setInterval(loadPortfolio, 60000);
        setInterval(loadMarket, 60000);
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def web_interface():
    return HTML_PAGE

if __name__ == "__main__":
    print("=" * 50)
    print("🚀 AAHAVAN AI AGENT - CLOUD")
    print("=" * 50)
    print(f"📊 Running on port: {PORT}")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
