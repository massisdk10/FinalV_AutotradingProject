"""
Creative and friendly Telegram bot messages with emojis and personality.
Every message is crafted to feel professional yet warm and encouraging.
"""


# ──────────────────────────────────────────────
# Welcome & General
# ──────────────────────────────────────────────
WELCOME = (
    "🚀 *Welcome aboard, Commander!*\n\n"
    "Your *MT5 Private Execution System* is online\n"
    "and ready to conquer the markets! 💎\n\n"
    "🎮 Use the menu below to take control.\n"
    "Let's make some magic happen! ✨"
)

MAIN_MENU = (
    "🏠 *Command Center*\n\n"
    "What would you like to do, Champion? 👇"
)

GOODBYE = (
    "👋 See you later, Legend!\n"
    "The markets will be waiting for your return! 🌟"
)

UNAUTHORIZED = (
    "🚫 *Access Denied*\n\n"
    "Sorry, this system is for authorized personnel only! 🔐"
)

# ──────────────────────────────────────────────
# Account Management
# ──────────────────────────────────────────────
LOGIN_SUCCESS = (
    "🔓 *Locked & Loaded!*\n\n"
    "✅ MT5 connected successfully!\n"
    "🎯 Account: `{account_id}`\n"
    "🌐 Server: `{server}`\n"
    "💰 Balance: `{balance}`\n"
    "📊 Mode: *{mode}*\n\n"
    "Ready to execute with precision! ⚡"
)

LOGIN_FAILED = (
    "❌ *Login Failed!*\n\n"
    "Could not connect to MT5.\n"
    "🔍 Please check your credentials and try again.\n\n"
    "💡 Make sure MT5 terminal is running!"
)

LOGOUT_SUCCESS = (
    "🔒 *MT5 Disconnected*\n\n"
    "All clear! Connection closed safely. ✅\n\n"
    "Come back anytime, Champion! 💪"
)

ALREADY_LOGGED_IN = (
    "✅ You're already connected!\n\n"
    "🎯 Use the menu to manage your session."
)

NOT_LOGGED_IN = (
    "🔒 *Not Connected*\n\n"
    "Please login to MT5 first! 🔐\n"
    "Go to 🔐 *Account Management* → *Login*"
)

MODE_SWITCHED = (
    "🔄 *Account Mode Changed!*\n\n"
    "📊 Now running on: *{mode}* mode\n\n"
    "{emoji} {message}\n\n"
    "⚠️ Please *re-login* to apply the change!"
)

# ──────────────────────────────────────────────
# Settings
# ──────────────────────────────────────────────
SETTINGS_VIEW = (
    "⚙️ *Current Settings*\n\n"
    "📦 Lot Size: `{lot_size}`\n"
    "🛡️ Max Daily Stop Loss: `${max_daily_sl}`\n"
    "📊 Account Mode: *{mode}*\n"
    "🔐 MT5 Connection: *{login_status}*\n\n"
    "🔧 Tap below to modify settings 👇"
)

LOT_SIZE_SET = (
    "📦 *Lot Size Updated!*\n\n"
    "New lot size: `{lot_size}`\n\n"
    "✅ All future trades will use this size! 🎯"
)

LOT_SIZE_PROMPT = (
    "📦 *Set Lot Size*\n\n"
    "Current: `{current}`\n\n"
    "📝 Send the new lot size (e.g., `0.01`, `0.1`, `1.0`):"
)

MAX_DAILY_SL_SET = (
    "🛡️ *Daily Stop Loss Updated!*\n\n"
    "New limit: `${max_daily_sl}`\n\n"
    "✅ Execution will pause if daily loss reaches this! 🔒"
)

MAX_DAILY_SL_PROMPT = (
    "🛡️ *Set Max Daily Stop Loss*\n\n"
    "Current: `${current}`\n\n"
    "📝 Send the new maximum daily loss amount (e.g., `50`, `100`, `200`):"
)

LIVE_CREDS_PROMPT = (
    "🔴 *Update Live Account Credentials*\n\n"
    "📝 Send your credentials in this format:\n\n"
    "`account_id`\n"
    "`password`\n"
    "`server`\n\n"
    "Example:\n"
    "`12345678`\n"
    "`MyP@ssw0rd`\n"
    "`ICMarkets-Live`"
)

DEMO_CREDS_PROMPT = (
    "🟢 *Update Demo Account Credentials*\n\n"
    "📝 Send your credentials in this format:\n\n"
    "`account_id`\n"
    "`password`\n"
    "`server`\n\n"
    "Example:\n"
    "`87654321`\n"
    "`DemoPass123`\n"
    "`ICMarkets-Demo`"
)

