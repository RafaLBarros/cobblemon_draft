from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from services.dex_db import DEFAULT_DB_PATH, init_database, seed_default_presets


def main() -> None:
    init_database(DEFAULT_DB_PATH)
    seed_default_presets(DEFAULT_DB_PATH)
    print("Presets padrão criados/atualizados.")


if __name__ == "__main__":
    main()
