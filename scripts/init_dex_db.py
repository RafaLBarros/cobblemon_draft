from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from services.dex_db import DEFAULT_DB_PATH, init_database, seed_default_presets, seed_default_ability_presets


def main() -> None:
    parser = argparse.ArgumentParser(description="Cria/atualiza o banco SQLite do MegaDex.")
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Caminho do banco SQLite. Padrão: data/mega_dex.sqlite3",
    )
    args = parser.parse_args()

    db_path = init_database(Path(args.db))
    seed_default_presets(db_path)
    seed_default_ability_presets(db_path)
    print(f"MegaDex inicializado em: {db_path}")
    print("Presets padrão criados/atualizados.")


if __name__ == "__main__":
    main()
