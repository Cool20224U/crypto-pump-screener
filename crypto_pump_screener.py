import streamlit as st
import pandas as pd
import pandas_ta as ta
import ccxt
import requests
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from plyer import notification
from streamlit_autorefresh import st_autorefresh
import io

st.set_page_config(page_title="🚀 Early Crypto Pump Screener + Portfolio", layout="wide", initial_sidebar_state="expanded")

# Dark Mode
if "theme" not in st.session_state:
    st.session_state.theme = "light"
theme_toggle = st.sidebar.toggle("🌙 Dark Mode", value=st.session_state.theme == "dark")
st.session_state.theme = "dark" if theme_toggle else "light"

if st.session_state.theme == "dark":
    st.markdown("<style>body{background-color:#0e1117;color:white;}</style>", unsafe_allow_html=True)

st.title("🚀 Top 300 Early Uptrend Screener + Portfolio Tracker")
st_autorefresh(interval=60_000, key="data_refresh")

# ================== SIDEBAR ==================
with st.sidebar:
    st.header("⚙️ Settings")
    TELEGRAM_TOKEN = st.text_input("Telegram Bot Token", type="password")
    TELEGRAM_CHAT_ID = st.text_input("Telegram Chat ID")
    LUNAR_KEY = st.text_input("LunarCrush API Key (optional)", type="password")
    MIN_RVOL = st.slider("Min RVOL", 1.2, 3.0, 1.3, step=0.1)
    COOLDOWN_HOURS = st.slider("Cooldown hours", 1, 6, 1)
    MAX_24H_GAIN = st.slider("Max 24h Gain % to consider", 15, 60, 50)
    st.caption("History saved to JSON | Ready for 24/7 deployment")

# Exchanges
spot = ccxt.binance()
futures = ccxt.binanceusdm()

if 'alerted' not in st.session_state:
    st.session_state.alerted = {}
alerted = st.session_state.alerted

# History
history_file = "signal_history.json"
if os.path.exists(history_file):
    with open(history_file, 'r') as f:
        try:
            st.session_state.signal_history = json.load(f)
        except:
            pass

def save_history():
    with open(history_file, 'w') as f:
        json.dump(st.session_state.signal_history, f)

def get_top_300():
    try:
        data = requests.get("https://api.coingecko.com/api/v3/coins/markets", params={
            "vs_currency": "usd", "order": "market_cap_desc", "per_page": 300, "page": 1,
            "price_change_percentage": "1h,24h"
        }, timeout=10).json()
        df = pd.DataFrame(data)
        return df[df['market_cap_rank'] <= 300]
    except:
        return pd.DataFrame()

def get_futures_momentum(symbol):
    try:
        sym = f"{symbol.upper()}/USDT"
        funding = futures.fetch_funding_rate(sym)
        oi = futures.fetch_open_interest(sym)
        return {"funding_rate": round(funding.get('fundingRate', 0) * 100, 4),
                "oi": oi.get('openInterestAmount', 0)}
    except:
        return {"funding_rate": 0, "oi": 0}

def get_social_spike(symbol):
    if not LUNAR_KEY:
        return "No key"
    try:
        r = requests.get(f"https://lunarcrush.com/api4/public/coins/{symbol.lower()}/v1?key={LUNAR_KEY}")
        data = r.json().get('data', {})
        mentions = data.get('social_volume_24h', 0) or data.get('twitter_mentions_24h', 0)
        galaxy = round(data.get('galaxy_score', 0), 1)
        return f"📣 {mentions:,} | Galaxy {galaxy}"
    except:
        return "API error"

def calculate_pump_score(rvol, df):
    score = 0
    if rvol >= MIN_RVOL: score += 35
    if df['ema9'].iloc[-1] > df['ema21'].iloc[-1] and df['ema9'].iloc[-2] <= df['ema21'].iloc[-2]:
        score += 25
    if df['MACD_12_26_9'].iloc[-1] > df['MACDs_12_26_9'].iloc[-1] and df['MACDh_12_26_9'].iloc[-1] > 0:
        score += 20
    if 50 < df['rsi'].iloc[-1] < 70:
        score += 10
    return min(100, score)

