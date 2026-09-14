import os
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
# Telegram (Telethon - Signal Listener)
# ──────────────────────────────────────────────
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE", "")

# ──────────────────────────────────────────────
# Telegram Bot (Management Interface)
# ──────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID", "0"))

# ──────────────────────────────────────────────
# Signal Source
# ──────────────────────────────────────────────
SIGNAL_CHANNEL_ID = int(os.getenv("SIGNAL_CHANNEL_ID", "0"))

# ──────────────────────────────────────────────
# Database
# ──────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/copytrading")

# ──────────────────────────────────────────────
# MT5
# ──────────────────────────────────────────────
MT5_PATH = os.getenv("MT5_PATH", "")

# ──────────────────────────────────────────────
# Position Monitor Interval (seconds)
# ──────────────────────────────────────────────
MONITOR_INTERVAL = int(os.getenv("MONITOR_INTERVAL", "2"))

# ──────────────────────────────────────────────
# Trading Safety & Defaults
# ──────────────────────────────────────────────
# Timeout for SIGNAL_FULL to arrive after NOW (seconds)
# Extended from 90s to 180s for better cache matching
SIGNAL_FULL_TIMEOUT = int(os.getenv("SIGNAL_FULL_TIMEOUT", "180"))

# Default SL/TP if SIGNAL_FULL never arrives (conservative values)
# These are in pips - will be applied based on signal direction

# XAUUSD and general defaults
DEFAULT_SL_PIPS = float(os.getenv("DEFAULT_SL_PIPS", "1000.0"))  # 1000 pips = $10 max loss with 0.01 lot during NOW→SIGNAL_FULL wait
DEFAULT_TP1_PIPS = float(os.getenv("DEFAULT_TP1_PIPS", "50.0"))  # 50 pips TP1 (wide to avoid premature close before real signal)
DEFAULT_TP2_PIPS = float(os.getenv("DEFAULT_TP2_PIPS", "150.0"))  # 150 pips TP2 (wide to avoid premature close before real signal)
DEFAULT_TP3_PIPS = float(os.getenv("DEFAULT_TP3_PIPS", "0.0"))  # Runner (no TP)

# BTCUSD specific defaults (client requirement)
DEFAULT_BTC_SL_PIPS = float(os.getenv("DEFAULT_BTC_SL_PIPS", "350.0"))  # 350 pips SL for BTC
DEFAULT_BTC_TP1_PIPS = float(os.getenv("DEFAULT_BTC_TP1_PIPS", "350.0"))  # 350 pips TP1
DEFAULT_BTC_TP2_PIPS = float(os.getenv("DEFAULT_BTC_TP2_PIPS", "1050.0"))  # 1050 pips TP2
DEFAULT_BTC_TP3_PIPS = float(os.getenv("DEFAULT_BTC_TP3_PIPS", "0.0"))  # Runner (no TP)

# ──────────────────────────────────────────────
# Advanced Safety & Protection Parameters
# ──────────────────────────────────────────────
# Maximum price movement during SIGNAL_FULL timeout (pips)
# If exceeded, positions are closed instead of applying defaults
# Gold moves ~$0.50-2.00 in 3 mins normally, so 100 pips ($1.00) is reasonable
MAX_TIMEOUT_MOVEMENT_PIPS = float(os.getenv("MAX_TIMEOUT_MOVEMENT_PIPS", "100.0"))

# Symbol-specific maximum gap from signal entry to current price (pips)
# If exceeded, trade is skipped to prevent late entries
# Client accepts normal latency: Gold ~70 pips, BTC ~600 pips acceptable
MAX_ENTRY_GAP_GOLD = float(os.getenv("MAX_ENTRY_GAP_GOLD", "70.0"))  # Gold: ~18 USD with 0.01 lot
MAX_ENTRY_GAP_BTC = float(os.getenv("MAX_ENTRY_GAP_BTC", "600.0"))  # BTC: High volatility tolerance
MAX_ENTRY_GAP_FOREX = float(os.getenv("MAX_ENTRY_GAP_FOREX", "10.0"))  # Forex: Conservative

# ──────────────────────────────────────────────
# Symbol-specific Lot Sizes
# ──────────────────────────────────────────────
# Different brokers have different minimum lot sizes per instrument
# XAUUSD: 0.01 lot minimum (most brokers)
# BTCUSD: 0.1 or 1.0 lot minimum (check with broker)
SYMBOL_LOT_SIZES = {
    "XAUUSD": 0.01,
    "BTCUSD": 0.1,  # Adjust based on broker requirements (may need 1.0)
    "XAGUSD": 0.01,
    # Forex pairs typically 0.01
    "EURUSD": 0.01,
    "GBPUSD": 0.01,
    "USDJPY": 0.01,
}
DEFAULT_LOT_SIZE = 0.01  # Fallback for unlisted symbols

