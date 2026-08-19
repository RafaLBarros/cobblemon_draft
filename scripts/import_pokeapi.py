from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from services.dex_db import DEFAULT_DB_PATH, init_database, normalize_slug

API_BASE = "https://pokeapi.co/api/v2"
CACHE_DIR = ROOT_DIR / "data" / ".pokeapi_cache"
USER_AGENT = "mega-draft-local-tool/0.1"
RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
FAILED_IMPORT_LOG = ROOT_DIR / "data" / "import_errors.jsonl"

STAT_MAP = {
    "hp": "hp",
    "attack": "attack",
    "defense": "defense",
    "special-attack": "sp_attack",
    "special-defense": "sp_defense",
    "speed": "speed",
}


def titleize_slug(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.replace("-", " ").split())


def english_text(entries: List[Dict[str, Any]], key: str = "effect") -> Optional[str]:
    for entry in entries or []:
        language = entry.get("language") or {}
        if language.get("name") == "en" and entry.get(key):
            return str(entry[key]).replace("\n", " ").replace("\f", " ").strip()
    return None


def retry_delay_seconds(attempt: int, base_sleep_seconds: float = 1.0) -> float:
    return min(60.0, base_sleep_seconds * math.pow(2, max(0, attempt - 1)))


def should_retry(exc: BaseException) -> bool:
    if isinstance(exc, HTTPError):
        return int(exc.code) in RETRYABLE_HTTP_CODES
    return isinstance(exc, (URLError, TimeoutError))


def candidate_pokeapi_urls(url: str) -> List[str]:
    """Retorna variações seguras da URL para contornar falhas pontuais de CDN.

    A PokéAPI geralmente aceita recursos com e sem barra final. Em alguns casos
    raros, a URL com barra pode retornar 502 enquanto a mesma URL sem barra
    responde normalmente. Mantemos a URL original primeiro e tentamos a versão
    sem barra como fallback transparente.
    """
    urls = [url]
    if url.startswith(API_BASE) and url.endswith("/"):
        without_trailing_slash = url.rstrip("/")
        if without_trailing_slash and without_trailing_slash not in urls:
            urls.append(without_trailing_slash)
    return urls


def fetch_json(
    url: str,
    *,
    use_cache: bool = True,
    sleep_seconds: float = 0.05,
    max_attempts: int = 5,
) -> Dict[str, Any]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_key = normalize_slug(url.replace(API_BASE, "pokeapi")) + ".json"
    cache_path = CACHE_DIR / cache_key

    if use_cache and cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    candidate_urls = candidate_pokeapi_urls(url)
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        retryable_failure = False
        for candidate_url in candidate_urls:
            request = Request(candidate_url, headers={"User-Agent": USER_AGENT})
            try:
                with urlopen(request, timeout=30) as response:
                    data = json.loads(response.read().decode("utf-8"))
                cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
                return data
            except (HTTPError, URLError, TimeoutError) as exc:
                last_exc = exc
                if should_retry(exc):
                    retryable_failure = True
                if len(candidate_urls) > 1:
                    print(f"Aviso: falha ao consultar {candidate_url}: {exc}.")

        if attempt >= max_attempts or not retryable_failure:
            break
        wait_seconds = retry_delay_seconds(attempt)
        print(
            f"Aviso: falha temporária ao consultar {url}. "
            f"Tentando novamente em {wait_seconds:.1f}s ({attempt + 1}/{max_attempts})..."
        )
        time.sleep(wait_seconds)

    raise RuntimeError(f"Falha ao consultar {url} após {max_attempts} tentativa(s): {last_exc}") from last_exc


def log_import_error(resource: Dict[str, Any], exc: BaseException) -> None:
    FAILED_IMPORT_LOG.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "resource_name": resource.get("name"),
        "resource_url": resource.get("url"),
        "error": str(exc),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with FAILED_IMPORT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def pokemon_resource_count() -> int:
    payload = fetch_json(f"{API_BASE}/pokemon?limit=1&offset=0")
    return int(payload.get("count") or 0)


