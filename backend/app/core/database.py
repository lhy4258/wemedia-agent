from __future__ import annotations

from app.db.init_sql import build_init_sql


def init_database_sql() -> str:
    return build_init_sql()
