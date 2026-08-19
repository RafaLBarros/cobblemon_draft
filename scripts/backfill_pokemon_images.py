from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Optional

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from services.dex_db import DEFAULT_DB_PATH, ensure_schema_upgrades  # noqa: E402
from import_pokeapi import extract_sprite_urls, fetch_json  # noqa: E402


def pokemon_api_url(row: sqlite3.Row) -> str:
    pokeapi_id = row["pokeapi_id"]
    slug = row["slug"]
    identifier = pokeapi_id if pokeapi_id else slug
    # Sem barra final: evita casos raros de 502 em alguns endpoints/CDNs da PokéAPI.
    return f"https://pokeapi.co/api/v2/pokemon/{identifier}"


def backfill_images(
    *,
    db_path: Path,
    only_missing: bool,
    limit: Optional[int],
    continue_on_error: bool,
) -> int:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        ensure_schema_upgrades(connection)

        where_sql = "WHERE image_url IS NULL OR image_url = ''" if only_missing else ""
        limit_sql = "LIMIT ?" if limit else ""
        params = (int(limit),) if limit else ()
        rows = connection.execute(
            f"""
            SELECT id, pokeapi_id, name, slug, image_url
            FROM pokemon
            {where_sql}
            ORDER BY pokeapi_id ASC, name COLLATE NOCASE ASC
            {limit_sql}
            """,
            params,
        ).fetchall()

        total = len(rows)
        updated = 0
        print(f"Pokémon para processar: {total}")
        for index, row in enumerate(rows, start=1):
            label = f"[{index}/{total}] {row['name']}"
            try:
                payload: Dict[str, Any] = fetch_json(pokemon_api_url(row))
                urls = extract_sprite_urls(payload)
                connection.execute(
                    """
                    UPDATE pokemon
                    SET sprite_url = ?, artwork_url = ?, image_url = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        urls.get("sprite_url"),
                        urls.get("artwork_url"),
                        urls.get("image_url"),
                        row["id"],
                    ),
                )
                connection.commit()
                updated += 1
                print(f"{label}: imagem atualizada")
            except Exception as exc:  # noqa: BLE001
                connection.rollback()
                print(f"{label}: falhou ({exc})")
                if not continue_on_error:
                    raise

    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Preenche URLs de imagens/sprites dos Pokémon já importados no MegaDex.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Caminho do SQLite do MegaDex.")
    parser.add_argument("--all", action="store_true", help="Atualiza todos os Pokémon, não apenas os que estão sem imagem.")
    parser.add_argument("--limit", type=int, default=None, help="Limita quantos Pokémon serão processados nesta execução.")
    parser.add_argument("--continue-on-error", action="store_true", help="Continua mesmo se algum endpoint falhar.")
    args = parser.parse_args()

    updated = backfill_images(
        db_path=Path(args.db),
        only_missing=not args.all,
        limit=args.limit,
        continue_on_error=args.continue_on_error,
    )
    print(f"Concluído. Registros atualizados: {updated}")


if __name__ == "__main__":
    main()
