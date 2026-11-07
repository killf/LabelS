from typing import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from labelu.internal.common.config import settings

engine = None
database_url = settings.DATABASE_URL

# SQLite 的目录在 K8s 中挂载 PVC，数据库文件及 journal 一起持久化。
parsed_url = make_url(database_url)
if parsed_url.get_backend_name() == "sqlite" and parsed_url.database != ":memory:":
    Path(parsed_url.database).parent.mkdir(parents=True, exist_ok=True)

if settings.DATABASE_URL.startswith("mysql"):
    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=3600,
    )
else:
    # connect_args is needed only for SQLite. It's not needed for other databases
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 30},
    )

SessionLocal = sessionmaker(autoflush=False, bind=engine)

Base = declarative_base()


# create database tables
def init_tables() -> None:
    Base.metadata.create_all(bind=engine)


def begin_transaction(session: Session):
    """Begin a writable transaction after any SQLAlchemy 2.0 autobegin-only work."""
    if session.in_transaction():
        session.rollback()
    return session.begin()


def get_db() -> Generator:
    db = None
    try:
        db = SessionLocal()
        yield db
    finally:
        if db is not None:
            db.close()
