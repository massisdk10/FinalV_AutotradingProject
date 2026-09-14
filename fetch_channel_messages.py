"""
Fetch Messages from Signal Channel by Date Range
=================================================
Uses Telethon to retrieve messages from the configured signal channel
within a specific date range for analysis and debugging.
"""

import asyncio
import sys
import json
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient
from listener.message_parser import classify_message, MessageType
import config

# Color codes
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"


async def fetch_messages(start_date=None, end_date=None, limit=500, save_to_file=True):
    """
    Fetch and display messages from signal channel within date range.
    
    Args:
        start_date: Start date (YYYY-MM-DD) or datetime object. Default: 7 days ago
        end_date: End date (YYYY-MM-DD) or datetime object. Default: now
        limit: Maximum messages to fetch. Default: 500
        save_to_file: Save results to JSON file. Default: True
    """
    
    # Parse dates (make timezone-aware to match Telegram timestamps)
    if start_date is None:
        start_dt = datetime.now(timezone.utc) - timedelta(days=7)
    elif isinstance(start_date, str):
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        start_dt = start_date if start_date.tzinfo else start_date.replace(tzinfo=timezone.utc)
    
    if end_date is None:
        end_dt = datetime.now(timezone.utc)
    elif isinstance(end_date, str):
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
    else:
        end_dt = end_date if end_date.tzinfo else end_date.replace(tzinfo=timezone.utc)
    
    print(f"\n{CYAN}╔════════════════════════════════════════════════════════════════════╗")
    print(f"║  📥 FETCHING MESSAGES FROM SIGNAL CHANNEL                         ║")
    print(f"╚════════════════════════════════════════════════════════════════════╝{RESET}\n")
    
    print(f"Connecting to Telegram...")
    print(f"Channel ID: {config.SIGNAL_CHANNEL_ID}")
    print(f"Phone: {config.TELEGRAM_PHONE}")
    print(f"Date Range: {start_dt.strftime('%Y-%m-%d %H:%M')} to {end_dt.strftime('%Y-%m-%d %H:%M')}")
    print(f"Max Messages: {limit}\n")
    
    try:
        # Create Telethon client
        client = TelegramClient(
            'session_fetch_messages',
            config.TELEGRAM_API_ID,
            config.TELEGRAM_API_HASH
        )
        
        await client.start(phone=config.TELEGRAM_PHONE)
        print(f"{GREEN}✅ Connected to Telegram{RESET}\n")
        
        # Fetch channel entity
        channel = await client.get_entity(config.SIGNAL_CHANNEL_ID)
        print(f"Channel: {channel.title}")
        print(f"Fetching last 50 messages...\n")
        
        # Fetch messages within date range
        messages = []
        count = 0
        async for message in client.iter_messages(channel, limit=limit):
            # Check if message is within date range
            if message.date < start_dt:
                break  # Older than start date, stop
            if message.date <= end_dt:
                messages.append(message)
                count += 1
        
        print(f"Fetched {count} messages within date range...\n")
        
        print(f"{BLUE}{'=' * 70}{RESET}")
        print(f"{GREEN}Found {len(messages)} messages in date range{RESET}")
        print(f"{BLUE}{'=' * 70}{RESET}\n")
        
        # Prepare data for JSON export
        messages_data = []
        
        # Display messages in reverse order (oldest first)
        for msg in reversed(messages):
            print(f"\n{YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
            print(f"{CYAN}[Message ID: {msg.id}]{RESET}")
            print(f"Date: {msg.date.strftime('%Y-%m-%d %H:%M:%S')}")
            
            reply_to_id = None
            if msg.reply_to:
                reply_to_id = msg.reply_to.reply_to_msg_id
                print(f"Reply to: Message {reply_to_id}")
            
            msg_data = {
                "id": msg.id,
                "date": msg.date.strftime('%Y-%m-%d %H:%M:%S'),
                "timestamp": msg.date.timestamp(),
                "reply_to": reply_to_id,
                "text": msg.text,
                "parsed": None
            }
            
            if msg.text:
                # Display message text
                text_preview = msg.text[:200] if len(msg.text) > 200 else msg.text
                print(f"\nText:\n{text_preview}")
                if len(msg.text) > 200:
                    print(f"... ({len(msg.text)} chars total)")
                
                # Parse and classify
                result = classify_message(msg.text, reply_to_id)
                msg_type = result.get("type")
                
                # Store parsed data
                msg_data["parsed"] = {
                    "type": msg_type.value if hasattr(msg_type, 'value') else str(msg_type),
                    "data": {k: v for k, v in result.items() if k != 'type'}
                }
                
                if msg_type != MessageType.INFO_ONLY:
                    print(f"\n{GREEN}📊 Parser Result:{RESET}")
                    print(f"  Type: {msg_type.value if hasattr(msg_type, 'value') else msg_type}")
                    
                    if msg_type == MessageType.NOW_TRIGGER:
                        print(f"  Symbol: {result.get('symbol')}")
                        print(f"  Side: {result.get('side')}")
                    
                    elif msg_type == MessageType.SIGNAL_FULL:
                        print(f"  Symbol: {result.get('symbol')}")
                        print(f"  Side: {result.get('side')}")
                        print(f"  Entry: {result.get('entry_price')}")
                        print(f"  SL: {result.get('sl')}")
                        print(f"  TP1: {result.get('tp1')}")
                        print(f"  TP2: {result.get('tp2')}")
                        print(f"  TP3: {result.get('tp3', 'Open')}")
                    
                    elif msg_type == MessageType.TP_HIT:
                        print(f"  TP Level: {result.get('tp_level')}")
                        print(f"  Pips: +{result.get('pips')}")
                        print(f"  Manual: {result.get('is_manual', False)}")
                    
                    elif msg_type == MessageType.BREAKEVEN:
                        print(f"  Action: Move SL to breakeven")
                    
                    elif msg_type == MessageType.SL_HIT:
                        print(f"  Pips: -{result.get('pips')}")
                    
                    elif msg_type == MessageType.MODIFY_SL:
                        print(f"  New SL: {result.get('new_sl')}")
                    
                    elif msg_type == MessageType.MODIFY_TP:
                        print(f"  TP Level: {result.get('tp_level')}")
                        print(f"  New TP: {result.get('new_tp')}")
                else:
                    print(f"\n{YELLOW}ℹ️  INFO_ONLY (ignored by bot){RESET}")
            else:
                print(f"\n{YELLOW}(No text - media or other content){RESET}")
            
            messages_data.append(msg_data)
        
        print(f"\n{BLUE}{'=' * 70}{RESET}")
        print(f"{GREEN}✅ Fetch complete!{RESET}\n")
        
        # Statistics
        now_count = sum(1 for m in messages if m.text and classify_message(m.text).get("type") == MessageType.NOW_TRIGGER)
        signal_count = sum(1 for m in messages if m.text and classify_message(m.text).get("type") == MessageType.SIGNAL_FULL)
        reply_count = sum(1 for m in messages if m.text and m.reply_to and classify_message(m.text, m.reply_to.reply_to_msg_id).get("type") != MessageType.INFO_ONLY)
        info_count = sum(1 for m in messages if m.text and classify_message(m.text, m.reply_to.reply_to_msg_id if m.reply_to else None).get("type") == MessageType.INFO_ONLY)
        
        print(f"\n{CYAN}📊 Message Statistics:{RESET}")
        print(f"  NOW Triggers: {now_count}")
        print(f"  SIGNAL_FULL: {signal_count}")
        print(f"  Reply Actions: {reply_count}")
        print(f"  Info/Ignored: {info_count}")
        print(f"  Total: {len(messages)}\n")
        
        # Save to JSON file
        if save_to_file:
            filename = f"channel_messages_{start_dt.strftime('%Y%m%d')}_{end_dt.strftime('%Y%m%d')}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump({
                    "fetch_date": datetime.now().isoformat(),
                    "date_range": {
                        "start": start_dt.isoformat(),
                        "end": end_dt.isoformat()
                    },
                    "channel_id": config.SIGNAL_CHANNEL_ID,
                    "total_messages": len(messages),
                    "statistics": {
                        "now_triggers": now_count,
                        "signal_full": signal_count,
                        "reply_actions": reply_count,
                        "info_only": info_count
                    },
                    "messages": messages_data
                }, f, indent=2, ensure_ascii=False)
            
            print(f"{GREEN}💾 Saved to: {filename}{RESET}\n")
        
        await client.disconnect()
        
    except Exception as e:
        print(f"\n{RED}❌ Error: {e}{RESET}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Fetch messages from signal channel')
    parser.add_argument('--start', type=str, help='Start date (YYYY-MM-DD). Default: 7 days ago')
    parser.add_argument('--end', type=str, help='End date (YYYY-MM-DD). Default: today')
    parser.add_argument('--limit', type=int, default=500, help='Max messages to fetch. Default: 500')
    parser.add_argument('--no-save', action='store_true', help='Do not save to JSON file')
    
    args = parser.parse_args()
    
    try:
        success = asyncio.run(fetch_messages(
            start_date=args.start,
            end_date=args.end,
            limit=args.limit,
            save_to_file=not args.no_save
        ))
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print(f"\n\n{YELLOW}Cancelled by user.{RESET}")
        sys.exit(0)
