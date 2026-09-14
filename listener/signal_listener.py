"""
Station X — Signal Listener
==============================
Real-time Telethon listener for Station X channel.
Classifies messages and dispatches to TradeExecutor.
"""

import asyncio
import logging
import time
from telethon import TelegramClient, events
from listener.message_parser import classify_message, MessageType
import config

logger = logging.getLogger("SignalListener")


class SignalListener:
    """
    Real-time event-driven Telegram message listener using Telethon.
    Captures messages from Station X and dispatches them
    to the trade executor based on classified type.
    """

    # How many seconds a NOW trigger stays valid before being considered stale
    # Extended to match SIGNAL_FULL_TIMEOUT for better cache matching
    NOW_TTL_SECONDS = 180

    def __init__(self, trade_executor):
        self.executor = trade_executor
        self.client = TelegramClient(
            "signal_session",
            config.TELEGRAM_API_ID,
            config.TELEGRAM_API_HASH,
        )
        self._running = False
        # Track recent NOW triggers: key="SYMBOL_SIDE" → timestamp
        self._recent_now: dict[str, float] = {}

    async def start(self):
        """Start the Telethon client and register event handlers with auto-reconnection."""
        await self.client.start(phone=config.TELEGRAM_PHONE)
        self._running = True

        # Verify channel access
        try:
            entity = await self.client.get_entity(config.SIGNAL_CHANNEL_ID)
            logger.info(f"📡 Listening to channel: {getattr(entity, 'title', 'Unknown')} (ID: {config.SIGNAL_CHANNEL_ID})")
        except Exception as e:
            logger.error(f"❌ Cannot access signal channel: {e}")
            return

        # Register the new message handler
        @self.client.on(events.NewMessage(chats=config.SIGNAL_CHANNEL_ID))
        async def on_new_message(event):
            await self._handle_message(event)

        logger.info("🚀 Signal Listener is LIVE and waiting for Station X signals!")
        
        # Auto-reconnection loop with exponential backoff
        backoff = 1
        max_backoff = 30
        
        while self._running:
            try:
                logger.info("📡 Telethon connected and listening...")
                await self.client.run_until_disconnected()
                
                # If we reach here and still running, it means unexpected disconnect
                if not self._running:
                    break
                
                logger.warning(f"⚠️ Telethon disconnected unexpectedly! Reconnecting in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
                
                # Reconnect
                if not self.client.is_connected():
                    await self.client.connect()
                    logger.info("✅ Telethon reconnected successfully!")
                    backoff = 1  # Reset backoff on successful reconnection
                
            except ConnectionError as e:
                logger.error(f"❌ Connection error: {e}. Retrying in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
                try:
                    if not self.client.is_connected():
                        await self.client.connect()
                except Exception as reconnect_err:
                    logger.error(f"❌ Reconnection failed: {reconnect_err}")
                
            except Exception as e:
                logger.error(f"❌ Unexpected error in Telethon listener: {e}. Retrying in {backoff}s...", exc_info=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
                try:
                    if not self.client.is_connected():
                        await self.client.connect()
                except Exception as reconnect_err:
                    logger.error(f"❌ Reconnection failed: {reconnect_err}")

    async def _handle_message(self, event):
        """Process incoming messages from the signal channel."""
        try:
            text = event.message.text
            if not text:
                return

            msg_id = event.message.id
            reply_to = None
            if event.message.reply_to:
                reply_to = event.message.reply_to.reply_to_msg_id

            logger.info(f"📩 New message [{msg_id}]: {text[:80]}...")

            # Classify the message
            result = classify_message(text, reply_to)
            msg_type = result["type"]

            # ── SIGNAL_FULL → Open positions + apply SL/TP in one shot ──
            if msg_type == MessageType.SIGNAL_FULL:
                symbol = result["symbol"]
                side = result["side"]

                # ── DUPLICATE SIGNAL DETECTION ──
                # Station X sometimes sends a signal then corrects it seconds later.
                # Track last processed SIGNAL_FULL per symbol+side to prevent duplicates.
                dedup_key = f"{symbol}_{side}"
                now_time = time.time()
                
                if not hasattr(self, '_recent_signal_full'):
                    self._recent_signal_full: dict[str, float] = {}
                
                if dedup_key in self._recent_signal_full:
                    last_signal_time = self._recent_signal_full[dedup_key]
                    if now_time - last_signal_time < 30:  # 30s cooldown
                        # Check if there's already an ACTIVE trade for this symbol+side
                        from database.engine import get_session
                        from database import crud
                        from database.models import TradeGroupStatus
                        from datetime import datetime, timedelta
                        
                        with get_session() as session:
                            recent_active = (
                                session.query(crud.TradeGroup)
                                .filter(
                                    crud.TradeGroup.symbol == symbol,
                                    crud.TradeGroup.side == side,
                                    crud.TradeGroup.status.in_([
                                        TradeGroupStatus.ACTIVE,
                                        TradeGroupStatus.PENDING_DETAILS,
                                        TradeGroupStatus.PENDING,
                                    ]),
                                    crud.TradeGroup.created_at >= datetime.now() - timedelta(seconds=300)
                                )
                                .order_by(crud.TradeGroup.created_at.desc())
                                .first()
                            )
                        
                        if recent_active:
                            logger.warning(
                                f"⚠️ DUPLICATE SIGNAL_FULL for {symbol} {side} "
                                f"(within 30s of previous, active TG#{recent_active.id} exists) — updating instead of creating new"
                            )
                            # Update existing trade with corrected values
                            update_result = await self.executor.handle_signal_full_update(
                                tg_id=recent_active.id,
                                details_message_id=msg_id,
                                entry_price=result.get("entry_price", 0.0),
                                sl=result["sl"],
                                tp1=result["tp1"],
                                tp2=result.get("tp2", 0.0),
                                tp3=result.get("tp3", 0.0),
                            )
                            self._recent_signal_full[dedup_key] = now_time
                            return
                
                self._recent_signal_full[dedup_key] = now_time

                # ── CHECK FOR MATCHING NOW TRIGGER ──
                now_key = f"{symbol}_{side}"
                tg_id = None
                
                # First check in-memory cache (with TTL enforcement!)
                if now_key in self._recent_now:
                    now_data = self._recent_now[now_key]
                    elapsed = time.time() - now_data["timestamp"]
                    
                    # BUG 4 FIX: Enforce TTL — reject stale cache entries
                    if elapsed <= self.NOW_TTL_SECONDS:
                        tg_id = now_data["tg_id"]
                        logger.info(f"📋 Found NOW trade in cache (elapsed: {elapsed:.0f}s)")
                    else:
                        logger.warning(f"⚠️ Stale NOW cache entry (elapsed: {elapsed:.0f}s > TTL {self.NOW_TTL_SECONDS}s) — ignoring")
                    
                    del self._recent_now[now_key]
                
                # Fallback: Search database for recent PENDING_DETAILS (last 300 seconds / 5 minutes)
                if not tg_id:
                    from database.engine import get_session
                    from database import crud
                    from database.models import TradeGroupStatus
                    from datetime import datetime, timedelta
                    
                    with get_session() as session:
                        recent_cutoff = datetime.now() - timedelta(seconds=300)
                        pending_tg = (
                            session.query(crud.TradeGroup)
                            .filter(
                                crud.TradeGroup.symbol == symbol,
                                crud.TradeGroup.side == side,
                                crud.TradeGroup.status == TradeGroupStatus.PENDING_DETAILS,
                                crud.TradeGroup.created_at >= recent_cutoff
                            )
                            .order_by(crud.TradeGroup.created_at.desc())
                            .first()
                        )
                        if pending_tg:
                            tg_id = pending_tg.id
                            logger.info(f"📋 Found NOW trade in database (fallback search, 5min window)")
                
                if tg_id:
                    # NOW positions already opened - UPDATE them with correct SL/TP
                    logger.info(
                        f"📋 SIGNAL_FULL UPDATE: {symbol} {side} "
                        f"entry={result.get('entry_price')} SL={result.get('sl')} "
                        f"TP1={result.get('tp1')} TP2={result.get('tp2')} TP3={result.get('tp3')}"
                    )
                    
                    update_result = await self.executor.handle_signal_full_update(
                        tg_id=tg_id,
                        details_message_id=msg_id,
                        entry_price=result.get("entry_price", 0.0),
                        sl=result["sl"],
                        tp1=result["tp1"],
                        tp2=result.get("tp2", 0.0),
                        tp3=result.get("tp3", 0.0),
                    )
                    
                    # BUG 5 FIX: NEVER fall through to create new LIMIT orders 
                    # when a NOW-triggered trade was found (even if update failed).
                    # "already_handled" means TG exists but is CLOSED/ACTIVE — do NOT duplicate.
                    if update_result == "already_handled":
                        logger.info(f"📋 TradeGroup #{tg_id} already handled — skipping LIMIT order creation")
                    elif not update_result:
                        logger.warning(f"⚠️ SIGNAL_FULL update failed for TradeGroup #{tg_id} — NOT creating duplicates")
                    # Either way, don't create new positions
                else:
                    # No NOW trigger found — but check if there's already
                    # a recent ACTIVE/CLOSED trade for this symbol+side (anti-duplicate)
                    from database.engine import get_session
                    from database import crud
                    from database.models import TradeGroupStatus
                    from datetime import datetime, timedelta
                    
                    skip_limit = False
                    with get_session() as session:
                        recent_cutoff = datetime.now() - timedelta(seconds=120)
                        existing_tg = (
                            session.query(crud.TradeGroup)
                            .filter(
                                crud.TradeGroup.symbol == symbol,
                                crud.TradeGroup.side == side,
                                crud.TradeGroup.status.in_([
                                    TradeGroupStatus.ACTIVE,
                                    TradeGroupStatus.CLOSED,
                                    TradeGroupStatus.PENDING_DETAILS,
                                ]),
                                crud.TradeGroup.created_at >= recent_cutoff
                            )
                            .order_by(crud.TradeGroup.created_at.desc())
                            .first()
                        )
                        if existing_tg:
                            skip_limit = True
                            # Still store details_message_id for reply matching
                            if not existing_tg.details_message_id:
                                existing_tg.details_message_id = msg_id
                                session.commit()
                            logger.warning(
                                f"⚠️ SIGNAL_FULL (No NOW) but recent TradeGroup #{existing_tg.id} "
                                f"(status={existing_tg.status}) exists — skipping LIMIT to prevent double entry"
                            )
                    
                    if not skip_limit:
                        # Genuine standalone signal — no recent NOW, no recent trade
                        logger.info(
                            f"📋 SIGNAL_FULL (No NOW): {symbol} {side} "
                            f"entry={result.get('entry_price')} SL={result.get('sl')} "
                            f"TP1={result.get('tp1')} TP2={result.get('tp2')} TP3={result.get('tp3')}"
                        )
                        await self.executor.handle_signal_full(
                            message_id=msg_id,
                            symbol=symbol,
                            side=side,
                            entry_price=result.get("entry_price", 0.0),
                            sl=result["sl"],
                            tp1=result["tp1"],
                            tp2=result.get("tp2", 0.0),
                            tp3=result.get("tp3", 0.0),
                            is_now=False,
                        )

            # ── NOW_TRIGGER → Execute 3 positions IMMEDIATELY with 300-pip SL ──
            elif msg_type == MessageType.NOW_TRIGGER:
                symbol = result['symbol']
                side = result['side']
                now_key = f"{symbol}_{side}"
                
                logger.info(f"⚡ NOW TRIGGER IMMEDIATE EXECUTION: {now_key}")
                
                # Execute immediately
                tg_id = await self.executor.handle_now_trigger(
                    message_id=msg_id,
                    symbol=symbol,
                    side=side,
                )
                
                # Store the tg_id to update later when full signal arrives
                if tg_id:
                    self._recent_now[now_key] = {"timestamp": time.time(), "tg_id": tg_id}
                    logger.info(f"⚡ NOW executed, TradeGroup #{tg_id} awaiting full signal update")

            # ── TP_HIT → Handle take profit hit (reply to signal) ──
            elif msg_type == MessageType.TP_HIT:
                tp_level = result["tp_level"]
                pips = result.get("pips", 0)
                is_manual = result.get("is_manual", False)
                logger.info(f"🎯 TP{tp_level} HIT (reply to {result['reply_to']}) +{pips} pips {'(manual)' if is_manual else ''}")
                await self._handle_reply_action(
                    result["reply_to"],
                    lambda tg_id: self.executor.handle_tp_hit(tg_id, tp_level, pips, is_manual),
                    f"TP{tp_level} HIT",
                )

            # ── BREAKEVEN → Move SL to entry (reply to signal) ──
            elif msg_type == MessageType.BREAKEVEN:
                logger.info(f"🛡️ BREAKEVEN signal (reply to {result['reply_to']})")
                await self._handle_reply_action(
                    result["reply_to"],
                    lambda tg_id: self.executor.handle_move_sl_to_be(tg_id),
                    "BREAKEVEN",
                )

            # ── CLOSE_TRADE → Close at entry (reply to signal) ──
            elif msg_type == MessageType.CLOSE_TRADE:
                logger.info(f"🔒 CLOSE signal (reply to {result['reply_to']})")
                await self._handle_reply_action(
                    result["reply_to"],
                    lambda tg_id: self.executor.handle_close_at_entry(tg_id),
                    "CLOSE_TRADE",
                )

            # ── SL_HIT → SL was triggered (reply to signal) ──
            elif msg_type == MessageType.SL_HIT:
                pips = result.get("pips", 0)
                logger.info(f"🛑 SL HIT -{pips} pips (reply to {result['reply_to']})")
                await self._handle_reply_action(
                    result["reply_to"],
                    lambda tg_id: self.executor.handle_sl_hit_from_signal(tg_id, pips),
                    "SL_HIT",
                )

            # ── MODIFY_SL → Update SL on open positions (reply to signal) ──
            elif msg_type == MessageType.MODIFY_SL:
                new_sl = result["new_sl"]
                logger.info(f"🔧 MODIFY SL → {new_sl} (reply to {result['reply_to']})")
                await self._handle_reply_action(
                    result["reply_to"],
                    lambda tg_id: self.executor.handle_modify_sl(tg_id, new_sl),
                    "MODIFY_SL",
                )

            # ── MODIFY_TP → Update TP on specific position (reply to signal) ──
            elif msg_type == MessageType.MODIFY_TP:
                tp_level = result["tp_level"]
                new_tp = result["new_tp"]
                logger.info(f"🔧 MODIFY TP{tp_level} → {new_tp} (reply to {result['reply_to']})")
                await self._handle_reply_action(
                    result["reply_to"],
                    lambda tg_id: self.executor.handle_modify_tp(tg_id, tp_level, new_tp),
                    f"MODIFY_TP{tp_level}",
                )

            else:
                logger.debug(f"ℹ️ INFO_ONLY message ignored: {text[:50]}...")

        except Exception as e:
            logger.error(f"❌ Error processing message: {e}", exc_info=True)

    async def _handle_reply_action(self, signal_msg_id: int, action_fn, action_name: str):
        """
        Find the TradeGroup linked to a signal message ID, then execute the action.
        Replies in Station X reference the SIGNAL_FULL message (the J'ACHÈTE/JE VENDS message).
        """
        from database.engine import get_session
        from database import crud

        with get_session() as session:
            # Look up by signal message ID (now_message_id stores the SIGNAL_FULL msg id)
            tg = crud.get_trade_group_by_signal_msg(session, signal_msg_id)
            if not tg:
                logger.warning(f"⚠️ No TradeGroup found for signal message {signal_msg_id} ({action_name})")
                return
            tg_id = tg.id

        await action_fn(tg_id)

    async def stop(self):
        """Disconnect the Telethon client."""
        self._running = False
        if self.client.is_connected():
            await self.client.disconnect()
        logger.info("📡 Signal Listener stopped")
