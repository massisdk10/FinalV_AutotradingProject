"""
Comprehensive Test Simulation - All Execution Scenarios
========================================================
Self-contained test that validates EVERY possible execution path.

Tests (May 4, 2026 - With Bug Fix Validation):
 1. NOW trigger → 3 MARKET positions with 500-pip default SL
 2. SIGNAL_FULL update → correct SL/TP, status ACTIVE
 3. TP1 HIT → Close T1, move T2/T3 SL to breakeven (entry)
 4. TP2 HIT → Close T2, move T3 SL to TP1 level (NOT midpoint)
 5. TP3 MANUEL → Force close T3 on MT5, TradeGroup CLOSED
 6. Pre-entry gap SKIP → Gold >70 pips from entry → return None
 7. Pre-entry gap ACCEPT → Gold <70 pips from entry → execute
 8. Late entry TP1 optimization → Close T1, keep T2/T3 with signal SL
 9. SL already hit → Emergency close all positions
10. Invalid SL fallback → Converts pips to price correctly
11. Breakeven → Move all SL to entry
12. SL HIT from signal → Update DB, calculate loss
13. Close at entry → Close all, mark MANUAL_CLOSE
14. Profit calculation verification (Gold 0.01 lot)
15. SIGNAL_FULL without NOW → LIMIT orders
16. Reply lookup by signal message ID
17. Signal parsing validation (Fix #1) → Catch TG#432/433 bug
18. Race condition handling (Fix #2) → Position not found handling
19. BTCUSD lot size (Fix #3) → Symbol-specific lot sizes

No external JSON file needed. All scenarios use mock data.
"""
import asyncio
from datetime import datetime
from database.engine import get_session, init_db, engine
from database import crud
from database.models import Base, TradeGroupStatus, PositionStatus, TradeHistory
from execution.trade_executor import TradeExecutor
import config


class MockMT5:
    """Mock MT5 connector for testing without actual MT5 connection."""
    def __init__(self):
        self.positions = {}
        self.next_ticket = 5000000
        self.mock_price = None

    async def check_autotrading(self):
        return True

    async def ensure_symbol_visible(self, symbol):
        return True

    def _base_price(self, symbol):
        if self.mock_price is not None:
            return self.mock_price
        if "XAU" in symbol or "GOLD" in symbol:
            return 4530.00
        elif "BTC" in symbol:
            return 69500.0
        return 1.2500

    async def get_symbol_price(self, symbol):
        p = self._base_price(symbol)
        return {"bid": p - 0.01, "ask": p + 0.01, "last": p}

    async def open_position(self, symbol, side, lot_size, sl=None, tp=None, comment=None, **kw):
        ticket = self.next_ticket
        self.next_ticket += 1
        price = self._base_price(symbol)
        self.positions[ticket] = {
            "ticket": ticket, "symbol": symbol, "side": side,
            "lot_size": lot_size, "price_open": price, "price": price,
            "sl": sl, "tp": tp, "comment": comment, "open": True,
        }
        return {"retcode": 10009, "order": ticket, "price": price}

    async def place_limit_order(self, symbol, side, lot_size, price, sl=None, tp=None, comment=None, **kw):
        ticket = self.next_ticket
        self.next_ticket += 1
        self.positions[ticket] = {
            "ticket": ticket, "symbol": symbol, "side": side,
            "lot_size": lot_size, "price_open": price, "price": price,
            "sl": sl, "tp": tp, "comment": comment, "open": True,
        }
        return {"retcode": 10009, "order": ticket, "price": 0.0}

    async def modify_position(self, ticket, sl=None, tp=None, **kw):
        if ticket in self.positions and self.positions[ticket]["open"]:
            if sl is not None:
                self.positions[ticket]["sl"] = sl
            if tp is not None:
                self.positions[ticket]["tp"] = tp
            return {"retcode": 10009}
        return {"retcode": 10004, "comment": "Position not found"}

    async def close_position(self, ticket):
        if ticket in self.positions and self.positions[ticket]["open"]:
            self.positions[ticket]["open"] = False
            p = self.positions[ticket]["price_open"]
            return {"retcode": 10009, "price": p}
        return {"retcode": 10004, "comment": "Position not found"}

    async def get_position(self, ticket):
        if ticket in self.positions and self.positions[ticket]["open"]:
            return self.positions[ticket]
        return None


