from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = BASE_DIR / "data" / "mega_dex.sqlite3"
SCHEMA_PATH = BASE_DIR / "database" / "schema.sql"
OFFICIAL_ARTWORK_BASE_URL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{pokeapi_id}.png"
DEFAULT_SPRITE_BASE_URL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{pokeapi_id}.png"


class DexUnavailable(RuntimeError):
    """Usado quando o MegaDex ainda não foi inicializado."""


def normalize_slug(value: str) -> str:
    """Normaliza nomes para slugs compatíveis com a PokéAPI."""
    value = value.strip().lower()
    value = value.replace("♀", "-f").replace("♂", "-m")
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path = Path(db_path)
    if not db_path.exists():
        raise DexUnavailable(f"Banco do MegaDex não encontrado em: {db_path}")
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    if column_name not in _table_columns(connection, table_name):
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def ensure_schema_upgrades(connection: sqlite3.Connection) -> None:
    """Aplica migrações pequenas que o CREATE TABLE IF NOT EXISTS não cobre.

    Isso mantém bancos locais antigos compatíveis quando novos campos são
    adicionados ao MegaDex sem exigir rebuild completo.
    """
    _ensure_column(connection, "pokemon", "evolution_chain_id", "INTEGER")
    _ensure_column(connection, "pokemon", "evolution_line_slug", "TEXT")
    _ensure_column(connection, "pokemon", "evolution_stage", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "pokemon", "is_final_evolution", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "pokemon", "sprite_url", "TEXT")
    _ensure_column(connection, "pokemon", "artwork_url", "TEXT")
    _ensure_column(connection, "pokemon", "image_url", "TEXT")

    connection.execute("CREATE INDEX IF NOT EXISTS idx_pokemon_species ON pokemon(species_slug)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_pokemon_evolution_line ON pokemon(evolution_chain_id, evolution_line_slug)")


def init_database(db_path: Path | str = DEFAULT_DB_PATH) -> Path:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        ensure_schema_upgrades(connection)
    return db_path


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> List[Dict[str, Any]]:
    return [dict(row) for row in rows]


def coerce_optional_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def truthy_filter(value: Any, *, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "não", "nao", "off"}


def dex_summary(db_path: Path | str = DEFAULT_DB_PATH) -> Dict[str, int]:
    with connect(db_path) as connection:
        pokemon_count = connection.execute("SELECT COUNT(*) FROM pokemon").fetchone()[0]
        ability_count = connection.execute("SELECT COUNT(*) FROM abilities").fetchone()[0]
        move_count = connection.execute("SELECT COUNT(*) FROM moves").fetchone()[0]
        pokemon_move_count = connection.execute("SELECT COUNT(*) FROM pokemon_moves").fetchone()[0]
        tag_count = connection.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        evolution_line_count = connection.execute("SELECT COUNT(*) FROM evolution_lines").fetchone()[0]
    return {
        "pokemon_count": pokemon_count,
        "ability_count": ability_count,
        "move_count": move_count,
        "pokemon_move_count": pokemon_move_count,
        "tag_count": tag_count,
        "evolution_line_count": evolution_line_count,
    }


def preset_slug(name: str) -> str:
    slug = normalize_slug(name)
    return slug or "preset"


def clean_filter_payload(filters: Dict[str, Any]) -> Dict[str, str]:
    """Mantém apenas filtros conhecidos e valores preenchidos para salvar presets."""
    allowed = {
        "q",
        "type",
        "ability",
        "move",
        "tag",
        "min_bst",
        "max_bst",
        "min_hp",
        "min_attack",
        "min_defense",
        "min_sp_attack",
        "min_sp_defense",
        "min_speed",
        "include_legendary",
        "include_mythical",
    }
    cleaned: Dict[str, str] = {}
    for key in allowed:
        if key not in filters:
            continue
        value = filters.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            cleaned[key] = text
    return cleaned


def search_pokemon_from_filters(filters: Dict[str, Any], *, db_path: Path | str = DEFAULT_DB_PATH, limit: int = 200) -> List[Dict[str, Any]]:
    return search_pokemon(
        q=str(filters.get("q", "")),
        pokemon_type=str(filters.get("type", "")),
        ability=str(filters.get("ability", "")),
        move=str(filters.get("move", "")),
        tag=str(filters.get("tag", "")),
        min_bst=coerce_optional_int(filters.get("min_bst")),
        max_bst=coerce_optional_int(filters.get("max_bst")),
        min_hp=coerce_optional_int(filters.get("min_hp")),
        min_attack=coerce_optional_int(filters.get("min_attack")),
        min_defense=coerce_optional_int(filters.get("min_defense")),
        min_sp_attack=coerce_optional_int(filters.get("min_sp_attack")),
        min_sp_defense=coerce_optional_int(filters.get("min_sp_defense")),
        min_speed=coerce_optional_int(filters.get("min_speed")),
        include_legendary=truthy_filter(filters.get("include_legendary"), default=True),
        include_mythical=truthy_filter(filters.get("include_mythical"), default=True),
        limit=limit,
        db_path=db_path,
    )


def list_presets(db_path: Path | str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, name, slug, description, filters_json, created_at, updated_at
            FROM draft_presets
            ORDER BY name COLLATE NOCASE ASC
            """
        ).fetchall()
    presets = rows_to_dicts(rows)
    for preset in presets:
        try:
            preset["filters"] = json.loads(preset.get("filters_json") or "{}")
        except json.JSONDecodeError:
            preset["filters"] = {}
    return presets


def get_preset(preset_id: int, db_path: Path | str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, name, slug, description, filters_json, created_at, updated_at
            FROM draft_presets
            WHERE id = ?
            """,
            (preset_id,),
        ).fetchone()
    if not row:
        return None
    preset = dict(row)
    try:
        preset["filters"] = json.loads(preset.get("filters_json") or "{}")
    except json.JSONDecodeError:
        preset["filters"] = {}
    return preset