CREDS_UPDATED = (
    "✅ *{mode} Account Credentials Updated!*\n\n"
    "🎯 Account ID: `{account_id}`\n"
    "🌐 Server: `{server}`\n\n"
    "🔐 Stored securely! Please *re-login* to use. 💪"
)

CREDS_INVALID = (
    "❌ *Invalid Format!*\n\n"
    "Please send exactly 3 lines:\n"
    "Line 1: Account ID\n"
    "Line 2: Password\n"
    "Line 3: Server\n\n"
    "Try again! 💡"
)

# ──────────────────────────────────────────────
# Trading
# ──────────────────────────────────────────────
OPEN_TRADE_GROUPS = (
    "📊 *Open TradeGroups ({count})*\n\n"
    "{groups}\n\n"
    "💎 Stay focused, the targets are in sight!"
)

NO_OPEN_TRADES = (
    "📭 *No Open TradeGroups*\n\n"
    "The battlefield is clear! 🏖️\n"
    "Waiting for the next signal... 📡"
)

TRADE_GROUP_DETAIL = (
    "━━━━━━━━━━━━━━━━━━━━\n"
    "🔹 *TradeGroup #{tg_id}*\n"
    "📊 {symbol} | {side}\n"
    "📍 Entry: `{entry}`\n"
    "🛡️ SL: `{sl}`\n"
    "🥇 TP1: `{tp1}` {t1_icon}\n"
    "🥈 TP2: `{tp2}` {t2_icon}\n"
    "🏆 TP3: `{tp3}` {t3_icon}\n"
    "⏱️ Opened: {created}\n"
)

CLOSE_TG_PROMPT = (
    "🔴 *Close TradeGroup*\n\n"
    "📝 Send the TradeGroup ID to close (e.g., `1`):\n\n"
    "⚠️ This will close ALL remaining positions in that group!"
)

CLOSE_TG_SUCCESS = (
    "✅ *TradeGroup #{tg_id} Closed!*\n\n"
    "📊 {symbol} — All positions sealed.\n\n"
    "💪 Well played, Champion! On to the next! 🚀"
)

CLOSE_TG_NOT_FOUND = "❌ TradeGroup not found or already closed."

# ──────────────────────────────────────────────
# History & Performance
# ──────────────────────────────────────────────
TRADE_HISTORY_HEADER = (
    "📈 *Trade History (Last {count})*\n\n"
)

TRADE_HISTORY_ROW = (
    "▫️ #{tg_id} {symbol} {side} | {label} | "
    "P&L: `{profit}` | {status_icon}\n"
)

DAILY_PERFORMANCE = (
    "📊 *Today's Performance*\n\n"
    "💰 Total P&L: `${pnl}`\n"
    "📈 Trades: `{count}`\n"
    "✅ Wins: `{wins}`\n"
    "❌ Losses: `{losses}`\n"
    "🎯 Win Rate: `{winrate}%`\n\n"
    "{verdict}"
)

PERFORMANCE_GREAT = "🔥 *Outstanding day, Champion!* Keep crushing it! 💎"
PERFORMANCE_GOOD = "👍 *Solid performance!* Consistency is key! 💪"
PERFORMANCE_NEUTRAL = "🤝 *Break-even day.* Tomorrow is a new opportunity! 🌅"
PERFORMANCE_LOSS = "🛡️ *Tough day.* Every pro has them. Stay disciplined! 🧘"

ACCOUNT_INFO = (
    "💼 *MT5 Account Info*\n\n"
    "👤 Name: `{name}`\n"
    "🔢 Account: `{login}`\n"
    "🌐 Server: `{server}`\n"
    "💰 Balance: `${balance}`\n"
    "📊 Equity: `${equity}`\n"
    "📈 Profit: `${profit}`\n"
    "🔒 Margin: `${margin}`\n"
    "💎 Free Margin: `${free_margin}`\n"
    "📐 Leverage: `1:{leverage}`\n"
)

# ──────────────────────────────────────────────
# Status Icons
# ──────────────────────────────────────────────
def status_icon(status_str: str) -> str:
    icons = {
        "open": "🟢",
        "tp_hit": "🎯",
        "sl_hit": "🛡️",
        "manual_close": "🔵",
        "closed": "⚫",
    }
    return icons.get(status_str, "⚪")
