import asyncio
import logging
from typing import Optional, Dict, Any
import MetaTrader5 as mt5
import config

logger = logging.getLogger("MT5Connector")


class MT5Connector:
    """Handles all communication with MetaTrader 5 terminal."""

    def __init__(self):
        self._connected = False
        self._logged_in = False

    # ──────────────────────────────────────────
    # Connection
    # ──────────────────────────────────────────
    async def initialize(self) -> bool:
        """Initialize MT5 terminal connection."""
        def _init():
            path = config.MT5_PATH if config.MT5_PATH else None
            if path:
                return mt5.initialize(path)
            return mt5.initialize()

        result = await asyncio.to_thread(_init)
        if result:
            self._connected = True
            logger.info("✅ MT5 terminal initialized successfully")
        else:
            error = mt5.last_error()
            logger.error(f"❌ MT5 initialization failed: {error}")
        return result

    async def login(self, account_id: str, password: str, server: str) -> bool:
        """Login to MT5 account."""
        def _login():
            return mt5.login(int(account_id), password=password, server=server)

        if not self._connected:
            await self.initialize()

        result = await asyncio.to_thread(_login)
        if result:
            self._logged_in = True
            logger.info(f"✅ Logged in to account {account_id} on {server}")
        else:
            error = mt5.last_error()
            logger.error(f"❌ Login failed: {error}")
        return result

    async def logout(self):
        """Shutdown MT5 connection."""
        def _shutdown():
            mt5.shutdown()

        await asyncio.to_thread(_shutdown)
        self._connected = False
        self._logged_in = False
        logger.info("🔒 MT5 connection closed")

    @property
    def is_connected(self) -> bool:
        return self._connected and self._logged_in

    # ──────────────────────────────────────────
    # Account Info
    # ──────────────────────────────────────────
    async def get_account_info(self) -> Optional[Dict[str, Any]]:
        def _info():
            info = mt5.account_info()
            if info:
                return info._asdict()
            return None
        return await asyncio.to_thread(_info)
    
    async def check_autotrading(self) -> bool:
        """Check if AutoTrading is enabled in the MT5 terminal."""
        def _check():
            info = mt5.terminal_info()
            if info:
                return info.trade_allowed
            return False
        return await asyncio.to_thread(_check)

    # ──────────────────────────────────────────
    # Symbol Info
    # ──────────────────────────────────────────
    async def get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        def _info():
            info = mt5.symbol_info(symbol)
            if info:
                return info._asdict()
            return None
        return await asyncio.to_thread(_info)

    async def ensure_symbol_visible(self, symbol: str) -> bool:
        def _ensure():
            info = mt5.symbol_info(symbol)
            if info is None:
                return False
            if not info.visible:
                mt5.symbol_select(symbol, True)
            return True
        return await asyncio.to_thread(_ensure)

    # ──────────────────────────────────────────
    # Order Execution
    # ──────────────────────────────────────────
    async def open_position(
        self,
        symbol: str,
        side: str,
        lot_size: float,
        sl: float = None,
        tp: float = None,
        comment: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Open a market position. Returns order result dict or None."""

        def _open():
            mt5.symbol_select(symbol, True)
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                logger.error(f"❌ Cannot get tick for {symbol}")
                return None

            order_type = mt5.ORDER_TYPE_BUY if side.upper() == "BUY" else mt5.ORDER_TYPE_SELL
            price = tick.ask if side.upper() == "BUY" else tick.bid

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": lot_size,
                "type": order_type,
                "price": price,
                "deviation": 20,
                "magic": 123456,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            if sl is not None:
                request["sl"] = sl
            if tp is not None:
                request["tp"] = tp

            result = mt5.order_send(request)
            if result is None:
                logger.error(f"❌ order_send returned None for {symbol}")
                return None
            return result._asdict()

        return await asyncio.to_thread(_open)

    async def place_limit_order(
        self,
        symbol: str,
        side: str,
        lot_size: float,
        price: float,
        sl: float = None,
        tp: float = None,
        comment: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Place a pending limit order (BUY_LIMIT / SELL_LIMIT)."""

        def _place():
            mt5.symbol_select(symbol, True)
            order_type = mt5.ORDER_TYPE_BUY_LIMIT if side.upper() == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT

            request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": symbol,
                "volume": lot_size,
                "type": order_type,
                "price": price,
                "deviation": 20,
                "magic": 123456,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_RETURN,
            }
            if sl is not None:
                request["sl"] = sl
            if tp is not None:
                request["tp"] = tp

            result = mt5.order_send(request)
            if result is None:
                logger.error(f"❌ limit order_send returned None for {symbol}")
                return None
            return result._asdict()

        return await asyncio.to_thread(_place)

    async def cancel_order(self, order_ticket: int) -> Optional[Dict[str, Any]]:
        """Cancel a pending order by ticket."""
        def _cancel():
            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": order_ticket,
            }
            result = mt5.order_send(request)
            if result is None:
                return None
            return result._asdict()
        return await asyncio.to_thread(_cancel)

    async def close_position(self, ticket: int) -> Optional[Dict[str, Any]]:
        """Close a position by ticket."""
        def _close():
            position = mt5.positions_get(ticket=ticket)
            if not position:
                logger.warning(f"⚠️ Position {ticket} not found")
                return None

            pos = position[0]
            order_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
            tick = mt5.symbol_info_tick(pos.symbol)
            if tick is None:
                return None

            price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": pos.symbol,
                "volume": pos.volume,
                "type": order_type,
                "position": ticket,
                "price": price,
                "deviation": 20,
                "magic": 123456,
                "comment": "close",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            if result is None:
                return None
            return result._asdict()

        return await asyncio.to_thread(_close)

    async def modify_position(
        self, ticket: int, sl: float = None, tp: float = None
    ) -> Optional[Dict[str, Any]]:
        """Modify SL/TP of an existing position."""
        def _modify():
            position = mt5.positions_get(ticket=ticket)
            if not position:
                logger.warning(f"⚠️ Position {ticket} not found for modification")
                return None

            pos = position[0]
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "symbol": pos.symbol,
                "position": ticket,
                "sl": sl if sl is not None else pos.sl,
                "tp": tp if tp is not None else pos.tp,
            }
            result = mt5.order_send(request)
            if result is None:
                return None
            return result._asdict()

        return await asyncio.to_thread(_modify)

    async def get_position(self, ticket: int) -> Optional[Dict[str, Any]]:
        """Get a single position by ticket."""
        def _get():
            positions = mt5.positions_get(ticket=ticket)
            if positions:
                return positions[0]._asdict()
            return None
        return await asyncio.to_thread(_get)

    async def get_open_positions(self) -> list:
        """Get all open positions."""
        def _get():
            positions = mt5.positions_get()
            if positions:
                return [p._asdict() for p in positions]
            return []
        return await asyncio.to_thread(_get)

    async def get_symbol_price(self, symbol: str) -> Optional[Dict[str, float]]:
        """Get current bid/ask for a symbol."""
        def _get():
            tick = mt5.symbol_info_tick(symbol)
            if tick:
                return {"bid": tick.bid, "ask": tick.ask}
            return None
        return await asyncio.to_thread(_get)