def resource_id(resource: Dict[str, Any]) -> Optional[int]:
    url = str(resource.get("url") or "").rstrip("/")
    try:
        return int(url.rsplit("/", 1)[-1])
    except (TypeError, ValueError):
        return None


def parse_csv_ints(raw_values: Iterable[str]) -> Set[int]:
    values: Set[int] = set()
    for raw_value in raw_values:
        for part in str(raw_value).split(","):
            part = part.strip()
            if not part:
                continue
            try:
                values.add(int(part))
            except ValueError as exc:
                raise ValueError(f"ID inválido em --skip-pokeapi-id: {part}") from exc
    return values


def parse_csv_slugs(raw_values: Iterable[str]) -> Set[str]:
    values: Set[str] = set()
    for raw_value in raw_values:
        for part in str(raw_value).split(","):
            part = part.strip().lower()
            if part:
                values.add(part)
    return values


def upsert_ability(connection: sqlite3.Connection, ability_ref: Dict[str, Any], *, fetch_details: bool) -> int:
    slug = ability_ref["ability"]["name"] if "ability" in ability_ref else ability_ref["name"]
    pokeapi_id = resource_id(ability_ref.get("ability", ability_ref))
    name = titleize_slug(slug)
    effect = None
    short_effect = None

    if fetch_details:
        ability_url = ability_ref.get("ability", ability_ref).get("url")
        if ability_url:
            detail = fetch_json(ability_url)
            pokeapi_id = detail.get("id") or pokeapi_id
            effect = english_text(detail.get("effect_entries", []), "effect")
            short_effect = english_text(detail.get("effect_entries", []), "short_effect")

    connection.execute(
        """
        INSERT INTO abilities (pokeapi_id, name, slug, effect, short_effect, updated_at)
        VALUES (:pokeapi_id, :name, :slug, :effect, :short_effect, CURRENT_TIMESTAMP)
        ON CONFLICT(slug) DO UPDATE SET
            pokeapi_id = COALESCE(excluded.pokeapi_id, abilities.pokeapi_id),
            name = excluded.name,
            effect = COALESCE(excluded.effect, abilities.effect),
            short_effect = COALESCE(excluded.short_effect, abilities.short_effect),
            updated_at = CURRENT_TIMESTAMP
        """,
        {
            "pokeapi_id": pokeapi_id,
            "name": name,
            "slug": slug,
            "effect": effect,
            "short_effect": short_effect,
        },
    )
    return connection.execute("SELECT id FROM abilities WHERE slug = ?", (slug,)).fetchone()[0]


def upsert_move(connection: sqlite3.Connection, move_ref: Dict[str, Any], *, fetch_details: bool) -> int:
    slug = move_ref["move"]["name"] if "move" in move_ref else move_ref["name"]
    pokeapi_id = resource_id(move_ref.get("move", move_ref))
    name = titleize_slug(slug)
    payload = {
        "pokeapi_id": pokeapi_id,
        "name": name,
        "slug": slug,
        "type": None,
        "category": None,
        "power": None,
        "accuracy": None,
        "pp": None,
        "priority": 0,
        "effect": None,
        "short_effect": None,
    }

    if fetch_details:
        move_url = move_ref.get("move", move_ref).get("url")
        if move_url:
            detail = fetch_json(move_url)
            payload.update(
                {
                    "pokeapi_id": detail.get("id") or pokeapi_id,
                    "type": (detail.get("type") or {}).get("name"),
                    "category": (detail.get("damage_class") or {}).get("name"),
                    "power": detail.get("power"),
                    "accuracy": detail.get("accuracy"),
                    "pp": detail.get("pp"),
                    "priority": detail.get("priority") or 0,
                    "effect": english_text(detail.get("effect_entries", []), "effect"),
                    "short_effect": english_text(detail.get("effect_entries", []), "short_effect"),
                }
            )

    connection.execute(
        """
        INSERT INTO moves (
            pokeapi_id, name, slug, type, category, power, accuracy, pp, priority, effect, short_effect, updated_at
        )
        VALUES (
            :pokeapi_id, :name, :slug, :type, :category, :power, :accuracy, :pp, :priority, :effect, :short_effect, CURRENT_TIMESTAMP
        )
        ON CONFLICT(slug) DO UPDATE SET
            pokeapi_id = COALESCE(excluded.pokeapi_id, moves.pokeapi_id),
            name = excluded.name,
            type = COALESCE(excluded.type, moves.type),
            category = COALESCE(excluded.category, moves.category),
            power = COALESCE(excluded.power, moves.power),
            accuracy = COALESCE(excluded.accuracy, moves.accuracy),
            pp = COALESCE(excluded.pp, moves.pp),
            priority = COALESCE(excluded.priority, moves.priority),
            effect = COALESCE(excluded.effect, moves.effect),
            short_effect = COALESCE(excluded.short_effect, moves.short_effect),
            updated_at = CURRENT_TIMESTAMP
        """,
        payload,
    )
    return connection.execute("SELECT id FROM moves WHERE slug = ?", (slug,)).fetchone()[0]


