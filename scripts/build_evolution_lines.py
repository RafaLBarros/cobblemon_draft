from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from services.dex_db import DEFAULT_DB_PATH, init_database, normalize_slug
from scripts.import_pokeapi import fetch_json, resource_id, titleize_slug


def flatten_chain(node: Dict[str, Any], stage: int = 0, rows: List[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    rows = rows if rows is not None else []
    species = node.get("species") or {}
    species_slug = str(species.get("name") or "").strip().lower()
    evolves_to = node.get("evolves_to") or []
    if species_slug:
        rows.append(
            {
                "species_slug": species_slug,
                "stage": stage,
                "is_final": 0 if evolves_to else 1,
            }
        )
    for child in evolves_to:
        flatten_chain(child, stage + 1, rows)
    return rows


def unique_preserve_order(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        cleaned = str(value or "").strip().lower()
        if cleaned and cleaned not in seen:
            result.append(cleaned)
            seen.add(cleaned)
    return result


def fetch_species_chain_urls(connection: sqlite3.Connection, *, only_species: str = "") -> Dict[int, str]:
    params: Tuple[Any, ...]
    where_sql = "WHERE species_slug IS NOT NULL AND species_slug != ''"
    params = ()
    if only_species.strip():
        where_sql += " AND species_slug = ?"
        params = (normalize_slug(only_species),)

    rows = connection.execute(
        f"SELECT DISTINCT species_slug FROM pokemon {where_sql} ORDER BY species_slug COLLATE NOCASE ASC",
        params,
    ).fetchall()

    chain_urls: Dict[int, str] = {}
    for index, row in enumerate(rows, start=1):
        species_slug = str(row[0])
        print(f"[{index}/{len(rows)}] Lendo species {species_slug}...")
        species = fetch_json(f"https://pokeapi.co/api/v2/pokemon-species/{species_slug}/")
        chain_ref = species.get("evolution_chain") or {}
        chain_url = str(chain_ref.get("url") or "")
        chain_id = resource_id(chain_ref)
        if chain_url and chain_id:
            chain_urls[int(chain_id)] = chain_url
    return chain_urls


def pokemon_rows_for_species(connection: sqlite3.Connection, species_slugs: List[str]) -> List[Dict[str, Any]]:
    if not species_slugs:
        return []
    placeholders = ",".join("?" for _ in species_slugs)
    rows = connection.execute(
        f"""
        SELECT id, name, slug, species_slug, is_default, bst, evolution_stage
        FROM pokemon
        WHERE species_slug IN ({placeholders})
        ORDER BY species_slug ASC, is_default DESC, name COLLATE NOCASE ASC
        """,
        species_slugs,
    ).fetchall()
    return [dict(row) for row in rows]


def choose_representative(rows: List[Dict[str, Any]], stage_by_species: Dict[str, int]) -> Dict[str, Any] | None:
    if not rows:
        return None
    return sorted(
        rows,
        key=lambda row: (
            int(row.get("bst") or 0),
            int(stage_by_species.get(str(row.get("species_slug") or ""), 0)),
            int(row.get("is_default") or 0),
            str(row.get("name") or ""),
        ),
        reverse=True,
    )[0]


def upsert_line(connection: sqlite3.Connection, chain_id: int, chain_payload: Dict[str, Any]) -> None:
    chain_rows = flatten_chain(chain_payload.get("chain") or {})
    if not chain_rows:
        return

    species_slugs = unique_preserve_order(row["species_slug"] for row in chain_rows)
    final_species_slugs = unique_preserve_order(row["species_slug"] for row in chain_rows if row.get("is_final"))
    stage_by_species = {row["species_slug"]: int(row.get("stage") or 0) for row in chain_rows}
    final_species_set = set(final_species_slugs)
    root_species_slug = species_slugs[0]
    line_slug = root_species_slug

    pokemon_rows = pokemon_rows_for_species(connection, species_slugs)
    pokemon_slugs = unique_preserve_order(row["slug"] for row in pokemon_rows)
    if not pokemon_rows:
        return

    representative = choose_representative(pokemon_rows, stage_by_species)
    default_rows = [row for row in pokemon_rows if int(row.get("is_default") or 0) == 1]
    max_bst = max(int(row.get("bst") or 0) for row in pokemon_rows)
    default_max_bst = max((int(row.get("bst") or 0) for row in default_rows), default=max_bst)

    connection.execute(
        """
        INSERT INTO evolution_lines (
            pokeapi_chain_id, line_slug, root_species_slug, species_slugs_json,
            final_species_slugs_json, pokemon_slugs_json, representative_pokemon_slug,
            representative_pokemon_name, max_bst, default_max_bst, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(pokeapi_chain_id) DO UPDATE SET
            line_slug = excluded.line_slug,
            root_species_slug = excluded.root_species_slug,
            species_slugs_json = excluded.species_slugs_json,
            final_species_slugs_json = excluded.final_species_slugs_json,
            pokemon_slugs_json = excluded.pokemon_slugs_json,
            representative_pokemon_slug = excluded.representative_pokemon_slug,
            representative_pokemon_name = excluded.representative_pokemon_name,
            max_bst = excluded.max_bst,
            default_max_bst = excluded.default_max_bst,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            chain_id,
            line_slug,
            root_species_slug,
            json.dumps(species_slugs, ensure_ascii=False),
            json.dumps(final_species_slugs, ensure_ascii=False),
            json.dumps(pokemon_slugs, ensure_ascii=False),
            representative.get("slug") if representative else None,
            representative.get("name") if representative else None,
            max_bst,
            default_max_bst,
        ),
    )

    for species_slug in species_slugs:
        connection.execute(
            """
            UPDATE pokemon
            SET evolution_chain_id = ?,
                evolution_line_slug = ?,
                evolution_stage = ?,
                is_final_evolution = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE species_slug = ?
            """,
            (
                chain_id,
                line_slug,
                stage_by_species.get(species_slug, 0),
                1 if species_slug in final_species_set else 0,
                species_slug,
            ),
        )


def build_evolution_lines(db_path: Path | str = DEFAULT_DB_PATH, *, only_species: str = "") -> int:
    db_path = Path(db_path)
    init_database(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        chain_urls = fetch_species_chain_urls(connection, only_species=only_species)
        print(f"Encontradas {len(chain_urls)} linhas evolutivas únicas.")
        imported = 0
        for index, (chain_id, chain_url) in enumerate(sorted(chain_urls.items()), start=1):
            print(f"[{index}/{len(chain_urls)}] Montando linha evolutiva #{chain_id}...")
            chain_payload = fetch_json(chain_url)
            upsert_line(connection, chain_id, chain_payload)
            imported += 1
            connection.commit()
        return imported


def main() -> None:
    parser = argparse.ArgumentParser(description="Monta linhas evolutivas e formas no MegaDex usando a PokéAPI.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Caminho do banco SQLite.")
    parser.add_argument(
        "--only-species",
        default="",
        help="Atualiza apenas a linha evolutiva que contém essa species, ex.: toxel, drakloak, eevee.",
    )
    args = parser.parse_args()
    total = build_evolution_lines(Path(args.db), only_species=args.only_species)
    print(f"Linhas evolutivas atualizadas: {total}")


if __name__ == "__main__":
    main()