def scan_coins():
    coins = get_top_300()
    if coins.empty:
        return pd.DataFrame(), [], pd.DataFrame()

    signals = []
    partials = []

    for _, coin in coins.iterrows():
        symbol = coin['symbol'].upper()
        price_change_24h = coin.get('price_change_percentage_24h', 0)

        if coin.get('total_volume', 0) < 3_000_000 or price_change_24h > MAX_24H_GAIN:
            continue

        try:
            ohlcv = spot.fetch_ohlcv(f"{symbol}/USDT", '15m', limit=100)
            df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])

            df['ema9'] = ta.ema(df['close'], 9)
            df['ema21'] = ta.ema(df['close'], 21)
            df['rsi'] = ta.rsi(df['close'])
            macd = ta.macd(df['close'])
            df = pd.concat([df, macd], axis=1)

            try:
                st_df = ta.supertrend(df['high'], df['low'], df['close'])
                df['supertrend'] = st_df['SUPERT_7_3.0']
            except:
                df['supertrend'] = df['close']

            avg_vol = df['volume'].rolling(20).mean().iloc[-1]
            rvol = df['volume'].iloc[-1] / avg_vol if avg_vol > 0 else 0

            ema_cross = (df['ema9'].iloc[-1] > df['ema21'].iloc[-1]) and (df['ema9'].iloc[-2] <= df['ema21'].iloc[-2])
            macd_bull = (df['MACD_12_26_9'].iloc[-1] > df['MACDs_12_26_9'].iloc[-1]) and (df['MACDh_12_26_9'].iloc[-1] > 0)

            if (ema_cross or rvol >= MIN_RVOL) and macd_bull:
                pump_score = calculate_pump_score(rvol, df)
                futures_m = get_futures_momentum(symbol)
                social = get_social_spike(symbol)

                signal = {
                    "Coin": symbol,
                    "Rank": int(coin.get('market_cap_rank', 999)),
                    "Price": round(coin.get('current_price', 0), 6),
                    "RVOL": round(rvol, 1),
                    "1h %": round(coin.get('price_change_percentage_1h', 0), 2),
                    "24h %": round(price_change_24h, 2),
                    "Pump Score": pump_score,
                    "Funding Rate": futures_m['funding_rate'],
                    "Social": social,
                    "Link": f"https://www.coingecko.com/en/coins/{coin['id']}"
                }
                signals.append(signal)

            # Partial Signals
            partial_score = 0
            reasons = []
            if rvol >= 1.3:
                partial_score += 2
                reasons.append(f"RVOL {round(rvol,1)}x")
            if macd_bull:
                partial_score += 1
                reasons.append("MACD Bull")
            if ema_cross:
                partial_score += 1
                reasons.append("EMA Cross")

            if partial_score >= 1 and price_change_24h < MAX_24H_GAIN + 20:
                partials.append({
                    "Coin": symbol,
                    "Rank": int(coin.get('market_cap_rank', 999)),
                    "RVOL": round(rvol, 1),
                    "1h %": round(coin.get('price_change_percentage_1h', 0), 2),
                    "24h %": round(price_change_24h, 2),
                    "Partial Score": partial_score,
                    "Reasons": ", ".join(reasons),
                    "Link": f"https://www.coingecko.com/en/coins/{coin['id']}"
                })

        except:
            continue

    df_signals = pd.DataFrame(signals)
    if not df_signals.empty:
        df_signals = df_signals.sort_values("Pump Score", ascending=False)

    df_partials = pd.DataFrame(partials)
    if not df_partials.empty:
        df_partials = df_partials.sort_values("24h %", ascending=False)

    return df_signals, signals[:5], df_partials

# ===================== TABS =====================
tab1, tab2, tab3, tab4 = st.tabs(["📡 Live Scanner", "💼 Portfolio Tracker", "📜 History", "📊 Backtesting"])

with tab1:
    dubai_tz = datetime.now(ZoneInfo("Asia/Dubai"))

    st.subheader("Live Early Pump Signals (Auto-refresh every 1 min)")
    st.caption(f"🕒 Last scan: {dubai_tz.strftime('%Y-%m-%d %H:%M:%S')} **Dubai time** | "
               f"Min RVOL: {MIN_RVOL} | Max 24h: {MAX_24H_GAIN}%")

    with st.spinner("Scanning top 300 coins..."):
        df_signals, top5, df_partials = scan_coins()

    # Live Strong Signals
    st.subheader("🚀 Live Strong Signals (Max 5)")
    if not df_signals.empty:
        live_display = df_signals.head(5).copy()
        live_display['Detected (Dubai)'] = dubai_tz.strftime('%H:%M:%S')
        st.dataframe(live_display, use_container_width=True, hide_index=True,
                     column_config={"Link": st.column_config.LinkColumn("Link")})
    else:
        st.info("No full strong signals right now")

    # Partial Signals
    st.subheader("🔍 Partial / Near-Miss Signals (Max 5)")
    if not df_partials.empty:
        partial_display = df_partials.head(5).copy()
        partial_display['Detected (Dubai)'] = dubai_tz.strftime('%H:%M:%S')
        st.dataframe(partial_display, use_container_width=True, hide_index=True,
                     column_config={"Link": st.column_config.LinkColumn("Link")})
    else:
        st.info("No near-misses detected this scan")

    # Hot Movers - Ultra Safe
    st.subheader("🔥 Hot Movers Watchlist (Top 5 by 24h %)")
    coins = get_top_300()
    if not coins.empty:
        hot = coins.sort_values('price_change_percentage_24h', ascending=False).head(5).copy()
        
        display_hot = pd.DataFrame({
            "Coin": hot["symbol"].str.upper(),
            "Price ($)": hot["current_price"].round(6),
            "1h %": hot.get("price_change_percentage_1h", 
                           hot.get("price_change_percentage_1h_in_currency", 0.0)).round(2),
            "24h %": hot["price_change_percentage_24h"].round(2),
            "24h Volume": hot["total_volume"].apply(lambda x: f"${x:,.0f}" if pd.notna(x) else "N/A"),
            "Detected (Dubai)": dubai_tz.strftime("%H:%M:%S")
        })
        
        st.dataframe(display_hot, use_container_width=True, hide_index=True)
        st.caption("Top 5 hottest movers right now")
    else:
        st.info("Could not load hot movers this scan")

with tab2:
    st.subheader("💼 Portfolio Tracker")
    st.info("Portfolio tracker can be added later if needed.")

with tab3:
    st.subheader("📜 Signal History")
    if st.session_state.signal_history:
        hist_df = pd.DataFrame(st.session_state.signal_history)
        csv_buffer = io.StringIO()
        hist_df.to_csv(csv_buffer, index=False)
        st.download_button("📥 Export History to CSV", csv_buffer.getvalue(), "pump_history.csv", "text/csv")
        st.dataframe(hist_df, use_container_width=True, hide_index=True)
    else:
        st.info("No signals recorded yet")

with tab4:
    st.subheader("📊 Backtesting Mode")
    st.info("Simplified demo.")

st.caption("✅ Correct Dubai time | Safe Hot Movers | Max 5 rows | Signal Time added")

if st.button("Save Current History"):
    save_history()
    st.success("History saved!")
