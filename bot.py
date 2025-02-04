import requests
import time
import sqlite3
import pandas as pd
import json
from datetime import datetime
import telebot  # Telegram Bot API

# Load Config
with open("config.json", "r") as config_file:
    config = json.load(config_file)

# Constants
DEXSCREENER_API_URL = config["dex_api_url"]
RUGCHECK_API_URL = config["rugcheck_api_url"]
DATABASE_NAME = config["database_name"]
UPDATE_INTERVAL = config["update_interval_seconds"]
FILTERS = config["filters"]
BLACKLIST = config["blacklist"]
TELEGRAM_BOT_TOKEN = config["telegram"]["bot_token"]
TELEGRAM_CHAT_ID = config["telegram"]["chat_id"]
BONKBOT_COMMAND_PREFIX = config["bonkbot"]["command_prefix"]
BONKBOT_TRADE_COMMAND = config["bonkbot"]["trade_command"]

# Initialize Telegram Bot
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Initialize SQLite Database
def init_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tokens (
            id TEXT PRIMARY KEY,
            name TEXT,
            symbol TEXT,
            price REAL,
            liquidity REAL,
            volume REAL,
            market_cap REAL,
            dev_address TEXT,
            is_bundled_supply BOOLEAN,
            rugcheck_status TEXT,
            timestamp DATETIME
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_id TEXT,
            event_type TEXT,  -- e.g., "rug", "pump", "cex_listing"
            details TEXT,
            timestamp DATETIME
        )
    ''')
    conn.commit()
    conn.close()

# Fetch Token Data from DexScreener
def fetch_token_data(token_address):
    response = requests.get(f"{DEXSCREENER_API_URL}/{token_address}")
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to fetch data for token {token_address}")
        return None

# Check Token on Rugcheck
def check_rugcheck(token_address):
    response = requests.get(f"{RUGCHECK_API_URL}/{token_address}")
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to fetch Rugcheck data for token {token_address}")
        return None

# Check if Token is Blacklisted
def is_blacklisted(token_data):
    token = token_data['token']
    symbol = token['symbol']
    dev_address = token.get('dev_address', '')

    # Check coin blacklist
    if symbol in BLACKLIST["coins"]:
        return True

    # Check dev blacklist
    if dev_address in BLACKLIST["devs"]:
        return True

    return False

# Apply Filters
def apply_filters(token_data):
    token = token_data['token']
    liquidity = token.get('liquidity', 0)
    price = token.get('price', 0)
    volume = token.get('volume', 0)

    if (liquidity < FILTERS["min_liquidity"] or
        price > FILTERS["max_price"] or
        volume < FILTERS["min_volume"]):
        return False

    # Check volume/liquidity ratio
    if volume > FILTERS["max_volume_liquidity_ratio"] * liquidity:
        return False

    return True

# Save Token Data to Database
def save_token_data(token_data, rugcheck_data):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    token = token_data['token']
    cursor.execute('''
        INSERT INTO tokens (id, name, symbol, price, liquidity, volume, market_cap, dev_address, is_bundled_supply, rugcheck_status, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        token['id'],
        token['name'],
        token['symbol'],
        token['price'],
        token['liquidity'],
        token['volume'],
        token['marketCap'],
        token.get('dev_address', ''),
        rugcheck_data.get('is_bundled_supply', False),
        rugcheck_data.get('status', 'Unknown'),
        datetime.now()
    ))
    conn.commit()
    conn.close()

# Send Telegram Notification
def send_telegram_notification(message):
    bot.send_message(TELEGRAM_CHAT_ID, message)

# Execute BonkBot Trade Command
def execute_bonkbot_trade(token_symbol):
    command = f"{BONKBOT_COMMAND_PREFIX} {BONKBOT_TRADE_COMMAND} {token_symbol}"
    send_telegram_notification(f"Executing trade command: {command}")

# Detect Events (Rug, Pump, CEX Listing)
def detect_events(token_data):
    token = token_data['token']
    price = token['price']
    liquidity = token['liquidity']
    volume = token['volume']

    # Example: Detect Rug Pull (sudden drop in liquidity and price)
    if liquidity < 1000 and price < 0.1 * get_historical_avg_price(token['id']):
        log_event(token['id'], "rug", "Liquidity and price dropped significantly")
        send_telegram_notification(f"🚨 Rug Pull Detected: {token['symbol']}")

    # Example: Detect Pump (sudden increase in price and volume)
    if volume > 1000000 and price > 1.5 * get_historical_avg_price(token['id']):
        log_event(token['id'], "pump", "Price and volume increased significantly")
        send_telegram_notification(f"🚀 Pump Detected: {token['symbol']}")
        execute_bonkbot_trade(token['symbol'])

# Log Event to Database
def log_event(token_id, event_type, details):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO events (token_id, event_type, details, timestamp)
        VALUES (?, ?, ?, ?)
    ''', (token_id, event_type, details, datetime.now()))
    conn.commit()
    conn.close()

# Get Historical Average Price
def get_historical_avg_price(token_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT AVG(price) FROM tokens WHERE id = ?', (token_id,))
    avg_price = cursor.fetchone()[0] or 0
    conn.close()
    return avg_price

# Analyze Patterns Using Machine Learning
def analyze_patterns():
    conn = sqlite3.connect(DATABASE_NAME)
    df = pd.read_sql_query("SELECT * FROM tokens", conn)
    conn.close()

    # Example: Use Isolation Forest to detect anomalies
    model = IsolationForest(contamination=0.1)
    df['anomaly'] = model.fit_predict(df[['price', 'volume', 'liquidity']])
    anomalies = df[df['anomaly'] == -1]
    print("Detected Anomalies:")
    print(anomalies)

# Main Loop
def main():
    init_db()
    token_addresses = ["TOKEN_ADDRESS_1", "TOKEN_ADDRESS_2"]  # Add token addresses to monitor

    while True:
        for token_address in token_addresses:
            token_data = fetch_token_data(token_address)
            if token_data:
                # Skip blacklisted tokens and devs
                if is_blacklisted(token_data):
                    print(f"Skipping blacklisted token: {token_data['token']['symbol']}")
                    continue

                # Apply filters
                if not apply_filters(token_data):
                    print(f"Skipping token due to filters: {token_data['token']['symbol']}")
                    continue

                # Check Rugcheck status
                rugcheck_data = check_rugcheck(token_address)
                if not rugcheck_data:
                    print(f"Skipping token due to Rugcheck API failure: {token_data['token']['symbol']}")
                    continue

                # Skip if not marked as "Good" or supply is bundled
                if rugcheck_data.get('status') != "Good" or rugcheck_data.get('is_bundled_supply', False):
                    print(f"Skipping token with bad Rugcheck status or bundled supply: {token_data['token']['symbol']}")
                    # Add to blacklist if supply is bundled
                    if rugcheck_data.get('is_bundled_supply', False):
                        BLACKLIST["coins"].append(token_data['token']['symbol'])
                        BLACKLIST["devs"].append(token_data['token'].get('dev_address', ''))
                    continue

                # Save and analyze data
                save_token_data(token_data, rugcheck_data)
                detect_events(token_data)
        analyze_patterns()
        time.sleep(UPDATE_INTERVAL)  # Wait before next update

if __name__ == "__main__":
    main()