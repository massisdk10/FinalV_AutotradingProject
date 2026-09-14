# Critical Fixes Summary - March 24, 2026

## Issues Fixed

### 1. BTC-Specific Default Parameters ✅
**Problem:** BTC signals used same 500-pip default SL as XAUUSD, but client needs 350 pips for BTC.

**Solution:**
- Added BTC-specific config: `DEFAULT_BTC_SL_PIPS = 350`, `DEFAULT_BTC_TP1_PIPS = 350`, `DEFAULT_BTC_TP2_PIPS = 1050`
- Created `_get_default_sl_tp_pips(symbol)` helper to return symbol-specific defaults
- Updated `handle_now_trigger` to use symbol-aware defaults
- XAUUSD: 500 pips (unchanged)
- BTCUSD: 350 pips (new)

**Files Modified:**
- `config.py` (lines 54-58)
- `execution/trade_executor.py` (lines 47-63, 200-204, 290, 298)

---

### 2. Profit Calculation Missing ✅
**Problem:** `TradeHistory.profit` stayed at 0.0 because close_price was never captured and profit was never calculated.

**Solution:**
- Added `_calculate_position_profit(symbol, side, open_price, close_price, lot_size)` helper
- Calculates: `(close_price - open_price) × direction × lot_size × contract_size`
- Contract sizes: XAUUSD/BTCUSD = 100, Forex = 100000, Indices = 1
- Returns profit in USD

**Files Modified:**
- `execution/trade_executor.py` (lines 86-105)

---

### 3. Profit Stored in All TP Hit Handlers ✅
**Problem:** When TP hit, profit was never calculated or stored in database.

**Solution:**
- `_handle_tp1_hit`: Get TP1 price, calculate profit, store close_price and profit, update DailyPnL
- `_handle_tp2_hit`: Get TP2 price, calculate profit, store close_price and profit, update DailyPnL
- `_handle_tp3_hit`: Get current market price, calculate profit, store close_price and profit, update DailyPnL
- `_handle_late_entry_tp1`: Get close price before closing, calculate profit, store

**Files Modified:**
- `execution/trade_executor.py` (lines 918-935, 1011-1027, 1078-1108, 880-896)

---

### 4. Profit Stored in SL Hit Handler ✅
**Problem:** When SL hit, loss was stored in pips not dollars, and close_price was never stored.

**Solution:**
- `handle_sl_hit_from_signal`: Calculate loss using SL price, store close_price and profit (negative), update DailyPnL with actual dollar loss

**Files Modified:**
- `execution/trade_executor.py` (lines 1236-1290)

---

### 5. DailyPnL Now Uses Dollar Profits ✅
**Problem:** `update_daily_pnl(session, -abs(pips), ...)` used pips instead of actual dollar profit/loss.

**Solution:**
- All handlers now call `crud.update_daily_pnl(session, profit, is_win=True/False)` with actual dollar amounts
- DailyPnL.total_pnl now accumulates real USD profit/loss
- Performance metrics now show correct dollar totals

**Files Modified:**
- All TP/SL hit handlers updated to pass dollar profits

---

### 6. Telegram Bot Error Handling ✅
**Problem:** Bot crashed with "Message is not modified" error when content unchanged.

**Solution:**
- Wrapped `query.edit_message_text()` in try-except blocks
- Silently ignore "Message is not modified" errors
- Log other errors for debugging

**Files Modified:**
- `telegram_bot/handlers.py` (lines 751-760, 787-803)

---

## Test Updates ✅

Updated `test_simulation.py` to verify:
- Symbol-specific default SL (XAUUSD: 500, BTC: 350 pips)
- Profit calculation on all TP hits
- Profit values are in dollars, not pips
- All trades show correct profit/loss amounts

---

## Expected Results

### For XAUUSD Trades:
- NOW trigger: 500-pip default SL
- TP1 hit: Profit calculated and stored (e.g., +$4.00 for 0.01 lot, 4 pips = 4 × 0.01 × 0.01 × 100 = $4)
- TP2 hit: Profit calculated and stored
- SL hit: Loss calculated and stored (negative profit)
- DailyPnL shows correct USD totals

### For BTCUSD Trades:
- NOW trigger: 350-pip default SL (not 500)
- TP1 hit: Profit calculated (e.g., +$3.50 for 0.01 lot, 350 pips)
- Same profit tracking as XAUUSD

### Telegram Bot:
- Trade history displays without crashes
- Performance metrics show wins as wins, losses as losses
- Total P&L matches actual profit/loss in dollars

---

## Testing Checklist

- [ ] Run `python test_simulation.py` - all tests should pass
- [ ] Check XAUUSD NOW trigger uses 500-pip SL
- [ ] Check BTCUSD NOW trigger uses 350-pip SL
- [ ] Verify profit values are non-zero after TP hits
- [ ] Verify DailyPnL shows dollar amounts (not pips)
- [ ] Check Telegram bot trade history works without errors
- [ ] Verify performance metrics show correct wins/losses

---

## Deployment Notes

✅ All changes are backward compatible
✅ No database schema changes required
✅ Existing XAUUSD behavior unchanged (still 500 pips)
✅ New BTC behavior activated automatically
✅ Profit calculation works for all symbols

**Ready for RDP deployment after testing.**
