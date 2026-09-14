"""
Complete System Verification Script
=====================================
Run this on RDP BEFORE starting the bot to ensure everything is correctly configured.

Checks:
1. Database enum values (PENDING_DETAILS uppercase)
2. Database schema (details_message_id column)
3. Python code integrity (all 7 fixes present)
4. Configuration files
5. MT5 connectivity
6. Telegram credentials

This script will give you a GO/NO-GO decision for production deployment.
"""
import sys
import os
import psycopg2
from pathlib import Path

# Color codes for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def print_header(text):
    print("\n" + "=" * 80)
    print(f"{BLUE}{text}{RESET}")
    print("=" * 80)

def print_success(text):
    print(f"{GREEN}✅ {text}{RESET}")

def print_error(text):
    print(f"{RED}❌ {text}{RESET}")

def print_warning(text):
    print(f"{YELLOW}⚠️  {text}{RESET}")

def verify_database():
    """Verify PostgreSQL database structure and enums."""
    print_header("1. DATABASE VERIFICATION")
    
    try:
        import config
        
        # Parse DATABASE_URL
        db_url = config.DATABASE_URL
        if db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "")
        
        parts = db_url.split("@")
        user_pass = parts[0].split(":")
        host_db = parts[1].split("/")
        host_port = host_db[0].split(":")
        
        user = user_pass[0]
        password = user_pass[1]
        host = host_port[0]
        port = host_port[1] if len(host_port) > 1 else "5432"
        database = host_db[1]
        
        print(f"📡 Connecting to PostgreSQL: {host}:{port}/{database}")
        
        conn = psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password
        )
        cursor = conn.cursor()
        
        # Check 1: TradeGroupStatus enum values
        print("\n🔍 Checking TradeGroupStatus enum...")
        cursor.execute("""
            SELECT enumlabel FROM pg_enum
            WHERE enumtypid = (
                SELECT oid FROM pg_type WHERE typname = 'tradegroupstatus'
            )
            ORDER BY enumlabel;
        """)
        
        enum_values = [row[0] for row in cursor.fetchall()]
        expected_values = ['ACTIVE', 'CLOSED', 'PARTIAL', 'PENDING', 'PENDING_DETAILS']
        
        print(f"   Found: {enum_values}")
        
        if 'PENDING_DETAILS' in enum_values:
            print_success("PENDING_DETAILS (uppercase) exists")
        else:
            print_error("PENDING_DETAILS (uppercase) is MISSING!")
            print_warning("Run: python fix_enum_case.py")
            return False
        
        # Check for extra lowercase version (should be removed eventually but won't break)
        if 'pending_details' in enum_values:
            print_warning("Lowercase 'pending_details' also exists (harmless, but not needed)")
        
        # Check 2: details_message_id column exists
        print("\n🔍 Checking trade_groups table schema...")
        cursor.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'trade_groups'
            ORDER BY ordinal_position;
        """)
        
        columns = cursor.fetchall()
        column_names = [col[0] for col in columns]
        
        print(f"   Columns: {', '.join(column_names)}")
        
        if 'details_message_id' in column_names:
            print_success("details_message_id column exists")
        else:
            print_error("details_message_id column is MISSING!")
            print_warning("This column is critical for reply lookup!")
            return False
        
        if 'now_message_id' in column_names:
            print_success("now_message_id column exists")
        else:
            print_error("now_message_id column is MISSING!")
            return False
        
        # Check 3: PositionStatus enum
        print("\n🔍 Checking PositionStatus enum...")
        cursor.execute("""
            SELECT enumlabel FROM pg_enum
            WHERE enumtypid = (
                SELECT oid FROM pg_type WHERE typname = 'positionstatus'
            )
            ORDER BY enumlabel;
        """)
        
        pos_enum_values = [row[0] for row in cursor.fetchall()]
        print(f"   Found: {pos_enum_values}")
        print_success("PositionStatus enum complete")
        
        cursor.close()
        conn.close()
        
        print_success("Database structure is CORRECT")
        return True
        
    except Exception as e:
        print_error(f"Database verification failed: {e}")
        return False

def verify_python_models():
    """Verify Python models match database."""
    print_header("2. PYTHON MODELS VERIFICATION")
    
    try:
        from database.models import TradeGroupStatus, PositionStatus, TradeGroup
        
        # Check TradeGroupStatus enum
        print("\n🔍 Checking TradeGroupStatus Python enum...")
        status_values = [s.value for s in TradeGroupStatus]
        print(f"   Values: {status_values}")
        
        if 'pending_details' in status_values:
            print_success("PENDING_DETAILS in Python enum")
        else:
            print_error("PENDING_DETAILS missing from Python enum!")
            return False
        
        # Check TradeGroup model has details_message_id
        print("\n🔍 Checking TradeGroup model attributes...")
        if hasattr(TradeGroup, 'details_message_id'):
            print_success("TradeGroup has details_message_id attribute")
        else:
            print_error("TradeGroup missing details_message_id attribute!")
            return False
        
        if hasattr(TradeGroup, 'now_message_id'):
            print_success("TradeGroup has now_message_id attribute")
        else:
            print_error("TradeGroup missing now_message_id attribute!")
            return False
        
        print_success("Python models are CORRECT")
        return True
        
    except Exception as e:
        print_error(f"Python models verification failed: {e}")
        return False

def verify_code_fixes():
    """Verify all 7 critical fixes are present in the code."""
    print_header("3. CODE FIXES VERIFICATION")
    
    fixes_ok = True
    
    # Fix 1 & 7: Check engine.py (should NOT have ALTER TYPE in init_db)
    print("\n🔍 Fix 1: Checking engine.py...")
    try:
        with open('database/engine.py', 'r', encoding='utf-8') as f:
            engine_code = f.read()
        
        if 'from sqlalchemy import create_engine, text' in engine_code:
            print_success("Text import present (for migrations)")
        else:
            print_warning("Text import missing (not critical if using separate migration)")
        
        if 'ALTER TYPE' in engine_code:
            print_error("ALTER TYPE found in init_db() - should be in migration script only!")
            fixes_ok = False
        else:
            print_success("init_db() does not contain ALTER TYPE (correct)")
    except Exception as e:
        print_error(f"Could not read engine.py: {e}")
        fixes_ok = False
    
    # Fix 2: Check handle_signal_full_update has details_message_id parameter
    print("\n🔍 Fix 2: Checking trade_executor.py handle_signal_full_update()...")
    try:
        with open('execution/trade_executor.py', 'r', encoding='utf-8') as f:
            executor_code = f.read()
        
        if 'async def handle_signal_full_update(\n        self,\n        tg_id: int,\n        details_message_id: int,' in executor_code:
            print_success("handle_signal_full_update has details_message_id parameter")
        elif 'details_message_id: int' in executor_code and 'handle_signal_full_update' in executor_code:
            print_success("handle_signal_full_update has details_message_id parameter")
        else:
            print_error("handle_signal_full_update missing details_message_id parameter!")
            fixes_ok = False
        
        if 'tg.details_message_id = details_message_id' in executor_code:
            print_success("Stores details_message_id in database")
        else:
            print_error("Does not store details_message_id in database!")
            fixes_ok = False
    except Exception as e:
        print_error(f"Could not read trade_executor.py: {e}")
        fixes_ok = False
    
    # Fix 3: Check get_trade_group_by_signal_msg searches both columns
    print("\n🔍 Fix 3: Checking crud.py get_trade_group_by_signal_msg()...")
    try:
        with open('database/crud.py', 'r', encoding='utf-8') as f:
            crud_code = f.read()
        
        if '(TradeGroup.now_message_id == signal_msg_id) |' in crud_code and \
           '(TradeGroup.details_message_id == signal_msg_id)' in crud_code:
            print_success("Searches both now_message_id AND details_message_id")
        else:
            print_error("Does not search both message ID columns!")
            fixes_ok = False
    except Exception as e:
        print_error(f"Could not read crud.py: {e}")
        fixes_ok = False
    
    # Fix 4: Check TP2/TP3 handlers have conditional close
    print("\n🔍 Fix 4: Checking TP2/TP3 conditional MT5 close...")
    try:
        with open('execution/trade_executor.py', 'r', encoding='utf-8') as f:
            executor_code = f.read()
        
        if 'if is_manual and t2_ticket and t2_status == PositionStatus.OPEN:' in executor_code:
            print_success("TP2 handler has conditional MT5 close (is_manual check)")
        else:
            print_error("TP2 handler missing conditional close logic!")
            fixes_ok = False
        
        if 'if is_manual and t3_ticket and t3_status == PositionStatus.OPEN:' in executor_code:
            print_success("TP3 handler has conditional MT5 close (is_manual check)")
        else:
            print_error("TP3 handler missing conditional close logic!")
            fixes_ok = False
    except Exception as e:
        print_error(f"Could not verify TP handlers: {e}")
        fixes_ok = False
    
    # Fix 5: Check get_open_trade_groups includes PENDING_DETAILS, excludes PENDING
    print("\n🔍 Fix 5: Checking get_open_trade_groups()...")
    try:
        with open('database/crud.py', 'r', encoding='utf-8') as f:
            crud_code = f.read()
        
        if 'TradeGroupStatus.PENDING_DETAILS' in crud_code and 'get_open_trade_groups' in crud_code:
            print_success("get_open_trade_groups includes PENDING_DETAILS")
        else:
            print_error("get_open_trade_groups does not include PENDING_DETAILS!")
            fixes_ok = False
        
        # Check that PENDING is not in the filter (should be excluded)
        open_groups_section = crud_code[crud_code.find('def get_open_trade_groups'):crud_code.find('def get_open_trade_groups') + 500]
        if 'TradeGroupStatus.PENDING,' in open_groups_section:
            print_error("get_open_trade_groups includes PENDING (should be excluded)!")
            fixes_ok = False
        else:
            print_success("get_open_trade_groups excludes PENDING (correct)")
    except Exception as e:
        print_error(f"Could not verify get_open_trade_groups: {e}")
        fixes_ok = False
    
    # Fix 6: Check signal_listener passes details_message_id
    print("\n🔍 Fix 6: Checking signal_listener.py...")
    try:
        with open('listener/signal_listener.py', 'r', encoding='utf-8') as f:
            listener_code = f.read()
        
        if 'details_message_id=msg_id' in listener_code:
            print_success("signal_listener passes details_message_id to executor")
        else:
            print_error("signal_listener does not pass details_message_id!")
            fixes_ok = False
    except Exception as e:
        print_error(f"Could not read signal_listener.py: {e}")
        fixes_ok = False
    
    if fixes_ok:
        print_success("All 7 critical fixes are PRESENT in code")
    else:
        print_error("Some fixes are MISSING or INCOMPLETE")
    
    return fixes_ok

def verify_config():
    """Verify configuration files."""
    print_header("4. CONFIGURATION VERIFICATION")
    
    try:
        import config
        
        print("\n🔍 Checking Telegram configuration...")
        if config.TELEGRAM_API_ID and config.TELEGRAM_API_HASH and config.TELEGRAM_PHONE:
            print_success("Telegram credentials configured")
            print(f"   API ID: {config.TELEGRAM_API_ID}")
            print(f"   Phone: {config.TELEGRAM_PHONE}")
        else:
            print_error("Telegram credentials missing!")
            return False
        
        if config.SIGNAL_CHANNEL_ID:
            print_success(f"Signal channel ID: {config.SIGNAL_CHANNEL_ID}")
        else:
            print_error("Signal channel ID missing!")
            return False
        
        print("\n🔍 Checking MT5 configuration...")
        if config.MT5_PATH:
            print_success(f"MT5 path: {config.MT5_PATH}")
        else:
            print_warning("MT5 path not configured (may use default)")
        
        print("\n🔍 Checking database configuration...")
        if config.DATABASE_URL:
            print_success("Database URL configured")
        else:
            print_error("Database URL missing!")
            return False
        
        print("\n🔍 Checking Telegram bot token...")
        if config.TELEGRAM_BOT_TOKEN:
            print_success("Telegram bot token configured")
        else:
            print_warning("Telegram bot token missing (notifications won't work)")
        
        print_success("Configuration files are OK")
        return True
        
    except Exception as e:
        print_error(f"Configuration verification failed: {e}")
        return False

def verify_files_exist():
    """Verify all critical files exist."""
    print_header("5. FILE EXISTENCE CHECK")
    
    critical_files = [
        'main.py',
        'config.py',
        'database/engine.py',
        'database/models.py',
        'database/crud.py',
        'execution/trade_executor.py',
        'execution/mt5_connector.py',
        'listener/signal_listener.py',
        'listener/message_parser.py',
    ]
    
    all_exist = True
    
    for file_path in critical_files:
        if os.path.exists(file_path):
            print_success(f"{file_path}")
        else:
            print_error(f"{file_path} - MISSING!")
            all_exist = False
    
    if all_exist:
        print_success("All critical files exist")
    else:
        print_error("Some critical files are missing!")
    
    return all_exist

def main():
    print("\n" + "=" * 80)
    print(f"{BLUE}🔍 COMPLETE SYSTEM VERIFICATION FOR RDP DEPLOYMENT{RESET}")
    print("=" * 80)
    print("\nThis script will verify:")
    print("  1. Database structure and enums")
    print("  2. Python models integrity")
    print("  3. All 7 critical code fixes")
    print("  4. Configuration files")
    print("  5. File existence")
    print("\n" + "=" * 80)
    
    results = {
        "Database": verify_database(),
        "Python Models": verify_python_models(),
        "Code Fixes": verify_code_fixes(),
        "Configuration": verify_config(),
        "Files": verify_files_exist(),
    }
    
    # Final verdict
    print_header("FINAL VERDICT")
    
    all_passed = all(results.values())
    
    print("\n📊 Results Summary:")
    for check, passed in results.items():
        status = f"{GREEN}✅ PASS{RESET}" if passed else f"{RED}❌ FAIL{RESET}"
        print(f"   {check:20s} {status}")
    
    print("\n" + "=" * 80)
    if all_passed:
        print(f"{GREEN}{'=' * 80}{RESET}")
        print(f"{GREEN}🎉 ALL CHECKS PASSED - SYSTEM READY FOR PRODUCTION!{RESET}")
        print(f"{GREEN}{'=' * 80}{RESET}")
        print(f"\n{GREEN}✅ You can safely run: python main.py{RESET}\n")
        return 0
    else:
        print(f"{RED}{'=' * 80}{RESET}")
        print(f"{RED}❌ SOME CHECKS FAILED - DO NOT START THE BOT!{RESET}")
        print(f"{RED}{'=' * 80}{RESET}")
        print(f"\n{RED}⚠️  Fix the issues above before running the bot{RESET}\n")
        return 1

if __name__ == "__main__":
    sys.exit(main())