def save_preset(
    *,
    name: str,
    description: str,
    filters: Dict[str, Any],
    db_path: Path | str = DEFAULT_DB_PATH,
) -> int:
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("Nome do preset é obrigatório.")
    cleaned_filters = clean_filter_payload(filters)
    if not cleaned_filters:
        raise ValueError("O preset precisa ter pelo menos um filtro preenchido.")

    slug = preset_slug(cleaned_name)
    filters_json = json.dumps(cleaned_filters, ensure_ascii=False, sort_keys=True)
    with connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO draft_presets (name, slug, description, filters_json, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(slug) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                filters_json = excluded.filters_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (cleaned_name, slug, description.strip(), filters_json),
        )
        row = connection.execute("SELECT id FROM draft_presets WHERE slug = ?", (slug,)).fetchone()
        connection.commit()
    return int(row[0])


def delete_preset(preset_id: int, db_path: Path | str = DEFAULT_DB_PATH) -> bool:
    with connect(db_path) as connection:
        cursor = connection.execute("DELETE FROM draft_presets WHERE id = ?", (preset_id,))
        connection.commit()
    return cursor.rowcount > 0


def get_pokemon_pool_from_preset(
    preset_id: int,
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
    limit: int = 5000,
) -> List[str]:
    """Retorna uma lista de nomes de Pokémon/forms a partir de um preset salvo."""
    preset = get_preset(int(preset_id), db_path)
    if not preset:
        return []
    rows = search_pokemon_from_filters(preset.get("filters", {}), db_path=db_path, limit=limit)
    names: List[str] = []
    seen = set()
    for row in rows[: max(1, min(limit, 10000))]:
        name = str(row.get("name") or "").strip()
        key = normalize_slug(name)
        if name and key not in seen:
            names.append(name)
            seen.add(key)
    return names


