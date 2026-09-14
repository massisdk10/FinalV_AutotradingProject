"""
Station X Message Fetcher — Diagnostic Tool
============================================
Fetches today's messages from the Station X channel to analyze
the message-reply structure and verify our parsing logic.
"""

import asyncio
import sys
import json
from datetime import datetime, timezone
from telethon import TelegramClient
from listener.message_parser import classify_message
import config

async def fetch_today_messages():
    """Fetch all messages from today and show their structure."""
    
    # Connect to Telegram
    client = TelegramClient(
        "diagnostic_session",
        config.TELEGRAM_API_ID,
        config.TELEGRAM_API_HASH,
    )
    
    await client.start(phone=config.TELEGRAM_PHONE)
    
    print("=" * 80)
    print("📡 Station X Message Fetcher")
    print("=" * 80)
    
    try:
        # Get channel entity
        entity = await client.get_entity(config.SIGNAL_CHANNEL_ID)
        print(f"Channel: {getattr(entity, 'title', 'Unknown')} (ID: {config.SIGNAL_CHANNEL_ID})\n")
        
        now = datetime.now(timezone.utc)
        
        print(f"Fetching last 200 messages...")
        print(f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
        
        # Fetch last 200 messages
        messages = []
        async for msg in client.iter_messages(entity, limit=200):
            if msg.text:
                messages.append(msg)
        
        # Reverse to show oldest first
        messages.reverse()
        
        print(f"✅ Found {len(messages)} messages\n")
        print("=" * 80)
        
        # Build JSON structure
        messages_data = []
        
        for msg in messages:
            msg_id = msg.id
            reply_to = msg.reply_to.reply_to_msg_id if msg.reply_to else None
            text = msg.text
            timestamp = msg.date.strftime('%Y-%m-%d %H:%M:%S')
            
            # Classify the message
            result = classify_message(msg.text, reply_to)
            msg_type = result.get("type")
            
            # Build message object
            msg_obj = {
                "msg_id": msg_id,
                "reply_to_msg_id": reply_to,
                "timestamp": timestamp,
                "text": text,
                "classification": {
                    "type": msg_type.name,
                    "details": {}
                }
            }
            
            # Add classification details
            if msg_type.name == "SIGNAL_FULL":
                msg_obj["classification"]["details"] = {
                    "symbol": result.get('symbol'),
                    "side": result.get('side'),
                    "entry_price": result.get('entry_price'),
                    "sl": result.get('sl'),
                    "tp1": result.get('tp1'),
                    "tp2": result.get('tp2'),
                    "tp3": result.get('tp3')
                }
            elif msg_type.name == "NOW_TRIGGER":
                msg_obj["classification"]["details"] = {
                    "symbol": result.get('symbol'),
                    "side": result.get('side')
                }
            elif msg_type.name == "TP_HIT":
                msg_obj["classification"]["details"] = {
                    "tp_level": result.get('tp_level'),
                    "is_manual": result.get('is_manual'),
                    "pips": result.get('pips')
                }
            elif msg_type.name == "SL_HIT":
                msg_obj["classification"]["details"] = {
                    "pips": result.get('pips')
                }
            elif msg_type.name == "MODIFY_SL":
                msg_obj["classification"]["details"] = {
                    "new_sl": result.get('new_sl')
                }
            elif msg_type.name == "MODIFY_TP":
                msg_obj["classification"]["details"] = {
                    "tp_level": result.get('tp_level'),
                    "new_tp": result.get('new_tp')
                }
            elif msg_type.name == "BREAKEVEN":
                msg_obj["classification"]["details"] = {"action": "move_sl_to_be"}
            elif msg_type.name == "CLOSE_TRADE":
                msg_obj["classification"]["details"] = {"action": "close_positions"}
            
            messages_data.append(msg_obj)
            
            # Print summary
            line = f"[{msg_id}]"
            if reply_to:
                line += f" ↪️ Reply to [{reply_to}]"
            line += f" | {msg_type.name}"
            if msg_obj["classification"]["details"]:
                line += f" | {json.dumps(msg_obj['classification']['details'])}"
            print(line)
        
        # Save JSON
        json_path = "messages.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(messages_data, f, indent=2, ensure_ascii=False)
        
        print(f"\n✅ JSON output saved to: {json_path}")
        
        # Also create a readable summary
        print("\n" + "=" * 80)
        print("📊 MESSAGE FLOW SUMMARY")
        print("=" * 80)
        
        # Group by parent message
        reply_groups = {}
        root_msgs = []
        
        for msg_obj in messages_data:
            if msg_obj["reply_to_msg_id"]:
                parent = msg_obj["reply_to_msg_id"]
                if parent not in reply_groups:
                    reply_groups[parent] = []
                reply_groups[parent].append(msg_obj)
            else:
                root_msgs.append(msg_obj)
        
        for root in root_msgs:
            print(f"\n🔹 [{root['msg_id']}] {root['classification']['type']}")
            print(f"   {root['text'][:100]}...")
            
            if root['msg_id'] in reply_groups:
                for reply in reply_groups[root['msg_id']]:
                    print(f"   └─► [{reply['msg_id']}] {reply['classification']['type']} - {json.dumps(reply['classification']['details'])}")
        
        print("\n" + "=" * 80)
        print(f"✅ Full analysis saved to: {json_path}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await client.disconnect()
        print("\n📡 Disconnected from Telegram")

if __name__ == "__main__":
    asyncio.run(fetch_today_messages())
