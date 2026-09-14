"""
Migration Script: Add PENDING_DETAILS to TradeGroupStatus Enum

This script safely adds the PENDING_DETAILS value to the PostgreSQL enum type.
It must be run OUTSIDE a transaction to avoid the "cannot run inside a transaction block" error.

Run this ONCE before starting the bot.
"""
import psycopg2
import config

def migrate():
    print("=" * 80)
    print("🔧 MIGRATION: Adding PENDING_DETAILS to tradegroupstatus enum")
    print("=" * 80)
    
    # Parse DATABASE_URL to get connection params
    # Format: postgresql://user:password@host:port/database
    db_url = config.DATABASE_URL
    
    # Extract connection params
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
    
    # Connect with autocommit=True to run ALTER TYPE outside transaction
    conn = psycopg2.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password
    )
    conn.set_session(autocommit=True)
    
    cursor = conn.cursor()
    
    # First, check what case convention the existing enums use
    cursor.execute("""
        SELECT enumlabel FROM pg_enum
        WHERE enumtypid = (
            SELECT oid FROM pg_type WHERE typname = 'tradegroupstatus'
        )
        ORDER BY enumlabel;
    """)
    
    existing_values = [row[0] for row in cursor.fetchall()]
    print(f"📋 Existing enum values: {existing_values}")
    
    # Determine if we should use uppercase or lowercase based on existing values
    uses_uppercase = any(val.isupper() or val[0].isupper() for val in existing_values)
    value_to_add = 'PENDING_DETAILS' if uses_uppercase else 'pending_details'
    
    # Check if value already exists (check both cases)
    if value_to_add in existing_values:
        print(f"✅ {value_to_add} already exists in tradegroupstatus enum")
        print("   No migration needed!")
    elif ('PENDING_DETAILS' in existing_values or 'pending_details' in existing_values):
        print(f"✅ PENDING_DETAILS already exists (different case) in tradegroupstatus enum")
        print("   No migration needed!")
    else:
        print(f"📝 Adding {value_to_add} to tradegroupstatus enum...")
        cursor.execute(f"ALTER TYPE tradegroupstatus ADD VALUE '{value_to_add}'")
        print(f"✅ Successfully added {value_to_add} to tradegroupstatus enum!")
    
    cursor.close()
    conn.close()
    
    print("=" * 80)
    print("✅ MIGRATION COMPLETE!")
    print("=" * 80)
    print("\n🚀 You can now run: python main.py")

if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        print(f"\n❌ MIGRATION FAILED: {e}")
        print("\n💡 If error persists, you can manually run this SQL in pgAdmin:")
        print("   ALTER TYPE tradegroupstatus ADD VALUE 'pending_details';")
        exit(1)
