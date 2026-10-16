"""SQLAlchemy models and session."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


class Metric(Base):
    __tablename__ = "metrics"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    name = Column(String(64))
    value = Column(Float)
    tags = Column(JSON)


class Forecast(Base):
    __tablename__ = "forecasts"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    horizon_min = Column(Integer)
    p50 = Column(Float)
    p90 = Column(Float)
    model = Column(String(64))


class Decision(Base):
    __tablename__ = "decisions"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    desired = Column(Integer)
    current = Column(Integer)
    action = Column(String(32))
    reason = Column(Text)
    p50 = Column(Float)
    p90 = Column(Float)


class Experiment(Base):
    __tablename__ = "experiments"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    policy = Column(String(32))
    trace = Column(String(128))
    summary = Column(JSON)


def get_engine(db_url: str):
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False} if db_url.startswith("sqlite") else {},
        pool_pre_ping=True,
    )
    return engine


def init_db(engine) -> None:
    Base.metadata.create_all(bind=engine)


def get_session_factory(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db(session_factory) -> Session:
    with session_factory() as s:
        yield s
