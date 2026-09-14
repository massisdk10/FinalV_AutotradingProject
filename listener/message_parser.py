"""
Station X — Message Parser
============================
Parses real Station X signal channel messages (French).

Signal Flow:
  1. NOW_TRIGGER:  "ACHAT XAUUSD NOW !"  (heads-up, no details)
  2. SIGNAL_FULL:  "🟢 J'ACHÈTE XAUUSD à 3131 🎯 TP1 : 3134 ..." (entry + TP + SL)
  3. TP_HIT:       "TP1 TOUCHÉ 🔥 +350 PIPS ✅"  (reply to SIGNAL_FULL)
  4. BREAKEVEN:    "Mettez votre SL BE ✅"          (reply to SIGNAL_FULL)
  5. CLOSE_TRADE:  "Clôturez NOW au prix d'entrée ✅" (reply to SIGNAL_FULL)
  6. SL_HIT:       "SL -350 pips"                   (reply to SIGNAL_FULL)
  7. MODIFY_SL:    "🔒 Modifier SL : 108 450"       (reply to SIGNAL_FULL)
  8. MODIFY_TP:    "MODIFICATION TP1 : 109 330"     (reply to SIGNAL_FULL)
"""

import re
import logging
from typing import Optional, Dict, Any
from enum import Enum

logger = logging.getLogger("MessageParser")


# ──────────────────────────────────────────────
# Message & Action Types
# ──────────────────────────────────────────────
class MessageType(Enum):
    NOW_TRIGGER = "NOW_TRIGGER"
    SIGNAL_FULL = "SIGNAL_FULL"
    TP_HIT = "TP_HIT"
    BREAKEVEN = "BREAKEVEN"
    CLOSE_TRADE = "CLOSE_TRADE"
    SL_HIT = "SL_HIT"
    MODIFY_SL = "MODIFY_SL"
    MODIFY_TP = "MODIFY_TP"
    INFO_ONLY = "INFO_ONLY"


# ──────────────────────────────────────────────
# Known Symbols
# ──────────────────────────────────────────────
SYMBOL_MAP = {
    "GOLD": "XAUUSD", "SILVER": "XAGUSD", "OR": "XAUUSD",
    "BITCOIN": "BTCUSD", "BTC": "BTCUSD",
}

ALL_SYMBOLS = [
    "XAUUSD", "XAGUSD", "BTCUSD", "NAS100", "US30", "US100", "SP500", "GER40",
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
    "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "GBPAUD", "GBPCAD", "GBPCHF",
    "EURAUD", "EURNZD", "GBPNZD", "AUDNZD", "AUDCAD", "CADJPY", "CHFJPY",
    "ETHUSD", "ETHUSDT", "BTCUSDT",
]


# ──────────────────────────────────────────────
# Price Parsing — handles "83 550", "3131.5", "102 300"
# ──────────────────────────────────────────────
def _parse_price(raw: str) -> Optional[float]:
    """Convert a space-separated or plain price string to float."""
    if not raw:
        return None
    # Remove spaces and commas
    cleaned = raw.replace(" ", "").replace(",", "").strip()
    # BUG 7 FIX: Strip any trailing non-numeric characters (e.g., "467»" → "467")
    cleaned = re.sub(r'[^\d.]', '', cleaned)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_price_after(text: str, keyword_pattern: str) -> Optional[float]:
    """Extract a price that follows a keyword pattern, handling space-separated numbers."""
    match = re.search(keyword_pattern + r'\s*[:\=→]?\s*([\d][\d\s]*[\d](?:[\.,]\d+)?|\d+(?:[\.,]\d+)?)', text)
    if match:
        return _parse_price(match.group(1))
    return None


# ──────────────────────────────────────────────
# Symbol Extraction
# ──────────────────────────────────────────────
def _extract_symbol(text: str) -> Optional[str]:
    """Extract trading symbol from text, handling aliases."""
    text_upper = text.upper()

    # Direct match
    for sym in ALL_SYMBOLS:
        if sym in text_upper:
            return sym

    # Alias match (GOLD, BITCOIN, OR, BTC)
    for alias, sym in SYMBOL_MAP.items():
        if re.search(r'\b' + alias + r'\b', text_upper):
            return sym

    return None


