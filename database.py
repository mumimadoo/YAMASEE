import os

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config import settings


database_url = settings.database_url
db_dir = "data"

# Ensure target directory exists for SQLite file paths
if database_url.startswith("sqlite"):
    db_path = database_url.replace("sqlite:///", "")
    db_dir = os.path.dirname(db_path)

    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)


connect_args = {}

if database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False


engine = create_engine(
    database_url,
    connect_args=connect_args,
    echo=False,
)


# เปิด Foreign Key enforcement, busy_timeout และ WAL mode ให้ SQLite ทุก connection
if database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(
        dbapi_connection,
        connection_record,
    ) -> None:
        cursor = dbapi_connection.cursor()

        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            if ":memory:" not in database_url:
                try:
                    cursor.execute("PRAGMA journal_mode=WAL")
                except Exception:
                    pass
        finally:
            cursor.close()

    @event.listens_for(engine, "checkout")
    def ensure_sqlite_foreign_keys_checkout(
        dbapi_connection,
        connection_record,
        connection_proxy,
    ) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()