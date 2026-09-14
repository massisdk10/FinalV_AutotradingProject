from datetime import datetime, date
from typing import Optional, List
from sqlalchemy.orm import Session
from database.models import (
    Settings, TradeGroup, TradeHistory, ExecutionLog, DailyPnL,
    AccountMode, TradeGroupStatus, PositionStatus
)


# ──────────────────────────────────────────────
# Settings CRUD
# ──────────────────────────────────────────────
def get_settings(session: Session) -> Settings:
    settings = session.query(Settings).first()
    if not settings:
        settings = Settings(id=1)
        session.add(settings)
        session.flush()
    return settings


def update_settings(session: Session, **kwargs) -> Settings:
    settings = get_settings(session)
    for key, value in kwargs.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    session.flush()
    return settings


def get_active_credentials(session: Session) -> dict:
    settings = get_settings(session)
    if settings.account_mode == AccountMode.LIVE:
        return {
            "login": settings.live_account_id,
            "password": settings.live_account_pass,
            "server": settings.live_account_server,
        }
    return {
        "login": settings.demo_account_id,
        "password": settings.demo_account_pass,
        "server": settings.demo_account_server,
    }


# ──────────────────────────────────────────────
# TradeGroup CRUD
# ──────────────────────────────────────────────
def create_trade_group(
    session: Session,
    now_message_id: int,
    symbol: str,
    side: str,
) -> TradeGroup:
    tg = TradeGroup(
        now_message_id=now_message_id,
        symbol=symbol.upper(),
        side=side.upper(),
        status=TradeGroupStatus.PENDING,
    )
    session.add(tg)
    session.flush()
    return tg


def get_trade_group(session: Session, tg_id: int) -> Optional[TradeGroup]:
    return session.query(TradeGroup).filter(TradeGroup.id == tg_id).first()


def get_latest_pending_trade_group(session: Session) -> Optional[TradeGroup]:
    return (
        session.query(TradeGroup)
        .filter(TradeGroup.status == TradeGroupStatus.PENDING)
        .order_by(TradeGroup.created_at.desc())
        .first()
    )


def get_trade_group_by_details_msg(session: Session, details_msg_id: int) -> Optional[TradeGroup]:
    return (
        session.query(TradeGroup)
        .filter(TradeGroup.details_message_id == details_msg_id)
        .first()
    )


def get_trade_group_by_signal_msg(session: Session, signal_msg_id: int) -> Optional[TradeGroup]:
    """
    Find TradeGroup by signal message ID.
    Searches both now_message_id AND details_message_id because:
    - NOW-triggered trades: now_message_id=NOW, details_message_id=SIGNAL_FULL
    - Non-NOW trades: both fields have the same message ID
    - Replies always reference the SIGNAL_FULL message
    """
    return (
        session.query(TradeGroup)
        .filter(
            (TradeGroup.now_message_id == signal_msg_id) |
            (TradeGroup.details_message_id == signal_msg_id)
        )
        .first()
    )


def get_open_trade_groups(session: Session) -> List[TradeGroup]:
    """
    Get trade groups that should be monitored for TP/SL hits.
    
    Excludes PENDING (LIMIT orders not yet filled) to avoid false alarms.
    Includes PENDING_DETAILS (NOW-triggered trades awaiting full signal update).
    """
    return (
        session.query(TradeGroup)
        .filter(TradeGroup.status.in_([
            TradeGroupStatus.PENDING_DETAILS,  # NOW-triggered, positions open, awaiting update
            TradeGroupStatus.ACTIVE,            # Full trades with SL/TP set
            TradeGroupStatus.PARTIAL,           # Some positions closed
        ]))
        .order_by(TradeGroup.created_at.desc())
        .all()
    )


def get_all_trade_groups(session: Session, limit: int = 50) -> List[TradeGroup]:
    return (
        session.query(TradeGroup)
        .order_by(TradeGroup.created_at.desc())
        .limit(limit)
        .all()
    )


def update_trade_group(session: Session, tg_id: int, **kwargs) -> Optional[TradeGroup]:
    tg = get_trade_group(session, tg_id)
    if tg:
        for key, value in kwargs.items():
            if hasattr(tg, key):
                setattr(tg, key, value)
        tg.updated_at = datetime.utcnow()
        session.flush()
    return tg


def close_trade_group(session: Session, tg_id: int) -> Optional[TradeGroup]:
    return update_trade_group(session, tg_id, status=TradeGroupStatus.CLOSED)


# ──────────────────────────────────────────────
# Trade History CRUD
# ──────────────────────────────────────────────
def create_trade_history(
    session: Session,
    trade_group_id: int,
    position_label: str,
    symbol: str,
    side: str,
    lot_size: float,
    ticket: int = None,
    open_price: float = None,
    sl: float = None,
    tp: float = None,
) -> TradeHistory:
    trade = TradeHistory(
        trade_group_id=trade_group_id,
        position_label=position_label,
        symbol=symbol,
        side=side,
        lot_size=lot_size,
        ticket=ticket,
        open_price=open_price,
        sl=sl,
        tp=tp,
        status=PositionStatus.OPEN,
    )
    session.add(trade)
    session.flush()
    return trade


def update_trade_history(session: Session, ticket: int, **kwargs) -> Optional[TradeHistory]:
    trade = session.query(TradeHistory).filter(TradeHistory.ticket == ticket).first()
    if trade:
        for key, value in kwargs.items():
            if hasattr(trade, key):
                setattr(trade, key, value)
        session.flush()
    return trade


def get_trades_by_group(session: Session, tg_id: int) -> List[TradeHistory]:
    return session.query(TradeHistory).filter(TradeHistory.trade_group_id == tg_id).all()


def get_recent_trades(session: Session, limit: int = 20) -> List[TradeHistory]:
    return (
        session.query(TradeHistory)
        .order_by(TradeHistory.opened_at.desc())
        .limit(limit)
        .all()
    )


# ──────────────────────────────────────────────
# Execution Logs
# ──────────────────────────────────────────────
def add_execution_log(
    session: Session,
    action: str,
    details: str = "",
    trade_group_id: int = None,
) -> ExecutionLog:
    log = ExecutionLog(
        trade_group_id=trade_group_id,
        action=action,
        details=details,
    )
    session.add(log)
    session.flush()
    return log


def get_execution_logs(session: Session, limit: int = 50) -> List[ExecutionLog]:
    return (
        session.query(ExecutionLog)
        .order_by(ExecutionLog.timestamp.desc())
        .limit(limit)
        .all()
    )


# ──────────────────────────────────────────────
# Daily P&L
# ──────────────────────────────────────────────
def get_today_pnl(session: Session) -> DailyPnL:
    today = date.today()
    pnl = session.query(DailyPnL).filter(DailyPnL.date == today).first()
    if not pnl:
        pnl = DailyPnL(date=today)
        session.add(pnl)
        session.flush()
    return pnl


def update_daily_pnl(session: Session, profit: float, is_win: bool):
    pnl = get_today_pnl(session)
    pnl.total_pnl += profit
    pnl.trade_count += 1
    if is_win:
        pnl.win_count += 1
    else:
        pnl.loss_count += 1
    session.flush()
    return pnl


def check_daily_stop_loss(session: Session) -> bool:
    """Returns True if daily stop loss has been breached."""
    settings = get_settings(session)
    pnl = get_today_pnl(session)
    if pnl.total_pnl < 0 and abs(pnl.total_pnl) >= settings.max_daily_stop_loss:
        return True
    return False
