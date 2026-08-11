from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from services.dex_db import DEFAULT_DB_PATH, init_database
from scripts.import_pokeapi import API_BASE, fetch_json, pokemon_resource_count, resource_id


def load_pokeapi_resources() -> List[Dict[str, Any]]:
    total = pokemon_resource_count()
    payload = fetch_json(f"{API_BASE}/pokemon?limit={total}&offset=0")
    return payload.get("results", [])


def local_pokeapi_ids(db_path: Path) -> set[int]:
    init_database(db_path)
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT pokeapi_id FROM pokemon WHERE pokeapi_id IS NOT NULL ORDER BY pokeapi_id"
        ).fetchall()
    return {int(row[0]) for row in rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="Mostra Pokémon/forms existentes na PokéAPI que ainda não estão no MegaDex local.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Caminho do banco SQLite.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Também grava o resultado completo em data/missing_pokemon.json.",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    resources = load_pokeapi_resources()
    existing_ids = local_pokeapi_ids(db_path)
    missing = []

    for resource in resources:
        rid = resource_id(resource)
        if rid is None:
            continue
        if rid not in existing_ids:
            missing.append({"pokeapi_id": rid, "name": resource.get("name"), "url": resource.get("url")})

    print(f"Pokémon/forms na PokéAPI: {len(resources)}")
    print(f"Pokémon/forms no banco: {len(existing_ids)}")
    print(f"Faltando no banco: {len(missing)}")

    if missing:
        print("\nPrimeiros faltantes:")
        for item in missing[:50]:
            print(f"- #{item['pokeapi_id']}: {item['name']} ({item['url']})")
        if len(missing) > 50:
            print(f"... e mais {len(missing) - 50}.")

    if args.json:
        output_path = ROOT_DIR / "data" / "missing_pokemon.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(missing, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nArquivo gravado: {output_path}")


if __name__ == "__main__":
    main()
