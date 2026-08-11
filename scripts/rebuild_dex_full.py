from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from services.dex_db import DEFAULT_DB_PATH, init_database, seed_default_presets
from scripts.import_pokeapi import import_pokemon_list, parse_csv_ints, parse_csv_slugs, pokemon_resource_count
from scripts.seed_dex_tags import seed_tags


def main() -> None:
    parser = argparse.ArgumentParser(description="Cria/atualiza o MegaDex e importa tudo da PokéAPI.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Caminho do banco SQLite.")
    parser.add_argument("--offset", type=int, default=0, help="Offset inicial da lista /pokemon.")
    parser.add_argument(
        "--version-group",
        default="scarlet-violet",
        help="Version group usado para filtrar learnsets. Use vazio com --version-group '' para importar todos.",
    )
    parser.add_argument(
        "--skip-ability-details",
        action="store_true",
        help="Não baixa descrições das abilities. Use apenas para teste rápido.",
    )
    parser.add_argument("--move-details", action="store_true", help="Baixa detalhes completos dos moves. Demora mais.")
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continua a importação se algum Pokémon/form falhar temporariamente.",
    )
    parser.add_argument(
        "--skip-pokeapi-id",
        action="append",
        default=[],
        help="Pula um ou mais IDs da PokéAPI. Aceita repetição ou lista separada por vírgula, ex.: --skip-pokeapi-id 886.",
    )
    parser.add_argument(
        "--skip-slug",
        action="append",
        default=[],
        help="Pula um ou mais slugs/nomes da PokéAPI. Aceita repetição ou lista separada por vírgula, ex.: --skip-slug drakloak.",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    init_database(db_path)
    total = pokemon_resource_count()
    limit = max(0, total - args.offset)
    version_group = args.version_group.strip() or None

    print(f"Importando {limit} Pokémon/forms da PokéAPI para {db_path}...")
    import_pokemon_list(
        db_path,
        limit=limit,
        offset=args.offset,
        fetch_ability_details=not args.skip_ability_details,
        fetch_move_details=args.move_details,
        version_group=version_group,
        continue_on_error=args.continue_on_error,
        skip_pokeapi_ids=parse_csv_ints(args.skip_pokeapi_id),
        skip_slugs=parse_csv_slugs(args.skip_slug),
    )
    seed_tags(db_path)
    seed_default_presets(db_path)
    print("MegaDex completo importado/atualizado.")


if __name__ == "__main__":
    main()
