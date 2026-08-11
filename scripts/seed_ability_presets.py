from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.dex_db import DEFAULT_DB_PATH, init_database, seed_default_ability_presets


def main() -> None:
    parser = argparse.ArgumentParser(description="Cria presets padrão de abilities para o Mega Draft.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Caminho do SQLite do MegaDex.")
    args = parser.parse_args()

    db_path = Path(args.db)
    init_database(db_path)
    seed_default_ability_presets(db_path)
    print(f"Presets padrão de abilities criados/atualizados em: {db_path}")


if __name__ == "__main__":
    main()
