"""
Fix Enum Case - Add PENDING_DETAILS (uppercase)

The database has lowercase 'pending_details' but needs uppercase 'PENDING_DETAILS'
to match the existing convention (ACTIVE, CLOSED, PARTIAL, PENDING).

This script adds the uppercase version.
"""
import psycopg2
import config

def fix_enum_case():
    print("=" * 80)
    print("🔧 FIX: Adding PENDING_DETAILS (uppercase) to match enum convention")
    print("=" * 80)
    
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
    conn.set_session(autocommit=True)
    
    cursor = conn.cursor()
    
    # Check existing values
    cursor.execute("""
        SELECT enumlabel FROM pg_enum
        WHERE enumtypid = (
            SELECT oid FROM pg_type WHERE typname = 'tradegroupstatus'
        )
        ORDER BY enumlabel;
    """)
    
    existing = [row[0] for row in cursor.fetchall()]
    print(f"📋 Current enum values: {existing}")
    
    if 'PENDING_DETAILS' in existing:
        print("\n✅ PENDING_DETAILS (uppercase) already exists!")
        print("   No fix needed!")
    else:
        print("\n📝 Adding PENDING_DETAILS (uppercase)...")
        cursor.execute("ALTER TYPE tradegroupstatus ADD VALUE 'PENDING_DETAILS'")
        print("✅ Successfully added PENDING_DETAILS (uppercase)!")
        
        # Show updated list
        cursor.execute("""
            SELECT enumlabel FROM pg_enum
            WHERE enumtypid = (
                SELECT oid FROM pg_type WHERE typname = 'tradegroupstatus'
            )
            ORDER BY enumlabel;
        """)
        updated = [row[0] for row in cursor.fetchall()]
        print(f"\n📋 Updated enum values: {updated}")
    
    cursor.close()
    conn.close()
    
    print("\n" + "=" * 80)
    print("✅ FIX COMPLETE!")
    print("=" * 80)
    print("\n🚀 You can now run: python test_simulation.py")

if __name__ == "__main__":
    try:
        fix_enum_case()
    except Exception as e:
        print(f"\n❌ FIX FAILED: {e}")
        print("\n💡 Manual SQL command:")
        print("   ALTER TYPE tradegroupstatus ADD VALUE 'PENDING_DETAILS';")
        exit(1)
