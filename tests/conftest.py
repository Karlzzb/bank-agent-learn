"""共享 fixtures:种子 SQLite 库(临时文件,确定性数据)。"""

import pytest
from sqlmodel import Session

from bank_agent.core.db import init_db, make_engine
from bank_agent.core.seed import seed


@pytest.fixture
def seeded_db(tmp_path):
    db_path = str(tmp_path / "bank.sqlite3")
    engine = make_engine(db_path)
    init_db(engine)
    with Session(engine) as session:
        seed(session)
    return db_path, engine