# ══════════════════════════════════════════════
# MAIN CLASSIFIER
# ══════════════════════════════════════════════
def classify_message(text: str, reply_to_msg_id: int = None) -> Dict[str, Any]:
    """
    Classify a Station X Telegram message.

    Returns a dict with "type" and relevant parsed data.
    If the message is a reply (reply_to_msg_id is set), it checks for
    reply-based actions (TP hit, BE, close, SL hit, modify).
    """
    if not text or not text.strip():
        return {"type": MessageType.INFO_ONLY}

    text_stripped = text.strip()
    text_upper = text_stripped.upper()

    # ── Reply-based messages (must have reply_to) ──
    if reply_to_msg_id:
        result = _classify_reply(text_stripped, text_upper, reply_to_msg_id)
        if result:
            return result

    # ── SIGNAL_FULL: "🟢 J'ACHÈTE XAUUSD à 3131 🎯 TP1 : 3134 ... 🔒 SL : 3128" ──
    signal = _parse_signal_full(text_stripped, text_upper)
    if signal:
        return signal

    # ── NOW_TRIGGER: "ACHAT XAUUSD NOW !" ──
    trigger = _parse_now_trigger(text_stripped, text_upper)
    if trigger:
        return trigger

    return {"type": MessageType.INFO_ONLY}


# ══════════════════════════════════════════════
# NOW TRIGGER — "ACHAT XAUUSD NOW !"
# ══════════════════════════════════════════════
def _parse_now_trigger(text: str, text_upper: str) -> Optional[Dict[str, Any]]:
    """
    Detect simple NOW trigger messages.
    Examples:
      "ACHAT XAUUSD NOW !"
      "VENTE BITCOIN NOW !"
      "ACHAT BITCOIN NOW !"
    """
    if "NOW" not in text_upper:
        return None

    side = None
    if re.search(r'\b(ACHAT|BUY)\b', text_upper):
        side = "BUY"
    elif re.search(r'\b(VENTE|SELL)\b', text_upper):
        side = "SELL"

    if not side:
        return None

    symbol = _extract_symbol(text)
    if not symbol:
        return None

    return {
        "type": MessageType.NOW_TRIGGER,
        "symbol": symbol,
        "side": side,
    }


# ══════════════════════════════════════════════
# SIGNAL_FULL — Full signal with entry + TP/SL
# ══════════════════════════════════════════════
def _parse_signal_full(text: str, text_upper: str) -> Optional[Dict[str, Any]]:
    """
    Detect full signal messages containing entry price, TPs, and SL.
    Examples:
      "🟢 J'ACHÈTE XAUUSD à 3131\n\n🎯 TP1 : 3134\n🎯 TP2 : 3140\n🎯 TP3 : Ouvert\n\n🔒 SL : 3128"
      "🛑 JE VENDS BTCUSD à 83 550\n\n🎯 TP1 : 83 200\n🎯 TP2 : 82 500\n🎯 TP3 : Ouvert\n\n🔒 SL : 83 900"
      "🛑 JE VENDS NAS100 à 19 110\n\n🎯 TP1 : 19 075\n..."
    """
    # Must contain TP1 and SL to be a full signal
    has_tp = re.search(r'TP\s*1', text_upper)
    has_sl = re.search(r'(SL|STOP\s*LOSS)', text_upper)
    if not has_tp or not has_sl:
        return None

    # Determine side
    side = None
    if re.search(r"(J.ACH[EÈ]TE|ACHAT|BUY|\bLONG\b)", text_upper):
        side = "BUY"
    elif re.search(r"(JE\s*VENDS|J.VENDS|VENTE|SELL|\bSHORT\b)", text_upper):
        side = "SELL"

    if not side:
        return None

    # Extract symbol
    symbol = _extract_symbol(text)
    if not symbol:
        return None

    # Extract entry price — "à 3131" or "à 83 550"
    entry_price = _extract_price_after(text_upper, r'[ÀA]\s')
    if not entry_price:
        # Try after symbol name
        entry_price = _extract_price_after(text_upper, symbol)

    # Extract TP1, TP2, TP3
    tp1 = _extract_price_after(text_upper, r'TP\s*1')
    tp2 = _extract_price_after(text_upper, r'TP\s*2')
    tp3 = _extract_price_after(text_upper, r'TP\s*3')

    # TP3 "Ouvert" means open/runner — no fixed TP3
    if tp3 is None and re.search(r'TP\s*3\s*[:\=→]?\s*(OUVERT|OPEN|LIBRE)', text_upper):
        tp3 = 0.0  # 0 = open runner

    # Extract SL
    sl = _extract_price_after(text_upper, r'(?:🔒\s*)?SL')
    if not sl:
        sl = _extract_price_after(text_upper, r'STOP\s*LOSS')

    # Must have at least SL and TP1
    if not sl or not tp1:
        return None

    return {
        "type": MessageType.SIGNAL_FULL,
        "symbol": symbol,
        "side": side,
        "entry_price": entry_price or 0.0,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2 or 0.0,
        "tp3": tp3 if tp3 is not None else 0.0,
    }