def get_pokemon_records_by_names(
    names: Iterable[str],
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> Dict[str, Dict[str, Any]]:
    """Retorna dados básicos de custo/orçamento para uma lista de nomes de Pokémon/forms."""
    wanted_slugs = []
    seen = set()
    for name in names:
        slug = normalize_slug(str(name or ""))
        if slug and slug not in seen:
            wanted_slugs.append(slug)
            seen.add(slug)
    if not wanted_slugs:
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    # Evita queries gigantescas se o usuário importar milhares de forms.
    with connect(db_path) as connection:
        for start in range(0, len(wanted_slugs), 800):
            chunk = wanted_slugs[start:start + 800]
            placeholders = ",".join("?" for _ in chunk)
            rows = connection.execute(
                f"""
                SELECT
                    id, pokeapi_id, name, slug, species_slug, evolution_chain_id, evolution_line_slug,
                    evolution_stage, is_final_evolution, generation, type1, type2,
                    hp, attack, defense, sp_attack, sp_defense, speed, bst,
                    sprite_url, artwork_url, image_url,
                    is_legendary, is_mythical, is_pseudo, is_ultra_beast, is_paradox, is_starter
                FROM pokemon
                WHERE slug IN ({placeholders})
                """,
                chunk,
            ).fetchall()
            for row in rows:
                data = dict(row)
                result[str(data.get("slug") or "")] = data
    return result


def get_pokemon_record_by_name(
    name: str,
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> Optional[Dict[str, Any]]:
    records = get_pokemon_records_by_names([name], db_path=db_path)
    return records.get(normalize_slug(name))


def get_pokemon_records_by_species_for_pokemon_name(
    name: str,
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Retorna todas as formas/Pokémon que compartilham a species do Pokémon informado."""
    record = get_pokemon_record_by_name(name, db_path=db_path)
    if not record:
        return []
    species_slug = str(record.get("species_slug") or "").strip()
    if not species_slug:
        return [record]
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                id, pokeapi_id, name, slug, species_slug, evolution_chain_id, evolution_line_slug,
                evolution_stage, is_final_evolution, generation, type1, type2,
                hp, attack, defense, sp_attack, sp_defense, speed, bst,
                sprite_url, artwork_url, image_url,
                is_legendary, is_mythical, is_pseudo, is_ultra_beast, is_paradox, is_starter
            FROM pokemon
            WHERE species_slug = ?
            ORDER BY is_default DESC, name COLLATE NOCASE ASC
            """,
            (species_slug,),
        ).fetchall()
    return rows_to_dicts(rows)


def get_species_summaries_by_species_slugs(
    species_slugs: Iterable[str],
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> Dict[str, Dict[str, Any]]:
    """Retorna o maior BST e o representante de cada species/forma agrupada."""
    cleaned: List[str] = []
    seen = set()
    for value in species_slugs:
        slug = str(value or "").strip()
        if slug and slug not in seen:
            cleaned.append(slug)
            seen.add(slug)
    if not cleaned:
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    with connect(db_path) as connection:
        for start in range(0, len(cleaned), 800):
            chunk = cleaned[start:start + 800]
            placeholders = ",".join("?" for _ in chunk)
            rows = connection.execute(
                f"""
                SELECT species_slug, name, slug, bst, is_default
                FROM pokemon
                WHERE species_slug IN ({placeholders})
                ORDER BY species_slug COLLATE NOCASE ASC, bst DESC, is_default DESC, name COLLATE NOCASE ASC
                """,
                chunk,
            ).fetchall()
            for row in rows:
                data = dict(row)
                species_slug = str(data.get("species_slug") or "").strip()
                if not species_slug:
                    continue
                current = result.setdefault(
                    species_slug,
                    {
                        "species_slug": species_slug,
                        "max_bst": 0,
                        "representative_pokemon_name": "",
                        "representative_pokemon_slug": "",
                        "form_count": 0,
                    },
                )
                current["form_count"] = int(current.get("form_count") or 0) + 1
                bst = int(data.get("bst") or 0)
                if bst > int(current.get("max_bst") or 0):
                    current["max_bst"] = bst
                    current["representative_pokemon_name"] = data.get("name") or ""
                    current["representative_pokemon_slug"] = data.get("slug") or ""
    return result


def _safe_json_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        parsed = []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _parse_evolution_line(row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
    data = dict(row)
    data["species_slugs"] = _safe_json_list(data.get("species_slugs_json"))
    data["final_species_slugs"] = _safe_json_list(data.get("final_species_slugs_json"))
    data["pokemon_slugs"] = _safe_json_list(data.get("pokemon_slugs_json"))
    return data


def get_evolution_line_for_pokemon_name(
    name: str,
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> Optional[Dict[str, Any]]:
    slug = normalize_slug(name)
    if not slug:
        return None
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT el.*
            FROM pokemon p
            JOIN evolution_lines el ON el.pokeapi_chain_id = p.evolution_chain_id
            WHERE p.slug = ?
            LIMIT 1
            """,
            (slug,),
        ).fetchone()
    return _parse_evolution_line(row) if row else None


def get_evolution_lines_by_chain_ids(
    chain_ids: Iterable[int],
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> Dict[int, Dict[str, Any]]:
    cleaned: List[int] = []
    seen = set()
    for value in chain_ids:
        try:
            chain_id = int(value)
        except (TypeError, ValueError):
            continue
        if chain_id not in seen:
            cleaned.append(chain_id)
            seen.add(chain_id)
    if not cleaned:
        return {}

    result: Dict[int, Dict[str, Any]] = {}
    with connect(db_path) as connection:
        for start in range(0, len(cleaned), 800):
            chunk = cleaned[start:start + 800]
            placeholders = ",".join("?" for _ in chunk)
            rows = connection.execute(
                f"SELECT * FROM evolution_lines WHERE pokeapi_chain_id IN ({placeholders})",
                chunk,
            ).fetchall()
            for row in rows:
                data = _parse_evolution_line(row)
                result[int(data["pokeapi_chain_id"])] = data
    return result


def get_pokemon_records_in_evolution_line(
    line: Dict[str, Any],
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    chain_id = line.get("pokeapi_chain_id")
    try:
        chain_id_int = int(chain_id)
    except (TypeError, ValueError):
        return []
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, pokeapi_id, name, slug, species_slug, evolution_chain_id, evolution_line_slug,
                   evolution_stage, is_final_evolution, generation, type1, type2,
                   hp, attack, defense, sp_attack, sp_defense, speed, bst,
                   sprite_url, artwork_url, image_url,
                   is_legendary, is_mythical, is_pseudo, is_ultra_beast, is_paradox, is_starter
            FROM pokemon
            WHERE evolution_chain_id = ?
            ORDER BY evolution_stage ASC, is_default DESC, species_slug ASC, name COLLATE NOCASE ASC
            """,
            (chain_id_int,),
        ).fetchall()
    return rows_to_dicts(rows)


def search_evolution_lines(
    *,
    q: str = "",
    db_path: Path | str = DEFAULT_DB_PATH,
    limit: int = 300,
) -> List[Dict[str, Any]]:
    conditions: List[str] = []
    params: Dict[str, Any] = {"limit": max(1, min(limit, 1000))}
    if q.strip():
        conditions.append(
            "(line_slug LIKE :q OR root_species_slug LIKE :q OR species_slugs_json LIKE :q OR pokemon_slugs_json LIKE :q "
            "OR representative_pokemon_name LIKE :q OR representative_pokemon_slug LIKE :q)"
        )
        params["q"] = f"%{normalize_slug(q) or q.strip()}%"
    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    with connect(db_path) as connection:
        rows = connection.execute(
            f"""
            SELECT *
            FROM evolution_lines
            {where_sql}
            ORDER BY root_species_slug COLLATE NOCASE ASC
            LIMIT :limit
            """,
            params,
        ).fetchall()
    return [_parse_evolution_line(row) for row in rows]


def list_ability_names(
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
    include_banned: bool = False,
    tag: str = "",
    limit: int = 5000,
) -> List[str]:
    """Lista abilities disponíveis no MegaDex para sorteio."""
    conditions: List[str] = [] if include_banned else ["a.is_banned = 0"]
    params: Dict[str, Any] = {"limit": max(1, min(limit, 10000))}

    if tag.strip():
        conditions.append(
            "EXISTS ("
            "SELECT 1 FROM ability_tags at "
            "JOIN tags t ON t.id = at.tag_id "
            "WHERE at.ability_id = a.id AND (t.name LIKE :tag OR t.category LIKE :tag)"
            ")"
        )
        params["tag"] = f"%{tag.strip()}%"

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""
        SELECT a.name
        FROM abilities a
        {where_sql}
        ORDER BY a.name COLLATE NOCASE ASC
        LIMIT :limit
    """
    with connect(db_path) as connection:
        rows = connection.execute(query, params).fetchall()
    return [str(row["name"]) for row in rows if str(row["name"]).strip()]


def list_tags(
    *,
    category: str = "",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    conditions: List[str] = []
    params: Dict[str, Any] = {}
    if category.strip():
        conditions.append("category = :category")
        params["category"] = category.strip()
    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""
        SELECT id, name, category, description
        FROM tags
        {where_sql}
        ORDER BY category COLLATE NOCASE ASC, name COLLATE NOCASE ASC
    """
    with connect(db_path) as connection:
        return rows_to_dicts(connection.execute(query, params).fetchall())


def list_ability_tags(*, db_path: Path | str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Tags úteis para filtrar/sortear abilities."""
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT t.id, t.name, t.category, t.description
            FROM tags t
            LEFT JOIN ability_tags at ON at.tag_id = t.id
            WHERE t.category = 'ability' OR at.ability_id IS NOT NULL
            ORDER BY t.name COLLATE NOCASE ASC
            """
        ).fetchall()
    return rows_to_dicts(rows)


def get_ability_record_by_name(name: str, db_path: Path | str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    slug = normalize_slug(str(name or ""))
    if not slug:
        return None

    query = """
        SELECT
            a.id,
            a.pokeapi_id,
            a.name,
            a.slug,
            a.short_effect,
            a.effect,
            a.is_battle_relevant,
            a.is_banned,
            a.notes,
            COALESCE(GROUP_CONCAT(t.name, '||'), '') AS tags_text
        FROM abilities a
        LEFT JOIN ability_tags at ON at.ability_id = a.id
        LEFT JOIN tags t ON t.id = at.tag_id
        WHERE a.slug = :slug OR LOWER(a.name) = LOWER(:name)
        GROUP BY a.id
        LIMIT 1
    """
    with connect(db_path) as connection:
        row = connection.execute(query, {"slug": slug, "name": str(name or "").strip()}).fetchone()
    if not row:
        return None
    record = dict(row)
    tags_text = str(record.pop("tags_text", "") or "")
    record["tags"] = [tag_name for tag_name in tags_text.split("||") if tag_name]
    return record


def search_abilities(
    *,
    q: str = "",
    tag: str = "",
    include_banned: bool = True,
    db_path: Path | str = DEFAULT_DB_PATH,
    limit: int = 300,
) -> List[Dict[str, Any]]:
    """Busca abilities e retorna as tags já agrupadas para a tela Ability Lab."""
    conditions: List[str] = []
    params: Dict[str, Any] = {"limit": max(1, min(limit, 1000))}

    if q.strip():
        conditions.append("(a.name LIKE :q OR a.slug LIKE :q OR a.short_effect LIKE :q OR a.effect LIKE :q)")
        params["q"] = f"%{q.strip()}%"

    if tag.strip():
        conditions.append(
            "EXISTS ("
            "SELECT 1 FROM ability_tags at2 "
            "JOIN tags t2 ON t2.id = at2.tag_id "
            "WHERE at2.ability_id = a.id AND (t2.name LIKE :tag OR t2.category LIKE :tag)"
            ")"
        )
        params["tag"] = f"%{tag.strip()}%"

    if not include_banned:
        conditions.append("a.is_banned = 0")

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""
        SELECT
            a.id,
            a.pokeapi_id,
            a.name,
            a.slug,
            a.short_effect,
            a.effect,
            a.is_battle_relevant,
            a.is_banned,
            a.notes,
            COALESCE(GROUP_CONCAT(t.name, '||'), '') AS tags_text
        FROM abilities a
        LEFT JOIN ability_tags at ON at.ability_id = a.id
        LEFT JOIN tags t ON t.id = at.tag_id
        {where_sql}
        GROUP BY a.id
        ORDER BY a.name COLLATE NOCASE ASC
        LIMIT :limit
    """
    with connect(db_path) as connection:
        rows = rows_to_dicts(connection.execute(query, params).fetchall())

    for row in rows:
        tags_text = str(row.pop("tags_text", "") or "")
        row["tags"] = [tag_name for tag_name in tags_text.split("||") if tag_name]
    return rows


def split_tag_names(raw_tags: str | Iterable[str]) -> List[str]:
    if isinstance(raw_tags, str):
        pieces = re.split(r"[,;\n]+", raw_tags)
    else:
        pieces = [str(item) for item in raw_tags]
    tags: List[str] = []
    seen = set()
    for piece in pieces:
        tag = piece.strip()
        key = tag.lower()
        if tag and key not in seen:
            tags.append(tag)
            seen.add(key)
    return tags




def normalize_tag_list(raw_tags: str | Iterable[str]) -> List[str]:
    return split_tag_names(raw_tags)


def tag_list_to_text(raw_tags: str | Iterable[str]) -> str:
    return ", ".join(normalize_tag_list(raw_tags))

def upsert_tag(connection: sqlite3.Connection, name: str, category: str = "ability", description: str = "") -> int:
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("Nome da tag é obrigatório.")
    connection.execute(
        """
        INSERT INTO tags (name, category, description)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            category = CASE WHEN tags.category = '' THEN excluded.category ELSE tags.category END,
            description = CASE WHEN excluded.description != '' THEN excluded.description ELSE tags.description END
        """,
        (cleaned_name, category.strip() or "ability", description.strip()),
    )
    return int(connection.execute("SELECT id FROM tags WHERE name = ?", (cleaned_name,)).fetchone()[0])


def update_ability_metadata(
    *,
    ability_id: int,
    tags: str | Iterable[str],
    is_banned: bool,
    is_battle_relevant: bool,
    notes: str = "",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> None:
    """Atualiza tags/flags manuais de uma ability pelo Ability Lab."""
    tag_names = split_tag_names(tags)
    with connect(db_path) as connection:
        ability = connection.execute("SELECT id FROM abilities WHERE id = ?", (ability_id,)).fetchone()
        if not ability:
            raise ValueError("Ability não encontrada.")

        connection.execute("DELETE FROM ability_tags WHERE ability_id = ?", (ability_id,))
        for tag_name in tag_names:
            tag_id = upsert_tag(connection, tag_name, category="ability")
            connection.execute(
                "INSERT OR IGNORE INTO ability_tags (ability_id, tag_id) VALUES (?, ?)",
                (ability_id, tag_id),
            )

        connection.execute(
            """
            UPDATE abilities
            SET is_banned = ?, is_battle_relevant = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (1 if is_banned else 0, 1 if is_battle_relevant else 0, notes.strip(), ability_id),
        )
        connection.commit()


def _json_tag_list(value: Any) -> List[str]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value or "[]")
        except json.JSONDecodeError:
            return []
    else:
        parsed = value
    if not isinstance(parsed, list):
        return []
    return normalize_tag_list(parsed)


def list_ability_presets(db_path: Path | str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, name, slug, description, required_tags_json, excluded_tags_json,
                   required_mode, include_banned, created_at, updated_at
            FROM ability_presets
            ORDER BY name COLLATE NOCASE ASC
            """
        ).fetchall()
    presets = rows_to_dicts(rows)
    for preset in presets:
        preset["required_tags"] = _json_tag_list(preset.get("required_tags_json"))
        preset["excluded_tags"] = _json_tag_list(preset.get("excluded_tags_json"))
        preset["required_tags_text"] = tag_list_to_text(preset["required_tags"])
        preset["excluded_tags_text"] = tag_list_to_text(preset["excluded_tags"])
        preset["include_banned"] = bool(preset.get("include_banned"))
        if str(preset.get("required_mode") or "any") not in {"any", "all"}:
            preset["required_mode"] = "any"
    return presets


def get_ability_preset(preset_id: int, db_path: Path | str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, name, slug, description, required_tags_json, excluded_tags_json,
                   required_mode, include_banned, created_at, updated_at
            FROM ability_presets
            WHERE id = ?
            """,
            (preset_id,),
        ).fetchone()
    if not row:
        return None
    preset = dict(row)
    preset["required_tags"] = _json_tag_list(preset.get("required_tags_json"))
    preset["excluded_tags"] = _json_tag_list(preset.get("excluded_tags_json"))
    preset["required_tags_text"] = tag_list_to_text(preset["required_tags"])
    preset["excluded_tags_text"] = tag_list_to_text(preset["excluded_tags"])
    preset["include_banned"] = bool(preset.get("include_banned"))
    if str(preset.get("required_mode") or "any") not in {"any", "all"}:
        preset["required_mode"] = "any"
    return preset


def save_ability_preset(
    *,
    name: str,
    description: str,
    required_tags: str | Iterable[str],
    excluded_tags: str | Iterable[str],
    required_mode: str = "any",
    include_banned: bool = False,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> int:
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("Nome do preset de ability é obrigatório.")
    required = normalize_tag_list(required_tags)
    excluded = normalize_tag_list(excluded_tags)
    mode = required_mode if required_mode in {"any", "all"} else "any"
    if not required and not excluded and include_banned:
        raise ValueError("O preset precisa filtrar por pelo menos uma tag ou excluir banidas.")
    if not required and not excluded and not include_banned:
        raise ValueError("O preset precisa ter pelo menos uma tag obrigatória ou excluída.")

    slug = preset_slug(cleaned_name)
    required_json = json.dumps(required, ensure_ascii=False, sort_keys=True)
    excluded_json = json.dumps(excluded, ensure_ascii=False, sort_keys=True)

    with connect(db_path) as connection:
        # Garante que tags digitadas no preset existam e apareçam nas telas de filtro.
        for tag_name in required + excluded:
            upsert_tag(connection, tag_name, category="ability")
        connection.execute(
            """
            INSERT INTO ability_presets
                (name, slug, description, required_tags_json, excluded_tags_json, required_mode, include_banned, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(slug) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                required_tags_json = excluded.required_tags_json,
                excluded_tags_json = excluded.excluded_tags_json,
                required_mode = excluded.required_mode,
                include_banned = excluded.include_banned,
                updated_at = CURRENT_TIMESTAMP
            """,
            (cleaned_name, slug, description.strip(), required_json, excluded_json, mode, 1 if include_banned else 0),
        )
        row = connection.execute("SELECT id FROM ability_presets WHERE slug = ?", (slug,)).fetchone()
        connection.commit()
    return int(row[0])


def delete_ability_preset(preset_id: int, db_path: Path | str = DEFAULT_DB_PATH) -> bool:
    with connect(db_path) as connection:
        cursor = connection.execute("DELETE FROM ability_presets WHERE id = ?", (preset_id,))
        connection.commit()
    return cursor.rowcount > 0


def search_abilities_from_preset(
    preset: Dict[str, Any],
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    required_tags = normalize_tag_list(preset.get("required_tags", []))
    excluded_tags = normalize_tag_list(preset.get("excluded_tags", []))
    mode = str(preset.get("required_mode") or "any")
    include_banned = bool(preset.get("include_banned"))

    conditions: List[str] = [] if include_banned else ["a.is_banned = 0"]
    params: Dict[str, Any] = {"limit": max(1, min(limit, 10000))}

    if required_tags:
        if mode == "all":
            for index, tag_name in enumerate(required_tags):
                param = f"required_tag_{index}"
                conditions.append(
                    "EXISTS ("
                    "SELECT 1 FROM ability_tags at_req "
                    "JOIN tags t_req ON t_req.id = at_req.tag_id "
                    f"WHERE at_req.ability_id = a.id AND t_req.name = :{param}"
                    ")"
                )
                params[param] = tag_name
        else:
            placeholders = []
            for index, tag_name in enumerate(required_tags):
                param = f"required_tag_{index}"
                placeholders.append(f":{param}")
                params[param] = tag_name
            conditions.append(
                "EXISTS ("
                "SELECT 1 FROM ability_tags at_req "
                "JOIN tags t_req ON t_req.id = at_req.tag_id "
                f"WHERE at_req.ability_id = a.id AND t_req.name IN ({', '.join(placeholders)})"
                ")"
            )

    if excluded_tags:
        placeholders = []
        for index, tag_name in enumerate(excluded_tags):
            param = f"excluded_tag_{index}"
            placeholders.append(f":{param}")
            params[param] = tag_name
        conditions.append(
            "NOT EXISTS ("
            "SELECT 1 FROM ability_tags at_ex "
            "JOIN tags t_ex ON t_ex.id = at_ex.tag_id "
            f"WHERE at_ex.ability_id = a.id AND t_ex.name IN ({', '.join(placeholders)})"
            ")"
        )

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""
        SELECT
            a.id,
            a.pokeapi_id,
            a.name,
            a.slug,
            a.short_effect,
            a.effect,
            a.is_battle_relevant,
            a.is_banned,
            a.notes,
            COALESCE(GROUP_CONCAT(t.name, '||'), '') AS tags_text
        FROM abilities a
        LEFT JOIN ability_tags at ON at.ability_id = a.id
        LEFT JOIN tags t ON t.id = at.tag_id
        {where_sql}
        GROUP BY a.id
        ORDER BY a.name COLLATE NOCASE ASC
        LIMIT :limit
    """
    with connect(db_path) as connection:
        rows = rows_to_dicts(connection.execute(query, params).fetchall())
    for row in rows:
        tags_text = str(row.pop("tags_text", "") or "")
        row["tags"] = [tag_name for tag_name in tags_text.split("||") if tag_name]
    return rows


def get_ability_pool_from_preset(
    preset_id: int,
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
    limit: int = 10000,
) -> List[str]:
    preset = get_ability_preset(int(preset_id), db_path)
    if not preset:
        return []
    rows = search_abilities_from_preset(preset, db_path=db_path, limit=limit)
    names: List[str] = []
    seen = set()
    for row in rows[: max(1, min(limit, 10000))]:
        name = str(row.get("name") or "").strip()
        key = normalize_slug(name)
        if name and key not in seen:
            names.append(name)
            seen.add(key)
    return names




RULESET_POKEMON_POOL_SOURCES = {"txt", "dex_preset"}
RULESET_ABILITY_POOL_SOURCES = {"txt", "dex_all", "dex_tag", "dex_preset"}
RULESET_POKEMON_LOCK_SCOPES = {"exact", "species", "evolution_line", "legacy_group"}


def parse_bool_setting(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "sim", "yes", "on", "checked"}


def clamp_int_setting(value: Any, *, default: int, minimum: int = 1, maximum: int = 100) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def normalize_ruleset_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza as configurações que um ruleset pode aplicar no draft."""
    pokemon_source = str(settings.get("pokemon_pool_source") or "txt").strip()
    if pokemon_source not in RULESET_POKEMON_POOL_SOURCES:
        pokemon_source = "txt"

    ability_source = str(settings.get("ability_pool_source") or "txt").strip()
    if ability_source not in RULESET_ABILITY_POOL_SOURCES:
        ability_source = "txt"

    def optional_int(value: Any) -> Optional[int]:
        if value is None or str(value).strip() == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    raw_karma = settings.get("flag_karma") if isinstance(settings.get("flag_karma"), dict) else {}
    lock_scope = str(settings.get("pokemon_lock_scope") or "evolution_line").strip()
    if lock_scope not in RULESET_POKEMON_LOCK_SCOPES:
        lock_scope = "evolution_line"

    return {
        "max_pokemon": clamp_int_setting(settings.get("max_pokemon"), default=6, minimum=1, maximum=30),
        "pokemon_options_per_draw": clamp_int_setting(settings.get("pokemon_options_per_draw"), default=3, minimum=1, maximum=20),
        "ability_options_per_draw": clamp_int_setting(settings.get("ability_options_per_draw"), default=3, minimum=1, maximum=20),
        "pokemon_pool_source": pokemon_source,
        "pokemon_preset_id": optional_int(settings.get("pokemon_preset_id")),
        "ability_pool_source": ability_source,
        "ability_tag_filter": str(settings.get("ability_tag_filter") or "").strip(),
        "ability_preset_id": optional_int(settings.get("ability_preset_id")),
        "lock_chosen_pokemon_globally": parse_bool_setting(settings.get("lock_chosen_pokemon_globally"), default=True),
        "pokemon_lock_scope": lock_scope,
        "lock_abilities_globally": parse_bool_setting(settings.get("lock_abilities_globally"), default=False),
        "budget_enabled": parse_bool_setting(settings.get("budget_enabled"), default=False),
        "budget_points_per_player": clamp_int_setting(settings.get("budget_points_per_player"), default=3000, minimum=1, maximum=20000),
        "budget_unknown_pokemon_cost": clamp_int_setting(settings.get("budget_unknown_pokemon_cost"), default=450, minimum=0, maximum=20000),
        "budget_cost_mode": settings.get("budget_cost_mode") if settings.get("budget_cost_mode") in {"pokemon_bst", "species_max_bst", "line_max_bst"} else "pokemon_bst",
        "budget_flag_costs": settings.get("budget_flag_costs") if isinstance(settings.get("budget_flag_costs"), dict) else {},
        "flag_karma": raw_karma,
    }


def ruleset_settings_to_labels(settings: Dict[str, Any]) -> Dict[str, str]:
    normalized = normalize_ruleset_settings(settings)
    pokemon_source = "MegaDex/preset" if normalized["pokemon_pool_source"] == "dex_preset" else "TXT legado"
    ability_source_map = {
        "txt": "TXT legado",
        "dex_all": "MegaDex/todas",
        "dex_tag": "MegaDex/tag",
        "dex_preset": "MegaDex/preset",
    }
    budget_mode_map = {
        "pokemon_bst": "forma sorteada",
        "species_max_bst": "species/formas",
        "line_max_bst": "linha evolutiva",
    }
    budget_mode_label = budget_mode_map.get(normalized.get("budget_cost_mode"), "forma sorteada")
    lock_scope_map = {
        "exact": "forma sorteada",
        "species": "formas da species",
        "evolution_line": "linha evolutiva",
        "legacy_group": "grupos TXT",
    }
    if normalized.get("lock_chosen_pokemon_globally"):
        lock_label = "Pokémon global: " + lock_scope_map.get(normalized.get("pokemon_lock_scope"), "linha evolutiva")
    else:
        lock_label = "Pokémon não trava globalmente"
    if normalized["lock_abilities_globally"]:
        lock_label += " + abilities globais"
    return {
        "pokemon_source": pokemon_source,
        "ability_source": ability_source_map.get(normalized["ability_pool_source"], normalized["ability_pool_source"]),
        "max_pokemon": str(normalized["max_pokemon"]),
        "pokemon_options_per_draw": str(normalized["pokemon_options_per_draw"]),
        "ability_options_per_draw": str(normalized["ability_options_per_draw"]),
        "budget": f"{normalized['budget_points_per_player']} pts · {budget_mode_label}" if normalized.get("budget_enabled") else "desativado",
        "locks": lock_label,
    }


def _decode_ruleset(row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
    ruleset = dict(row)
    try:
        settings = json.loads(ruleset.get("settings_json") or "{}")
    except json.JSONDecodeError:
        settings = {}
    ruleset["settings"] = normalize_ruleset_settings(settings if isinstance(settings, dict) else {})
    ruleset["labels"] = ruleset_settings_to_labels(ruleset["settings"])
    return ruleset


def list_draft_rulesets(db_path: Path | str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, name, slug, description, settings_json, created_at, updated_at
            FROM draft_rulesets
            ORDER BY name COLLATE NOCASE ASC
            """
        ).fetchall()
    return [_decode_ruleset(row) for row in rows]


def get_draft_ruleset(ruleset_id: int, db_path: Path | str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, name, slug, description, settings_json, created_at, updated_at
            FROM draft_rulesets
            WHERE id = ?
            """,
            (ruleset_id,),
        ).fetchone()
    return _decode_ruleset(row) if row else None


def save_draft_ruleset(
    *,
    name: str,
    description: str,
    settings: Dict[str, Any],
    db_path: Path | str = DEFAULT_DB_PATH,
) -> int:
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("Nome do ruleset é obrigatório.")
    normalized = normalize_ruleset_settings(settings)
    if normalized["pokemon_pool_source"] == "dex_preset" and not normalized.get("pokemon_preset_id"):
        raise ValueError("Ruleset usando MegaDex para Pokémon precisa de um preset de Pokémon.")
    if normalized["ability_pool_source"] == "dex_tag" and not normalized.get("ability_tag_filter"):
        raise ValueError("Ruleset usando abilities por tag precisa de uma tag de ability.")
    if normalized["ability_pool_source"] == "dex_preset" and not normalized.get("ability_preset_id"):
        raise ValueError("Ruleset usando preset de abilities precisa de um preset de ability.")

    slug = preset_slug(cleaned_name)
    settings_json = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    with connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO draft_rulesets (name, slug, description, settings_json, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(slug) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                settings_json = excluded.settings_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (cleaned_name, slug, description.strip(), settings_json),
        )
        row = connection.execute("SELECT id FROM draft_rulesets WHERE slug = ?", (slug,)).fetchone()
        connection.commit()
    return int(row[0])


def delete_draft_ruleset(ruleset_id: int, db_path: Path | str = DEFAULT_DB_PATH) -> bool:
    with connect(db_path) as connection:
        cursor = connection.execute("DELETE FROM draft_rulesets WHERE id = ?", (ruleset_id,))
        connection.commit()
    return cursor.rowcount > 0


def find_preset_id_by_slug_or_name(
    *,
    slug: str,
    name: str = "",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> Optional[int]:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT id FROM draft_presets WHERE slug = ? OR name = ?",
            (slug, name.strip() or slug),
        ).fetchone()
    return int(row[0]) if row else None


def find_ability_preset_id_by_slug_or_name(
    *,
    slug: str,
    name: str = "",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> Optional[int]:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT id FROM ability_presets WHERE slug = ? OR name = ?",
            (slug, name.strip() or slug),
        ).fetchone()
    return int(row[0]) if row else None


def seed_default_draft_rulesets(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    """Cria rulesets prontos combinando presets de Pokémon e abilities quando eles existirem."""
    metronome_preset_id = find_preset_id_by_slug_or_name(slug="metronome-cup", name="Metronome Cup", db_path=db_path)
    metronome_ability_preset_id = find_ability_preset_id_by_slug_or_name(slug="metronome-abilities-funcionais", name="Metronome Abilities Funcionais", db_path=db_path)
    bulky_preset_id = find_preset_id_by_slug_or_name(slug="bulky-400", name="Bulky 400+", db_path=db_path)
    singles_ability_preset_id = find_ability_preset_id_by_slug_or_name(slug="singles-estaveis", name="Singles Estáveis", db_path=db_path)

    defaults: List[Dict[str, Any]] = []
    if metronome_preset_id:
        defaults.append({
            "name": "Metronome Cup Completo",
            "description": "Ruleset pronto: Pokémon que aprendem Metronome, abilities funcionais e 6 escolhas por jogador.",
            "settings": {
                "max_pokemon": 6,
                "pokemon_options_per_draw": 3,
                "ability_options_per_draw": 3,
                "pokemon_pool_source": "dex_preset",
                "pokemon_preset_id": metronome_preset_id,
                "ability_pool_source": "dex_preset" if metronome_ability_preset_id else "dex_tag",
                "ability_preset_id": metronome_ability_preset_id,
                "ability_tag_filter": "Metronome Boa" if not metronome_ability_preset_id else "",
                "lock_chosen_pokemon_globally": True,
                "lock_abilities_globally": False,
                "flag_karma": {},
            },
        })
    if bulky_preset_id:
        defaults.append({
            "name": "Bulky Random Ability",
            "description": "Pokémon bulky do MegaDex com abilities estáveis de singles.",
            "settings": {
                "max_pokemon": 6,
                "pokemon_options_per_draw": 3,
                "ability_options_per_draw": 3,
                "pokemon_pool_source": "dex_preset",
                "pokemon_preset_id": bulky_preset_id,
                "ability_pool_source": "dex_preset" if singles_ability_preset_id else "dex_all",
                "ability_preset_id": singles_ability_preset_id,
                "ability_tag_filter": "",
                "lock_chosen_pokemon_globally": True,
                "lock_abilities_globally": False,
                "flag_karma": {},
            },
        })

    for ruleset in defaults:
        try:
            save_draft_ruleset(db_path=db_path, **ruleset)
        except ValueError:
            continue

def seed_default_ability_presets(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    defaults = [
        {
            "name": "Metronome Abilities Funcionais",
            "description": "Abilities marcadas como boas para Metronome, excluindo ruins, baníveis e inúteis em singles.",
            "required_tags": "Metronome Boa",
            "excluded_tags": "Metronome Ruim, Banível, Inútil em singles",
            "required_mode": "any",
            "include_banned": False,
        },
        {
            "name": "Singles Estáveis",
            "description": "Abilities que funcionam em singles e evitam dependências muito situacionais.",
            "required_tags": "Funciona em singles",
            "excluded_tags": "Depende de doubles, Precisa de golpe específico, Banível, Inútil em singles",
            "required_mode": "any",
            "include_banned": False,
        },
        {
            "name": "Ofensivas Úteis",
            "description": "Abilities ofensivas úteis sem as principais tags problemáticas.",
            "required_tags": "Ofensiva",
            "excluded_tags": "Metronome Ruim, Banível, Inútil em singles",
            "required_mode": "any",
            "include_banned": False,
        },
        {
            "name": "Defensivas Úteis",
            "description": "Abilities defensivas úteis sem as principais tags problemáticas.",
            "required_tags": "Defensiva",
            "excluded_tags": "Metronome Ruim, Banível, Inútil em singles",
            "required_mode": "any",
            "include_banned": False,
        },
    ]
    for preset in defaults:
        try:
            save_ability_preset(db_path=db_path, **preset)
        except ValueError:
            continue


def seed_default_presets(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    defaults = [
        {
            "name": "Metronome Cup",
            "description": "Pokémon que aprendem Metronome, sem lendários nem míticos.",
            "filters": {"move": "metronome", "include_legendary": "0", "include_mythical": "0"},
        },
        {
            "name": "Inicial Draft",
            "description": "Linhas de iniciais marcadas pelo script de tags.",
            "filters": {"tag": "Inicial"},
        },
        {
            "name": "Bulky 400+",
            "description": "Pokémon com BST 400+ e pelo menos uma defesa base 90+.",
            "filters": {"min_bst": "400", "min_defense": "90", "include_legendary": "0", "include_mythical": "0"},
        },
    ]
    for preset in defaults:
        try:
            save_preset(
                name=preset["name"],
                description=preset["description"],
                filters=preset["filters"],
                db_path=db_path,
            )
        except ValueError:
            continue


def fallback_sprite_url(pokeapi_id: Any, *, official: bool = True) -> str:
    try:
        numeric_id = int(pokeapi_id)
    except (TypeError, ValueError):
        return ""
    if numeric_id <= 0:
        return ""
    base = OFFICIAL_ARTWORK_BASE_URL if official else DEFAULT_SPRITE_BASE_URL
    return base.format(pokeapi_id=numeric_id)


def pokemon_image_from_record(record: Optional[Dict[str, Any]], *, prefer_artwork: bool = True) -> str:
    if not record:
        return ""
    candidates = []
    if prefer_artwork:
        candidates.extend([record.get("image_url"), record.get("artwork_url"), record.get("sprite_url")])
    else:
        candidates.extend([record.get("sprite_url"), record.get("image_url"), record.get("artwork_url")])
    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text
    return fallback_sprite_url(record.get("pokeapi_id"), official=prefer_artwork)


def get_pokemon_image_url(
    name: str,
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
    prefer_artwork: bool = True,
) -> str:
    record = get_pokemon_record_by_name(name, db_path=db_path)
    return pokemon_image_from_record(record, prefer_artwork=prefer_artwork)


def search_pokemon(
    *,
    q: str = "",
    pokemon_type: str = "",
    ability: str = "",
    move: str = "",
    tag: str = "",
    min_bst: Optional[int] = None,
    max_bst: Optional[int] = None,
    min_hp: Optional[int] = None,
    min_attack: Optional[int] = None,
    min_defense: Optional[int] = None,
    min_sp_attack: Optional[int] = None,
    min_sp_defense: Optional[int] = None,
    min_speed: Optional[int] = None,
    include_legendary: bool = True,
    include_mythical: bool = True,
    limit: int = 200,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Busca Pokémon por filtros básicos. Será a base do Mega Draft Engine."""
    conditions: List[str] = []
    params: Dict[str, Any] = {"limit": max(1, min(limit, 500))}

    if q.strip():
        conditions.append("(p.name LIKE :q OR p.slug LIKE :q)")
        params["q"] = f"%{q.strip()}%"

    if pokemon_type.strip():
        conditions.append("(p.type1 = :type OR p.type2 = :type)")
        params["type"] = normalize_slug(pokemon_type)

    numeric_filters = {
        "min_bst": ("p.bst >= :min_bst", min_bst),
        "max_bst": ("p.bst <= :max_bst", max_bst),
        "min_hp": ("p.hp >= :min_hp", min_hp),
        "min_attack": ("p.attack >= :min_attack", min_attack),
        "min_defense": ("p.defense >= :min_defense", min_defense),
        "min_sp_attack": ("p.sp_attack >= :min_sp_attack", min_sp_attack),
        "min_sp_defense": ("p.sp_defense >= :min_sp_defense", min_sp_defense),
        "min_speed": ("p.speed >= :min_speed", min_speed),
    }
    for key, (condition, value) in numeric_filters.items():
        if value is not None:
            conditions.append(condition)
            params[key] = value

    if not include_legendary:
        conditions.append("p.is_legendary = 0")
    if not include_mythical:
        conditions.append("p.is_mythical = 0")

    if ability.strip():
        conditions.append(
            "EXISTS ("
            "SELECT 1 FROM pokemon_abilities pa "
            "JOIN abilities a ON a.id = pa.ability_id "
            "WHERE pa.pokemon_id = p.id AND (a.name LIKE :ability OR a.slug LIKE :ability)"
            ")"
        )
        params["ability"] = f"%{ability.strip().lower()}%"

    if move.strip():
        conditions.append(
            "EXISTS ("
            "SELECT 1 FROM pokemon_moves pm "
            "JOIN moves m ON m.id = pm.move_id "
            "WHERE pm.pokemon_id = p.id AND (m.name LIKE :move OR m.slug LIKE :move)"
            ")"
        )
        params["move"] = f"%{move.strip().lower()}%"

    if tag.strip():
        conditions.append(
            "EXISTS ("
            "SELECT 1 FROM pokemon_tags pt "
            "JOIN tags t ON t.id = pt.tag_id "
            "WHERE pt.pokemon_id = p.id AND (t.name LIKE :tag OR t.category LIKE :tag)"
            ")"
        )
        params["tag"] = f"%{tag.strip()}%"

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""
        SELECT
            p.id,
            p.pokeapi_id,
            p.name,
            p.slug,
            p.generation,
            p.type1,
            p.type2,
            p.hp,
            p.attack,
            p.defense,
            p.sp_attack,
            p.sp_defense,
            p.speed,
            p.bst,
            p.sprite_url,
            p.artwork_url,
            p.image_url,
            p.is_legendary,
            p.is_mythical,
            p.is_pseudo,
            p.is_ultra_beast,
            p.is_paradox,
            p.is_starter
        FROM pokemon p
        {where_sql}
        ORDER BY p.bst DESC, p.name ASC
        LIMIT :limit
    """

    with connect(db_path) as connection:
        return rows_to_dicts(connection.execute(query, params).fetchall())
