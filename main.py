"""
MT5 Private Execution System — Main Entry Point

Starts all components concurrently:
  1. Signal Listener (Telethon) — listens for trading signals
  2. Telegram Management Bot — admin control interface
  3. Position Monitor — watches for TP/SL hits on MT5
"""

import asyncio
import logging
import sys

import config
from database.engine import init_db
from execution.mt5_connector import MT5Connector
from execution.trade_executor import TradeExecutor
from listener.signal_listener import SignalListener
from telegram_bot.bot import ManagementBot

# ──────────────────────────────────────────────
# Logging Configuration
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-18s │ %(levelname)-7s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("copytrading.log", encoding="utf-8"),
    ],
)
# Silence noisy third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telethon").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

logger = logging.getLogger("Main")


async def main():
    logger.info("=" * 60)
    logger.info("  🚀 MT5 PRIVATE EXECUTION SYSTEM — STARTING UP")
    logger.info("=" * 60)

    # ── Step 1: Initialize Database ──
    logger.info("📦 Initializing database...")
    init_db()
    logger.info("✅ Database ready")

    # ── Step 2: Create Components ──
    mt5 = MT5Connector()
    # Note: MT5 will initialize when user clicks Login in Telegram bot
    # await mt5.initialize()

    # Create the management bot first (for notifications)
    bot = ManagementBot(mt5, trade_executor=None)

    # Create trade executor with notification callback
    executor = TradeExecutor(mt5, notify_callback=bot.send_notification)

    # Wire executor into bot
    bot.executor = executor
    from telegram_bot.handlers import set_components
    set_components(mt5, executor)

    # Create signal listener
    listener = SignalListener(executor)

    logger.info("✅ All components initialized")

    # ── Step 3: Start All Services ──
    tasks = []

    # Start Telegram Management Bot
    try:
        await bot.start()
        logger.info("✅ Telegram Management Bot started")
    except Exception as e:
        logger.error(f"❌ Failed to start Telegram bot: {e}")
        return

    # Start Position Monitor (background task)
    monitor_task = asyncio.create_task(
        executor.monitor_positions(interval=config.MONITOR_INTERVAL)
    )
    tasks.append(monitor_task)
    logger.info("✅ Position Monitor started")

    # Start Signal Listener (this blocks until disconnected)
    logger.info("📡 Starting Signal Listener...")
    try:
        listener_task = asyncio.create_task(listener.start())
        tasks.append(listener_task)
        logger.info("✅ Signal Listener started")
    except Exception as e:
        logger.error(f"❌ Failed to start Signal Listener: {e}")

    logger.info("=" * 60)
    logger.info("  ✅ ALL SYSTEMS GO — RUNNING")
    logger.info("=" * 60)

    # ── Step 4: Keep Running ──
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("🛑 Shutdown signal received")
    except KeyboardInterrupt:
        logger.info("🛑 Keyboard interrupt received")
    finally:
        # Cleanup
        logger.info("🧹 Cleaning up...")
        executor.stop_monitor()
        await listener.stop()
        await bot.stop()
        await mt5.logout()
        logger.info("👋 System shutdown complete. Goodbye!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Goodbye!")