# ══════════════════════════════════════════════
# REPLY CLASSIFIER
# ══════════════════════════════════════════════
def _classify_reply(text: str, text_upper: str, reply_to: int) -> Optional[Dict[str, Any]]:
    """
    Classify reply messages to a signal.
    All these reply to the SIGNAL_FULL message.
    """

    # ── TP HIT: "TP1 TOUCHÉ 🔥 +350 PIPS ✅" or "TP3 MANUEL 🔥 +1700 PIPS ✅" ──
    tp_match = re.search(r'TP\s*([123])\s*(TOUCH|ATTEINT|VALID|MANUEL|HIT|PRIS)', text_upper)
    if tp_match:
        tp_level = int(tp_match.group(1))
        is_manual = "MANUEL" in text_upper
        pips_match = re.search(r'[+\-]?\s*(\d[\d\s]*)\s*PIPS?', text_upper)
        pips = 0
        if pips_match:
            pips = int(pips_match.group(1).replace(" ", ""))
        return {
            "type": MessageType.TP_HIT,
            "reply_to": reply_to,
            "tp_level": tp_level,
            "is_manual": is_manual,
            "pips": pips,
        }

    # ── BREAKEVEN: "Mettez votre SL BE ✅" ──
    if re.search(r'(SL\s*BE|BREAK\s*EVEN|SL\s*À?\s*(BE|BREAKEVEN|ENTR[ÉE]E))', text_upper):
        return {
            "type": MessageType.BREAKEVEN,
            "reply_to": reply_to,
        }

    # ── CLOSE TRADE: "Clôturez NOW au prix d'entrée ✅" or "CLOSE cette position" ──
    if re.search(r'(CL[ÔO]TUR|\bCLOSE\b|ON\s*FERME|ON\s*COUPE|ON\s*SORT|S[ÉE]CURIS)', text_upper):
        return {
            "type": MessageType.CLOSE_TRADE,
            "reply_to": reply_to,
        }

    # ── SL HIT: "SL -350 pips" ──
    sl_loss = re.search(r'SL\s*[-–]\s*(\d[\d\s]*)\s*PIPS?', text_upper)
    if sl_loss:
        pips = int(sl_loss.group(1).replace(" ", ""))
        return {
            "type": MessageType.SL_HIT,
            "reply_to": reply_to,
            "pips": pips,
        }

    # ── MODIFY SL: "🔒 Modifier SL : 108 450" or bare "SL : 3120" in reply ──
    modify_sl = re.search(r'(MODIFIER?\s*SL|SL\s*MODIFI)', text_upper)
    if modify_sl:
        new_sl = _extract_price_after(text_upper, r'(?:MODIFIER?\s*)?SL')
        if new_sl:
            return {
                "type": MessageType.MODIFY_SL,
                "reply_to": reply_to,
                "new_sl": new_sl,
            }

    # Bare "SL : <price>" in a reply context = MODIFY_SL
    bare_sl = re.search(r'^[^\w]*SL\s*[:\=→]\s*(\d[\d\s]*\d(?:[\.,]\d+)?|\d+(?:[\.,]\d+)?)', text_upper)
    if bare_sl:
        new_sl = _parse_price(bare_sl.group(1))
        if new_sl:
            return {
                "type": MessageType.MODIFY_SL,
                "reply_to": reply_to,
                "new_sl": new_sl,
            }

    # ── MODIFY TP: "MODIFICATION TP1 : 109 330" or bare "TP2 : 3155" in reply ──
    modify_tp = re.search(r'MODIFI\w*\s*TP\s*([123])', text_upper)
    if modify_tp:
        tp_level = int(modify_tp.group(1))
        new_tp = _extract_price_after(text_upper, r'TP\s*' + str(tp_level))
        if new_tp:
            return {
                "type": MessageType.MODIFY_TP,
                "reply_to": reply_to,
                "tp_level": tp_level,
                "new_tp": new_tp,
            }

    # Bare "TPx : <price>" in a reply context = MODIFY_TP
    bare_tp = re.search(r'TP\s*([123])\s*[:\=→]\s*([\d][\d\s]*[\d](?:[\.,]\d+)?|\d+(?:[\.,]\d+)?)', text_upper)
    if bare_tp:
        tp_level = int(bare_tp.group(1))
        new_tp = _parse_price(bare_tp.group(2))
        if new_tp:
            return {
                "type": MessageType.MODIFY_TP,
                "reply_to": reply_to,
                "tp_level": tp_level,
                "new_tp": new_tp,
            }

    return None
