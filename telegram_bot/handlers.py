import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database.engine import get_session
from database import crud
from database.models import AccountMode, PositionStatus
from telegram_bot import messages as msg
from telegram_bot import keyboards as kb

logger = logging.getLogger("BotHandlers")

# Store references to shared components (set by bot.py on startup)
_mt5_connector = None
_trade_executor = None


def set_components(mt5_connector, trade_executor):
    global _mt5_connector, _trade_executor
    _mt5_connector = mt5_connector
    _trade_executor = trade_executor


def _is_admin(update: Update) -> bool:
    """Check if the user is the authorized admin."""
    import config
    user_id = update.effective_user.id
    return user_id == config.TELEGRAM_ADMIN_ID


async def _get_status_bar() -> str:
    """Build a compact status bar showing mode, connection, balance, daily stats."""
    with get_session() as session:
        settings = crud.get_settings(session)
        pnl = crud.get_today_pnl(session)
        mode = settings.account_mode.value.upper()
        mode_emoji = "🔴" if mode == "LIVE" else "🟢"
        connected = settings.is_logged_in
        trade_count = pnl.trade_count
        total_pnl = pnl.total_pnl
        if mode == "LIVE":
            acct_id = settings.live_account_id or "—"
            server = settings.live_account_server or "—"
        else:
            acct_id = settings.demo_account_id or "—"
            server = settings.demo_account_server or "—"

    # Fetch live balance and AutoTrading status from MT5
    balance_str = "—"
    autotrading_enabled = False
    if _mt5_connector and connected:
        try:
            info = await _mt5_connector.get_account_info()
            if info:
                balance_str = f"${info.get('balance', 0):.2f}"
            autotrading_enabled = await _mt5_connector.check_autotrading()
        except Exception:
            pass

    pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
    auto_emoji = "✅" if autotrading_enabled else "❌"
    lines = (
        f"{mode_emoji} Mode: *{mode}*  |  "
        f"MT5: *{'Connected ✅' if connected else 'Disconnected ❌'}*\n"
        f"👤 Account: `{acct_id}` @ `{server}`\n"
        f"💰 Balance: *{balance_str}*\n"
        f"⚡ AutoTrading: *{auto_emoji}*\n"
        f"{pnl_emoji} Today: *{trade_count}* trades  |  "
        f"P&L: *${total_pnl:+.2f}*"
    )
    return lines


# ──────────────────────────────────────────────
# /start Command
# ──────────────────────────────────────────────
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        await update.message.reply_text(msg.UNAUTHORIZED, parse_mode=ParseMode.MARKDOWN)
        return
    status = await _get_status_bar()
    await update.message.reply_text(
        f"{msg.WELCOME}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{status}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.main_menu_keyboard(),
    )


# ──────────────────────────────────────────────
# /menu Command
# ──────────────────────────────────────────────
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        await update.message.reply_text(msg.UNAUTHORIZED, parse_mode=ParseMode.MARKDOWN)
        return
    status = await _get_status_bar()
    await update.message.reply_text(
        f"{msg.MAIN_MENU}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{status}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.main_menu_keyboard(),
    )


