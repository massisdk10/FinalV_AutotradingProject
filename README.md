# 🚀 CopyTrading — MT5 Private Execution System

A deterministic, private, single-user MT5 execution system that automates trade execution based on structured Telegram signals.

---

## 📋 Features

- **Signal Listener** (Telethon) — Real-time event-driven message listener
- **Execution Engine** (MT5) — Opens 3 positions per TradeGroup with automatic SL/TP management
- **Telegram Bot** — Full menu-driven control system with friendly, creative messages
- **PostgreSQL Database** — Complete trade history, settings, execution logs
- **Position Monitor** — Continuous reconciliation with broker state

---

## 🏗️ Architecture

```
Signal Channel (Telegram)
        │
        ▼
┌──────────────────┐
│  Signal Listener  │  ← Telethon (user session)
│  (message_parser) │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐     ┌──────────────┐
│  Trade Executor   │────▶│  MT5 Terminal │
│  (execution logic)│     └──────────────┘
└────────┬─────────┘
         │
         ▼
┌──────────────────┐     ┌──────────────┐
│    Database       │     │  Telegram Bot │ ← Admin control
│  (PostgreSQL)     │     │  (management) │
└──────────────────┘     └──────────────┘
```

---

## ⚡ Execution Strategy

| Step | Event | Action |
|------|-------|--------|
| 1 | **NOW** signal | Open 3 market positions (T1, T2, T3) |
| 2 | **DETAILS** | Apply SL/TP to all positions |
| 3 | **TP1 hit** (broker) | Move SL of T2 & T3 to breakeven |
| 4 | **TP2 hit** (broker) | Move SL of T3 to midpoint |
| 5 | **TP3 hit** | Close final position — TradeGroup complete |
| 6 | **Manual reply** | Move SL to BE / Close at entry / TP3 manual |

---

## 🛠️ Setup

### 1. Prerequisites

- Python 3.10+
- PostgreSQL database
- MetaTrader 5 terminal installed
- Telegram account + Bot token
- Telegram API credentials (api_id, api_hash)

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Required values:
- `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` — from https://my.telegram.org
- `TELEGRAM_BOT_TOKEN` — from @BotFather
- `TELEGRAM_ADMIN_ID` — your Telegram user ID
- `SIGNAL_CHANNEL_ID` — the source signal channel
- `DATABASE_URL` — PostgreSQL connection string

### 4. Create Database

```sql
CREATE DATABASE copytrading;
```

Tables are auto-created on first run.

### 5. Run

```bash
python main.py
```

---

## 🎮 Telegram Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message + main menu |
| `/menu` | Open the control panel |
| `/status` | Quick system status overview |

### Menu Structure

- 🔐 **Account Management** — Login, Logout, Switch Demo/Live, Account Info
- ⚡ **Execution Control** — Start/Stop execution, View status
- ⚙️ **Settings** — Lot size, Max daily SL, Account credentials
- 📊 **Open Trades** — View/close TradeGroups
- 📈 **History & Performance** — Daily P&L, trade history

---

## 📁 Project Structure

```
CopyTrading/
├── main.py                    # Entry point
├── config.py                  # Configuration loader
├── requirements.txt           # Dependencies
├── .env.example               # Environment template
│
├── database/
│   ├── __init__.py
│   ├── engine.py              # SQLAlchemy engine & session
│   ├── models.py              # Database models (Settings, TradeGroup, etc.)
│   └── crud.py                # CRUD operations
│
├── execution/
│   ├── __init__.py
│   ├── mt5_connector.py       # MetaTrader 5 interface
│   └── trade_executor.py      # Trade execution logic & position monitor
│
├── listener/
│   ├── __init__.py
│   ├── message_parser.py      # Message classification & parsing
│   └── signal_listener.py     # Telethon event listener
│
└── telegram_bot/
    ├── __init__.py
    ├── bot.py                 # Bot application runner
    ├── handlers.py            # Command & callback handlers
    ├── keyboards.py           # Inline keyboard layouts
    └── messages.py            # Creative bot messages
```

---

## 🗄️ Database Schema

### Settings
| Column | Type | Description |
|--------|------|-------------|
| lot_size | Float | Position size per trade |
| max_daily_stop_loss | Float | Maximum daily loss before auto-pause |
| live_account_id/pass/server | String | Live MT5 credentials |
| demo_account_id/pass/server | String | Demo MT5 credentials |
| account_mode | Enum | DEMO or LIVE |
| execution_enabled | Boolean | Whether execution is active |
| is_logged_in | Boolean | MT5 connection status |

### TradeGroups
Stores each signal group with T1/T2/T3 tickets, SL/TP levels, and status tracking.

### TradeHistory
Individual position records with open/close prices, P&L, and timestamps.

### ExecutionLogs
Full audit trail of every action taken by the system.

### DailyPnL
Daily performance aggregation with win/loss counts.

---

## 🔒 Safety Features

- Execution disabled when logged out
- Daily stop loss auto-pause
- No assumptions — only explicit signals are executed
- One TradeGroup never affects another
- Full audit logging
- Admin-only bot access

---

## 📜 License

Private use only.
