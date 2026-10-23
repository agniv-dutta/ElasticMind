"""SQLAlchemy models and session."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
)
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
    observed_load = Column(Float)
    forecast_p50 = Column(Float)
    forecast_p90 = Column(Float)
    horizon = Column(Integer)
    model_version = Column(String(128))
    desired_ml = Column(Integer)
    desired_reactive = Column(Integer)
    final_desired = Column(Integer)
    ml_candidate = Column(Integer)
    reactive_candidate = Column(Integer)
    applied = Column(Integer)
    blocked_by = Column(String(16))
    decision_source = Column(String(24))
    cooldown_state = Column(String(128))
    running_replicas = Column(Integer)
    starting_replicas = Column(Integer)
    draining_replicas = Column(Integer)


class Experiment(Base):
    __tablename__ = "experiments"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    policy = Column(String(32))
    trace = Column(String(128))
    summary = Column(JSON)


def get_engine(db_url: str):
    if db_url.startswith("sqlite:///") and not db_url.endswith(":memory:"):
        database_path = Path(db_url.replace("sqlite:///", "", 1))
        database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False} if db_url.startswith("sqlite") else {},
        pool_pre_ping=True,
    )
    return engine


def init_db(engine) -> None:
    Base.metadata.create_all(bind=engine)
    # Upgrade existing local databases created before ControlTick fields existed.
    from sqlalchemy import inspect, text

    columns = {column["name"] for column in inspect(engine).get_columns("decisions")}
    additions = {
        "observed_load": "FLOAT",
        "forecast_p50": "FLOAT",
        "forecast_p90": "FLOAT",
        "horizon": "INTEGER",
        "model_version": "VARCHAR(128)",
        "desired_ml": "INTEGER",
        "desired_reactive": "INTEGER",
        "final_desired": "INTEGER",
        "decision_source": "VARCHAR(24)",
        "cooldown_state": "VARCHAR(128)",
        "running_replicas": "INTEGER",
        "starting_replicas": "INTEGER",
        "draining_replicas": "INTEGER",
        "ml_candidate": "INTEGER",
        "reactive_candidate": "INTEGER",
        "applied": "INTEGER",
        "blocked_by": "VARCHAR(16)",
    }
    with engine.begin() as connection:
        for name, sql_type in additions.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE decisions ADD COLUMN {name} {sql_type}"))


def get_session_factory(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db(session_factory) -> Session:
    with session_factory() as s:
        yield s
