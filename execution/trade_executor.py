"""
Station X — Trade Executor
==============================
Executes trades on MT5 based on Station X signals.
Handles the full trade lifecycle:
  SIGNAL_FULL → open 3 positions with SL/TP
  TP HIT → manage remaining positions
  BREAKEVEN → move SL to entry
  CLOSE → close all positions
  SL HIT → log stop loss from signal
  MODIFY SL/TP → update levels on open positions
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Callable, Awaitable
import time

from database.engine import get_session
from database.models import TradeGroupStatus, PositionStatus, TradeHistory
from database import crud
from execution.mt5_connector import MT5Connector
import config

logger = logging.getLogger("TradeExecutor")


class TradeExecutor:
    """Orchestrates trade execution logic for Station X signals."""

    def __init__(self, mt5: MT5Connector, notify_callback: Callable[..., Awaitable] = None):
        self.mt5 = mt5
        self._notify = notify_callback
        self._monitoring = False

    async def notify(self, message: str):
        if self._notify:
            try:
                await self._notify(message)
            except Exception as e:
                logger.error(f"Notification error: {e}")

    # ──────────────────────────────────────────
    # Utility Methods
    # ──────────────────────────────────────────
    def _get_default_sl_tp_pips(self, symbol: str) -> dict:
        """Return symbol-specific default SL/TP in pips."""
        if "BTC" in symbol:
            return {
                "sl_pips": config.DEFAULT_BTC_SL_PIPS,
                "tp1_pips": config.DEFAULT_BTC_TP1_PIPS,
                "tp2_pips": config.DEFAULT_BTC_TP2_PIPS,
                "tp3_pips": config.DEFAULT_BTC_TP3_PIPS,
            }
        else:
            # XAUUSD and others use DEFAULT_SL_PIPS from config (200 pips)
            return {
                "sl_pips": config.DEFAULT_SL_PIPS,
                "tp1_pips": config.DEFAULT_TP1_PIPS,
                "tp2_pips": config.DEFAULT_TP2_PIPS,
                "tp3_pips": config.DEFAULT_TP3_PIPS,
            }
    
    def _calculate_pip_value(self, symbol: str) -> float:
        """Return pip value for different instruments."""
        if symbol in ["XAUUSD", "BTCUSD"]:
            return 0.01
        elif symbol in ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD",
                        "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "GBPAUD", "GBPCAD",
                        "GBPCHF", "EURAUD", "EURNZD", "GBPNZD", "AUDNZD", "AUDCAD",
                        "CADJPY", "CHFJPY", "NZDJPY", "NZDCAD"]:
            return 0.0001
        elif symbol in ["NAS100", "US30", "US100", "SP500", "GER40"]:
            return 0.1
        return 0.0001

    def _calculate_sl_from_pips(self, price: float, side: str, pips: float, pip_value: float) -> float:
        """Calculate SL from entry price and pip distance."""
        pip_distance = pips * pip_value
        if side == "BUY":
            return round(price - pip_distance, 5)
        else:  # SELL
            return round(price + pip_distance, 5)
    
    def _calculate_position_profit(self, symbol: str, side: str, open_price: float, close_price: float, lot_size: float) -> float:
        """Calculate profit in USD for a closed position."""
        # Direction multiplier
        direction = 1 if side == "BUY" else -1
        
        # Price difference
        price_diff = close_price - open_price
        
        # Contract size varies by instrument
        if symbol in ["XAUUSD", "BTCUSD", "XAGUSD"]:
            contract_size = 100  # Metals and crypto
        elif symbol in ["NAS100", "US30", "US100", "SP500", "GER40"]:
            contract_size = 1  # Indices (1 point = $1 per contract)
        else:
            contract_size = 100000  # Forex pairs
        
        # Profit = (close - open) * direction * lot_size * contract_size
        profit = price_diff * direction * lot_size * contract_size
        
        return round(profit, 2)
    
    async def _emergency_close_all_positions(
        self,
        tg_id: int,
        t1_ticket: int,
        t2_ticket: int,
        t3_ticket: int,
        reason: str
    ) -> int:
        """
        Emergency close all positions with detailed logging.
        Returns number of positions successfully closed.
        """
        logger.error(f"🚨 EMERGENCY CLOSE TradeGroup #{tg_id}: {reason}")
        
        closed_count = 0
        close_prices = {}
        
        for ticket, label in [(t1_ticket, "T1"), (t2_ticket, "T2"), (t3_ticket, "T3")]:
            if ticket:
                # Get position before closing for price info
                pos = await self.mt5.get_position(ticket)
                if pos:
                    result = await self.mt5.close_position(ticket)
                    if result and result.get("retcode") == 10009:
                        closed_count += 1
                        close_prices[ticket] = result.get("price", 0)
                        logger.info(f"✅ Emergency closed {label} (ticket {ticket})")
                    else:
                        logger.error(f"❌ Failed to emergency close {label} (ticket {ticket})")
        
        # Update database
        with get_session() as session:
            tg = crud.get_trade_group(session, tg_id)
            if tg:
                tg.status = TradeGroupStatus.CLOSED
                tg.t1_status = PositionStatus.CLOSED
                tg.t2_status = PositionStatus.CLOSED
                tg.t3_status = PositionStatus.CLOSED
                
                # Update trade history with close prices
                for ticket, close_price in close_prices.items():
                    if close_price > 0:
                        crud.update_trade_history(
                            session, ticket,
                            status=PositionStatus.CLOSED,
                            close_price=close_price,
                            closed_at=datetime.utcnow()
                        )
                
                crud.add_execution_log(session, "EMERGENCY_CLOSE", reason, tg_id)
        
        await self.notify(
            f"🚨 *EMERGENCY CLOSE — TradeGroup #{tg_id}*\n\n"
            f"**Reason**: {reason}\n"
            f"**Closed**: {closed_count}/3 positions\n\n"
            f"⚠️ Protection activated to prevent major loss"
        )
        
        return closed_count
    
    # ──────────────────────────────────────────
    # Pre-flight Checks
    # ──────────────────────────────────────────
    async def _preflight_check(self) -> tuple[bool, str]:
        """Check if execution is allowed."""
        with get_session() as session:
            settings = crud.get_settings(session)
            if not settings.is_logged_in:
                return False, "🔒 Not logged in to MT5"
            if crud.check_daily_stop_loss(session):
                return False, "🛑 Daily stop loss limit reached"
        
        # Check if AutoTrading is enabled in MT5 terminal
        autotrading_enabled = await self.mt5.check_autotrading()
        if not autotrading_enabled:
            return False, (
                "⚠️ AutoTrading is DISABLED in MT5 terminal!\n\n"
                "👉 Fix: Click the 'AutoTrading' button (or press Ctrl+E) in MT5 toolbar.\n"
                "   It should be GREEN ✅\n\n"
                "Also check: Tools → Options → Expert Advisors → 'Allow Algo Trading' ☑️"
            )
        
        return True, ""

    async def _update_position_with_retry(self, ticket: int, sl: float, tp: Optional[float], max_retries: int = 3) -> bool:
        """
        Update MT5 position with retry logic for transient failures.
        
        Args:
            ticket: Position ticket number
            sl: Stop loss price
            tp: Take profit price (None for no TP)
            max_retries: Maximum number of retry attempts
            
        Returns:
            True if update succeeded, False otherwise
        """
        for attempt in range(max_retries):
            try:
                result = await self.mt5.modify_position(ticket, sl=sl, tp=tp)
                if result and result.get("retcode") == 10009:
                    return True
                
                # MT5 error - retry if we have attempts left
                if attempt < max_retries - 1:
                    logger.debug(f"🔄 Retry {attempt + 1}/{max_retries - 1} for ticket {ticket}")
                    await asyncio.sleep(0.5)  # Brief delay before retry
                else:
                    error_msg = result.get("comment", "Unknown error") if result else "No response"
                    logger.error(f"❌ Failed to update ticket {ticket} after {max_retries} attempts: {error_msg}")
                    
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.debug(f"🔄 Retry {attempt + 1}/{max_retries - 1} for ticket {ticket} (exception: {e})")
                    await asyncio.sleep(0.5)
                else:
                    logger.error(f"❌ Failed to update ticket {ticket} after {max_retries} attempts: {e}")
        
        return False

    # ──────────────────────────────────────────
    # NOW TRIGGER → Immediate Execution with 500-pip SL
    # ──────────────────────────────────────────
    async def handle_now_trigger(
        self,
        message_id: int,
        symbol: str,
        side: str,
        entry_price: float = 0.0,
    ) -> Optional[int]:
        """
        Execute 3 MARKET positions immediately when NOW trigger arrives.
        Uses default 500-pip SL (no TP yet).
        Full signal will arrive later to update SL/TP.
        """
        ok, reason = await self._preflight_check()
        if not ok:
            await self.notify(f"⚠️ Cannot execute NOW signal: {reason}")
            return None

        # Get symbol-specific lot size (fixes BTCUSD "Invalid volume" errors)
        lot_size = config.SYMBOL_LOT_SIZES.get(symbol, None)
        if lot_size is None:
            # Fallback to database settings or default
            with get_session() as session:
                lot_size = crud.get_settings(session).lot_size or config.DEFAULT_LOT_SIZE
            logger.debug(f"Using lot size from DB/default: {lot_size} for {symbol}")
        else:
            logger.debug(f"Using symbol-specific lot size: {lot_size} for {symbol}")

        await self.mt5.ensure_symbol_visible(symbol)

        # Get current market price
        current_price_data = await self.mt5.get_symbol_price(symbol)
        if not current_price_data:
            await self.notify(f"❌ Cannot get price for {symbol}")
            return None

        current_price = current_price_data["ask"] if side == "BUY" else current_price_data["bid"]
        pip_value = self._calculate_pip_value(symbol)
        
        # SAFETY CHECK: Pre-entry price validation (symbol-specific)
        # Don't open if price too far from signal entry (prevents late entries)
        if entry_price > 0:
            pips_from_entry = abs(current_price - entry_price) / pip_value
            
            # Get symbol-specific entry gap limit
            symbol_upper = symbol.upper().replace(".", "")
            if "XAU" in symbol_upper or "GOLD" in symbol_upper:
                max_allowed_gap = config.MAX_ENTRY_GAP_GOLD
            elif "BTC" in symbol_upper:
                max_allowed_gap = config.MAX_ENTRY_GAP_BTC
            else:
                max_allowed_gap = config.MAX_ENTRY_GAP_FOREX
            
            if pips_from_entry > max_allowed_gap:
                logger.error(f"🚨 Price too far from entry! Current {current_price} vs Entry {entry_price} = {pips_from_entry:.1f} pips (max {max_allowed_gap})")
                await self.notify(
                    f"🚨 *SKIPPED NOW SIGNAL*\n\n"
                    f"Price moved {pips_from_entry:.1f} pips from entry\n"
                    f"Max allowed: {max_allowed_gap:.0f} pips\n"
                    f"Current: {current_price:.2f}\n"
                    f"Signal Entry: {entry_price:.2f}\n\n"
                    f"⚠️ Too late to enter - protecting capital"
                )
                return None
        
        # Get symbol-specific default SL/TP
        defaults = self._get_default_sl_tp_pips(symbol)
        default_sl = self._calculate_sl_from_pips(current_price, side, defaults["sl_pips"], pip_value)

        logger.info(f"⚡ NOW EXECUTION: {symbol} {side} | Market: {current_price} | {defaults['sl_pips']:.0f}-pip SL: {default_sl}")

        # Open 3 MARKET positions with default SL, no TP
        tickets = []
        errors = []
        targets = [("T1", 0.0), ("T2", 0.0), ("T3", 0.0)]

        for label, _ in targets:
            result = await self.mt5.open_position(
                symbol=symbol,
                side=side,
                lot_size=lot_size,
                comment=f"STX-NOW-{label}",
            )

            if result and result.get("retcode") == 10009:
                ticket = result.get("order", 0)
                price = result.get("price", current_price)
                tickets.append((label, ticket, price))
                logger.info(f"✅ {label} MARKET NOW: ticket={ticket}, price={price}")
            else:
                error_msg = result.get("comment", "Unknown error") if result else "No response"
                errors.append((label, error_msg))
                logger.error(f"❌ Failed MARKET NOW {label}: {error_msg}")

        if not tickets:
            # All positions failed
            if errors and all(err[1] == errors[0][1] for err in errors):
                common_error = errors[0][1]
                fix_msg = ""
                if "AutoTrading disabled" in common_error:
                    fix_msg = (
                        "\n\n👉 **Fix:** Enable AutoTrading in MT5\n"
                        "   1. Click the 'AutoTrading' button in MT5 toolbar (or press Ctrl+E)\n"
                        "   2. It must be **GREEN** ✅\n"
                        "   3. Also check: Tools → Options → Expert Advisors → 'Allow Algo Trading' ☑️"
                    )
                await self.notify(
                    f"💥 *All 3 NOW positions failed for {symbol} {side}!*\n\n"
                    f"Reason: `{common_error}`{fix_msg}"
                )
            return None

        # Apply default SL to all positions
        sl_ok = 0
        for label, ticket, price in tickets:
            result = await self.mt5.modify_position(ticket, sl=default_sl)
            if result and result.get("retcode") == 10009:
                sl_ok += 1
                logger.info(f"🛡️ {label} default SL set to {default_sl}")

        # Fetch actual execution data from MT5 for each position
        execution_data = {}
        for label, ticket, price in tickets:
            pos = await self.mt5.get_position(ticket)
            if pos:
                execution_data[ticket] = {
                    "open_price": pos.get("price_open", price),
                    "volume": pos.get("volume", lot_size)
                }
                logger.debug(f"✅ Fetched execution data for {label}: price={pos.get('price_open')}, volume={pos.get('volume')}")
            else:
                # Fallback to order result if position not found
                execution_data[ticket] = {
                    "open_price": price,
                    "volume": lot_size
                }

        # Save to database with PENDING_DETAILS status
        with get_session() as session:
            tg = crud.create_trade_group(session, message_id, symbol, side)
            tg_id = tg.id
            tg.entry_price = current_price
            tg.sl = default_sl
            tg.tp1 = 0.0
            tg.tp2 = 0.0
            tg.tp3 = 0.0
            tg.status = TradeGroupStatus.PENDING_DETAILS

            for label, ticket, price in tickets:
                if label == "T1":
                    tg.t1_ticket = ticket
                elif label == "T2":
                    tg.t2_ticket = ticket
                elif label == "T3":
                    tg.t3_ticket = ticket

                # Use actual execution data from MT5
                exec_data = execution_data.get(ticket, {"open_price": price, "volume": lot_size})
                crud.create_trade_history(
                    session,
                    trade_group_id=tg_id,
                    position_label=label,
                    symbol=symbol,
                    side=side,
                    lot_size=exec_data["volume"],
                    ticket=ticket,
                    open_price=exec_data["open_price"],
                    sl=default_sl,
                    tp=None,
                )

            crud.add_execution_log(
                session,
                action="MARKET_NOW",
                details=f"Opened {len(tickets)} positions with {defaults['sl_pips']:.0f}-pip SL",
                trade_group_id=tg_id,
            )

        await self.notify(
            f"⚡ *NOW EXECUTION — TradeGroup #{tg_id}!* 🔥\n\n"
            f"📊 *{symbol}* — {side} MARKET\n"
            f"📍 Entry: `{current_price:.2f}`\n"
            f"🛡️ Default SL ({defaults['sl_pips']:.0f} pips): `{default_sl:.2f}`\n"
            f"⏳ TP: _Waiting for full signal..._\n\n"
            f"📦 {len(tickets)}/3 positions opened\n"
            f"💎 Lot: {lot_size} | SL: {sl_ok}/{len(tickets)} configured\n\n"
            f"⏱️ Full signal incoming soon with targets!"
        )
        
        # Start timeout monitor for SIGNAL_FULL (safety net)
        asyncio.create_task(self._start_signal_full_timeout_monitor(tg_id, time.time()))
        
        return tg_id

    # ──────────────────────────────────────────
    # SAFETY: Timeout monitor for missing SIGNAL_FULL
    # ──────────────────────────────────────────
    async def _start_signal_full_timeout_monitor(self, tg_id: int, now_timestamp: float):
        """
        Monitor for SIGNAL_FULL timeout.
        SMART VERSION: Check if price moved significantly - close if unsafe, apply defaults if stable.
        """
        await asyncio.sleep(config.SIGNAL_FULL_TIMEOUT)  # 180 seconds (extended)
        
        with get_session() as session:
            tg = crud.get_trade_group(session, tg_id)
            if not tg or tg.status != TradeGroupStatus.PENDING_DETAILS:
                return  # Already updated or closed
            
            # Extract data
            symbol = tg.symbol
            side = tg.side
            entry_price = tg.entry_price or 0.0
            t1_ticket = tg.t1_ticket
            t2_ticket = tg.t2_ticket
            t3_ticket = tg.t3_ticket
        
        logger.warning(f"⏰ SIGNAL_FULL timeout for TradeGroup #{tg_id}")
        
        # Get average entry price from opened positions
        actual_entries = []
        for ticket in [t1_ticket, t2_ticket, t3_ticket]:
            if ticket:
                pos = await self.mt5.get_position(ticket)
                if pos:
                    actual_entries.append(pos.get("price_open", 0))
        
        if not actual_entries:
            logger.warning(f"⚠️ No open positions for timeout handling (TradeGroup #{tg_id})")
            return
        
        avg_entry = sum(actual_entries) / len(actual_entries)
        
        # Apply conservative defaults (300-pip SL already protects us)
        logger.info(
            f"📋 SIGNAL_FULL timeout - applying default SL/TP values"
        )
        
        # Get symbol-specific defaults
        defaults = self._get_default_sl_tp_pips(symbol)
        pip_value = self._calculate_pip_value(symbol)
        
        # Calculate default values from average entry
        if side == "BUY":
            default_sl = avg_entry - (defaults["sl_pips"] * pip_value)
            default_tp1 = avg_entry + (defaults["tp1_pips"] * pip_value)
            default_tp2 = avg_entry + (defaults["tp2_pips"] * pip_value)
        else:
            default_sl = avg_entry + (defaults["sl_pips"] * pip_value)
            default_tp1 = avg_entry - (defaults["tp1_pips"] * pip_value)
            default_tp2 = avg_entry - (defaults["tp2_pips"] * pip_value)
        
        # Apply defaults
        await self.handle_signal_full_update(
            tg_id=tg_id,
            details_message_id=0,
            entry_price=avg_entry,
            sl=default_sl,
            tp1=default_tp1,
            tp2=default_tp2,
            tp3=0.0
        )
        
        await self.notify(
            f"⏰ *SIGNAL_FULL Timeout — TradeGroup #{tg_id}*\n\n"
            f"Applied conservative defaults after {config.SIGNAL_FULL_TIMEOUT}s:\n"
            f"SL: `{default_sl:.2f}` ({defaults['sl_pips']:.0f} pips)\n"
            f"TP1: `{default_tp1:.2f}` ({defaults['tp1_pips']:.0f} pips)\n"
            f"TP2: `{default_tp2:.2f}` ({defaults['tp2_pips']:.0f} pips)\n\n"
            f"⚠️ Full signal did not arrive in time"
        )

    # ──────────────────────────────────────────
    # SIGNAL_FULL UPDATE → Update NOW positions with correct SL/TP
    # ──────────────────────────────────────────
    async def handle_signal_full_update(
        self,
        tg_id: int,
        details_message_id: int,
        entry_price: float,
        sl: float,
        tp1: float,
        tp2: float,
        tp3: float,
    ) -> bool:
        """
        Update existing positions (opened from NOW) with correct SL/TP from SIGNAL_FULL.
        This is called when the full signal arrives after immediate NOW execution.
        Stores details_message_id so replies can find this trade group.
        """
        with get_session() as session:
            tg = crud.get_trade_group(session, tg_id)
            if not tg:
                logger.warning(f"⚠️ TradeGroup {tg_id} not found for update")
                return False

            if tg.status != TradeGroupStatus.PENDING_DETAILS:
                logger.warning(f"⚠️ TradeGroup {tg_id} is not PENDING_DETAILS (status={tg.status})")
                # BUG 2 FIX: Still store details_message_id so TP/SL replies can find this trade
                if details_message_id and not tg.details_message_id:
                    tg.details_message_id = details_message_id
                    session.commit()
                    logger.info(f"📋 Stored details_message_id={details_message_id} on TradeGroup #{tg_id} (for reply matching)")
                return "already_handled"  # Distinct from False ("not found")

            # Get position data before session closes
            symbol = tg.symbol
            side = tg.side
            t1_ticket = tg.t1_ticket
            t2_ticket = tg.t2_ticket
            t3_ticket = tg.t3_ticket
            t1_status = tg.t1_status
            t2_status = tg.t2_status
            t3_status = tg.t3_status

        logger.info(f"📋 Updating TradeGroup #{tg_id} with SL={sl} TP1={tp1} TP2={tp2} TP3={tp3}")

        # BUG 6 FIX: Get actual MT5 entry prices (signal entry can differ from fill price)
        # Example: Signal says entry=4713 but positions actually filled at 4614
        actual_entries = []
        for ticket in [t1_ticket, t2_ticket, t3_ticket]:
            if ticket:
                pos = await self.mt5.get_position(ticket)
                if pos:
                    actual_entries.append(pos.get("price_open", 0))
        
        actual_avg_entry = sum(actual_entries) / len(actual_entries) if actual_entries else entry_price
        
        # CRITICAL FIX: Validate signal entry price against actual NOW execution
        # This prevents catastrophic losses from signal parsing errors (e.g., TG#432, TG#433)
        entry_price_corrected = False  # Track if we corrected the entry
        if actual_entries and entry_price > 0:
            pip_value = self._calculate_pip_value(symbol)
            # 500 pips tolerance (5 price points): normal variance is 1-3 price points (100-300 pips)
            # TG#432/433 were 100 price points off (10000 pips), so 500 pips catches real parsing errors
            max_deviation_pips = 500.0
            max_deviation = max_deviation_pips * pip_value
            deviation = abs(entry_price - actual_avg_entry)
            
            if deviation > max_deviation:
                logger.error(
                    f"🚨 ENTRY PRICE MISMATCH DETECTED!\n"
                    f"   NOW execution: {actual_avg_entry:.2f}\n"
                    f"   Signal parsed: {entry_price}\n"
                    f"   Deviation: {deviation:.2f} ({deviation/pip_value:.1f} pips)\n"
                    f"   Max allowed: {max_deviation:.2f} ({max_deviation_pips} pips)\n"
                    f"   🛡️ Using NOW execution price as source of truth"
                )
                # Use actual execution price instead of parsed (wrong) signal price
                entry_price = actual_avg_entry
                entry_price_corrected = True  # Mark that we corrected it
                
                await self.notify(
                    f"🚨 *Signal Parsing Error Detected — TradeGroup #{tg_id}*\n\n"
                    f"Parsed entry: `{entry_price}` differs from actual execution by {deviation/pip_value:.1f} pips!\n"
                    f"Actual NOW execution: `{actual_avg_entry:.2f}`\n\n"
                    f"🛡️ Using actual execution price to prevent loss"
                )
        
        # Use actual entry for SL validation (not the signal's entry which may be wrong)
        validation_entry = actual_avg_entry if actual_entries else entry_price
        
        # SAFETY CHECK 1: Validate SL logic (must be protective, not suicidal)
        sl_valid = True
        if side == "BUY" and sl >= validation_entry:
            logger.error(f"❌ Invalid SL for BUY: SL {sl} >= actual entry {validation_entry}")
            sl_valid = False
        elif side == "SELL" and sl <= validation_entry:
            logger.error(f"❌ Invalid SL for SELL: SL {sl} <= actual entry {validation_entry}")
            sl_valid = False
        
        if not sl_valid:
            # Use conservative fallback based on actual entry
            pip_value = self._calculate_pip_value(symbol)
            fallback_distance = config.DEFAULT_SL_PIPS * pip_value
            sl = validation_entry - fallback_distance if side == "BUY" else validation_entry + fallback_distance
            logger.warning(f"⚠️ Using fallback SL: {sl} ({config.DEFAULT_SL_PIPS} pips from actual entry {validation_entry})")
            
            await self.notify(
                f"⚠️ *Invalid SL Detected — TradeGroup #{tg_id}*\n\n"
                f"Signal entry: `{entry_price}` | Actual entry: `{validation_entry:.2f}`\n"
                f"Received bad SL value, using conservative fallback:\n"
                f"Fallback SL: `{sl}` ({config.DEFAULT_SL_PIPS} pips from actual entry)"
            )

        # SAFETY CHECK 2: Check if all positions already closed (500-pip SL hit)
        all_closed = (t1_status == PositionStatus.CLOSED and 
                      t2_status == PositionStatus.CLOSED and 
                      t3_status == PositionStatus.CLOSED)
        
        if all_closed:
            logger.error(f"🚨 All positions CLOSED before SIGNAL_FULL for TradeGroup #{tg_id}")
            logger.error(f"   This indicates 500-pip default SL was hit! MAJOR LOSS!")
            
            # Update DB with intended values for records
            with get_session() as session:
                tg = crud.get_trade_group(session, tg_id)
                tg.details_message_id = details_message_id
                tg.entry_price = entry_price if entry_price > 0 else tg.entry_price
                tg.sl = sl
                tg.tp1 = tp1
                tg.tp2 = tp2
                tg.tp3 = tp3
                tg.status = TradeGroupStatus.CLOSED  # Already closed
                crud.add_execution_log(
                    session, "SIGNAL_FULL_TOO_LATE",
                    f"All positions already closed (500-pip SL hit). Intended: SL={sl}",
                    tg_id
                )
            
            await self.notify(
                f"🚨 *LATE SIGNAL_FULL — TradeGroup #{tg_id}*\n\n"
                f"All positions already closed by 500-pip default SL!\n"
                f"Intended SL was: `{sl}` ({abs(sl - entry_price):.1f} pips)\n\n"
                f"⚠️ This caused unnecessary loss. Signal delivery too slow."
            )
            return False

        # SAFETY CHECK 3: Get current price for validation checks
        current_price_data = await self.mt5.get_symbol_price(symbol)
        if not current_price_data:
            logger.warning(f"⚠️ Could not get current price for {symbol}")
            current_price = entry_price  # Fallback
        else:
            current_price = current_price_data["ask"] if side == "BUY" else current_price_data["bid"]
        
        # SAFETY CHECK 4: Check if price ALREADY PAST SL (CRITICAL!)
        sl_already_hit = False
        if side == "BUY" and current_price <= sl:
            sl_already_hit = True
            logger.error(f"🚨 DANGER! Current price {current_price} already past SL {sl} for BUY")
        elif side == "SELL" and current_price >= sl:
            sl_already_hit = True
            logger.error(f"🚨 DANGER! Current price {current_price} already past SL {sl} for SELL")
        
        if sl_already_hit:
            # EMERGENCY: Close all positions immediately
            logger.error(f"🚨 Price already in SL zone! Emergency closing all positions.")
            await self._emergency_close_all_positions(
                tg_id, t1_ticket, t2_ticket, t3_ticket,
                f"Price {current_price} already past SL {sl} - preventing major loss"
            )
            return False
        
        # SAFETY CHECK 5: Check if TP1 already reached (late entry optimization)
        # BUT: Skip this check if we corrected the entry price (TP values unreliable)
        if tp1 > 0 and not entry_price_corrected:
            tp1_already_hit = False
            if side == "BUY" and current_price >= tp1:
                tp1_already_hit = True
                logger.warning(f"⚠️ Late entry detected! Current price {current_price} >= TP1 {tp1}")
            elif side == "SELL" and current_price <= tp1:
                tp1_already_hit = True
                logger.warning(f"⚠️ Late entry detected! Current price {current_price} <= TP1 {tp1}")
            
            if tp1_already_hit:
                # Handle late entry scenario - TP1 already reached
                await self._handle_late_entry_tp1(
                    tg_id, details_message_id, symbol, side, entry_price,
                    t1_ticket, t2_ticket, t3_ticket,
                    t1_status, t2_status, t3_status,
                    tp1, tp2, tp3, sl
                )
                return True
        elif entry_price_corrected:
            logger.info(f"🛡️ Skipping late entry check - entry price was corrected, TP values unreliable")

        # Update positions on MT5 with correct SL/TP
        # Check if positions still exist (race condition: TP may have hit before SIGNAL_FULL arrived)
        updates = [
            (t1_ticket, t1_status, "T1", tp1),
            (t2_ticket, t2_status, "T2", tp2),
            (t3_ticket, t3_status, "T3", tp3 if tp3 > 0 else None),
        ]

        updated_count = 0
        skipped_count = 0
        for ticket, status, label, tp in updates:
            if ticket and status == PositionStatus.OPEN:
                # Verify position still exists before updating
                pos_info = await self.mt5.get_position(ticket)
                if not pos_info:
                    logger.info(f"ℹ️ {label} already closed (TP hit before SIGNAL_FULL) - skipping update")
                    skipped_count += 1
                    continue
                    
                success = await self._update_position_with_retry(ticket, sl=sl, tp=tp)
                if success:
                    updated_count += 1
                    logger.info(f"✅ {label} updated: SL={sl}, TP={tp}")
                else:
                    logger.warning(f"⚠️ Failed to update {label} (ticket {ticket}) after retries")

        # Update database
        with get_session() as session:
            tg = crud.get_trade_group(session, tg_id)
            tg.details_message_id = details_message_id  # Store SIGNAL_FULL msg_id for replies
            tg.entry_price = entry_price if entry_price > 0 else tg.entry_price
            tg.sl = sl
            tg.tp1 = tp1
            tg.tp2 = tp2
            tg.tp3 = tp3
            tg.status = TradeGroupStatus.ACTIVE

            # Update trade history records
            for ticket, label, tp_val in [(t1_ticket, "T1", tp1), (t2_ticket, "T2", tp2), (t3_ticket, "T3", tp3)]:
                if ticket:
                    crud.update_trade_history(session, ticket, sl=sl, tp=tp_val if tp_val > 0 else None)

            crud.add_execution_log(
                session,
                action="SIGNAL_FULL_UPDATE",
                details=f"Updated {updated_count}/3 positions | SL={sl} TP1={tp1} TP2={tp2} TP3={tp3}",
                trade_group_id=tg_id,
            )

            # Fetch display data before session closes
            symbol_display = tg.symbol
            side_display = tg.side
            entry_display = tg.entry_price
            sl_display = tg.sl
            tp1_display = tg.tp1
            tp2_display = tg.tp2
            tp3_display = tg.tp3

        tp3_str = f"`{tp3_display}`" if tp3_display > 0 else "🔓 _Ouvert (runner)_"
        await self.notify(
            f"📋 *Full Signal Received — TradeGroup #{tg_id} Updated!*\n\n"
            f"📊 *{symbol_display}* — {side_display}\n"
            f"📍 Entry: `{entry_display:.2f}`\n"
            f"🛡️ SL: `{sl_display:.2f}`\n"
            f"🥇 TP1: `{tp1_display:.2f}`\n"
            f"🥈 TP2: `{tp2_display:.2f}`\n"
            f"🏆 TP3: {tp3_str}\n\n"
            f"✅ {updated_count}/3 positions updated with targets!\n"
            f"🎯 Locked and loaded! Let's hunt those TPs! 🔥"
        )
        return True

    # ──────────────────────────────────────────
    # SIGNAL_FULL → Open 3 Positions + Apply SL/TP
    # ──────────────────────────────────────────
    async def handle_signal_full(
        self,
        message_id: int,
        symbol: str,
        side: str,
        entry_price: float,
        sl: float,
        tp1: float,
        tp2: float,
        tp3: float,
        is_now: bool = True,
    ) -> Optional[int]:
        """
        Process a full Station X signal (J'ACHÈTE / JE VENDS message).

        Execution logic:
          - is_now=True (preceded by "ACHAT/VENTE NOW"):
              → 3 MARKET orders at current price
          - is_now=False (entry price only, no NOW):
              → 3 LIMIT orders at the specified entry price
        """
        ok, reason = await self._preflight_check()
        if not ok:
            await self.notify(f"⚠️ Cannot execute signal: {reason}")
            return None

        # Get symbol-specific lot size (fixes BTCUSD "Invalid volume" errors)
        lot_size = config.SYMBOL_LOT_SIZES.get(symbol, None)
        if lot_size is None:
            # Fallback to database settings or default
            with get_session() as session:
                lot_size = crud.get_settings(session).lot_size or config.DEFAULT_LOT_SIZE
            logger.debug(f"Using lot size from DB/default: {lot_size} for {symbol}")
        else:
            logger.debug(f"Using symbol-specific lot size: {lot_size} for {symbol}")

        await self.mt5.ensure_symbol_visible(symbol)

        # Decide market vs limit based on NOW trigger and price distance
        use_limit = False
        if not is_now and entry_price > 0:
            # No NOW trigger — check if entry price is far from market
            use_limit = True
        elif entry_price > 0:
            # NOW trigger present — but double-check price distance
            current_price = await self.mt5.get_symbol_price(symbol)
            if current_price:
                market = current_price["ask"] if side == "BUY" else current_price["bid"]
                # If entry is more than 0.5% away from market, use limit
                if market > 0 and abs(entry_price - market) / market > 0.005:
                    use_limit = True
                    logger.info(f"📋 Entry {entry_price} is far from market {market} — using LIMIT order")

        # TP3=0 means "Ouvert" (open runner) — no TP set on T3
        tp3_value = tp3 if tp3 > 0 else 0.0

        tickets = []
        targets = [
            ("T1", tp1),
            ("T2", tp2),
            ("T3", tp3_value),
        ]

        order_type_label = "LIMIT" if use_limit else "MARKET"
        errors = []

        for label, tp in targets:
            tp_val = tp if tp > 0 else None
            if use_limit:
                # LIMIT ORDER at specified entry price with SL/TP
                result = await self.mt5.place_limit_order(
                    symbol=symbol,
                    side=side,
                    lot_size=lot_size,
                    price=entry_price,
                    sl=sl,
                    tp=tp_val,
                    comment=f"STX-{label}",
                )
            else:
                # MARKET ORDER — execute immediately
                result = await self.mt5.open_position(
                    symbol=symbol,
                    side=side,
                    lot_size=lot_size,
                    comment=f"STX-{label}",
                )

            if result and result.get("retcode") == 10009:
                ticket = result.get("order", 0)
                price = result.get("price", entry_price if use_limit else 0.0)
                tickets.append((label, ticket, price, tp or 0.0))
                logger.info(f"✅ {label} {order_type_label}: ticket={ticket}, price={price}")
            else:
                error_msg = result.get("comment", "Unknown error") if result else "No response"
                errors.append((label, error_msg))
                logger.error(f"❌ Failed {order_type_label} {label}: {error_msg}")

        # Handle failures with smart grouping
        if not tickets:
            # All 3 positions failed - check if same error
            if errors and all(err[1] == errors[0][1] for err in errors):
                # All same error - send one grouped notification with fix instructions
                common_error = errors[0][1]
                fix_msg = ""
                if "AutoTrading disabled" in common_error:
                    fix_msg = (
                        "\n\n👉 **Fix:** Enable AutoTrading in MT5\n"
                        "   1. Click the 'AutoTrading' button in MT5 toolbar (or press Ctrl+E)\n"
                        "   2. It must be **GREEN** ✅\n"
                        "   3. Also check: Tools → Options → Expert Advisors → 'Allow Algo Trading' ☑️"
                    )
                
                await self.notify(
                    f"💥 *All 3 positions failed for {symbol} {side}!*\n\n"
                    f"Reason: `{common_error}`{fix_msg}"
                )
            else:
                # Different errors - list them
                error_list = "\n".join([f"  • {label}: {msg}" for label, msg in errors])
                await self.notify(
                    f"💥 *All positions failed for {symbol} {side}!*\n\n"
                    f"Errors:\n{error_list}\n\n"
                    f"Check your MT5 terminal."
                )
            return None

        # For market orders, apply SL/TP after opening
        sl_tp_ok = 0
        if not use_limit:
            for label, ticket, price, tp in tickets:
                tp_val = tp if tp > 0 else None
                result = await self.mt5.modify_position(ticket, sl=sl, tp=tp_val)
                if result and result.get("retcode") == 10009:
                    sl_tp_ok += 1
                    logger.info(f"✅ {label} SL={sl}, TP={tp_val if tp_val else 'OPEN'}")
                else:
                    logger.warning(f"⚠️ Failed to set SL/TP on {label} (ticket {ticket})")
        else:
            sl_tp_ok = len(tickets)  # Limit orders already have SL/TP

        # Save to database
        with get_session() as session:
            tg = crud.create_trade_group(session, message_id, symbol, side)
            tg_id = tg.id
            tg.details_message_id = message_id  # Store same ID for non-NOW signals (for consistency)
            tg.entry_price = entry_price if entry_price > 0 else (tickets[0][2] if tickets else 0.0)
            tg.sl = sl
            tg.tp1 = tp1
            tg.tp2 = tp2
            tg.tp3 = tp3
            tg.status = TradeGroupStatus.ACTIVE if not use_limit else TradeGroupStatus.PENDING

            for label, ticket, price, tp in tickets:
                if label == "T1":
                    tg.t1_ticket = ticket
                elif label == "T2":
                    tg.t2_ticket = ticket
                elif label == "T3":
                    tg.t3_ticket = ticket

                crud.create_trade_history(
                    session,
                    trade_group_id=tg_id,
                    position_label=label,
                    symbol=symbol,
                    side=side,
                    lot_size=lot_size,
                    ticket=ticket,
                    open_price=price,
                    sl=sl,
                    tp=tp if tp > 0 else None,
                )

            crud.add_execution_log(
                session,
                action=f"SIGNAL_{order_type_label}",
                details=f"{side} {symbol} | {len(tickets)}/3 {order_type_label} | SL={sl} TP1={tp1} TP2={tp2} TP3={tp3}",
                trade_group_id=tg_id,
            )

            # Extract display data before session closes
            entry_display = tg.entry_price
            symbol_display = tg.symbol
            side_display = tg.side

        tp3_display = f"`{tp3}`" if tp3 > 0 else "🔓 _Ouvert (runner)_"
        order_emoji = "⚡" if not use_limit else "📋"
        order_desc = "MARKET — LIVE NOW" if not use_limit else f"LIMIT @ `{entry_price}` — waiting for fill"
        await self.notify(
            f"{order_emoji} *TradeGroup #{tg_id} — {order_desc}!*\n\n"
            f"📊 *{symbol_display}* — {side_display}\n"
            f"📍 Entry: `{entry_display}`\n"
            f"🛡️ SL: `{sl}`\n"
            f"🥇 TP1: `{tp1}`\n"
            f"🥈 TP2: `{tp2}`\n"
            f"🏆 TP3: {tp3_display}\n\n"
            f"📦 {len(tickets)}/3 {order_type_label} orders placed\n"
            f"💎 Lot: {lot_size} | SL/TP: {sl_tp_ok}/{len(tickets)} configured\n\n"
            f"🔥 Let's go! Targets are locked! 💪"
        )
        return tg_id

    # ──────────────────────────────────────────
    # TP HIT (from Station X signal reply)
    # ──────────────────────────────────────────
    async def handle_tp_hit(self, tg_id: int, tp_level: int, pips: int = 0, is_manual: bool = False):
        """Handle TP1/TP2/TP3 hit from Station X signal."""
        if tp_level == 1:
            await self._handle_tp1_hit(tg_id, pips)
        elif tp_level == 2:
            await self._handle_tp2_hit(tg_id, pips, is_manual)
        elif tp_level == 3:
            await self._handle_tp3_hit(tg_id, pips, is_manual)

    async def _handle_late_entry_tp1(
        self,
        tg_id: int,
        details_message_id: int,
        symbol: str,
        side: str,
        entry_price: float,
        t1_ticket: int,
        t2_ticket: int,
        t3_ticket: int,
        t1_status: PositionStatus,
        t2_status: PositionStatus,
        t3_status: PositionStatus,
        tp1: float,
        tp2: float,
        tp3: float,
        sl: float,
    ):
        """
        Handle late entry scenario where TP1 is already hit when SIGNAL_FULL arrives.
        Strategy: Close T1 (TP1 already passed), keep T2/T3 with proper SL/TP targets.
        This allows capturing remaining profit potential from TP2/TP3.
        """
        logger.info(f"🚨 Late entry TP1 optimization for TradeGroup #{tg_id}")
        
        # Close T1 immediately on MT5 and get close price
        close_success = False
        close_price = 0.0
        if t1_ticket and t1_status == PositionStatus.OPEN:
            pos = await self.mt5.get_position(t1_ticket)
            if pos:
                # Get current price before closing
                price_data = await self.mt5.get_symbol_price(symbol)
                if price_data:
                    close_price = price_data["bid"] if side == "BUY" else price_data["ask"]
                
                close_result = await self.mt5.close_position(t1_ticket)
                if close_result and close_result.get("retcode") == 10009:
                    close_success = True
                    logger.info(f"✅ T1 auto-closed on MT5 (late entry, ticket {t1_ticket})")
                else:
                    logger.warning(f"⚠️ Failed to auto-close T1 (ticket {t1_ticket})")
        
        # Update T2/T3 with proper SL from signal and their respective TPs
        # This allows capturing TP2/TP3 profit instead of just protecting at breakeven
        moved = 0
        for ticket, status, label in [(t2_ticket, t2_status, "T2"), (t3_ticket, t3_status, "T3")]:
            if ticket and status == PositionStatus.OPEN:
                # Use proper SL from signal, not breakeven
                tp_val = tp2 if label == "T2" else (tp3 if tp3 > 0 else None)
                success = await self._update_position_with_retry(ticket, sl=sl, tp=tp_val)
                if success:
                    moved += 1
                    logger.info(f"✅ {label} updated: SL={sl}, TP={tp_val} (late entry optimization)")
        
        # Update database with profit calculation
        with get_session() as session:
            tg = crud.get_trade_group(session, tg_id)
            tg.details_message_id = details_message_id
            tg.entry_price = entry_price if entry_price > 0 else tg.entry_price
            tg.sl = sl
            tg.tp1 = tp1
            tg.tp2 = tp2
            tg.tp3 = tp3
            tg.t1_status = PositionStatus.TP_HIT
            tg.status = TradeGroupStatus.PARTIAL
            
            # Get T1 trade for profit calculation
            t1_trade = session.query(TradeHistory).filter_by(ticket=t1_ticket).first()
            if t1_trade and t1_trade.open_price and close_price > 0 and t1_trade.lot_size is not None:
                # Calculate profit using actual close price
                profit = self._calculate_position_profit(symbol, side, t1_trade.open_price, close_price, t1_trade.lot_size)
                crud.update_trade_history(
                    session, 
                    t1_ticket, 
                    status=PositionStatus.TP_HIT, 
                    close_price=close_price,
                    profit=profit,
                    closed_at=datetime.utcnow()
                )
                # Update daily P&L with actual profit
                crud.update_daily_pnl(session, profit, is_win=True)
            else:
                crud.update_trade_history(session, t1_ticket, status=PositionStatus.TP_HIT, closed_at=datetime.utcnow())
            
            # Update T2/T3 history with proper SL/TP from signal
            for ticket, label, tp_val in [(t2_ticket, "T2", tp2), (t3_ticket, "T3", tp3)]:
                if ticket:
                    crud.update_trade_history(session, ticket, sl=sl, tp=tp_val if tp_val > 0 else None)
            
            crud.add_execution_log(
                session,
                action="TP1_AUTO_HIT",
                details=f"Late entry optimization | T1 closed | T2/T3 active with SL={sl}",
                trade_group_id=tg_id,
            )
        
        # Send notification
        tp3_str = f"`{tp3}`" if tp3 > 0 else "🔓 _Ouvert (runner)_"
        await self.notify(
            f"⚠️ *Late Entry Optimization — TradeGroup #{tg_id}!* 🚨\n\n"
            f"📊 *{symbol}* — {side}\n"
            f"⏱️ TP1 already reached before signal update\n\n"
            f"✅ T1 auto-closed at market\n"
            f"🛡️ T2/T3 active with proper SL: `{sl}`\n"
            f"🥈 TP2: `{tp2}`\n"
            f"🏆 TP3: {tp3_str}\n\n"
            f"💎 Still capturing TP2/TP3 profit potential!\n"
            f"🎯 Let's hit those remaining targets! 🔥"
        )

    async def _handle_tp1_hit(self, tg_id: int, pips: int = 0):
        """TP1 hit: close T1, move SL of T2 and T3 to entry price (breakeven)."""
        with get_session() as session:
            tg = crud.get_trade_group(session, tg_id)
            if not tg:
                return

            tg.t1_status = PositionStatus.TP_HIT
            tg.status = TradeGroupStatus.PARTIAL
            symbol = tg.symbol
            side = tg.side
            tp1_price = tg.tp1 or 0.0
            entry = tg.entry_price or 0.0
            remaining = [(tg.t2_ticket, tg.t2_status, "T2"), (tg.t3_ticket, tg.t3_status, "T3")]
            
            # Get T1 trade info for profit calculation
            t1_trade = session.query(TradeHistory).filter_by(ticket=tg.t1_ticket).first()
            if t1_trade and t1_trade.open_price and tp1_price > 0 and t1_trade.lot_size is not None:
                # Use execution price for profit calc
                exec_entry = t1_trade.open_price
                # Calculate profit: TP1 was hit so close price = TP1
                profit = self._calculate_position_profit(symbol, side, exec_entry, tp1_price, t1_trade.lot_size)
                logger.info(f"DEBUG TP1: Calculated profit=${profit:.2f}")
                crud.update_trade_history(
                    session, 
                    tg.t1_ticket, 
                    status=PositionStatus.TP_HIT, 
                    close_price=tp1_price,
                    profit=profit,
                    closed_at=datetime.utcnow()
                )
                # Update daily P&L with actual profit
                crud.update_daily_pnl(session, profit, is_win=True)
            else:
                logger.warning(f"DEBUG TP1: Missing data - trade={t1_trade is not None}, entry={entry}, tp1={tp1_price}")
                crud.update_trade_history(session, tg.t1_ticket, status=PositionStatus.TP_HIT, closed_at=datetime.utcnow())
            
            # After TP1 hit, move SL to entry price (breakeven) - client requirement
            new_sl = entry
            
            crud.add_execution_log(session, "TP1_HIT", f"+{pips} pips | Moving SL to entry/BE ({new_sl:.2f})", tg_id)

        # Move SL to breakeven on remaining open positions
        # RACE CONDITION FIX: Check if positions still exist before modifying
        moved = 0
        race_condition_hits = 0
        
        for ticket, status, label in remaining:
            if ticket and status == PositionStatus.OPEN:
                # Check if position still exists on MT5
                pos = await self.mt5.get_position(ticket)
                if not pos:
                    # Position already closed - likely hit original SL in race condition
                    race_condition_hits += 1
                    logger.warning(
                        f"⚠️ {label} (ticket {ticket}) already closed on MT5 "
                        f"before breakeven SL could be applied. "
                        f"Likely hit original SL in race condition (2s monitor too slow)."
                    )
                    # Update DB to reflect reality
                    with get_session() as session:
                        tg = crud.get_trade_group(session, tg_id)
                        original_sl = tg.sl or 0.0
                        
                        # Mark as SL_HIT in database
                        if label == "T2":
                            tg.t2_status = PositionStatus.SL_HIT
                        else:  # T3
                            tg.t3_status = PositionStatus.SL_HIT
                        
                        # Calculate loss at original SL
                        t_trade = session.query(TradeHistory).filter_by(ticket=ticket).first()
                        if t_trade and t_trade.open_price and original_sl > 0:
                            profit = self._calculate_position_profit(
                                symbol, side, t_trade.open_price, original_sl, t_trade.lot_size or 0.01
                            )
                            crud.update_trade_history(
                                session, ticket,
                                status=PositionStatus.SL_HIT,
                                close_price=original_sl,
                                profit=profit,
                                closed_at=datetime.utcnow()
                            )
                            crud.update_daily_pnl(session, profit, is_win=False)
                            logger.info(f"📊 {label} race condition loss: ${profit:.2f}")
                        else:
                            crud.update_trade_history(session, ticket, status=PositionStatus.SL_HIT, closed_at=datetime.utcnow())
                    continue
                
                # Position exists, move to breakeven
                result = await self.mt5.modify_position(ticket, sl=new_sl)
                if result and result.get("retcode") == 10009:
                    moved += 1
                    logger.info(f"🎯 {label} SL moved to entry/BE ({new_sl:.2f})")
                else:
                    logger.warning(f"⚠️ Failed to move {label} SL: {result}")

        # Notification with race condition info
        race_msg = ""
        if race_condition_hits > 0:
            race_msg = f"\n⚠️ {race_condition_hits} position(s) already stopped out (race condition)\n"
        
        await self.notify(
            f"🎯 *TP1 HIT on TradeGroup #{tg_id}!* 🔥\n\n"
            f"📊 *{symbol}* — +{pips} pips ✅\n"
            f"🛡️ SL moved to breakeven (entry): `{new_sl:.2f}`\n"
            f"🔒 {moved} positions secured{race_msg}\n"
            f"💰 Risk-free trade! 🏆"
        )

    async def _handle_tp2_hit(self, tg_id: int, pips: int = 0, is_manual: bool = False):
        """TP2 hit: For MANUEL, force close T2 immediately. For auto TP, just update DB."""
        with get_session() as session:
            tg = crud.get_trade_group(session, tg_id)
            if not tg:
                return

            t2_ticket = tg.t2_ticket
            t2_status = tg.t2_status
            entry = tg.entry_price or 0.0
            tp2_val = tg.tp2 or 0.0
            symbol = tg.symbol
            t3_ticket = tg.t3_ticket
            t3_status = tg.t3_status

            # After TP2 hit, move T3 SL to TP1 level (proven support/resistance)
            tp1_val = tg.tp1 or 0.0
            t3_sl_level = tp1_val if tp1_val > 0 else round((entry + tp2_val) / 2, 5) if tp2_val else entry

        # For MANUAL: Force close T2 regardless of DB status
        close_attempted = False
        close_success = False
        close_status = ""
        
        if is_manual and t2_ticket:
            # Check if position exists on MT5 (source of truth)
            pos = await self.mt5.get_position(t2_ticket)
            if pos:
                close_result = await self.mt5.close_position(t2_ticket)
                close_attempted = True
                if close_result and close_result.get("retcode") == 10009:
                    close_success = True
                    close_status = "✅ Closed on MT5"
                    logger.info(f"✅ T2 MANUEL: Closed position on MT5 (ticket {t2_ticket})")
                else:
                    close_status = "❌ Close failed"
                    logger.warning(f"⚠️ T2 MANUEL: Failed to close on MT5 (ticket {t2_ticket})")
            else:
                close_status = "ℹ️ Already closed on MT5"
                logger.info(f"ℹ️ T2 MANUEL: Position already closed on MT5 (ticket {t2_ticket})")
        else:
            # Normal TP hit: MT5 already closed at TP price, just update DB
            close_status = "✅ Auto-closed at TP"

        # Move T3 SL to TP1 level (only if T3 is still open)
        if t3_ticket and t3_status == PositionStatus.OPEN:
            # Verify T3 still exists on MT5
            pos = await self.mt5.get_position(t3_ticket)
            if pos:
                await self.mt5.modify_position(t3_ticket, sl=t3_sl_level)
                logger.info(f"🏆 T3 SL moved to TP1 level ({t3_sl_level})")

        # Update database with profit calculation
        with get_session() as session:
            tg = crud.get_trade_group(session, tg_id)
            tg.t2_status = PositionStatus.TP_HIT
            
            # Get T2 trade info for profit calculation
            t2_trade = session.query(TradeHistory).filter_by(ticket=t2_ticket).first()
            if t2_trade and t2_trade.open_price and tp2_val > 0 and t2_trade.lot_size is not None:
                # Calculate profit: TP2 was hit so close price = TP2
                profit = self._calculate_position_profit(symbol, tg.side, t2_trade.open_price, tp2_val, t2_trade.lot_size)
                crud.update_trade_history(
                    session, 
                    t2_ticket, 
                    status=PositionStatus.TP_HIT, 
                    close_price=tp2_val,
                    profit=profit,
                    closed_at=datetime.utcnow()
                )
                # Update daily P&L with actual profit
                crud.update_daily_pnl(session, profit, is_win=True)
            else:
                crud.update_trade_history(session, t2_ticket, status=PositionStatus.TP_HIT, closed_at=datetime.utcnow())
            
            action = "TP2_MANUAL" if is_manual else "TP2_HIT"
            crud.add_execution_log(session, action, f"+{pips} pips | T2 closed, T3 SL → TP1 ({t3_sl_level})", tg_id)
            symbol_display = tg.symbol

        manual_tag = " (MANUEL)" if is_manual else ""
        await self.notify(
            f"🏆 *TP2{manual_tag} HIT on TradeGroup #{tg_id}!* 🔥\n\n"
            f"📊 *{symbol_display}* — +{pips} pips ✅\n"
            f"{close_status}\n"
            f"🛡️ T3 SL moved to TP1: `{t3_sl_level}`\n\n"
            f"📈 Locking in gains like a PRO! 💎"
        )

    async def _handle_tp3_hit(self, tg_id: int, pips: int = 0, is_manual: bool = False):
        """TP3 hit or manual close: For MANUEL, force close T3 immediately. For auto TP, just update DB."""
        with get_session() as session:
            tg = crud.get_trade_group(session, tg_id)
            if not tg:
                return

            t3_ticket = tg.t3_ticket
            t3_status = tg.t3_status
            symbol = tg.symbol
            side = tg.side
            entry_price = tg.entry_price

        # For MANUAL: Force close T3 regardless of DB status
        close_attempted = False
        close_success = False
        close_status = ""
        
        if is_manual and t3_ticket:
            # Check if position exists on MT5 (source of truth)
            pos = await self.mt5.get_position(t3_ticket)
            if pos:
                close_result = await self.mt5.close_position(t3_ticket)
                close_attempted = True
                if close_result and close_result.get("retcode") == 10009:
                    close_success = True
                    close_status = "✅ Closed on MT5"
                    logger.info(f"✅ T3 MANUEL: Closed position on MT5 (ticket {t3_ticket})")
                else:
                    close_status = "❌ Close failed"
                    logger.warning(f"⚠️ T3 MANUEL: Failed to close on MT5 (ticket {t3_ticket})")
            else:
                close_status = "ℹ️ Already closed on MT5"
                logger.info(f"ℹ️ T3 MANUEL: Position already closed on MT5 (ticket {t3_ticket})")
        else:
            # Normal TP hit: MT5 already closed at TP price, just update DB
            close_status = "✅ Auto-closed at TP"

        # Get close price for profit calculation
        # For MANUEL: position just closed, get current market price
        # For normal TP: assume TP3 hit (but TP3 is usually 0/runner, so use current price)
        close_price = 0.0
        if t3_ticket:
            # Try to get last known price from MT5
            price_data = await self.mt5.get_symbol_price(symbol)
            if price_data:
                close_price = price_data["bid"] if side == "BUY" else price_data["ask"]
        
        # Update database with profit calculation
        with get_session() as session:
            tg = crud.get_trade_group(session, tg_id)
            tg.t3_status = PositionStatus.TP_HIT
            tg.status = TradeGroupStatus.CLOSED
            
            # Get T3 trade info for profit calculation
            t3_trade = session.query(TradeHistory).filter_by(ticket=t3_ticket).first()
            if t3_trade and t3_trade.open_price and close_price > 0 and t3_trade.lot_size is not None:
                # Calculate profit using actual close price
                profit = self._calculate_position_profit(symbol, tg.side, t3_trade.open_price, close_price, t3_trade.lot_size)
                crud.update_trade_history(
                    session, 
                    t3_ticket, 
                    status=PositionStatus.TP_HIT, 
                    close_price=close_price,
                    profit=profit,
                    closed_at=datetime.utcnow()
                )
                # Update daily P&L with actual profit
                crud.update_daily_pnl(session, profit, is_win=True)
            else:
                crud.update_trade_history(session, t3_ticket, status=PositionStatus.TP_HIT, closed_at=datetime.utcnow())

            action = "TP3_MANUAL" if is_manual else "TP3_HIT"
            crud.add_execution_log(session, action, f"+{pips} pips | T3 closed, TradeGroup COMPLETE", tg_id)

            trades = crud.get_trades_by_group(session, tg_id)
            total_profit = sum(t.profit for t in trades if t.profit)
            symbol_display = tg.symbol

        manual_tag = " (MANUEL)" if is_manual else ""
        await self.notify(
            f"👑 *TP3{manual_tag} — TradeGroup #{tg_id} COMPLETE!* 🎉\n\n"
            f"📊 *{symbol_display}* — +{pips} pips ✅\n"
            f"{close_status}\n"
            f"💎 Total profit: `{total_profit:.2f}`\n\n"
            f"🏅 Absolute masterclass! On to the next! 🚀"
        )

    # ──────────────────────────────────────────
    # BREAKEVEN (from Station X reply)
    # ──────────────────────────────────────────
    async def handle_move_sl_to_be(self, tg_id: int):
        """Move all remaining positions' SL to entry price."""
        with get_session() as session:
            tg = crud.get_trade_group(session, tg_id)
            if not tg or not tg.entry_price:
                return
            entry = tg.entry_price
            symbol = tg.symbol
            positions = []
            for ticket, status, label in [
                (tg.t1_ticket, tg.t1_status, "T1"),
                (tg.t2_ticket, tg.t2_status, "T2"),
                (tg.t3_ticket, tg.t3_status, "T3"),
            ]:
                if ticket and status == PositionStatus.OPEN:
                    positions.append((ticket, label))

            crud.add_execution_log(session, "SL_TO_BE", f"Moving SL to {entry}", tg_id)

        moved = 0
        for ticket, label in positions:
            result = await self.mt5.modify_position(ticket, sl=entry)
            if result and result.get("retcode") == 10009:
                moved += 1
                logger.info(f"🛡️ {label} SL moved to BE ({entry})")

        await self.notify(
            f"🛡️ *SL → Breakeven on TradeGroup #{tg_id}!*\n\n"
            f"📊 *{symbol}* — SL → `{entry}`\n"
            f"🔒 {moved}/{len(positions)} positions secured\n\n"
            f"💪 Safety first, profits second!"
        )

    # ──────────────────────────────────────────
    # CLOSE TRADE (from Station X reply)
    # ──────────────────────────────────────────
    async def handle_close_at_entry(self, tg_id: int):
        """Close all remaining open positions in the TradeGroup."""
        with get_session() as session:
            tg = crud.get_trade_group(session, tg_id)
            if not tg:
                return
            symbol = tg.symbol
            positions = []
            for ticket, status, label in [
                (tg.t1_ticket, tg.t1_status, "T1"),
                (tg.t2_ticket, tg.t2_status, "T2"),
                (tg.t3_ticket, tg.t3_status, "T3"),
            ]:
                if ticket and status == PositionStatus.OPEN:
                    positions.append((ticket, label))

        closed = 0
        for ticket, label in positions:
            result = await self.mt5.close_position(ticket)
            if result and result.get("retcode") == 10009:
                closed += 1
                with get_session() as session:
                    crud.update_trade_history(
                        session, ticket,
                        status=PositionStatus.MANUAL_CLOSE,
                        closed_at=datetime.utcnow(),
                    )

        with get_session() as session:
            crud.close_trade_group(session, tg_id)
            crud.add_execution_log(session, "CLOSE_AT_ENTRY", f"Closed {closed}/{len(positions)} positions", tg_id)

        await self.notify(
            f"🔄 *TradeGroup #{tg_id} closed!*\n\n"
            f"📊 *{symbol}*\n"
            f"✅ {closed}/{len(positions)} positions closed\n\n"
            f"🧘 Smart move — live to trade another day!"
        )

    # ──────────────────────────────────────────
    # SL HIT from Station X signal reply
    # ──────────────────────────────────────────
    async def handle_sl_hit_from_signal(self, tg_id: int, pips: int = 0):
        """
        Handle SL HIT notification from Station X (e.g. "SL -350 pips").
        The broker already closed the position — we just update our records.
        """
        total_loss = 0.0
        with get_session() as session:
            tg = crud.get_trade_group(session, tg_id)
            if not tg:
                return

            symbol = tg.symbol
            side = tg.side
            entry = tg.entry_price or 0.0
            sl_price = tg.sl or 0.0
            
            # Mark all still-open positions as SL hit and calculate profit
            for ticket, status_attr, label in [
                (tg.t1_ticket, "t1_status", "T1"),
                (tg.t2_ticket, "t2_status", "T2"),
                (tg.t3_ticket, "t3_status", "T3"),
            ]:
                current_status = getattr(tg, status_attr)
                if ticket and current_status == PositionStatus.OPEN:
                    # Check if position still exists on MT5
                    pos = await self.mt5.get_position(ticket)
                    if pos is None:
                        setattr(tg, status_attr, PositionStatus.SL_HIT)
                        
                        # Calculate actual profit using SL price
                        trade = session.query(TradeHistory).filter_by(ticket=ticket).first()
                        if trade and entry > 0 and sl_price > 0:
                            profit = self._calculate_position_profit(symbol, side, entry, sl_price, trade.lot_size)
                            total_loss += profit
                            crud.update_trade_history(
                                session, ticket,
                                status=PositionStatus.SL_HIT,
                                close_price=sl_price,
                                profit=profit,
                                closed_at=datetime.utcnow(),
                            )
                        else:
                            crud.update_trade_history(
                                session, ticket,
                                status=PositionStatus.SL_HIT,
                                closed_at=datetime.utcnow(),
                            )

            all_closed = all(
                s != PositionStatus.OPEN
                for s in [tg.t1_status, tg.t2_status, tg.t3_status]
            )
            if all_closed:
                tg.status = TradeGroupStatus.CLOSED

            # Use actual profit for daily P&L
            if total_loss != 0.0:
                crud.update_daily_pnl(session, total_loss, is_win=False)
            
            crud.add_execution_log(session, "SL_HIT_SIGNAL", f"-{pips} pips | From Station X | Loss: ${total_loss:.2f}", tg_id)

        await self.notify(
            f"🛑 *SL HIT on TradeGroup #{tg_id}!*\n\n"
            f"📊 *{symbol}* — -{pips} pips ❌\n\n"
            f"💪 Protection worked! Stay strong, Champion!"
        )

        # Check daily stop loss limit
        with get_session() as session:
            if crud.check_daily_stop_loss(session):
                await self.notify(
                    "🚨 *DAILY STOP LOSS REACHED!*\n\n"
                    "⏸️ Trading is automatically blocked for today.\n"
                    "🧘 Rest up and come back stronger tomorrow! 💪"
                )

    # ──────────────────────────────────────────
    # MODIFY SL (from Station X reply)
    # ──────────────────────────────────────────
    async def handle_modify_sl(self, tg_id: int, new_sl: float):
        """Update SL on all open positions in the TradeGroup."""
        with get_session() as session:
            tg = crud.get_trade_group(session, tg_id)
            if not tg:
                return
            symbol = tg.symbol
            tg.sl = new_sl
            positions = []
            for ticket, status, label in [
                (tg.t1_ticket, tg.t1_status, "T1"),
                (tg.t2_ticket, tg.t2_status, "T2"),
                (tg.t3_ticket, tg.t3_status, "T3"),
            ]:
                if ticket and status == PositionStatus.OPEN:
                    positions.append((ticket, label))

            crud.add_execution_log(session, "MODIFY_SL", f"New SL: {new_sl}", tg_id)

        modified = 0
        for ticket, label in positions:
            result = await self.mt5.modify_position(ticket, sl=new_sl)
            if result and result.get("retcode") == 10009:
                modified += 1
                logger.info(f"🔧 {label} SL updated to {new_sl}")
                with get_session() as session:
                    crud.update_trade_history(session, ticket, sl=new_sl)

        await self.notify(
            f"� *SL Modified on TradeGroup #{tg_id}!*\n\n"
            f"📊 *{symbol}*\n"
            f"🛡️ New SL: `{new_sl}`\n"
            f"✅ {modified}/{len(positions)} positions updated"
        )

    # ──────────────────────────────────────────
    # MODIFY TP (from Station X reply)
    # ──────────────────────────────────────────
    async def handle_modify_tp(self, tg_id: int, tp_level: int, new_tp: float):
        """Update a specific TP level on the corresponding position."""
        with get_session() as session:
            tg = crud.get_trade_group(session, tg_id)
            if not tg:
                return
            symbol = tg.symbol

            # Update the TP in the trade group
            if tp_level == 1:
                tg.tp1 = new_tp
                ticket = tg.t1_ticket
                status = tg.t1_status
                label = "T1"
            elif tp_level == 2:
                tg.tp2 = new_tp
                ticket = tg.t2_ticket
                status = tg.t2_status
                label = "T2"
            elif tp_level == 3:
                tg.tp3 = new_tp
                ticket = tg.t3_ticket
                status = tg.t3_status
                label = "T3"
            else:
                return

            crud.add_execution_log(session, f"MODIFY_TP{tp_level}", f"New TP{tp_level}: {new_tp}", tg_id)

        if ticket and status == PositionStatus.OPEN:
            result = await self.mt5.modify_position(ticket, tp=new_tp)
            if result and result.get("retcode") == 10009:
                logger.info(f"🔧 {label} TP{tp_level} updated to {new_tp}")
                with get_session() as session:
                    crud.update_trade_history(session, ticket, tp=new_tp)

        await self.notify(
            f"🔧 *TP{tp_level} Modified on TradeGroup #{tg_id}!*\n\n"
            f"� *{symbol}*\n"
            f"🎯 New TP{tp_level}: `{new_tp}`"
        )

    # ──────────────────────────────────────────
    # SL Hit Handler (from MT5 position monitor)
    # ──────────────────────────────────────────
    async def handle_sl_hit(self, tg_id: int, label: str, ticket: int, profit: float):
        """Handle when a position's SL is hit detected by the monitor."""
        with get_session() as session:
            tg = crud.get_trade_group(session, tg_id)
            if not tg:
                return

            if label == "T1":
                tg.t1_status = PositionStatus.SL_HIT
            elif label == "T2":
                tg.t2_status = PositionStatus.SL_HIT
            elif label == "T3":
                tg.t3_status = PositionStatus.SL_HIT

            crud.update_trade_history(
                session, ticket,
                status=PositionStatus.SL_HIT,
                profit=profit,
                closed_at=datetime.utcnow(),
            )
            crud.update_daily_pnl(session, profit, is_win=False)

            all_closed = all(
                s != PositionStatus.OPEN
                for s in [tg.t1_status, tg.t2_status, tg.t3_status]
            )
            if all_closed:
                tg.status = TradeGroupStatus.CLOSED

            crud.add_execution_log(session, "SL_HIT", f"{label} SL hit, profit={profit}", tg_id)
            symbol = tg.symbol

        await self.notify(
            f"� *SL triggered on {label} — TradeGroup #{tg_id}*\n\n"
            f"📊 *{symbol}*\n"
            f"💰 P&L: `{profit:.2f}`\n\n"
            f"💪 Protection worked! Stay strong!"
        )

        with get_session() as session:
            if crud.check_daily_stop_loss(session):
                await self.notify(
                    "🚨 *DAILY STOP LOSS REACHED!*\n\n"
                    "⏸️ Trading is automatically blocked for today.\n"
                    "🧘 Rest up and come back stronger tomorrow! 💪"
                )

    # ──────────────────────────────────────────
    # Position Monitor Loop
    # ──────────────────────────────────────────
    async def monitor_positions(self, interval: int = 2):
        """Continuously monitor open positions for TP/SL hits on MT5."""
        self._monitoring = True
        logger.info("👁️ Position monitor started")

        while self._monitoring:
            try:
                with get_session() as session:
                    settings = crud.get_settings(session)
                    if not settings.is_logged_in:
                        await asyncio.sleep(interval)
                        continue

                    open_groups = crud.get_open_trade_groups(session)
                    tg_ids = [tg.id for tg in open_groups]

                for tg_id in tg_ids:
                    await self._check_trade_group_positions(tg_id)

            except Exception as e:
                logger.error(f"Monitor error: {e}")

            await asyncio.sleep(interval)

    async def _check_trade_group_positions(self, tg_id: int):
        """Check each position in a TradeGroup for TP/SL hits on MT5."""
        with get_session() as session:
            tg = crud.get_trade_group(session, tg_id)
            if not tg:
                return
            
            # Skip monitoring if waiting for SIGNAL_FULL (prevent race condition)
            if tg.status == TradeGroupStatus.PENDING_DETAILS:
                return  # Wait for SIGNAL_FULL to apply correct SL/TP first

            checks = [
                (tg.t1_ticket, tg.t1_status, "T1", tg.tp1),
                (tg.t2_ticket, tg.t2_status, "T2", tg.tp2),
                (tg.t3_ticket, tg.t3_status, "T3", tg.tp3),
            ]
            entry = tg.entry_price
            sl = tg.sl

        for ticket, status, label, tp in checks:
            if not ticket or status != PositionStatus.OPEN:
                continue

            pos = await self.mt5.get_position(ticket)
            if pos is None:
                # Position closed by broker — determine if TP or SL
                profit = 0.0
                with get_session() as session:
                    trade = session.query(TradeHistory).filter_by(ticket=ticket).first()
                    if trade and trade.status == PositionStatus.OPEN:
                        profit = trade.profit or 0.0

                if tp and entry:
                    # Assume TP hit
                    tp_level = int(label[1])  # T1→1, T2→2, T3→3
                    await self.handle_tp_hit(tg_id, tp_level, 0, False)
                else:
                    await self.handle_sl_hit(tg_id, label, ticket, profit)

    def stop_monitor(self):
        """Stop the position monitoring loop."""
        self._monitoring = False
        logger.info("🛑 Position monitor stopped")
