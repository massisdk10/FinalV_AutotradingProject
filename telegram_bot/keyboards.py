"""
Telegram bot inline keyboards for the menu-driven control system.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# ──────────────────────────────────────────────
# Callback Data Constants
# ──────────────────────────────────────────────
# Main Menu
CB_ACCOUNT = "menu_account"
CB_SETTINGS = "menu_settings"
CB_TRADING = "menu_trading"
CB_HISTORY = "menu_history"
CB_BACK_MAIN = "back_main"

# Account Management
CB_LOGIN = "account_login"
CB_LOGOUT = "account_logout"
CB_SWITCH_MODE = "account_switch_mode"
CB_ACCOUNT_INFO = "account_info"

# Settings
CB_SET_LOT = "settings_lot"
CB_SET_MAX_SL = "settings_max_sl"
CB_SET_LIVE_CREDS = "settings_live_creds"
CB_SET_DEMO_CREDS = "settings_demo_creds"
CB_VIEW_SETTINGS = "settings_view"

# Trading
CB_OPEN_TRADES = "trading_open"
CB_CLOSE_TG = "trading_close_tg"
CB_TRADE_HISTORY = "trading_history"

# History
CB_TODAY_PERF = "history_today"
CB_ALL_HISTORY = "history_all"

# Position-level actions (prefix + tg_id)
CB_POS_EDIT_SL = "pos_edit_sl_"    # pos_edit_sl_{tg_id}
CB_POS_EDIT_TP = "pos_edit_tp_"    # pos_edit_tp_{tg_id}
CB_POS_CLOSE = "pos_close_"        # pos_close_{tg_id}
CB_POS_REFRESH = "pos_refresh"

# Confirmation
CB_CONFIRM_YES = "confirm_yes"
CB_CONFIRM_NO = "confirm_no"


# ──────────────────────────────────────────────
# Keyboard Builders
# ──────────────────────────────────────────────
def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔐 Account Management", callback_data=CB_ACCOUNT)],
        [InlineKeyboardButton("⚙️ Settings", callback_data=CB_SETTINGS)],
        [InlineKeyboardButton("📊 Open Trades", callback_data=CB_TRADING)],
        [InlineKeyboardButton("📈 History & Performance", callback_data=CB_HISTORY)],
    ])


def account_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔓 Login", callback_data=CB_LOGIN),
            InlineKeyboardButton("🔒 Logout", callback_data=CB_LOGOUT),
        ],
        [
            InlineKeyboardButton("🔄 Switch Demo ↔ Live", callback_data=CB_SWITCH_MODE),
        ],
        [
            InlineKeyboardButton("💼 Account Info", callback_data=CB_ACCOUNT_INFO),
        ],
        [InlineKeyboardButton("◀️ Back to Menu", callback_data=CB_BACK_MAIN)],
    ])


def settings_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📦 Set Lot Size", callback_data=CB_SET_LOT),
            InlineKeyboardButton("🛡️ Max Daily SL", callback_data=CB_SET_MAX_SL),
        ],
        [
            InlineKeyboardButton("🔴 Live Account Creds", callback_data=CB_SET_LIVE_CREDS),
            InlineKeyboardButton("🟢 Demo Account Creds", callback_data=CB_SET_DEMO_CREDS),
        ],
        [
            InlineKeyboardButton("👁️ View All Settings", callback_data=CB_VIEW_SETTINGS),
        ],
        [InlineKeyboardButton("◀️ Back to Menu", callback_data=CB_BACK_MAIN)],
    ])


def trading_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Open TradeGroups", callback_data=CB_OPEN_TRADES),
        ],
        [
            InlineKeyboardButton("🔴 Close TradeGroup", callback_data=CB_CLOSE_TG),
        ],
        [
            InlineKeyboardButton("📜 Trade History", callback_data=CB_TRADE_HISTORY),
        ],
        [InlineKeyboardButton("◀️ Back to Menu", callback_data=CB_BACK_MAIN)],
    ])


def history_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Today's Performance", callback_data=CB_TODAY_PERF),
        ],
        [
            InlineKeyboardButton("📜 Full Trade History", callback_data=CB_ALL_HISTORY),
        ],
        [InlineKeyboardButton("◀️ Back to Menu", callback_data=CB_BACK_MAIN)],
    ])


def back_button_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Back to Menu", callback_data=CB_BACK_MAIN)],
    ])


def open_positions_keyboard(tg_data_list: list) -> InlineKeyboardMarkup:
    """Build keyboard with per-TradeGroup action buttons + refresh."""
    buttons = []
    for tg in tg_data_list:
        tg_id = tg["id"]
        buttons.append([
            InlineKeyboardButton(f"✏️ SL #{tg_id}", callback_data=f"{CB_POS_EDIT_SL}{tg_id}"),
            InlineKeyboardButton(f"🎯 TP #{tg_id}", callback_data=f"{CB_POS_EDIT_TP}{tg_id}"),
            InlineKeyboardButton(f"🔴 Close #{tg_id}", callback_data=f"{CB_POS_CLOSE}{tg_id}"),
        ])
    buttons.append([InlineKeyboardButton("🔄 Refresh", callback_data=CB_POS_REFRESH)])
    buttons.append([InlineKeyboardButton("◀️ Back to Menu", callback_data=CB_BACK_MAIN)])
    return InlineKeyboardMarkup(buttons)


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes", callback_data=CB_CONFIRM_YES),
            InlineKeyboardButton("❌ No", callback_data=CB_CONFIRM_NO),
        ],
    ])
