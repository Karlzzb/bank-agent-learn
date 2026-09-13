"""数据库引擎与会话管理。"""

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from bank_agent.core import models  # noqa: F401  确保表已注册


def make_engine(db_path: str) -> Engine:
    return create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)


def new_session(engine: Engine) -> Session:
    """每次工具调用独立开会话,用方负责 with 管理。"""
    return Session(engine)
