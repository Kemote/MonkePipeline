"""Engine / session setup. The SQLite file and the preview images both
live inside the database folder."""

import os
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from database.models import Base

DATABASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DATABASE_DIR, "studio.db")
PREVIEW_IMG_DIR = os.path.join(DATABASE_DIR, "preview_img")

engine = create_engine(f"sqlite:///{DB_PATH}", future=True)
SessionFactory = sessionmaker(bind=engine, future=True, expire_on_commit=False)


@event.listens_for(engine, "connect")
def _enable_foreign_keys(dbapi_connection, _record):
    # SQLite needs this pragma for ON DELETE CASCADE to work
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def init_db():
    """Create tables and the preview image folder if they do not exist."""
    os.makedirs(PREVIEW_IMG_DIR, exist_ok=True)
    Base.metadata.create_all(engine)


@contextmanager
def get_session():
    """Session context manager: commits on success, rolls back on error."""
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
