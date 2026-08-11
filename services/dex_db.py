from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = BASE_DIR / "data" / "mega_dex.sqlite3"
SCHEMA_PATH = BASE_DIR / "database" / "schema.sql"


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


def init_database(db_path: Path | str = DEFAULT_DB_PATH) -> Path:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
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
    return {
        "pokemon_count": pokemon_count,
        "ability_count": ability_count,
        "move_count": move_count,
        "pokemon_move_count": pokemon_move_count,
        "tag_count": tag_count,
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
