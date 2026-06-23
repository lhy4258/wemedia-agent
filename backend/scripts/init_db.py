from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.init_sql import build_init_sql


def main() -> None:
    print(build_init_sql())


if __name__ == "__main__":
    main()
