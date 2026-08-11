from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from services.dex_db import DEFAULT_DB_PATH, init_database, seed_default_presets
from scripts.import_pokeapi import (
    API_BASE,
    FAILED_IMPORT_LOG,
    fetch_json,
    import_one_pokemon,
    log_import_error,
    parse_csv_ints,
    parse_csv_slugs,
    pokemon_resource_count,
    resource_id,
)
from scripts.seed_dex_tags import seed_tags


def load_pokeapi_resources() -> List[Dict[str, Any]]:
    total = pokemon_resource_count()
    payload = fetch_json(f"{API_BASE}/pokemon?limit={total}&offset=0")
    return payload.get("results", [])


def local_pokeapi_ids(connection: sqlite3.Connection) -> set[int]:
    rows = connection.execute(
        "SELECT pokeapi_id FROM pokemon WHERE pokeapi_id IS NOT NULL ORDER BY pokeapi_id"
    ).fetchall()
    return {int(row[0]) for row in rows}


def selected_missing_resources(
    resources: List[Dict[str, Any]],
    existing_ids: Set[int],
    only_ids: Optional[Set[int]],
    skip_ids: Set[int],
    skip_slugs: Set[str],
) -> List[Dict[str, Any]]:
    selected = []
    for resource in resources:
        rid = resource_id(resource)
        slug = str(resource.get("name") or "").lower()
        if rid is None:
            continue
        if only_ids and rid not in only_ids:
            continue
        if rid in existing_ids:
            continue
        if rid in skip_ids or slug in skip_slugs:
            continue
        selected.append(resource)
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa apenas Pokémon/forms que ainda estão faltando no MegaDex local.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Caminho do banco SQLite.")
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
        help="Continua se algum Pokémon/form faltante falhar novamente.",
    )
    parser.add_argument(
        "--only-pokeapi-id",
        action="append",
        default=[],
        help="Tenta importar somente IDs específicos. Aceita repetição ou lista separada por vírgula, ex.: --only-pokeapi-id 886.",
    )
    parser.add_argument(
        "--skip-pokeapi-id",
        action="append",
        default=[],
        help="Pula IDs específicos. Aceita repetição ou lista separada por vírgula, ex.: --skip-pokeapi-id 886.",
    )
    parser.add_argument(
        "--skip-slug",
        action="append",
        default=[],
        help="Pula slugs/nomes específicos. Aceita repetição ou lista separada por vírgula, ex.: --skip-slug drakloak.",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    version_group = args.version_group.strip() or None
    only_ids = parse_csv_ints(args.only_pokeapi_id) or None
    skip_ids = parse_csv_ints(args.skip_pokeapi_id)
    skip_slugs = parse_csv_slugs(args.skip_slug)

    init_database(db_path)
    resources = load_pokeapi_resources()

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        existing_ids = local_pokeapi_ids(connection)
        missing = selected_missing_resources(resources, existing_ids, only_ids, skip_ids, skip_slugs)

        print(f"Faltantes selecionados para importar: {len(missing)}")
        failed = []
        for index, resource in enumerate(missing, start=1):
            print(f"[{index}/{len(missing)}] Importando faltante {resource['name']}...")
            try:
                import_one_pokemon(
                    connection,
                    resource["url"],
                    fetch_ability_details=not args.skip_ability_details,
                    fetch_move_details=args.move_details,
                    version_group=version_group,
                )
                connection.commit()
            except Exception as exc:
                connection.rollback()
                failed.append(resource)
                log_import_error(resource, exc)
                print(f"Aviso: falhou {resource['name']}. Detalhes em {FAILED_IMPORT_LOG}. Erro: {exc}")
                if not args.continue_on_error:
                    raise

    seed_tags(db_path)
    seed_default_presets(db_path)

    if failed:
        print(f"Importação parcial: {len(failed)} ainda falharam.")
        print(f"Veja {FAILED_IMPORT_LOG}.")
    else:
        print("Todos os faltantes selecionados foram importados.")


if __name__ == "__main__":
    main()