# ──────────────────────────────────────────────
# /status Command
# ──────────────────────────────────────────────
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    with get_session() as session:
        settings = crud.get_settings(session)
        pnl = crud.get_today_pnl(session)
        open_tgs = crud.get_open_trade_groups(session)
        mode = settings.account_mode.value.upper()
        mode_emoji = "🔴" if mode == "LIVE" else "🟢"
        connected = settings.is_logged_in
        lot_size = settings.lot_size
        max_sl = settings.max_daily_stop_loss
        total_pnl = pnl.total_pnl
        open_count = len(open_tgs)
        if mode == "LIVE":
            acct_id = settings.live_account_id or "—"
            server = settings.live_account_server or "—"
        else:
            acct_id = settings.demo_account_id or "—"
            server = settings.demo_account_server or "—"
    
    # Check AutoTrading status
    autotrading_enabled = False
    if _mt5_connector and connected:
        try:
            autotrading_enabled = await _mt5_connector.check_autotrading()
        except Exception:
            pass
    
    auto_status = "ON ✅" if autotrading_enabled else "OFF ❌"

    text = (
        "📡 *System Status*\n\n"
        f"────────────────────\n"
        f"{mode_emoji} Mode: *{mode}*\n"
        f"🔐 MT5: *{'Connected ✅' if connected else 'Disconnected ❌'}*\n"
        f"👤 Account: `{acct_id}` @ `{server}`\n"
        f"⚡ AutoTrading: *{auto_status}*\n"
        f"────────────────────\n\n"
        f"📦 Lot Size: `{lot_size}`\n"
        f"🛡️ Daily SL Limit: `${max_sl}`\n"
        f"📈 Today's P&L: `${total_pnl:.2f}`\n"
        f"📊 Open TradeGroups: `{open_count}`\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb.main_menu_keyboard())


# ──────────────────────────────────────────────
# Callback Query Router
# ──────────────────────────────────────────────
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not _is_admin(update):
        await query.edit_message_text(msg.UNAUTHORIZED, parse_mode=ParseMode.MARKDOWN)
        return

    data = query.data

    # Main Menu Navigation
    if data == kb.CB_BACK_MAIN:
        status = await _get_status_bar()
        await query.edit_message_text(
            f"{msg.MAIN_MENU}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{status}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.main_menu_keyboard(),
        )

    elif data == kb.CB_ACCOUNT:
        await _show_account_menu(query)

    elif data == kb.CB_SETTINGS:
        status = await _get_status_bar()
        await query.edit_message_text(
            f"⚙️ *Settings*\n\nConfigure your system 👇\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{status}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.settings_menu_keyboard(),
        )

    elif data == kb.CB_TRADING:
        status = await _get_status_bar()
        await query.edit_message_text(
            f"📊 *Trading Management*\n\nManage your positions 👇\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{status}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.trading_menu_keyboard(),
        )

    elif data == kb.CB_HISTORY:
        status = await _get_status_bar()
        await query.edit_message_text(
            f"📈 *History & Performance*\n\nReview your results 👇\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{status}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.history_menu_keyboard(),
        )

    # ──────────── Account Actions ────────────
    elif data == kb.CB_LOGIN:
        await _handle_login(query)

    elif data == kb.CB_LOGOUT:
        await _handle_logout(query)

    elif data == kb.CB_SWITCH_MODE:
        await _handle_switch_mode(query)

    elif data == kb.CB_ACCOUNT_INFO:
        await _handle_account_info(query)

    # ──────────── Settings Actions ────────────
    elif data == kb.CB_SET_LOT:
        await _handle_set_lot_prompt(query, context)

    elif data == kb.CB_SET_MAX_SL:
        await _handle_set_max_sl_prompt(query, context)

    elif data == kb.CB_SET_LIVE_CREDS:
        await _handle_set_creds_prompt(query, context, "live")

    elif data == kb.CB_SET_DEMO_CREDS:
        await _handle_set_creds_prompt(query, context, "demo")

    elif data == kb.CB_VIEW_SETTINGS:
        await _handle_view_settings(query)

    # ──────────── Trading Actions ────────────
    elif data == kb.CB_OPEN_TRADES:
        await _handle_open_trades(query)

    elif data == kb.CB_CLOSE_TG:
        await _handle_close_tg_prompt(query, context)

    elif data == kb.CB_TRADE_HISTORY:
        await _handle_trade_history(query)

    # ──────────── Position-Level Actions ────────────
    elif data == kb.CB_POS_REFRESH:
        await _handle_open_trades(query)

    elif data.startswith(kb.CB_POS_EDIT_SL):
        tg_id = int(data.replace(kb.CB_POS_EDIT_SL, ""))
        context.user_data["awaiting"] = "edit_sl"
        context.user_data["edit_tg_id"] = tg_id
        await query.edit_message_text(
            f"✏️ *Edit SL — TradeGroup #{tg_id}*\n\n"
            f"📝 Send the new SL price (e.g., `3128` or `108 450`):",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data.startswith(kb.CB_POS_EDIT_TP):
        tg_id = int(data.replace(kb.CB_POS_EDIT_TP, ""))
        context.user_data["awaiting"] = "edit_tp"
        context.user_data["edit_tg_id"] = tg_id
        await query.edit_message_text(
            f"🎯 *Edit TP — TradeGroup #{tg_id}*\n\n"
            f"📝 Send the TP level and price like:\n"
            f"`1 3134` (TP1 = 3134)\n"
            f"`2 3140` (TP2 = 3140)\n"
            f"`3 3155` (TP3 = 3155)",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data.startswith(kb.CB_POS_CLOSE):
        tg_id = int(data.replace(kb.CB_POS_CLOSE, ""))
        await _handle_close_position(query, tg_id)

    # ──────────── History Actions ────────────
    elif data == kb.CB_TODAY_PERF:
        await _handle_today_performance(query)

    elif data == kb.CB_ALL_HISTORY:
        await _handle_trade_history(query)


# ══════════════════════════════════════════════
# Dynamic Sub-Menu Headers
# ══════════════════════════════════════════════
async def _show_account_menu(query):
    """Show Account menu with full context: mode, which account, connection status."""
    with get_session() as session:
        settings = crud.get_settings(session)
        mode = settings.account_mode.value.upper()
        mode_emoji = "🔴" if mode == "LIVE" else "🟢"
        connected = settings.is_logged_in
        live_id = settings.live_account_id or "—"
        live_srv = settings.live_account_server or "—"
        demo_id = settings.demo_account_id or "—"
        demo_srv = settings.demo_account_server or "—"

    active_marker_live = " ◀ *ACTIVE*" if mode == "LIVE" else ""
    active_marker_demo = " ◀ *ACTIVE*" if mode == "DEMO" else ""

    text = (
        f"🔐 *Account Management*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{mode_emoji} Current Mode: *{mode}*\n"
        f"MT5: *{'Connected ✅' if connected else 'Disconnected ❌'}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔴 *Live Account*{active_marker_live}\n"
        f"   ID: `{live_id}`  |  Server: `{live_srv}`\n\n"
        f"🟢 *Demo Account*{active_marker_demo}\n"
        f"   ID: `{demo_id}`  |  Server: `{demo_srv}`\n\n"
        f"👇 Choose an action below:"
    )
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.account_menu_keyboard(),
    )


async def _show_execution_menu(query):
    """Show Execution menu with live status."""
    with get_session() as session:
        settings = crud.get_settings(session)
        mode = settings.account_mode.value.upper()
        mode_emoji = "🔴" if mode == "LIVE" else "🟢"
        connected = settings.is_logged_in
        if mode == "LIVE":
            acct_id = settings.live_account_id or "—"
        else:
            acct_id = settings.demo_account_id or "—"

    text = (
        f"⚡ *Execution Control*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{mode_emoji} Mode: *{mode}*  |  Account: `{acct_id}`\n"
        f"MT5: *{'Connected ✅' if connected else 'Disconnected ❌'}*\n"
        f"⚡ Execution: *{'ACTIVE 🟢' if execution else 'PAUSED 🔴'}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    if not connected:
        text += "⚠️ *Login to MT5 first before starting execution!*\n\n"
    text += "👇 Choose an action below:"

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.execution_menu_keyboard(),
    )


# ══════════════════════════════════════════════
# Account Handlers
# ══════════════════════════════════════════════
async def _handle_login(query):
    with get_session() as session:
        settings = crud.get_settings(session)
        if settings.is_logged_in:
            await query.edit_message_text(
                msg.ALREADY_LOGGED_IN,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb.account_menu_keyboard(),
            )
            return

        creds = crud.get_active_credentials(session)
        mode = settings.account_mode.value.upper()

    if not creds["login"] or not creds["password"] or not creds["server"]:
        await query.edit_message_text(
            "❌ *No credentials configured!*\n\n"
            f"Please set your *{mode}* account credentials first.\n"
            "Go to ⚙️ *Settings* → Account Creds",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.account_menu_keyboard(),
        )
        return

    await query.edit_message_text(
        f"🔄 *Connecting to MT5...*\n\n"
        f"📊 Mode: *{mode}*\n"
        f"🌐 Server: `{creds['server']}`\n\n"
        f"⏳ Please wait...",
        parse_mode=ParseMode.MARKDOWN,
    )

    success = await _mt5_connector.login(
        account_id=creds["login"],
        password=creds["password"],
        server=creds["server"],
    )

    if success:
        account_info = await _mt5_connector.get_account_info()
        balance = account_info.get("balance", 0) if account_info else 0
        
        # Check if AutoTrading is enabled
        autotrading_enabled = await _mt5_connector.check_autotrading()

        with get_session() as session:
            crud.update_settings(session, is_logged_in=True)
            crud.add_execution_log(session, "LOGIN", f"Connected to {mode} account")

        login_message = msg.LOGIN_SUCCESS.format(
            account_id=creds["login"],
            server=creds["server"],
            balance=f"${balance:.2f}",
            mode=mode,
        )
        
        # Append warning if AutoTrading is disabled
        if not autotrading_enabled:
            login_message += (
                "\n\n⚠️ *WARNING: AutoTrading is DISABLED!*\n\n"
                "👉 Click the 'AutoTrading' button in your MT5 toolbar (or press Ctrl+E).\n"
                "   It must be *GREEN* ✅ for trades to execute!\n\n"
                "Also check: Tools → Options → Expert Advisors → 'Allow Algo Trading' ☑️"
            )

        await query.edit_message_text(
            login_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.account_menu_keyboard(),
        )
    else:
        await query.edit_message_text(
            msg.LOGIN_FAILED,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.account_menu_keyboard(),
        )


async def _handle_logout(query):
    with get_session() as session:
        settings = crud.get_settings(session)
        if not settings.is_logged_in:
            await query.edit_message_text(
                msg.NOT_LOGGED_IN,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb.account_menu_keyboard(),
            )
            return

    await _mt5_connector.logout()

    with get_session() as session:
        crud.update_settings(session, is_logged_in=False)
        crud.add_execution_log(session, "LOGOUT", "Disconnected from MT5")

    await query.edit_message_text(
        msg.LOGOUT_SUCCESS,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.account_menu_keyboard(),
    )


async def _handle_switch_mode(query):
    with get_session() as session:
        settings = crud.get_settings(session)
        new_mode = AccountMode.LIVE if settings.account_mode == AccountMode.DEMO else AccountMode.DEMO
        crud.update_settings(session, account_mode=new_mode, is_logged_in=False)

        if new_mode == AccountMode.LIVE:
            emoji = "🔴"
            mode_msg = "LIVE trading — real money is on the line!"
        else:
            emoji = "🟢"
            mode_msg = "DEMO mode — practice makes perfect!"

    if _mt5_connector.is_connected:
        await _mt5_connector.logout()

    await query.edit_message_text(
        msg.MODE_SWITCHED.format(
            mode=new_mode.value.upper(),
            emoji=emoji,
            message=mode_msg,
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.account_menu_keyboard(),
    )


async def _handle_account_info(query):
    if not _mt5_connector.is_connected:
        await query.edit_message_text(
            msg.NOT_LOGGED_IN,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.account_menu_keyboard(),
        )
        return

    info = await _mt5_connector.get_account_info()
    if info:
        await query.edit_message_text(
            msg.ACCOUNT_INFO.format(
                name=info.get("name", "N/A"),
                login=info.get("login", "N/A"),
                server=info.get("server", "N/A"),
                balance=f"{info.get('balance', 0):.2f}",
                equity=f"{info.get('equity', 0):.2f}",
                profit=f"{info.get('profit', 0):.2f}",
                margin=f"{info.get('margin', 0):.2f}",
                free_margin=f"{info.get('margin_free', 0):.2f}",
                leverage=info.get("leverage", 0),
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.account_menu_keyboard(),
        )
    else:
        await query.edit_message_text(
            "❌ Could not retrieve account info.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.account_menu_keyboard(),
        )


# ══════════════════════════════════════════════
# Settings Handlers
# ══════════════════════════════════════════════
async def _handle_set_lot_prompt(query, context):
    with get_session() as session:
        settings = crud.get_settings(session)
        current = settings.lot_size

    context.user_data["awaiting"] = "lot_size"
    await query.edit_message_text(
        msg.LOT_SIZE_PROMPT.format(current=current),
        parse_mode=ParseMode.MARKDOWN,
    )


async def _handle_set_max_sl_prompt(query, context):
    with get_session() as session:
        settings = crud.get_settings(session)
        current = settings.max_daily_stop_loss

    context.user_data["awaiting"] = "max_daily_sl"
    await query.edit_message_text(
        msg.MAX_DAILY_SL_PROMPT.format(current=f"{current:.2f}"),
        parse_mode=ParseMode.MARKDOWN,
    )


async def _handle_set_creds_prompt(query, context, mode: str):
    context.user_data["awaiting"] = f"{mode}_creds"
    prompt = msg.LIVE_CREDS_PROMPT if mode == "live" else msg.DEMO_CREDS_PROMPT
    await query.edit_message_text(prompt, parse_mode=ParseMode.MARKDOWN)


async def _handle_view_settings(query):
    with get_session() as session:
        settings = crud.get_settings(session)
        lot_size = settings.lot_size
        max_daily_sl = f"{settings.max_daily_stop_loss:.2f}"
        mode = settings.account_mode.value.upper()
        login_status = "Connected ✅" if settings.is_logged_in else "Disconnected ❌"

    try:
        await query.edit_message_text(
            msg.SETTINGS_VIEW.format(
                lot_size=lot_size,
                max_daily_sl=max_daily_sl,
                mode=mode,
                login_status=login_status,
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.settings_menu_keyboard(),
        )
    except Exception as e:
        # Ignore "Message is not modified" errors
        if "Message is not modified" not in str(e):
            raise


# ══════════════════════════════════════════════
# Trading Handlers
# ══════════════════════════════════════════════
async def _handle_open_trades(query):
    with get_session() as session:
        open_tgs = crud.get_open_trade_groups(session)
        tg_data_list = []
        for tg in open_tgs:
            tg_data_list.append({
                "id": tg.id,
                "symbol": tg.symbol,
                "side": tg.side,
                "entry_price": tg.entry_price,
                "sl": tg.sl,
                "tp1": tg.tp1,
                "tp2": tg.tp2,
                "tp3": tg.tp3,
                "t1_status": tg.t1_status.value if tg.t1_status else "open",
                "t2_status": tg.t2_status.value if tg.t2_status else "open",
                "t3_status": tg.t3_status.value if tg.t3_status else "open",
                "t1_ticket": tg.t1_ticket,
                "t2_ticket": tg.t2_ticket,
                "t3_ticket": tg.t3_ticket,
                "created_at": tg.created_at.strftime("%H:%M %d/%m") if tg.created_at else "N/A",
            })

    if not tg_data_list:
        await query.edit_message_text(
            msg.NO_OPEN_TRADES,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.trading_menu_keyboard(),
        )
        return

    # Fetch live P&L from MT5 for each position
    for tg_data in tg_data_list:
        tg_data["positions"] = []
        for label, ticket_key, status_key, tp_key in [
            ("T1", "t1_ticket", "t1_status", "tp1"),
            ("T2", "t2_ticket", "t2_status", "tp2"),
            ("T3", "t3_ticket", "t3_status", "tp3"),
        ]:
            ticket = tg_data[ticket_key]
            status = tg_data[status_key]
            if ticket and status == "open":
                pos = await _mt5_connector.get_position(ticket) if _mt5_connector and _mt5_connector.is_connected else None
                profit = pos.get("profit", 0.0) if pos else 0.0
                current_sl = pos.get("sl", tg_data["sl"]) if pos else tg_data["sl"]
                current_tp = pos.get("tp", tg_data[tp_key]) if pos else tg_data[tp_key]
                tg_data["positions"].append({
                    "label": label,
                    "ticket": ticket,
                    "profit": profit,
                    "sl": current_sl,
                    "tp": current_tp,
                })

    groups_text = ""
    for tg_data in tg_data_list:
        t1_icon = msg.status_icon(tg_data["t1_status"])
        t2_icon = msg.status_icon(tg_data["t2_status"])
        t3_icon = msg.status_icon(tg_data["t3_status"])

        # Calculate total P&L for open positions
        total_pnl = sum(p["profit"] for p in tg_data["positions"])
        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"

        groups_text += (
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🔹 *TradeGroup #{tg_data['id']}*\n"
            f"📊 {tg_data['symbol']} | {tg_data['side']}\n"
            f"📍 Entry: `{tg_data['entry_price'] or 'Pending'}`\n"
            f"🛡️ SL: `{tg_data['sl'] or 'Pending'}`\n"
            f"🥇 TP1: `{tg_data['tp1'] or 'Pending'}` {t1_icon}\n"
            f"🥈 TP2: `{tg_data['tp2'] or 'Pending'}` {t2_icon}\n"
            f"🏆 TP3: `{tg_data['tp3'] or 'Pending'}` {t3_icon}\n"
            f"{pnl_emoji} P&L: `${total_pnl:+.2f}`\n"
            f"⏱️ Opened: {tg_data['created_at']}\n"
        )

        # Per-position details
        for p in tg_data["positions"]:
            p_emoji = "🟢" if p["profit"] >= 0 else "🔴"
            groups_text += (
                f"  ├ {p['label']} #{p['ticket']} | "
                f"{p_emoji} `${p['profit']:+.2f}` | "
                f"SL:`{p['sl']}` TP:`{p['tp']}`\n"
            )

    await query.edit_message_text(
        f"📊 *Open TradeGroups ({len(tg_data_list)})*\n\n"
        f"{groups_text}\n"
        f"💎 Stay focused, the targets are in sight!",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.open_positions_keyboard(tg_data_list),
    )


async def _handle_close_position(query, tg_id: int):
    """Close all open positions in a TradeGroup via MT5."""
    with get_session() as session:
        tg = crud.get_trade_group(session, tg_id)
        if not tg:
            await query.edit_message_text(
                f"❌ TradeGroup #{tg_id} not found.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb.trading_menu_keyboard(),
            )
            return
        symbol = tg.symbol

    await _trade_executor.handle_close_at_entry(tg_id)

    await query.edit_message_text(
        f"✅ *TradeGroup #{tg_id} — All positions closed!*\n\n"
        f"📊 {symbol} — sealed.\n\n"
        f"💪 Well played! On to the next! 🚀",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.trading_menu_keyboard(),
    )


async def _handle_close_tg_prompt(query, context):
    context.user_data["awaiting"] = "close_tg"
    await query.edit_message_text(
        msg.CLOSE_TG_PROMPT,
        parse_mode=ParseMode.MARKDOWN,
    )


async def _handle_trade_history(query):
    with get_session() as session:
        trades = crud.get_recent_trades(session, limit=15)
        trade_rows = []
        for t in trades:
            trade_rows.append({
                "tg_id": t.trade_group_id or "?",
                "symbol": t.symbol,
                "side": t.side,
                "label": t.position_label,
                "profit": f"{t.profit:.2f}" if t.profit else "0.00",
                "status": t.status.value if t.status else "open",
            })

    if not trade_rows:
        await query.edit_message_text(
            "📭 *No trade history yet.*\n\nStart trading to see results here! 🚀",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.history_menu_keyboard(),
        )
        return

    text = msg.TRADE_HISTORY_HEADER.format(count=len(trade_rows))
    for t in trade_rows:
        status_icon = msg.status_icon(t["status"])
        text += msg.TRADE_HISTORY_ROW.format(
            tg_id=t["tg_id"],
            symbol=t["symbol"],
            side=t["side"],
            label=t["label"],
            profit=t["profit"],
            status_icon=status_icon,
        )

    try:
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.history_menu_keyboard(),
        )
    except Exception as e:
        # Ignore "Message is not modified" errors (content unchanged)
        if "Message is not modified" not in str(e):
            logger.error(f"Error editing trade history message: {e}")


# ══════════════════════════════════════════════
# History Handlers
# ══════════════════════════════════════════════
async def _handle_today_performance(query):
    with get_session() as session:
        pnl = crud.get_today_pnl(session)
        total_pnl = pnl.total_pnl
        trade_count = pnl.trade_count
        win_count = pnl.win_count
        loss_count = pnl.loss_count

    winrate = 0
    if trade_count > 0:
        winrate = round((win_count / trade_count) * 100, 1)

    if total_pnl > 50:
        verdict = msg.PERFORMANCE_GREAT
    elif total_pnl > 0:
        verdict = msg.PERFORMANCE_GOOD
    elif total_pnl == 0:
        verdict = msg.PERFORMANCE_NEUTRAL
    else:
        verdict = msg.PERFORMANCE_LOSS

    try:
        await query.edit_message_text(
            msg.DAILY_PERFORMANCE.format(
                pnl=f"{total_pnl:.2f}",
                count=trade_count,
                wins=win_count,
                losses=loss_count,
                winrate=winrate,
                verdict=verdict,
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.history_menu_keyboard(),
        )
    except Exception as e:
        # Ignore "Message is not modified" errors (content unchanged)
        if "Message is not modified" not in str(e):
            logger.error(f"Error editing performance message: {e}")


# ══════════════════════════════════════════════
# Text Message Handler (for settings input)
# ══════════════════════════════════════════════
async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return

    awaiting = context.user_data.get("awaiting")
    if not awaiting:
        return

    text = update.message.text.strip()

    # ── Lot Size ──
    if awaiting == "lot_size":
        try:
            lot = float(text)
            if lot <= 0 or lot > 100:
                raise ValueError("Invalid lot size")
            with get_session() as session:
                crud.update_settings(session, lot_size=lot)
            await update.message.reply_text(
                msg.LOT_SIZE_SET.format(lot_size=lot),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb.settings_menu_keyboard(),
            )
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid lot size! Please enter a number like `0.01` or `0.1`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        context.user_data.pop("awaiting", None)

    # ── Max Daily Stop Loss ──
    elif awaiting == "max_daily_sl":
        try:
            max_sl = float(text)
            if max_sl <= 0:
                raise ValueError("Must be positive")
            with get_session() as session:
                crud.update_settings(session, max_daily_stop_loss=max_sl)
            await update.message.reply_text(
                msg.MAX_DAILY_SL_SET.format(max_daily_sl=f"{max_sl:.2f}"),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb.settings_menu_keyboard(),
            )
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid amount! Please enter a positive number like `50` or `100`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        context.user_data.pop("awaiting", None)

    # ── Live / Demo Credentials ──
    elif awaiting in ("live_creds", "demo_creds"):
        lines = text.strip().split("\n")
        if len(lines) != 3:
            await update.message.reply_text(
                msg.CREDS_INVALID,
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        account_id = lines[0].strip()
        password = lines[1].strip()
        server = lines[2].strip()

        mode = "live" if awaiting == "live_creds" else "demo"
        with get_session() as session:
            if mode == "live":
                crud.update_settings(
                    session,
                    live_account_id=account_id,
                    live_account_pass=password,
                    live_account_server=server,
                )
            else:
                crud.update_settings(
                    session,
                    demo_account_id=account_id,
                    demo_account_pass=password,
                    demo_account_server=server,
                )

        await update.message.reply_text(
            msg.CREDS_UPDATED.format(
                mode=mode.upper(),
                account_id=account_id,
                server=server,
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.settings_menu_keyboard(),
        )
        context.user_data.pop("awaiting", None)

    # ── Close TradeGroup ──
    elif awaiting == "close_tg":
        try:
            tg_id = int(text)
        except ValueError:
            await update.message.reply_text(
                "❌ Please send a valid TradeGroup ID number!",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        with get_session() as session:
            tg = crud.get_trade_group(session, tg_id)
            if not tg or tg.status.value == "closed":
                await update.message.reply_text(
                    msg.CLOSE_TG_NOT_FOUND,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb.trading_menu_keyboard(),
                )
                context.user_data.pop("awaiting", None)
                return
            symbol = tg.symbol

        await _trade_executor.handle_close_at_entry(tg_id)

        await update.message.reply_text(
            msg.CLOSE_TG_SUCCESS.format(tg_id=tg_id, symbol=symbol),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.trading_menu_keyboard(),
        )
        context.user_data.pop("awaiting", None)

    # ── Edit SL (from Open Positions) ──
    elif awaiting == "edit_sl":
        tg_id = context.user_data.get("edit_tg_id")
        if not tg_id:
            context.user_data.pop("awaiting", None)
            return
        try:
            new_sl = float(text.replace(" ", "").replace(",", "."))
            if new_sl <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid price! Send a number like `3128` or `108 450`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        await _trade_executor.handle_modify_sl(tg_id, new_sl)
        await update.message.reply_text(
            f"✅ *SL Updated — TradeGroup #{tg_id}*\n\n"
            f"🛡️ New SL: `{new_sl}`\n\n"
            f"🔒 All open positions updated!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.trading_menu_keyboard(),
        )
        context.user_data.pop("awaiting", None)
        context.user_data.pop("edit_tg_id", None)

    # ── Edit TP (from Open Positions) ──
    elif awaiting == "edit_tp":
        tg_id = context.user_data.get("edit_tg_id")
        if not tg_id:
            context.user_data.pop("awaiting", None)
            return
        try:
            parts = text.strip().split()
            if len(parts) != 2:
                raise ValueError("Expected: level price")
            tp_level = int(parts[0])
            if tp_level not in (1, 2, 3):
                raise ValueError("TP level must be 1, 2 or 3")
            new_tp = float(parts[1].replace(",", "."))
            if new_tp <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid format! Send like: `1 3134` or `2 3140`\n"
                "(first number = TP level, second = price)",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        await _trade_executor.handle_modify_tp(tg_id, tp_level, new_tp)
        await update.message.reply_text(
            f"✅ *TP{tp_level} Updated — TradeGroup #{tg_id}*\n\n"
            f"🎯 New TP{tp_level}: `{new_tp}`\n\n"
            f"🔒 Position updated on MT5!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.trading_menu_keyboard(),
        )
        context.user_data.pop("awaiting", None)
        context.user_data.pop("edit_tg_id", None)