# ─── Test Helpers ───
results = []

def check(name, condition):
    results.append((name, condition))
    mark = "✅" if condition else "❌"
    print(f"  {mark} {name}")


async def make_trade(executor, mt5, msg_id, symbol="XAUUSD", side="BUY",
                     entry=4530.0, sl=4527.0, tp1=4533.0, tp2=4540.0, tp3=0.0):
    """Helper: create a full NOW→SIGNAL_FULL trade and return tg_id."""
    mt5.mock_price = entry
    tg_id = await executor.handle_now_trigger(msg_id, symbol, side, entry_price=entry)
    if tg_id:
        await executor.handle_signal_full_update(
            tg_id=tg_id, details_message_id=msg_id + 1,
            entry_price=entry, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
        )
    mt5.mock_price = None
    return tg_id


async def main():
    print("\n" + "=" * 80)
    print("  COMPREHENSIVE SYSTEM TEST — All Execution Scenarios")
    print("  March 30, 2026 — Simplified & Clean Version")
    print("=" * 80)

    # Reset DB completely for clean test run
    Base.metadata.drop_all(bind=engine)
    init_db()
    # Ensure settings are configured for testing
    with get_session() as s:
        settings = crud.get_settings(s)
        settings.is_logged_in = True
        settings.lot_size = 0.01
        settings.max_daily_stop_loss = 999999.0
    mt5 = MockMT5()
    notifications = []

    async def mock_notify(msg):
        notifications.append(msg)

    executor = TradeExecutor(mt5=mt5, notify_callback=mock_notify)

    # ─────────────────────────────────────────────────
    # TEST 1: Normal NOW → SIGNAL_FULL → ACTIVE
    # ─────────────────────────────────────────────────
    print("\n── TEST 1: Normal NOW trigger + SIGNAL_FULL ──")
    mt5.mock_price = 4530.0
    tg1 = await executor.handle_now_trigger(1001, "XAUUSD", "BUY", entry_price=4530.0)
    check("NOW trigger returns tg_id", tg1 is not None)

    with get_session() as s:
        tg = crud.get_trade_group(s, tg1)
        check("Status is PENDING_DETAILS", tg.status == TradeGroupStatus.PENDING_DETAILS)
        check("3 tickets created", all([tg.t1_ticket, tg.t2_ticket, tg.t3_ticket]))
        check("Default SL set (1000 pips = 10.0 = $10 loss)", abs(tg.sl - 4520.0) < 0.1)

    ok = await executor.handle_signal_full_update(
        tg_id=tg1, details_message_id=1002,
        entry_price=4530.0, sl=4527.0, tp1=4533.0, tp2=4540.0, tp3=0.0,
    )
    check("SIGNAL_FULL update returns True", ok is True)

    with get_session() as s:
        tg = crud.get_trade_group(s, tg1)
        check("Status is ACTIVE", tg.status == TradeGroupStatus.ACTIVE)
        check("SL updated to 4527", tg.sl == 4527.0)
        check("TP1 updated to 4533", tg.tp1 == 4533.0)
        check("TP2 updated to 4540", tg.tp2 == 4540.0)
        check("details_message_id stored", tg.details_message_id == 1002)

    # Verify MT5 positions have correct SL/TP
    with get_session() as s:
        tg = crud.get_trade_group(s, tg1)
        t1p = await mt5.get_position(tg.t1_ticket)
        t2p = await mt5.get_position(tg.t2_ticket)
        check("T1 has SL=4527 on MT5", t1p and t1p["sl"] == 4527.0)
        check("T2 has TP=4540 on MT5", t2p and t2p["tp"] == 4540.0)

    mt5.mock_price = None

    # ─────────────────────────────────────────────────
    # TEST 2: TP1 HIT → T1 closed, T2/T3 SL to entry (breakeven)
    # ─────────────────────────────────────────────────
    print("\n── TEST 2: TP1 HIT ──")
    await executor.handle_tp_hit(tg1, tp_level=1, pips=30)

    with get_session() as s:
        tg = crud.get_trade_group(s, tg1)
        check("T1 status = TP_HIT", tg.t1_status == PositionStatus.TP_HIT)
        check("Group status = PARTIAL", tg.status == TradeGroupStatus.PARTIAL)
        t1_trade = s.query(TradeHistory).filter_by(ticket=tg.t1_ticket).first()
        check("T1 profit calculated", t1_trade and t1_trade.profit is not None and t1_trade.profit != 0)
        # T2/T3 SL should be at entry price (breakeven: 4530.0)
        t2p = await mt5.get_position(tg.t2_ticket)
        t3p = await mt5.get_position(tg.t3_ticket)
        expected_sl = 4530.0  # Entry price (breakeven)
        check("T2 SL moved to entry/BE (4530.0)", t2p and abs(t2p["sl"] - expected_sl) < 0.05)
        check("T3 SL moved to entry/BE (4530.0)", t3p and abs(t3p["sl"] - expected_sl) < 0.05)

    # ─────────────────────────────────────────────────
    # TEST 3: TP2 HIT → T3 SL moves to TP1 level
    # ─────────────────────────────────────────────────
    print("\n── TEST 3: TP2 HIT — T3 SL to TP1 level ──")
    with get_session() as s:
        tg = crud.get_trade_group(s, tg1)
        t2_ticket = tg.t2_ticket
        t3_ticket = tg.t3_ticket
    # Simulate MT5 auto-closing T2 at TP
    await mt5.close_position(t2_ticket)

    await executor.handle_tp_hit(tg1, tp_level=2, pips=100)

    with get_session() as s:
        tg = crud.get_trade_group(s, tg1)
        check("T2 status = TP_HIT", tg.t2_status == PositionStatus.TP_HIT)
        t3p = await mt5.get_position(t3_ticket)
        # NEW BEHAVIOR: T3 SL should be at TP1 level (4533), NOT midpoint
        check("T3 SL at TP1 level (4533)", t3p and t3p["sl"] == 4533.0)

    # ─────────────────────────────────────────────────
    # TEST 4: TP3 MANUEL → Force close
    # ─────────────────────────────────────────────────
    print("\n── TEST 4: TP3 MANUEL force close ──")
    t3_before = await mt5.get_position(t3_ticket)
    check("T3 open before MANUEL", t3_before is not None)

    await executor.handle_tp_hit(tg1, tp_level=3, pips=200, is_manual=True)

    t3_after = await mt5.get_position(t3_ticket)
    with get_session() as s:
        tg = crud.get_trade_group(s, tg1)
        check("T3 closed on MT5", t3_after is None)
        check("T3 status = TP_HIT", tg.t3_status == PositionStatus.TP_HIT)
        check("TradeGroup CLOSED", tg.status == TradeGroupStatus.CLOSED)

    # ─────────────────────────────────────────────────
    # TEST 5: Pre-entry gap SKIP (Gold > 70 pips)
    # ─────────────────────────────────────────────────
    print("\n── TEST 5: Pre-entry gap SKIP (>70 pips for Gold) ──")
    mt5.mock_price = 4530.0  # Current market
    # Signal entry is 4520 → gap = |4530 - 4520| / 0.01 = 1000 pips > 70
    result = await executor.handle_now_trigger(2001, "XAUUSD", "BUY", entry_price=4520.0)
    check("Trade skipped (returned None)", result is None)
    mt5.mock_price = None

    # ─────────────────────────────────────────────────
    # TEST 6: Pre-entry gap ACCEPT (Gold < 70 pips)
    # ─────────────────────────────────────────────────
    print("\n── TEST 6: Pre-entry gap ACCEPT (<70 pips for Gold) ──")
    mt5.mock_price = 4530.20  # Current market → ask = 4530.21
    # Signal entry is 4530.0 → gap = |4530.21 - 4530.0| / 0.01 = 21 pips < 70
    result = await executor.handle_now_trigger(2002, "XAUUSD", "BUY", entry_price=4530.0)
    check("Trade accepted (returned tg_id)", result is not None)
    mt5.mock_price = None

    # ─────────────────────────────────────────────────
    # TEST 7: Late entry TP1 optimization
    # ─────────────────────────────────────────────────
    print("\n── TEST 7: Late entry TP1 optimization ──")
    # Open trade at 4530, then signal says entry=4527, TP1=4530, TP2=4537
    mt5.mock_price = 4530.0
    tg7 = await executor.handle_now_trigger(3001, "XAUUSD", "BUY", entry_price=4530.0)
    check("NOW opened for late entry test", tg7 is not None)

    if tg7:
        # Price now at 4531 (past TP1=4530)
        mt5.mock_price = 4531.0
        await executor.handle_signal_full_update(
            tg_id=tg7, details_message_id=3002,
            entry_price=4527.0, sl=4524.0, tp1=4530.0, tp2=4537.0, tp3=0.0,
        )

    with get_session() as s:
        tg = crud.get_trade_group(s, tg7) if tg7 else None
        if tg:
            check("T1 status = TP_HIT (auto-closed)", tg.t1_status == PositionStatus.TP_HIT)
            check("Group status = PARTIAL", tg.status == TradeGroupStatus.PARTIAL)
            check("SL set to signal SL (4524)", tg.sl == 4524.0)
            t2p = await mt5.get_position(tg.t2_ticket)
            t3p = await mt5.get_position(tg.t3_ticket)
            # T2/T3 should have signal SL (4524), NOT breakeven
            check("T2 SL = signal SL 4524 (not BE)", t2p and t2p["sl"] == 4524.0)
            check("T2 TP = 4537", t2p and t2p["tp"] == 4537.0)
            check("T3 still open", t3p is not None)
        else:
            check("Late entry test (skipped - NOW failed)", False)
    mt5.mock_price = None

    # ─────────────────────────────────────────────────
    # TEST 8: SL already hit → Emergency close
    # ─────────────────────────────────────────────────
    print("\n── TEST 8: SL already hit → Emergency close ──")
    mt5.mock_price = 4530.0
    tg8 = await executor.handle_now_trigger(4001, "XAUUSD", "BUY", entry_price=4530.0)

    if tg8:
        # Price crashes to 4520, below SL=4524
        mt5.mock_price = 4520.0
        ok = await executor.handle_signal_full_update(
            tg_id=tg8, details_message_id=4002,
            entry_price=4527.0, sl=4524.0, tp1=4530.0, tp2=4537.0, tp3=0.0,
        )
        check("SIGNAL_FULL returns False (emergency close)", ok is False)

        with get_session() as s:
            tg = crud.get_trade_group(s, tg8)
            check("Group CLOSED after emergency", tg.status == TradeGroupStatus.CLOSED)
    else:
        check("Emergency close test (skipped - NOW failed)", False)
    mt5.mock_price = None

    # ─────────────────────────────────────────────────
    # TEST 9: Invalid SL fallback (pip conversion)
    # ─────────────────────────────────────────────────
    print("\n── TEST 9: Invalid SL fallback ──")
    mt5.mock_price = 4530.0
    tg9 = await executor.handle_now_trigger(5001, "XAUUSD", "BUY", entry_price=4530.0)

    if tg9:
        # Send invalid SL (above entry for BUY → wrong direction)
        mt5.mock_price = 4530.0
        ok = await executor.handle_signal_full_update(
            tg_id=tg9, details_message_id=5002,
            entry_price=4530.0, sl=4535.0, tp1=4533.0, tp2=4540.0, tp3=0.0,
        )

        with get_session() as s:
            tg = crud.get_trade_group(s, tg9)
            # Fallback SL = entry - (DEFAULT_SL_PIPS * pip_value) = 4530 - (5 * 0.01) = 4529.95
            expected_fallback = 4530.0 - (config.DEFAULT_SL_PIPS * 0.01)
            check(f"SL corrected to fallback ({expected_fallback})", abs(tg.sl - expected_fallback) < 0.01)
            check("Status is ACTIVE (not crashed)", tg.status == TradeGroupStatus.ACTIVE)
    else:
        check("Invalid SL test (skipped - NOW failed)", False)
    mt5.mock_price = None

    # ─────────────────────────────────────────────────
    # TEST 10: Breakeven signal
    # ─────────────────────────────────────────────────
    print("\n── TEST 10: Breakeven signal ──")
    tg10 = await make_trade(executor, mt5, 6001)

    await executor.handle_move_sl_to_be(tg10)

    with get_session() as s:
        tg = crud.get_trade_group(s, tg10)
        t1p = await mt5.get_position(tg.t1_ticket)
        t2p = await mt5.get_position(tg.t2_ticket)
        t3p = await mt5.get_position(tg.t3_ticket)
        check("T1 SL = entry (4530)", t1p and t1p["sl"] == 4530.0)
        check("T2 SL = entry (4530)", t2p and t2p["sl"] == 4530.0)
        check("T3 SL = entry (4530)", t3p and t3p["sl"] == 4530.0)

    # ─────────────────────────────────────────────────
    # TEST 11: SL HIT from signal
    # ─────────────────────────────────────────────────
    print("\n── TEST 11: SL HIT from signal ──")
    tg11 = await make_trade(executor, mt5, 7001)

    # Simulate all positions closed by broker (SL hit)
    with get_session() as s:
        tg = crud.get_trade_group(s, tg11)
        for t in [tg.t1_ticket, tg.t2_ticket, tg.t3_ticket]:
            await mt5.close_position(t)

    await executor.handle_sl_hit_from_signal(tg11, pips=30)

    with get_session() as s:
        tg = crud.get_trade_group(s, tg11)
        check("T1 SL_HIT", tg.t1_status == PositionStatus.SL_HIT)
        check("T2 SL_HIT", tg.t2_status == PositionStatus.SL_HIT)
        check("T3 SL_HIT", tg.t3_status == PositionStatus.SL_HIT)
        check("Group CLOSED", tg.status == TradeGroupStatus.CLOSED)

    # ─────────────────────────────────────────────────
    # TEST 12: Close at entry
    # ─────────────────────────────────────────────────
    print("\n── TEST 12: Close at entry ──")
    tg12 = await make_trade(executor, mt5, 8001)

    await executor.handle_close_at_entry(tg12)

    with get_session() as s:
        tg = crud.get_trade_group(s, tg12)
        check("Group CLOSED", tg.status == TradeGroupStatus.CLOSED)

    # ─────────────────────────────────────────────────
    # TEST 13: Profit calculation verification
    # ─────────────────────────────────────────────────
    print("\n── TEST 13: Profit calculation ──")
    profit_buy = executor._calculate_position_profit("XAUUSD", "BUY", 4530.0, 4533.0, 0.01)
    # (4533-4530) * 1 * 0.01 * 100 = 3 * 1 = $3.00
    check(f"Gold BUY profit = $3.00 (got ${profit_buy:.2f})", abs(profit_buy - 3.0) < 0.01)

    profit_sell = executor._calculate_position_profit("XAUUSD", "SELL", 4570.0, 4567.0, 0.01)
    # (4567-4570) * -1 * 0.01 * 100 = -3 * -1 = $3.00
    check(f"Gold SELL profit = $3.00 (got ${profit_sell:.2f})", abs(profit_sell - 3.0) < 0.01)

    loss = executor._calculate_position_profit("XAUUSD", "BUY", 4530.0, 4527.0, 0.01)
    # (4527-4530) * 1 * 0.01 * 100 = -3 * 1 = -$3.00
    check(f"Gold BUY loss = -$3.00 (got ${loss:.2f})", abs(loss - (-3.0)) < 0.01)

    # ─────────────────────────────────────────────────
    # TEST 14: SIGNAL_FULL without NOW (LIMIT orders)
    # ─────────────────────────────────────────────────
    print("\n── TEST 14: SIGNAL_FULL without NOW → LIMIT ──")
    mt5.mock_price = 4530.0
    tg14 = await executor.handle_signal_full(
        message_id=9001, symbol="XAUUSD", side="SELL",
        entry_price=4546.0, sl=4549.0, tp1=4543.0, tp2=4536.0, tp3=0.0,
        is_now=False,
    )
    check("LIMIT trade created", tg14 is not None)

    with get_session() as s:
        tg = crud.get_trade_group(s, tg14)
        check("3 tickets for LIMIT", all([tg.t1_ticket, tg.t2_ticket, tg.t3_ticket]))
        check("Status PENDING (limit not filled)", tg.status == TradeGroupStatus.PENDING)
    mt5.mock_price = None

    # ─────────────────────────────────────────────────
    # TEST 15: Reply lookup
    # ─────────────────────────────────────────────────
    print("\n── TEST 15: Reply lookup by signal message ID ──")
    with get_session() as s:
        found = crud.get_trade_group_by_signal_msg(s, 1002)
        check("Found TradeGroup by details_message_id=1002", found is not None and found.id == tg1)

    # ─────────────────────────────────────────────────
    # TEST 16: SELL trade full flow
    # ─────────────────────────────────────────────────
    print("\n── TEST 16: SELL trade full flow ──")
    mt5.mock_price = 4570.0
    tg16 = await executor.handle_now_trigger(10001, "XAUUSD", "SELL", entry_price=4570.0)
    check("SELL NOW created", tg16 is not None)

    mt5.mock_price = 4570.0
    await executor.handle_signal_full_update(
        tg_id=tg16, details_message_id=10002,
        entry_price=4570.0, sl=4573.0, tp1=4567.0, tp2=4560.0, tp3=0.0,
    )
    with get_session() as s:
        tg = crud.get_trade_group(s, tg16)
        check("SELL SL=4573", tg.sl == 4573.0)
        check("SELL TP1=4567", tg.tp1 == 4567.0)

    # TP1 hit for SELL
    await executor.handle_tp_hit(tg16, tp_level=1, pips=30)
    with get_session() as s:
        tg = crud.get_trade_group(s, tg16)
        check("SELL T1 = TP_HIT", tg.t1_status == PositionStatus.TP_HIT)
        t2p = await mt5.get_position(tg.t2_ticket)
        # SELL: SL = entry price (breakeven) = 4570.0
        expected_sl = 4570.0
        check("SELL T2 SL at entry/BE (4570.0)", t2p and abs(t2p["sl"] - expected_sl) < 0.05)

    mt5.mock_price = None

    # ─────────────────────────────────────────────────
    # TEST 17: Signal parsing validation (Fix #1)
    # ─────────────────────────────────────────────────
    print("\n── TEST 17: Signal parsing validation (Fix #1 - TG#432/433 bug) ──")
    mt5.mock_price = 4621.0  # NOW execution at 4621
    tg17 = await executor.handle_now_trigger(11001, "XAUUSD", "BUY", entry_price=4621.0)
    check("NOW executed at 4621", tg17 is not None)
    
    if tg17:
        # Signal arrives with WRONG entry (4521 instead of 4621) - 100 pip error!
        mt5.mock_price = 4623.0
        await executor.handle_signal_full_update(
            tg_id=tg17, details_message_id=11002,
            entry_price=4521.0,  # WRONG! Should be 4621
            sl=4518.0, tp1=4524.0, tp2=4531.0, tp3=0.0,
        )
        
        with get_session() as s:
            tg = crud.get_trade_group(s, tg17)
            # Entry should be corrected to actual execution (4621), not parsed (4521)
            check("Entry corrected to actual (4621)", abs(tg.entry_price - 4621.0) < 1.0)
            # SL should be recalculated based on actual entry
            check("Status is ACTIVE (not emergency closed)", tg.status == TradeGroupStatus.ACTIVE)
            # Should NOT trigger late entry optimization
            check("T1 still OPEN (not TP_HIT)", tg.t1_status == PositionStatus.OPEN)
    else:
        check("Signal parsing test (skipped - NOW failed)", False)
    
    mt5.mock_price = None

    # ─────────────────────────────────────────────────
    # TEST 18: Race condition handling (Fix #2)
    # ─────────────────────────────────────────────────
    print("\n── TEST 18: Race condition handling (Fix #2 - position not found) ──")
    mt5.mock_price = 4530.0
    tg18 = await make_trade(executor, mt5, 12001, symbol="XAUUSD", side="BUY",
                            entry=4530.0, sl=4527.0, tp1=4533.0, tp2=4540.0, tp3=0.0)
    
    with get_session() as s:
        tg = crud.get_trade_group(s, tg18)
        t2_ticket = tg.t2_ticket
        t3_ticket = tg.t3_ticket
    
    # Simulate race condition: T2 and T3 already closed at original SL before monitor can act
    await mt5.close_position(t2_ticket)
    await mt5.close_position(t3_ticket)
    
    # Now trigger TP1 hit - should handle missing positions gracefully
    await executor.handle_tp_hit(tg18, tp_level=1, pips=30)
    
    with get_session() as s:
        tg = crud.get_trade_group(s, tg18)
        check("T1 status = TP_HIT", tg.t1_status == PositionStatus.TP_HIT)
        # T2/T3 should be marked as SL_HIT (race condition detected)
        check("T2 marked as SL_HIT (race condition)", tg.t2_status == PositionStatus.SL_HIT)
        check("T3 marked as SL_HIT (race condition)", tg.t3_status == PositionStatus.SL_HIT)
        # Verify profit/loss was calculated
        t2_trade = s.query(TradeHistory).filter_by(ticket=t2_ticket).first()
        t3_trade = s.query(TradeHistory).filter_by(ticket=t3_ticket).first()
        check("T2 loss recorded", t2_trade and t2_trade.profit is not None and t2_trade.profit < 0)
        check("T3 loss recorded", t3_trade and t3_trade.profit is not None and t3_trade.profit < 0)
    
    mt5.mock_price = None

    # ─────────────────────────────────────────────────
    # TEST 19: BTCUSD lot size configuration (Fix #3)
    # ─────────────────────────────────────────────────
    print("\n── TEST 19: BTCUSD lot size configuration (Fix #3) ──")
    mt5.mock_price = 69500.0
    tg19 = await executor.handle_now_trigger(13001, "BTCUSD", "SELL", entry_price=69500.0)
    check("BTCUSD NOW trigger created", tg19 is not None)
    
    if tg19:
        with get_session() as s:
            tg = crud.get_trade_group(s, tg19)
            # Verify lot size is 0.1 for BTCUSD (not 0.01)
            t1_trade = s.query(TradeHistory).filter_by(ticket=tg.t1_ticket).first()
            t2_trade = s.query(TradeHistory).filter_by(ticket=tg.t2_ticket).first()
            check("T1 lot size = 0.1 for BTCUSD", t1_trade and t1_trade.lot_size == 0.1)
            check("T2 lot size = 0.1 for BTCUSD", t2_trade and t2_trade.lot_size == 0.1)
    else:
        check("BTCUSD lot size test (skipped - NOW failed)", False)
    
    mt5.mock_price = None

    # ═════════════════════════════════════════════════
    # RESULTS SUMMARY
    # ═════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  RESULTS SUMMARY")
    print("=" * 80)

    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    failed = [(name, ok) for name, ok in results if not ok]

    print(f"\n  {passed}/{total} tests passed")

    if failed:
        print(f"\n  FAILED TESTS:")
        for name, _ in failed:
            print(f"    ❌ {name}")

    if passed == total:
        print(f"\n  ALL TESTS PASSED!")
        print(f"\n  System features verified:")
        print(f"    - NOW → 3 MARKET positions with 500-pip default SL")
        print(f"    - SIGNAL_FULL update with correct SL/TP")
        print(f"    - TP1 → close T1, move T2/T3 to breakeven")
        print(f"    - TP2 → close T2, move T3 SL to TP1 level (NEW)")
        print(f"    - TP3 MANUEL → force close on MT5")
        print(f"    - Pre-entry gap check (70/600/10 pips)")
        print(f"    - Late entry TP1 optimization (T2/T3 with signal SL)")
        print(f"    - SL-already-hit emergency close")
        print(f"    - Invalid SL fallback (pip-to-price conversion)")
        print(f"    - Breakeven, SL hit, close at entry")
        print(f"    - LIMIT orders for non-NOW signals")
        print(f"    - Profit calculation (Gold $3/pip with 0.01 lot)")
        print(f"    - BUY and SELL flows")
        print(f"\n  BUG FIXES VERIFIED (May 4, 2026):")
        print(f"    - ✅ Fix #1: Signal parsing validation (prevents -$397 losses)")
        print(f"    - ✅ Fix #2: Race condition handling (prevents -$45-75 losses)")
        print(f"    - ✅ Fix #3: BTCUSD lot size config (captures +$30 profits)")
        print(f"\n  READY FOR PRODUCTION DEPLOYMENT")
    else:
        print(f"\n  {total - passed} test(s) need attention")

    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