def nested_get(payload: Dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def extract_sprite_urls(pokemon: Dict[str, Any]) -> Dict[str, Optional[str]]:
    sprites = pokemon.get("sprites") or {}
    sprite_url = sprites.get("front_default")
    artwork_url = nested_get(sprites, "other", "official-artwork", "front_default")
    home_url = nested_get(sprites, "other", "home", "front_default")
    dream_world_url = nested_get(sprites, "other", "dream_world", "front_default")
    image_url = artwork_url or home_url or dream_world_url or sprite_url
    return {
        "sprite_url": sprite_url,
        "artwork_url": artwork_url,
        "image_url": image_url,
    }


def upsert_pokemon(connection: sqlite3.Connection, pokemon: Dict[str, Any], species: Dict[str, Any]) -> int:
    stats = {value: 0 for value in STAT_MAP.values()}
    for stat_entry in pokemon.get("stats", []):
        stat_slug = (stat_entry.get("stat") or {}).get("name")
        if stat_slug in STAT_MAP:
            stats[STAT_MAP[stat_slug]] = int(stat_entry.get("base_stat") or 0)

    types = sorted(pokemon.get("types", []), key=lambda item: item.get("slot") or 0)
    type_names = [(item.get("type") or {}).get("name") for item in types]
    type_names = [item for item in type_names if item]

    payload = {
        "pokeapi_id": pokemon.get("id"),
        "name": titleize_slug(pokemon["name"]),
        "slug": pokemon["name"],
        "species_slug": (pokemon.get("species") or {}).get("name"),
        "form_name": None if pokemon.get("is_default") else titleize_slug(pokemon["name"]),
        "generation": (species.get("generation") or {}).get("name"),
        "type1": type_names[0] if len(type_names) >= 1 else None,
        "type2": type_names[1] if len(type_names) >= 2 else None,
        "height_dm": pokemon.get("height"),
        "weight_hg": pokemon.get("weight"),
        "base_experience": pokemon.get("base_experience"),
        **extract_sprite_urls(pokemon),
        "is_default": 1 if pokemon.get("is_default") else 0,
        "is_baby": 1 if species.get("is_baby") else 0,
        "is_legendary": 1 if species.get("is_legendary") else 0,
        "is_mythical": 1 if species.get("is_mythical") else 0,
        **stats,
    }
    payload["bst"] = sum(stats.values())

    connection.execute(
        """
        INSERT INTO pokemon (
            pokeapi_id, name, slug, species_slug, form_name, generation, type1, type2,
            hp, attack, defense, sp_attack, sp_defense, speed, bst,
            height_dm, weight_hg, base_experience, sprite_url, artwork_url, image_url,
            is_default, is_baby, is_legendary, is_mythical, updated_at
        )
        VALUES (
            :pokeapi_id, :name, :slug, :species_slug, :form_name, :generation, :type1, :type2,
            :hp, :attack, :defense, :sp_attack, :sp_defense, :speed, :bst,
            :height_dm, :weight_hg, :base_experience, :sprite_url, :artwork_url, :image_url,
            :is_default, :is_baby, :is_legendary, :is_mythical, CURRENT_TIMESTAMP
        )
        ON CONFLICT(slug) DO UPDATE SET
            pokeapi_id = excluded.pokeapi_id,
            name = excluded.name,
            species_slug = excluded.species_slug,
            form_name = excluded.form_name,
            generation = excluded.generation,
            type1 = excluded.type1,
            type2 = excluded.type2,
            hp = excluded.hp,
            attack = excluded.attack,
            defense = excluded.defense,
            sp_attack = excluded.sp_attack,
            sp_defense = excluded.sp_defense,
            speed = excluded.speed,
            bst = excluded.bst,
            height_dm = excluded.height_dm,
            weight_hg = excluded.weight_hg,
            base_experience = excluded.base_experience,
            sprite_url = excluded.sprite_url,
            artwork_url = excluded.artwork_url,
            image_url = excluded.image_url,
            is_default = excluded.is_default,
            is_baby = excluded.is_baby,
            is_legendary = excluded.is_legendary,
            is_mythical = excluded.is_mythical,
            updated_at = CURRENT_TIMESTAMP
        """,
        payload,
    )
    return connection.execute("SELECT id FROM pokemon WHERE slug = ?", (pokemon["name"],)).fetchone()[0]


def import_one_pokemon(
    connection: sqlite3.Connection,
    pokemon_url: str,
    *,
    fetch_ability_details: bool,
    fetch_move_details: bool,
    version_group: Optional[str],
) -> None:
    pokemon = fetch_json(pokemon_url)
    species_url = (pokemon.get("species") or {}).get("url")
    species = fetch_json(species_url) if species_url else {}

    pokemon_id = upsert_pokemon(connection, pokemon, species)

    connection.execute("DELETE FROM pokemon_abilities WHERE pokemon_id = ?", (pokemon_id,))
    for ability_ref in pokemon.get("abilities", []):
        ability_id = upsert_ability(connection, ability_ref, fetch_details=fetch_ability_details)
        connection.execute(
            """
            INSERT OR REPLACE INTO pokemon_abilities (pokemon_id, ability_id, slot, is_hidden)
            VALUES (?, ?, ?, ?)
            """,
            (
                pokemon_id,
                ability_id,
                int(ability_ref.get("slot") or 0),
                1 if ability_ref.get("is_hidden") else 0,
            ),
        )

    connection.execute("DELETE FROM pokemon_moves WHERE pokemon_id = ?", (pokemon_id,))
    for move_ref in pokemon.get("moves", []):
        move_id = upsert_move(connection, move_ref, fetch_details=fetch_move_details)
        for detail in move_ref.get("version_group_details", []):
            vg = (detail.get("version_group") or {}).get("name") or "unknown"
            if version_group and vg != version_group:
                continue
            method = (detail.get("move_learn_method") or {}).get("name") or "unknown"
            level = int(detail.get("level_learned_at") or 0)
            connection.execute(
                """
                INSERT OR IGNORE INTO pokemon_moves (pokemon_id, move_id, learn_method, version_group, level_learned_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (pokemon_id, move_id, method, vg, level),
            )


def import_pokemon_list(
    db_path: Path,
    *,
    limit: int,
    offset: int,
    fetch_ability_details: bool,
    fetch_move_details: bool,
    version_group: Optional[str],
    continue_on_error: bool = False,
    skip_pokeapi_ids: Optional[Set[int]] = None,
    skip_slugs: Optional[Set[str]] = None,
) -> None:
    init_database(db_path)
    list_url = f"{API_BASE}/pokemon?limit={limit}&offset={offset}"
    resources = fetch_json(list_url).get("results", [])
    skip_pokeapi_ids = skip_pokeapi_ids or set()
    skip_slugs = skip_slugs or set()

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        run_id = connection.execute(
            "INSERT INTO import_runs (source, source_detail) VALUES (?, ?)",
            (
                "pokeapi",
                f"pokemon limit={limit} offset={offset} version_group={version_group or 'all'} "
                f"skip_ids={sorted(skip_pokeapi_ids)} skip_slugs={sorted(skip_slugs)}",
            ),
        ).lastrowid
        imported = 0
        skipped = 0
        failed: List[Dict[str, Any]] = []
        try:
            for index, resource in enumerate(resources, start=1):
                current_id = resource_id(resource)
                current_slug = str(resource.get("name") or "").lower()
                if current_id in skip_pokeapi_ids or current_slug in skip_slugs:
                    skipped += 1
                    print(f"[{index}/{len(resources)}] Pulando {resource['name']} ({resource.get('url')}) por configuração de skip...")
                    continue

                print(f"[{index}/{len(resources)}] Importando {resource['name']}...")
                try:
                    import_one_pokemon(
                        connection,
                        resource["url"],
                        fetch_ability_details=fetch_ability_details,
                        fetch_move_details=fetch_move_details,
                        version_group=version_group,
                    )
                except Exception as exc:
                    if not continue_on_error:
                        raise
                    failed.append(resource)
                    log_import_error(resource, exc)
                    print(
                        f"Aviso: pulando {resource['name']} por erro de importação. "
                        f"Detalhes em {FAILED_IMPORT_LOG}. Erro: {exc}"
                    )
                    connection.rollback()
                    continue
                imported += 1
                connection.commit()
            status = 'partial' if failed else 'success'
            error_parts = []
            if failed:
                error_parts.append(f"{len(failed)} Pokémon/forms falharam. Veja {FAILED_IMPORT_LOG}.")
            if skipped:
                error_parts.append(f"{skipped} Pokémon/forms foram pulados por configuração.")
            error = " ".join(error_parts) or None
            connection.execute(
                """
                UPDATE import_runs
                SET finished_at = CURRENT_TIMESTAMP, imported_pokemon = ?, status = ?, error = ?
                WHERE id = ?
                """,
                (imported, status, error, run_id),
            )
            connection.commit()
        except Exception as exc:
            connection.execute(
                """
                UPDATE import_runs
                SET finished_at = CURRENT_TIMESTAMP, imported_pokemon = ?, status = 'error', error = ?
                WHERE id = ?
                """,
                (imported, str(exc), run_id),
            )
            connection.commit()
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa Pokémon, abilities e moves da PokéAPI para o MegaDex.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Caminho do banco SQLite.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Importa todos os Pokémon/forms disponíveis no endpoint /pokemon da PokéAPI.",
    )
    parser.add_argument("--limit", type=int, default=151, help="Quantidade de Pokémon/forms para importar.")
    parser.add_argument("--offset", type=int, default=0, help="Offset da lista da PokéAPI.")
    parser.add_argument(
        "--version-group",
        default=None,
        help="Filtra learnsets por version group, ex.: scarlet-violet. Se omitido, importa todos.",
    )
    parser.add_argument(
        "--ability-details",
        action="store_true",
        help="Também baixa descrições das abilities.",
    )
    parser.add_argument(
        "--move-details",
        action="store_true",
        help="Também baixa tipo/categoria/poder/descrição dos moves. É mais demorado.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continua a importação se um Pokémon/form falhar e registra o erro em data/import_errors.jsonl.",
    )
    parser.add_argument(
        "--skip-pokeapi-id",
        action="append",
        default=[],
        help="Pula um ou mais IDs da PokéAPI. Aceita repetição ou lista separada por vírgula, ex.: --skip-pokeapi-id 886,10001.",
    )
    parser.add_argument(
        "--skip-slug",
        action="append",
        default=[],
        help="Pula um ou mais slugs/nomes da PokéAPI. Aceita repetição ou lista separada por vírgula, ex.: --skip-slug drakloak.",
    )
    args = parser.parse_args()

    limit = args.limit
    if args.all:
        total = pokemon_resource_count()
        limit = max(0, total - args.offset)
        print(f"PokéAPI informou {total} Pokémon/forms. Importando {limit} a partir do offset {args.offset}.")

    import_pokemon_list(
        Path(args.db),
        limit=limit,
        offset=args.offset,
        fetch_ability_details=args.ability_details,
        fetch_move_details=args.move_details,
        version_group=args.version_group,
        continue_on_error=args.continue_on_error,
        skip_pokeapi_ids=parse_csv_ints(args.skip_pokeapi_id),
        skip_slugs=parse_csv_slugs(args.skip_slug),
    )
    print("Importação finalizada.")


if __name__ == "__main__":
    main()
