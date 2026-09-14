import enum
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, BigInteger, String, Float, Boolean, DateTime,
    Enum, ForeignKey, Date, Text
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────
class AccountMode(enum.Enum):
    DEMO = "demo"
    LIVE = "live"


class TradeGroupStatus(enum.Enum):
    PENDING = "pending"
    PENDING_DETAILS = "pending_details"
    ACTIVE = "active"
    PARTIAL = "partial"
    CLOSED = "closed"


class PositionStatus(enum.Enum):
    OPEN = "open"
    TP_HIT = "tp_hit"
    SL_HIT = "sl_hit"
    MANUAL_CLOSE = "manual_close"
    CLOSED = "closed"


# ──────────────────────────────────────────────
# Settings
# ──────────────────────────────────────────────
class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, default=1)
    lot_size = Column(Float, default=0.01)
    max_daily_stop_loss = Column(Float, default=100.0)

    # Live Account Credentials
    live_account_id = Column(String, default="")
    live_account_pass = Column(String, default="")
    live_account_server = Column(String, default="")

    # Demo Account Credentials
    demo_account_id = Column(String, default="")
    demo_account_pass = Column(String, default="")
    demo_account_server = Column(String, default="")

    # Runtime State
    account_mode = Column(Enum(AccountMode), default=AccountMode.DEMO)
    is_logged_in = Column(Boolean, default=False)


# ──────────────────────────────────────────────
# Trade Groups
# ──────────────────────────────────────────────
class TradeGroup(Base):
    __tablename__ = "trade_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    now_message_id = Column(Integer, nullable=False)
    details_message_id = Column(Integer, nullable=True)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)
    entry_price = Column(Float, nullable=True)
    sl = Column(Float, nullable=True)
    tp1 = Column(Float, nullable=True)
    tp2 = Column(Float, nullable=True)
    tp3 = Column(Float, nullable=True)

    # MT5 position tickets
    t1_ticket = Column(BigInteger, nullable=True)
    t2_ticket = Column(BigInteger, nullable=True)
    t3_ticket = Column(BigInteger, nullable=True)

    # Position statuses
    t1_status = Column(Enum(PositionStatus), default=PositionStatus.OPEN)
    t2_status = Column(Enum(PositionStatus), default=PositionStatus.OPEN)
    t3_status = Column(Enum(PositionStatus), default=PositionStatus.OPEN)

    # Overall status
    status = Column(Enum(TradeGroupStatus), default=TradeGroupStatus.PENDING)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    trades = relationship("TradeHistory", back_populates="trade_group", cascade="all, delete-orphan")
    logs = relationship("ExecutionLog", back_populates="trade_group", cascade="all, delete-orphan")


# ──────────────────────────────────────────────
# Trade History
# ──────────────────────────────────────────────
class TradeHistory(Base):
    __tablename__ = "trade_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_group_id = Column(Integer, ForeignKey("trade_groups.id"))
    ticket = Column(BigInteger, nullable=True)
    position_label = Column(String)
    symbol = Column(String)
    side = Column(String)
    lot_size = Column(Float)
    open_price = Column(Float, nullable=True)
    close_price = Column(Float, nullable=True)
    sl = Column(Float, nullable=True)
    tp = Column(Float, nullable=True)
    profit = Column(Float, default=0.0)
    status = Column(Enum(PositionStatus), default=PositionStatus.OPEN)
    opened_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

    trade_group = relationship("TradeGroup", back_populates="trades")


# ──────────────────────────────────────────────
# Execution Logs
# ──────────────────────────────────────────────
class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_group_id = Column(Integer, ForeignKey("trade_groups.id"), nullable=True)
    action = Column(String, nullable=False)
    details = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    trade_group = relationship("TradeGroup", back_populates="logs")


# ──────────────────────────────────────────────
# Daily P&L Tracking
# ──────────────────────────────────────────────
class DailyPnL(Base):
    __tablename__ = "daily_pnl"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, unique=True, default=date.today)
    total_pnl = Column(Float, default=0.0)
    trade_count = Column(Integer, default=0)
    win_count = Column(Integer, default=0)
    loss_count = Column(Integer, default=0)
