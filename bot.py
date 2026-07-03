import os
import time
import logging
from datetime import datetime
import pytz
import requests
import pandas as pd
import pandas_ta as ta
import ccxt

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Hardcoded credentials from your request
TELEGRAM_BOT_TOKEN = "8650963510:AAEuyDpP7TTURk0gfygY4uxXHQqCoqF179U"
TELEGRAM_CHAT_ID = "6088825847"

# Timezone config for Pakistan Standard Time
PKT_ZONE = pytz.timezone('Asia/Karachi')

# Initialize Binance Futures
exchange = ccxt.binance({'options': {'defaultType': 'future'}, 'enableRateLimit': True})

def get_pkt_now_str():
    """Returns the current Pakistan Time as a formatted string."""
    return datetime.now(PKT_ZONE).strftime('%Y-%m-%d %I:%M:%S %p')

def send_telegram_message(message):
    """Sends a notification message to Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            logging.error(f"Telegram error: {response.text}")
    except Exception as e:
        logging.error(f"Failed to send Telegram message: {e}")

def get_futures_symbols():
    """Fetches all active USDS-M Futures symbols on Binance."""
    try:
        exchange.load_markets()
        symbols = [symbol for symbol, market in exchange.markets.items() if market['linear'] and market['active']]
        return symbols
    except Exception as e:
        logging.error(f"Error fetching symbols: {e}")
        return []

def fetch_candles(symbol, timeframe='1d', limit=250):
    """Fetches historical candles safely. Returns DataFrame or None if failed/delisted."""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not ohlcv or len(ohlcv) < 50:
            return None
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        # Convert timestamp to UTC first, then localize to Pakistan Time
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert(PKT_ZONE)
        return df
    except Exception as e:
        logging.warning(f"Skipping {symbol}: Data unavailable or delisted. Error: {e}")
        return None

def analyze_strategy_1(symbol, df):
    """Strategy 1: RSI (14) Bearish/Bullish Divergence on maximum 50 daily candles."""
    df['rsi'] = ta.rsi(df['close'], length=14)
    df = df.dropna().reset_index(drop=True)
    
    # Analyze the last 50 candles maximum
    df = df.tail(50).reset_index(drop=True)
    n = len(df)
    if n < 5:
        return

    # Prioritize recent candles first (Iterate backward from the current candle)
    curr_high = df.loc[n-1, 'high']
    curr_low = df.loc[n-1, 'low']
    curr_rsi = df.loc[n-1, 'rsi']

    for i in range(n-2, 0, -1):
        prev_high = df.loc[i, 'high']
        prev_low = df.loc[i, 'low']
        prev_rsi = df.loc[i, 'rsi']
        
        # Bearish Divergence (Sell Signal)
        if curr_high >= prev_high and curr_rsi < prev_rsi:
            # Check if it's a structural pivot peak locally
            if i > 0 and prev_rsi > df.loc[i-1, 'rsi'] and (i < n-2 and prev_rsi > df.loc[i+1, 'rsi']):
                pkt_time = get_pkt_now_str()
                msg = (f"🚨 *Strategy 1: SELL Signal* 🚨\n"
                       f"Coin: `{symbol}`\n"
                       f"Price made Higher/Same High, RSI made Lower High.\n"
                       f"🇵🇰 *PKT Time:* `{pkt_time}`")
                send_telegram_message(msg)
                break 

        # Bullish Divergence (Buy Signal)
        if curr_low <= prev_low and curr_rsi > prev_rsi:
            # Check if it's a structural pivot low locally
            if i > 0 and prev_rsi < df.loc[i-1, 'rsi'] and (i < n-2 and prev_rsi < df.loc[i+1, 'rsi']):
                pkt_time = get_pkt_now_str()
                msg = (f"📈 *Strategy 1: BUY Signal* 📈\n"
                       f"Coin: `{symbol}`\n"
                       f"Price made Lower/Same Low, RSI made Higher Low.\n"
                       f"🇵🇰 *PKT Time:* `{pkt_time}`")
                send_telegram_message(msg)
                break

def analyze_strategy_2(symbol, df):
    """Strategy 2: Price touches EMA 190."""
    df['ema190'] = ta.ema(df['close'], length=190)
    if df['ema190'].isna().iloc[-1]:
        return # Not enough historical data built up yet for 190 EMA

    last_row = df.iloc[-1]
    low = last_row['low']
    high = last_row['high']
    ema = last_row['ema190']
    
    # Extract historical candle timestamp transformed into Pakistan Time format
    candle_date_pkt = last_row['datetime'].strftime('%Y-%m-%d %I:%M %p')

    # Check if price range touches or crosses EMA 190
    if low <= ema <= high:
        pkt_time = get_pkt_now_str()
        msg = (f"🔔 *Strategy 2: EMA 190 Touch* 🔔\n"
               f"Coin: `{symbol}`\n"
               f"Candle Date (PKT): `{candle_date_pkt}`\n"
               f"Status: `ema Touch`\n"
               f"🇵🇰 *Alert Sent (PKT):* `{pkt_time}`")
        send_telegram_message(msg)

def chunk_list(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def main_loop():
    pkt_time = get_pkt_now_str()
    send_telegram_message(f"🤖 *Bot is now LIVE and scanning symbols...*\n🇵🇰 *Start Time:* `{pkt_time}`")
    
    while True:
        try:
            symbols = get_futures_symbols()
            if not symbols:
                logging.warning("No symbols found. Retrying in 30 seconds...")
                time.sleep(30)
                continue

            # Split symbols into batches of 100
            batches = list(chunk_list(symbols, 100))
            
            for index, batch in enumerate(batches):
                logging.info(f"Processing batch {index + 1}/{len(batches)} ({len(batch)} coins)...")
                
                for symbol in batch:
                    df = fetch_candles(symbol, timeframe='1d', limit=250) 
                    if df is None:
                        continue
                    
                    # Run analysis strategies
                    analyze_strategy_1(symbol, df)
                    analyze_strategy_2(symbol, df)
                    
                pkt_time = get_pkt_now_str()
                send_telegram_message(f"✅ *Batch {index + 1} Scan Complete!*\n🇵🇰 *Completed At:* `{pkt_time}`")
                
                # Dynamic delay request: Scan after 5 min -> cool 3 min.
                logging.info("Batch completed. Entering 5-minute loop pause...")
                time.sleep(300) 
                
                logging.info("Sleeping for 3 minute operational rest...")
                time.sleep(180) 

        except Exception as e:
            logging.error(f"An unexpected loop crash occurred: {e}. Recovering immediately...")
            time.sleep(10) # Quick safety buffer before resuming loops

if __name__ == "__main__":
    main_loop()