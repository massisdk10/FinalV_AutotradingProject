from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from database.models import Base
import config

engine = create_engine(config.DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db():
    """
    Create all tables in the database.
    
    NOTE: Run migrate_add_pending_details.py FIRST to add PENDING_DETAILS enum value.
    Enum modifications must run outside transactions, so they're in separate migration scripts.
    """
    Base.metadata.create_all(bind=engine)
    
    with get_session() as session:
        from database.models import Settings
        existing = session.query(Settings).first()
        if not existing:
            session.add(Settings(id=1))
            session.commit()


@contextmanager
def get_session() -> Session:
    """Yield a database session with automatic cleanup."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
