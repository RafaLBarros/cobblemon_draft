from __future__ import annotations

import json
import os
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, Response, flash, redirect, render_template, request, session, url_for

from services.dex_db import (
    DexUnavailable,
    delete_ability_preset,
    delete_draft_ruleset,
    delete_preset,
    dex_summary,
    get_ability_pool_from_preset,
    get_ability_preset,
    get_draft_ruleset,
    get_evolution_line_for_pokemon_name,
    get_evolution_lines_by_chain_ids,
    get_pokemon_records_in_evolution_line,
    get_preset,
    get_pokemon_pool_from_preset,
    get_pokemon_record_by_name,
    get_pokemon_records_by_names,
    get_pokemon_records_by_species_for_pokemon_name,
    get_species_summaries_by_species_slugs,
    list_ability_names,
    list_ability_presets,
    list_ability_tags,
    list_draft_rulesets,
    list_presets,
    save_ability_preset,
    save_draft_ruleset,
    save_preset,
    search_abilities,
    search_abilities_from_preset,
    search_evolution_lines,
    search_pokemon_from_filters,
    update_ability_metadata,
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
STATE_FILE = BASE_DIR / "draft_state.json"
DEX_DB_FILE = DATA_DIR / "mega_dex.sqlite3"

POKEMON_FILE = DATA_DIR / "pokemon.txt"
ABILITIES_FILE = DATA_DIR / "abilities.txt"
POKEMON_BANLIST_FILE = DATA_DIR / "pokemon_banlist.txt"
ABILITIES_BANLIST_FILE = DATA_DIR / "abilities_banlist.txt"
POKEMON_GROUPS_FILE = DATA_DIR / "pokemon_groups.txt"
POKEMON_FLAGS_FILE = DATA_DIR / "pokemon_flags.json"

MAX_POKEMON = 6
POKEMON_OPTIONS_PER_DRAW = 3
ABILITY_OPTIONS_PER_DRAW = 3
OPTIONS_PER_DRAW = 3  # legado: estados antigos usavam este nome
POKEMON_POOL_SOURCE_TXT = "txt"
POKEMON_POOL_SOURCE_DEX_PRESET = "dex_preset"
ABILITY_POOL_SOURCE_TXT = "txt"
ABILITY_POOL_SOURCE_DEX = "dex_all"
ABILITY_POOL_SOURCE_DEX_TAG = "dex_tag"
ABILITY_POOL_SOURCE_DEX_PRESET = "dex_preset"
ROUND_POKEMON_POOL_SOURCE_GLOBAL = "global"
POKEMON_LOCK_SCOPE_EXACT = "exact"
POKEMON_LOCK_SCOPE_SPECIES = "species"
POKEMON_LOCK_SCOPE_EVOLUTION_LINE = "evolution_line"
POKEMON_LOCK_SCOPE_LEGACY_GROUP = "legacy_group"
DEFAULT_POKEMON_LOCK_SCOPE = POKEMON_LOCK_SCOPE_EVOLUTION_LINE
POKEMON_LOCK_SCOPE_LABELS = {
    POKEMON_LOCK_SCOPE_EXACT: "Somente forma sorteada",
    POKEMON_LOCK_SCOPE_SPECIES: "Formas da mesma espécie",
    POKEMON_LOCK_SCOPE_EVOLUTION_LINE: "Linha evolutiva inteira",
    POKEMON_LOCK_SCOPE_LEGACY_GROUP: "Grupos TXT legados",
}
BUDGET_COST_MODE_POKEMON_BST = "pokemon_bst"
BUDGET_COST_MODE_SPECIES_MAX_BST = "species_max_bst"
BUDGET_COST_MODE_LINE_MAX_BST = "line_max_bst"
DEFAULT_BUDGET_COST_MODE = BUDGET_COST_MODE_POKEMON_BST
DEFAULT_BUDGET_POINTS_PER_PLAYER = 3000
DEFAULT_UNKNOWN_POKEMON_COST = 450
DEFAULT_BUDGET_FLAG_COSTS = {
    "Lendario": 300,
    "Mitico": 300,
    "Ultra Beast": 150,
    "Paradox": 120,
    "Pseudo": 100,
    "Inicial": 50,
}
ADMIN_KEY = os.environ.get("DRAFT_ADMIN_KEY", "cobbleverse")
MASTER_KEY = os.environ.get("DRAFT_MASTER_KEY", "mestre")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def default_state() -> Dict[str, Any]:
    return {
        "created_at": now_text(),
        "updated_at": now_text(),
        "version": 0,
        "used_pokemon": [],
        "players": {},
        "settings": {
            "max_pokemon": MAX_POKEMON,
            "pokemon_options_per_draw": POKEMON_OPTIONS_PER_DRAW,
            "ability_options_per_draw": ABILITY_OPTIONS_PER_DRAW,
            "options_per_draw": POKEMON_OPTIONS_PER_DRAW,  # compatibilidade com versões antigas
            "pokemon_pool_source": POKEMON_POOL_SOURCE_DEX_PRESET,
            "pokemon_preset_id": None,
            "ability_pool_source": ABILITY_POOL_SOURCE_DEX_PRESET,
            "ability_tag_filter": "Metronome Boa",
            "ability_preset_id": None,
            "rounds_enabled": False,
            "draft_rounds": [],
            "budget_enabled": False,
            "budget_cost_mode": DEFAULT_BUDGET_COST_MODE,
            "budget_points_per_player": DEFAULT_BUDGET_POINTS_PER_PLAYER,
            "budget_unknown_pokemon_cost": DEFAULT_UNKNOWN_POKEMON_COST,
            "budget_flag_costs": dict(DEFAULT_BUDGET_FLAG_COSTS),
            "lock_chosen_pokemon_globally": True,
            "pokemon_lock_scope": DEFAULT_POKEMON_LOCK_SCOPE,
            "lock_abilities_globally": False,
            "flag_karma": {
                "Lendario": {
                    "enabled": True,
                    "guarantee_draw": 6,
                    "mode": "linear",
                }
            },
        },
    }


def empty_pending() -> Dict[str, Any]:
    return {
        "type": None,
        "pokemon_options": [],
        "ability_for_index": None,
        "ability_options": [],
        "choice_id": None,
        "round_index": None,
        "round_name": None,
    }


def generate_player_id(existing_ids: set[str]) -> str:
    """Gera um ID numérico para URL, evitando /player/Rafael ou algo adivinhável."""
    while True:
        player_id = "".join(random.choice("0123456789") for _ in range(10))
        if player_id not in existing_ids:
            return player_id


def ensure_files_exist() -> None:
    DATA_DIR.mkdir(exist_ok=True)

    if not POKEMON_FILE.exists():
        POKEMON_FILE.write_text(
            "\n".join(
                [
                    "Gengar",
                    "Toxtricity",
                    "Mismagius",
                    "Ceruledge",
                    "Sneasler",
                    "Indeedee-F",
                    "Arcanine",
                    "Azumarill",
                    "Rotom",
                    "Garchomp",
                    "Whimsicott",
                    "Archaludon",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    if not ABILITIES_FILE.exists():
        ABILITIES_FILE.write_text(
            "\n".join(
                [
                    "Adaptability",
                    "Intimidate",
                    "Levitate",
                    "Magic Guard",
                    "Prankster",
                    "Regenerator",
                    "Huge Power",
                    "Shadow Tag",
                    "Poison Touch",
                    "Punk Rock",
                    "Flash Fire",
                    "Swift Swim",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    for path in [POKEMON_BANLIST_FILE, ABILITIES_BANLIST_FILE]:
        if not path.exists():
            path.write_text("", encoding="utf-8")

    if not POKEMON_GROUPS_FILE.exists():
        POKEMON_GROUPS_FILE.write_text(
            "# Um grupo por linha. Quando um Pokémon do grupo for escolhido, todos ficam bloqueados.\n"
            "# Formatos aceitos:\n"
            "# Bulbasaur, Ivysaur, Venusaur\n"
            "# Charmander > Charmeleon > Charizard\n"
            "# Abra | Kadabra | Alakazam\n",
            encoding="utf-8",
        )

    if not POKEMON_FLAGS_FILE.exists():
        POKEMON_FLAGS_FILE.write_text(
            json.dumps(
                {
                    "flag_limits": {"Lendario": 1},
                    "pokemon_flags": {}
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def load_lines(path: Path) -> List[str]:
    ensure_files_exist()
    if not path.exists():
        return []

    seen = set()
    values: List[str] = []

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        key = line.lower()
        if key not in seen:
            seen.add(key)
            values.append(line)

    return values


def load_pool(pool_file: Path, banlist_file: Path) -> List[str]:
    pool = load_lines(pool_file)
    banlist = {item.lower() for item in load_lines(banlist_file)}
    return [item for item in pool if item.lower() not in banlist]



def safe_int_value(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def clamp_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(max_value, parsed))


def normalize_pokemon_lock_scope(value: Any) -> str:
    scope = str(value or DEFAULT_POKEMON_LOCK_SCOPE).strip()
    if scope not in POKEMON_LOCK_SCOPE_LABELS:
        return DEFAULT_POKEMON_LOCK_SCOPE
    return scope


def pokemon_lock_scope(state: Dict[str, Any]) -> str:
    settings = state.setdefault("settings", {})
    scope = normalize_pokemon_lock_scope(settings.get("pokemon_lock_scope"))
    settings["pokemon_lock_scope"] = scope
    return scope


def pokemon_lock_scope_label(state_or_scope: Any) -> str:
    if isinstance(state_or_scope, dict):
        scope = pokemon_lock_scope(state_or_scope)
    else:
        scope = normalize_pokemon_lock_scope(state_or_scope)
    return POKEMON_LOCK_SCOPE_LABELS.get(scope, POKEMON_LOCK_SCOPE_LABELS[DEFAULT_POKEMON_LOCK_SCOPE])


def pokemon_lock_scope_options() -> List[Dict[str, str]]:
    """Opções visíveis no fluxo novo do MegaDraft.

    O modo de grupos TXT continua reconhecido para compatibilidade de estados antigos,
    mas deixa de aparecer na UI principal.
    """
    return [
        {"value": value, "label": label}
        for value, label in POKEMON_LOCK_SCOPE_LABELS.items()
        if value != POKEMON_LOCK_SCOPE_LEGACY_GROUP
    ]


def get_active_pokemon_preset(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    settings = state.setdefault("settings", {})
    preset_id = safe_int_value(settings.get("pokemon_preset_id"))
    if preset_id is None:
        return None
    try:
        return get_preset(preset_id, DEX_DB_FILE)
    except DexUnavailable:
        return None


def get_active_ability_preset(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    settings = state.setdefault("settings", {})
    preset_id = safe_int_value(settings.get("ability_preset_id"))
    if preset_id is None:
        return None
    try:
        return get_ability_preset(preset_id, DEX_DB_FILE)
    except DexUnavailable:
        return None


def get_pokemon_pool_from_source(source: str, preset_id: Any = None) -> List[str]:
    """Retorna uma pool de Pokémon a partir de uma fonte específica."""
    if source == POKEMON_POOL_SOURCE_DEX_PRESET:
        parsed_preset_id = safe_int_value(preset_id)
        if parsed_preset_id is None:
            return []
        try:
            pool = get_pokemon_pool_from_preset(parsed_preset_id, db_path=DEX_DB_FILE, limit=10000)
        except DexUnavailable:
            return []
        banlist = {item.lower() for item in load_lines(POKEMON_BANLIST_FILE)}
        return [item for item in pool if item.lower() not in banlist]
    return load_pool(POKEMON_FILE, POKEMON_BANLIST_FILE)


def get_current_pokemon_pool(state: Dict[str, Any]) -> List[str]:
    """Retorna a pool global ativa de Pokémon a partir do MegaDex.

    Os TXT antigos continuam existindo só como compatibilidade interna para estados
    antigos/importados, mas a interface nova trabalha exclusivamente com presets.
    """
    settings = state.setdefault("settings", {})
    return get_pokemon_pool_from_source(
        str(settings.get("pokemon_pool_source", POKEMON_POOL_SOURCE_DEX_PRESET)),
        settings.get("pokemon_preset_id"),
    )


def get_current_ability_pool(state: Dict[str, Any]) -> List[str]:
    settings = state.setdefault("settings", {})
    source = settings.get("ability_pool_source", ABILITY_POOL_SOURCE_DEX_PRESET)
    if source == ABILITY_POOL_SOURCE_DEX_PRESET:
        preset_id = safe_int_value(settings.get("ability_preset_id"))
        if preset_id is None:
            return []
        try:
            pool = get_ability_pool_from_preset(preset_id, db_path=DEX_DB_FILE, limit=10000)
        except DexUnavailable:
            return []
        banlist = {item.lower() for item in load_lines(ABILITIES_BANLIST_FILE)}
        return [item for item in pool if item.lower() not in banlist]
    if source in {ABILITY_POOL_SOURCE_DEX, ABILITY_POOL_SOURCE_DEX_TAG}:
        tag_filter = str(settings.get("ability_tag_filter") or "").strip() if source == ABILITY_POOL_SOURCE_DEX_TAG else ""
        try:
            pool = list_ability_names(
                db_path=DEX_DB_FILE,
                include_banned=False,
                tag=tag_filter,
                limit=10000,
            )
        except DexUnavailable:
            return []
        banlist = {item.lower() for item in load_lines(ABILITIES_BANLIST_FILE)}
        return [item for item in pool if item.lower() not in banlist]
    return load_pool(ABILITIES_FILE, ABILITIES_BANLIST_FILE)


def pokemon_pool_source_label(state: Dict[str, Any]) -> str:
    settings = state.setdefault("settings", {})
    if settings.get("pokemon_pool_source") == POKEMON_POOL_SOURCE_DEX_PRESET:
        preset = get_active_pokemon_preset(state)
        return f"MegaDex: {preset['name']}" if preset else "MegaDex: preset inválido"
    return "Compatibilidade TXT"


def ability_pool_source_label(state: Dict[str, Any]) -> str:
    settings = state.setdefault("settings", {})
    if settings.get("ability_pool_source") == ABILITY_POOL_SOURCE_DEX:
        return "MegaDex: todas as abilities"
    if settings.get("ability_pool_source") == ABILITY_POOL_SOURCE_DEX_TAG:
        tag_filter = str(settings.get("ability_tag_filter") or "").strip()
        return f"MegaDex: tag {tag_filter}" if tag_filter else "MegaDex: tag vazia"
    if settings.get("ability_pool_source") == ABILITY_POOL_SOURCE_DEX_PRESET:
        preset = get_active_ability_preset(state)
        return f"MegaDex: preset {preset['name']}" if preset else "MegaDex: preset de ability inválido"
    return "Compatibilidade TXT"


def pool_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    pokemon_pool = get_current_pokemon_pool(state)
    ability_pool = get_current_ability_pool(state)
    return {
        "pokemon_count": len(pokemon_pool),
        "ability_count": len(ability_pool),
        "pokemon_source": pokemon_pool_source_label(state),
        "ability_source": ability_pool_source_label(state),
    }



def normalize_round_pokemon_source(value: Any) -> str:
    source = str(value or ROUND_POKEMON_POOL_SOURCE_GLOBAL).strip()
    if source == POKEMON_POOL_SOURCE_TXT:
        return ROUND_POKEMON_POOL_SOURCE_GLOBAL
    if source not in {ROUND_POKEMON_POOL_SOURCE_GLOBAL, POKEMON_POOL_SOURCE_DEX_PRESET}:
        return ROUND_POKEMON_POOL_SOURCE_GLOBAL
    return source


def normalize_draft_rounds(raw_rounds: Any, max_slots: int = MAX_POKEMON) -> List[Dict[str, Any]]:
    if not isinstance(raw_rounds, list):
        raw_rounds = []

    rounds: List[Dict[str, Any]] = []
    for index in range(max(1, min(max_slots, 30))):
        raw = raw_rounds[index] if index < len(raw_rounds) and isinstance(raw_rounds[index], dict) else {}
        source = normalize_round_pokemon_source(raw.get("pokemon_pool_source"))
        options_raw = safe_int_value(raw.get("pokemon_options_per_draw"))
        rounds.append({
            "index": index,
            "slot": index + 1,
            "name": str(raw.get("name") or f"Rodada {index + 1}").strip() or f"Rodada {index + 1}",
            "pokemon_pool_source": source,
            "pokemon_preset_id": safe_int_value(raw.get("pokemon_preset_id")) if source == POKEMON_POOL_SOURCE_DEX_PRESET else None,
            "pokemon_options_per_draw": options_raw if options_raw is not None else None,
        })
    return rounds


def draft_rounds_enabled(state: Dict[str, Any]) -> bool:
    return bool(state.setdefault("settings", {}).get("rounds_enabled"))


def get_configured_draft_rounds(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    settings = state.setdefault("settings", {})
    max_slots = setting_int(state, "max_pokemon", MAX_POKEMON, 1, 30)
    rounds = normalize_draft_rounds(settings.get("draft_rounds", []), max_slots=max_slots)
    settings["draft_rounds"] = rounds
    return rounds


def get_next_pokemon_round(player: Dict[str, Any], state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not draft_rounds_enabled(state):
        return None
    index = len(player.get("pokemon_picks", []))
    rounds = get_configured_draft_rounds(state)
    if 0 <= index < len(rounds):
        return rounds[index]
    return None


def pokemon_round_label(round_config: Optional[Dict[str, Any]], fallback_index: Optional[int] = None) -> str:
    if round_config:
        name = str(round_config.get("name") or "").strip()
        if name:
            return name
        slot = round_config.get("slot")
        if slot:
            return f"Rodada {slot}"
    if isinstance(fallback_index, int):
        return f"Rodada {fallback_index + 1}"
    return "Rodada global"


def pokemon_round_label_for_pick(pick: Dict[str, Any], index: int) -> str:
    name = str(pick.get("round_name") or "").strip() if isinstance(pick, dict) else ""
    return name


def get_pokemon_pool_for_round(state: Dict[str, Any], round_config: Optional[Dict[str, Any]]) -> List[str]:
    if not round_config or round_config.get("pokemon_pool_source") == ROUND_POKEMON_POOL_SOURCE_GLOBAL:
        return get_current_pokemon_pool(state)
    return get_pokemon_pool_from_source(
        str(round_config.get("pokemon_pool_source") or POKEMON_POOL_SOURCE_TXT),
        round_config.get("pokemon_preset_id"),
    )


def get_pokemon_options_per_draw_for_round(state: Dict[str, Any], round_config: Optional[Dict[str, Any]]) -> int:
    if round_config and round_config.get("pokemon_options_per_draw") is not None:
        return max(1, min(20, int(round_config.get("pokemon_options_per_draw"))))
    return get_pokemon_options_per_draw(state)


def next_pokemon_options_per_draw(player: Dict[str, Any], state: Dict[str, Any]) -> int:
    return get_pokemon_options_per_draw_for_round(state, get_next_pokemon_round(player, state))


def next_pokemon_round_summary(player: Dict[str, Any], state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    round_config = get_next_pokemon_round(player, state)
    if not round_config:
        return None
    pool = get_pokemon_pool_for_round(state, round_config)
    source = round_config.get("pokemon_pool_source")
    if source == POKEMON_POOL_SOURCE_DEX_PRESET:
        preset = None
        preset_id = safe_int_value(round_config.get("pokemon_preset_id"))
        if preset_id is not None:
            try:
                preset = get_preset(preset_id, DEX_DB_FILE)
            except DexUnavailable:
                preset = None
        source_label = f"MegaDex: {preset['name']}" if preset else "MegaDex: preset inválido"
    else:
        source_label = pokemon_pool_source_label(state)
    return {
        "index": round_config.get("index"),
        "slot": round_config.get("slot"),
        "name": pokemon_round_label(round_config),
        "source": source_label,
        "pokemon_count": len(pool),
        "options_per_draw": get_pokemon_options_per_draw_for_round(state, round_config),
    }


def draft_rounds_preview(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    previews: List[Dict[str, Any]] = []
    for round_config in get_configured_draft_rounds(state):
        pool = get_pokemon_pool_for_round(state, round_config)
        previews.append({
            **round_config,
            "label": pokemon_round_label(round_config),
            "pokemon_count": len(pool),
            "options_effective": get_pokemon_options_per_draw_for_round(state, round_config),
        })
    return previews


def get_lockable_pokemon_pool(state: Optional[Dict[str, Any]]) -> List[str]:
    """União da pool global com as pools de rodadas para travar famílias/evoluções corretamente."""
    if state is None:
        return load_pool(POKEMON_FILE, POKEMON_BANLIST_FILE)
    names: List[str] = []
    seen = set()
    for pool in [get_current_pokemon_pool(state)] + [get_pokemon_pool_for_round(state, round_config) for round_config in get_configured_draft_rounds(state)]:
        for name in pool:
            key = normalize_name_key(name)
            if key and key not in seen:
                seen.add(key)
                names.append(name)
    return names


def state_with_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    state = default_state()
    state["settings"].update(settings)
    return state


def ruleset_pool_summary(settings: Dict[str, Any]) -> Dict[str, Any]:
    return pool_summary(state_with_settings(settings))


def settings_from_ruleset_form(form: Any) -> Dict[str, Any]:
    """Lê do formulário as configurações que compõem um ruleset."""
    return {
        "max_pokemon": clamp_int(form.get("max_pokemon"), MAX_POKEMON, 1, 30),
        "pokemon_options_per_draw": clamp_int(form.get("pokemon_options_per_draw"), POKEMON_OPTIONS_PER_DRAW, 1, 20),
        "ability_options_per_draw": clamp_int(form.get("ability_options_per_draw"), ABILITY_OPTIONS_PER_DRAW, 1, 20),
        "pokemon_pool_source": POKEMON_POOL_SOURCE_DEX_PRESET,
        "pokemon_preset_id": safe_int_value(form.get("pokemon_preset_id")),
        "ability_pool_source": form.get("ability_pool_source", ABILITY_POOL_SOURCE_DEX_PRESET),
        "ability_tag_filter": form.get("ability_tag_filter", "").strip(),
        "ability_preset_id": safe_int_value(form.get("ability_preset_id")),
        "lock_chosen_pokemon_globally": form.get("lock_chosen_pokemon_globally") == "on",
        "pokemon_lock_scope": normalize_pokemon_lock_scope(form.get("pokemon_lock_scope")),
        "lock_abilities_globally": form.get("lock_abilities_globally") == "on",
        "budget_enabled": form.get("budget_enabled") == "on",
        "budget_cost_mode": normalize_budget_cost_mode(form.get("budget_cost_mode")),
        "budget_points_per_player": clamp_int(form.get("budget_points_per_player"), DEFAULT_BUDGET_POINTS_PER_PLAYER, 1, 20000),
        "budget_unknown_pokemon_cost": clamp_int(form.get("budget_unknown_pokemon_cost"), DEFAULT_UNKNOWN_POKEMON_COST, 0, 20000),
        "budget_flag_costs": parse_budget_flag_costs_text(form.get("budget_flag_costs", "")) or dict(DEFAULT_BUDGET_FLAG_COSTS),
        "flag_karma": parse_flag_karma_text(form.get("flag_karma", "")),
    }


def apply_ruleset_settings_to_state(state: Dict[str, Any], settings: Dict[str, Any]) -> None:
    """Aplica um ruleset no draft atual sem mexer em jogadores/escolhas existentes."""
    current = state.setdefault("settings", {})
    for key, value in settings.items():
        current[key] = value
    # Compatibilidade com partes antigas do estado que ainda liam options_per_draw.
    current["options_per_draw"] = current.get("pokemon_options_per_draw", POKEMON_OPTIONS_PER_DRAW)


def used_abilities_for_state(state: Dict[str, Any]) -> List[str]:
    used: List[str] = []
    seen = set()
    for player in state.get("players", {}).values():
        if not isinstance(player, dict):
            continue
        for pick in player.get("pokemon_picks", []):
            if not isinstance(pick, dict):
                continue
            ability = str(pick.get("ability") or "").strip()
            key = ability.lower()
            if ability and key not in seen:
                used.append(ability)
                seen.add(key)
    return used

def load_flag_config() -> Dict[str, Any]:
    ensure_files_exist()
    default = {"flag_limits": {"Lendario": 1}, "pokemon_flags": {}}
    try:
        data = json.loads(POKEMON_FLAGS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return default

    if not isinstance(data, dict):
        return default

    limits = data.get("flag_limits") if isinstance(data.get("flag_limits"), dict) else {}
    cleaned_limits: Dict[str, int] = {}
    for raw_flag, raw_limit in limits.items():
        flag = str(raw_flag).strip()
        if not flag:
            continue
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            continue
        cleaned_limits[flag] = max(0, limit)

    pokemon_flags = data.get("pokemon_flags") if isinstance(data.get("pokemon_flags"), dict) else {}
    cleaned_pokemon_flags: Dict[str, List[str]] = {}
    for raw_pokemon, raw_flags in pokemon_flags.items():
        pokemon = str(raw_pokemon).strip()
        if not pokemon:
            continue
        if isinstance(raw_flags, str):
            raw_flags = [raw_flags]
        if not isinstance(raw_flags, list):
            continue
        flags: List[str] = []
        seen = set()
        for raw_flag in raw_flags:
            flag = str(raw_flag).strip()
            key = flag.lower()
            if flag and key not in seen:
                flags.append(flag)
                seen.add(key)
        if flags:
            cleaned_pokemon_flags[pokemon] = flags

    return {
        "flag_limits": cleaned_limits or default["flag_limits"],
        "pokemon_flags": cleaned_pokemon_flags,
    }


def save_flag_config(config: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    POKEMON_FLAGS_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def flags_for_pokemon(pokemon_name: str, config: Optional[Dict[str, Any]] = None) -> List[str]:
    config = config or load_flag_config()
    wanted = normalize_name_key(pokemon_name)
    for configured_name, flags in config.get("pokemon_flags", {}).items():
        if normalize_name_key(configured_name) == wanted:
            return list(flags)
    return []


def player_flag_counts(player: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    config = config or load_flag_config()
    counts: Dict[str, int] = {}
    for pick in player.get("pokemon_picks", []):
        pokemon_name = pick.get("name") if isinstance(pick, dict) else str(pick)
        for flag in flags_for_pokemon(pokemon_name, config):
            counts[flag] = counts.get(flag, 0) + 1
    return counts


def excluded_by_flag_limits(player: Dict[str, Any], pokemon_pool: List[str], config: Optional[Dict[str, Any]] = None) -> List[str]:
    config = config or load_flag_config()
    counts = player_flag_counts(player, config)
    limits = config.get("flag_limits", {})
    blocked_flags = {flag for flag, limit in limits.items() if int(limit) >= 0 and counts.get(flag, 0) >= int(limit)}
    if not blocked_flags:
        return []

    excluded: List[str] = []
    for pokemon in pokemon_pool:
        if blocked_flags.intersection(set(flags_for_pokemon(pokemon, config))):
            excluded.append(pokemon)
    return excluded


def normalize_flag_config_from_form(flag_limits_text: str, pokemon_flags: Any) -> Dict[str, Any]:
    limits: Dict[str, int] = {}
    for raw_line in str(flag_limits_text or "").replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            flag, value = line.split("=", 1)
        elif ":" in line:
            flag, value = line.split(":", 1)
        else:
            continue
        flag = flag.strip()
        try:
            limit = int(value.strip())
        except ValueError:
            continue
        if flag:
            limits[flag] = max(0, limit)

    cleaned_flags: Dict[str, List[str]] = {}
    if isinstance(pokemon_flags, dict):
        pokemon_pool = load_pool(POKEMON_FILE, POKEMON_BANLIST_FILE)
        canonical = {normalize_name_key(name): name for name in pokemon_pool}
        known_flags = {flag.lower(): flag for flag in limits.keys()}
        for raw_pokemon, raw_flags in pokemon_flags.items():
            key = normalize_name_key(raw_pokemon)
            pokemon = canonical.get(key, str(raw_pokemon).strip())
            if not pokemon:
                continue
            if isinstance(raw_flags, str):
                raw_flags = [raw_flags]
            if not isinstance(raw_flags, list):
                continue
            flags: List[str] = []
            seen = set()
            for raw_flag in raw_flags:
                flag_key = str(raw_flag).strip().lower()
                flag = known_flags.get(flag_key, str(raw_flag).strip())
                if flag and flag_key not in seen:
                    flags.append(flag)
                    seen.add(flag_key)
            if flags:
                cleaned_flags[pokemon] = flags

    return {"flag_limits": limits or {"Lendario": 1}, "pokemon_flags": cleaned_flags}


def flag_limits_text(config: Dict[str, Any]) -> str:
    return "\n".join(f"{flag}={limit}" for flag, limit in config.get("flag_limits", {}).items())


def available_flags(config: Dict[str, Any]) -> List[str]:
    flags = list(config.get("flag_limits", {}).keys())
    seen = {flag.lower() for flag in flags}
    for flag_list in config.get("pokemon_flags", {}).values():
        for flag in flag_list:
            if str(flag).lower() not in seen:
                flags.append(str(flag))
                seen.add(str(flag).lower())
    return flags


def parse_budget_flag_costs_text(text: str) -> Dict[str, int]:
    costs: Dict[str, int] = {}
    for raw_line in str(text or "").replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            flag, value = line.split("=", 1)
        elif ":" in line:
            flag, value = line.split(":", 1)
        else:
            continue
        flag = flag.strip()
        if not flag:
            continue
        try:
            costs[flag] = int(value.strip())
        except ValueError:
            continue
    return costs


def normalize_budget_flag_costs(raw: Any) -> Dict[str, int]:
    if not isinstance(raw, dict):
        return dict(DEFAULT_BUDGET_FLAG_COSTS)
    normalized: Dict[str, int] = {}
    for raw_flag, raw_cost in raw.items():
        flag = str(raw_flag).strip()
        if not flag:
            continue
        try:
            normalized[flag] = int(raw_cost)
        except (TypeError, ValueError):
            continue
    return normalized or dict(DEFAULT_BUDGET_FLAG_COSTS)


def budget_flag_costs_text(settings: Dict[str, Any]) -> str:
    costs = normalize_budget_flag_costs(settings.get("budget_flag_costs"))
    return "\n".join(f"{flag}={cost}" for flag, cost in costs.items())


def budget_enabled(state: Dict[str, Any]) -> bool:
    return bool(state.setdefault("settings", {}).get("budget_enabled", False))


def budget_total_points(state: Dict[str, Any]) -> int:
    return setting_int(state, "budget_points_per_player", DEFAULT_BUDGET_POINTS_PER_PLAYER, 1, 20000)


def budget_unknown_pokemon_cost(state: Dict[str, Any]) -> int:
    return setting_int(state, "budget_unknown_pokemon_cost", DEFAULT_UNKNOWN_POKEMON_COST, 0, 20000)


def normalize_budget_cost_mode(value: Any) -> str:
    value = str(value or "").strip()
    if value in {
        BUDGET_COST_MODE_POKEMON_BST,
        BUDGET_COST_MODE_SPECIES_MAX_BST,
        BUDGET_COST_MODE_LINE_MAX_BST,
    }:
        return value
    return DEFAULT_BUDGET_COST_MODE


def budget_cost_mode(state: Dict[str, Any]) -> str:
    settings = state.setdefault("settings", {})
    mode = normalize_budget_cost_mode(settings.get("budget_cost_mode"))
    settings["budget_cost_mode"] = mode
    return mode


def budget_cost_mode_label(mode: str) -> str:
    labels = {
        BUDGET_COST_MODE_POKEMON_BST: "BST da forma sorteada",
        BUDGET_COST_MODE_SPECIES_MAX_BST: "Maior BST da species/formas",
        BUDGET_COST_MODE_LINE_MAX_BST: "Maior BST da linha evolutiva",
    }
    return labels.get(normalize_budget_cost_mode(mode), labels[BUDGET_COST_MODE_POKEMON_BST])


def intrinsic_budget_flags(record: Optional[Dict[str, Any]]) -> List[str]:
    if not record:
        return []
    flags: List[str] = []
    if int(record.get("is_legendary") or 0):
        flags.append("Lendario")
    if int(record.get("is_mythical") or 0):
        flags.append("Mitico")
    if int(record.get("is_ultra_beast") or 0):
        flags.append("Ultra Beast")
    if int(record.get("is_paradox") or 0):
        flags.append("Paradox")
    if int(record.get("is_pseudo") or 0):
        flags.append("Pseudo")
    if int(record.get("is_starter") or 0):
        flags.append("Inicial")
    return flags


def budget_flags_for_pokemon(pokemon_name: str, record: Optional[Dict[str, Any]] = None) -> List[str]:
    flags: List[str] = []
    seen = set()
    for flag in intrinsic_budget_flags(record) + flags_for_pokemon(pokemon_name):
        key = str(flag).strip().lower()
        if key and key not in seen:
            flags.append(str(flag).strip())
            seen.add(key)
    return flags


def budget_cost_payload(
    pokemon_name: str,
    state: Dict[str, Any],
    record: Optional[Dict[str, Any]] = None,
    evolution_line: Optional[Dict[str, Any]] = None,
    species_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if record is None:
        try:
            record = get_pokemon_record_by_name(pokemon_name, db_path=DEX_DB_FILE)
        except DexUnavailable:
            record = None

    unknown = record is None
    mode = budget_cost_mode(state)
    line_slug = None
    representative_name = None
    line_member_count = 0
    species_slug = None
    species_representative_name = None
    species_member_count = 0

    if record and mode == BUDGET_COST_MODE_SPECIES_MAX_BST:
        species_slug = str(record.get("species_slug") or "").strip() or None
        if species_summary is None and species_slug:
            try:
                species_summary = get_species_summaries_by_species_slugs([species_slug], db_path=DEX_DB_FILE).get(species_slug)
            except DexUnavailable:
                species_summary = None
        if species_summary:
            base_cost = int(species_summary.get("max_bst") or record.get("bst") or 0)
            species_slug = species_summary.get("species_slug") or species_slug
            species_representative_name = species_summary.get("representative_pokemon_name")
            species_member_count = int(species_summary.get("form_count") or 0)
        else:
            base_cost = int(record.get("bst") or 0)
    elif record and mode == BUDGET_COST_MODE_LINE_MAX_BST:
        if evolution_line is None:
            try:
                evolution_line = get_evolution_line_for_pokemon_name(str(record.get("slug") or pokemon_name), db_path=DEX_DB_FILE)
            except DexUnavailable:
                evolution_line = None
        if evolution_line:
            base_cost = int(evolution_line.get("max_bst") or record.get("bst") or 0)
            line_slug = evolution_line.get("line_slug")
            representative_name = evolution_line.get("representative_pokemon_name")
            line_member_count = len(evolution_line.get("pokemon_slugs") or [])
        else:
            base_cost = int(record.get("bst") or 0)
    else:
        base_cost = int(record.get("bst") or 0) if record else budget_unknown_pokemon_cost(state)

    flags = budget_flags_for_pokemon(pokemon_name, record)
    flag_costs = normalize_budget_flag_costs(state.setdefault("settings", {}).get("budget_flag_costs"))
    flag_cost_lookup = {flag.lower(): cost for flag, cost in flag_costs.items()}
    bonus = sum(int(flag_cost_lookup.get(flag.lower(), 0)) for flag in flags)
    cost = max(0, base_cost + bonus)
    return {
        "name": pokemon_name,
        "cost": cost,
        "base_cost": base_cost,
        "bonus_cost": bonus,
        "bst": int(record.get("bst") or 0) if record else None,
        "flags": flags,
        "unknown": unknown,
        "cost_mode": mode,
        "cost_mode_label": budget_cost_mode_label(mode),
        "line_slug": line_slug,
        "representative_name": representative_name,
        "line_member_count": line_member_count,
        "species_slug": species_slug,
        "species_representative_name": species_representative_name,
        "species_member_count": species_member_count,
    }


def budget_costs_for_pokemon_names(names: List[str], state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    try:
        records = get_pokemon_records_by_names(names, db_path=DEX_DB_FILE)
    except DexUnavailable:
        records = {}

    mode = budget_cost_mode(state)
    lines_by_chain: Dict[int, Dict[str, Any]] = {}
    species_summaries: Dict[str, Dict[str, Any]] = {}
    if mode == BUDGET_COST_MODE_LINE_MAX_BST:
        chain_ids = [
            int(record.get("evolution_chain_id"))
            for record in records.values()
            if record.get("evolution_chain_id") is not None
        ]
        try:
            lines_by_chain = get_evolution_lines_by_chain_ids(chain_ids, db_path=DEX_DB_FILE)
        except DexUnavailable:
            lines_by_chain = {}
    elif mode == BUDGET_COST_MODE_SPECIES_MAX_BST:
        species_slugs = [
            str(record.get("species_slug") or "").strip()
            for record in records.values()
            if str(record.get("species_slug") or "").strip()
        ]
        try:
            species_summaries = get_species_summaries_by_species_slugs(species_slugs, db_path=DEX_DB_FILE)
        except DexUnavailable:
            species_summaries = {}

    payloads: Dict[str, Dict[str, Any]] = {}
    for name in names:
        record = records.get(command_token(name)) or records.get(str(name).strip().lower())
        # command_token é permissivo demais para formas, então a chave correta é o slug da PokéAPI.
        if record is None:
            try:
                from services.dex_db import normalize_slug as _dex_normalize_slug
                record = records.get(_dex_normalize_slug(name))
            except Exception:
                record = None

        line = None
        if record and record.get("evolution_chain_id") is not None:
            try:
                line = lines_by_chain.get(int(record.get("evolution_chain_id")))
            except (TypeError, ValueError):
                line = None
        species_summary = None
        if record:
            species_summary = species_summaries.get(str(record.get("species_slug") or "").strip())
        payloads[name] = budget_cost_payload(name, state, record, line, species_summary)
    return payloads

def budget_cost_for_pick(pick: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    name = str(pick.get("name") or "").strip()
    stored_cost = safe_int_value(pick.get("budget_cost"))
    if stored_cost is not None:
        return {
            "name": name,
            "cost": stored_cost,
            "base_cost": safe_int_value(pick.get("budget_base_cost")),
            "bonus_cost": safe_int_value(pick.get("budget_bonus_cost")) or 0,
            "bst": safe_int_value(pick.get("budget_bst")),
            "flags": pick.get("budget_flags", []) if isinstance(pick.get("budget_flags"), list) else [],
            "unknown": bool(pick.get("budget_unknown", False)),
            "cost_mode": pick.get("budget_cost_mode") or budget_cost_mode(state),
            "cost_mode_label": budget_cost_mode_label(str(pick.get("budget_cost_mode") or budget_cost_mode(state))),
            "line_slug": pick.get("budget_line_slug"),
            "representative_name": pick.get("budget_representative_name"),
            "line_member_count": safe_int_value(pick.get("budget_line_member_count")) or 0,
            "species_slug": pick.get("budget_species_slug"),
            "species_representative_name": pick.get("budget_species_representative_name"),
            "species_member_count": safe_int_value(pick.get("budget_species_member_count")) or 0,
        }
    return budget_cost_payload(name, state)


def player_budget_spent(player: Dict[str, Any], state: Dict[str, Any]) -> int:
    return sum(budget_cost_for_pick(pick, state)["cost"] for pick in player.get("pokemon_picks", []) if isinstance(pick, dict))


def player_budget_summary(player: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    total = budget_total_points(state)
    spent = player_budget_spent(player, state)
    remaining = total - spent
    pick_costs = []
    for pick in player.get("pokemon_picks", []):
        if isinstance(pick, dict):
            pick_costs.append({"pick": pick, "cost": budget_cost_for_pick(pick, state)})
    return {
        "enabled": budget_enabled(state),
        "total": total,
        "spent": spent,
        "remaining": remaining,
        "over_budget": remaining < 0,
        "pick_costs": pick_costs,
    }


def excluded_by_budget_limits(player: Dict[str, Any], pokemon_pool: List[str], state: Dict[str, Any]) -> List[str]:
    if not budget_enabled(state):
        return []
    remaining = player_budget_summary(player, state)["remaining"]
    costs = budget_costs_for_pokemon_names(pokemon_pool, state)
    return [name for name in pokemon_pool if costs.get(name, {}).get("cost", 0) > remaining]


def stamp_budget_on_pick(pick: Dict[str, Any], pokemon_name: str, state: Dict[str, Any]) -> Dict[str, Any]:
    payload = budget_cost_payload(pokemon_name, state)
    pick["budget_cost"] = payload["cost"]
    pick["budget_base_cost"] = payload["base_cost"]
    pick["budget_bonus_cost"] = payload["bonus_cost"]
    pick["budget_bst"] = payload["bst"]
    pick["budget_flags"] = payload["flags"]
    pick["budget_unknown"] = payload["unknown"]
    pick["budget_cost_mode"] = payload.get("cost_mode")
    pick["budget_line_slug"] = payload.get("line_slug")
    pick["budget_representative_name"] = payload.get("representative_name")
    pick["budget_line_member_count"] = payload.get("line_member_count")
    pick["budget_species_slug"] = payload.get("species_slug")
    pick["budget_species_representative_name"] = payload.get("species_representative_name")
    pick["budget_species_member_count"] = payload.get("species_member_count")
    return pick


def reprice_all_picks(state: Dict[str, Any]) -> None:
    for player in state.get("players", {}).values():
        if not isinstance(player, dict):
            continue
        for pick in player.get("pokemon_picks", []):
            if isinstance(pick, dict):
                stamp_budget_on_pick(pick, str(pick.get("name") or ""), state)


def normalize_name_key(value: str) -> str:
    return str(value).strip().lower()


def split_group_line(line: str) -> List[str]:
    """Aceita linhas com vírgula, >, | ou ; como separador."""
    separators = [",", ">", "|", ";"]
    cleaned = line
    for sep in separators[1:]:
        cleaned = cleaned.replace(sep, separators[0])
    return [part.strip() for part in cleaned.split(separators[0]) if part.strip()]


def load_pokemon_groups() -> List[List[str]]:
    ensure_files_exist()
    if not POKEMON_GROUPS_FILE.exists():
        return []

    groups: List[List[str]] = []
    for raw_line in POKEMON_GROUPS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        group = split_group_line(line)
        seen = set()
        unique_group = []
        for pokemon in group:
            key = normalize_name_key(pokemon)
            if key not in seen:
                seen.add(key)
                unique_group.append(pokemon)

        if len(unique_group) >= 2:
            groups.append(unique_group)

    return groups


def related_pokemon_for(pokemon_name: str, groups: Optional[List[List[str]]] = None) -> List[str]:
    """Retorna o grupo vinculado ao Pokémon, ou só ele mesmo se não estiver agrupado."""
    wanted = normalize_name_key(pokemon_name)
    for group in groups if groups is not None else load_pokemon_groups():
        if wanted in {normalize_name_key(name) for name in group}:
            return group
    return [pokemon_name]


def group_lookup_map(groups: Optional[List[List[str]]] = None) -> Dict[str, List[str]]:
    mapping: Dict[str, List[str]] = {}
    for group in groups if groups is not None else load_pokemon_groups():
        for pokemon in group:
            mapping[normalize_name_key(pokemon)] = group
    return mapping


def related_pokemon_for_dex_species(pokemon_name: str, pokemon_pool: Optional[List[str]] = None) -> List[str]:
    try:
        records = get_pokemon_records_by_species_for_pokemon_name(pokemon_name, db_path=DEX_DB_FILE)
    except DexUnavailable:
        return []
    if not records:
        return []

    if pokemon_pool is not None:
        pool_by_slug = {}
        try:
            from services.dex_db import normalize_slug as _dex_normalize_slug
            for name in pokemon_pool:
                pool_by_slug[_dex_normalize_slug(name)] = name
        except Exception:
            pool_by_slug = {normalize_name_key(name).replace(" ", "-"): name for name in pokemon_pool}
        related = [pool_by_slug[str(record.get("slug") or "").strip().lower()] for record in records if str(record.get("slug") or "").strip().lower() in pool_by_slug]
        if related:
            return sorted(related, key=lambda item: str(item).lower())

    return [str(record.get("name")) for record in records if str(record.get("name") or "").strip()]


def related_pokemon_for_dex_line(pokemon_name: str, pokemon_pool: Optional[List[str]] = None) -> List[str]:
    try:
        line = get_evolution_line_for_pokemon_name(pokemon_name, db_path=DEX_DB_FILE)
    except DexUnavailable:
        return []
    if not line:
        return []

    line_slugs = {str(slug).strip().lower() for slug in line.get("pokemon_slugs", []) if str(slug).strip()}
    if not line_slugs:
        return []

    if pokemon_pool is not None:
        pool_by_slug = {}
        try:
            from services.dex_db import normalize_slug as _dex_normalize_slug
            for name in pokemon_pool:
                pool_by_slug[_dex_normalize_slug(name)] = name
        except Exception:
            pool_by_slug = {normalize_name_key(name).replace(" ", "-"): name for name in pokemon_pool}
        related = [pool_by_slug[slug] for slug in line_slugs if slug in pool_by_slug]
        if related:
            return sorted(related, key=lambda item: str(item).lower())

    try:
        records = get_pokemon_records_in_evolution_line(line, db_path=DEX_DB_FILE)
    except DexUnavailable:
        records = []
    return [str(record.get("name")) for record in records if str(record.get("name") or "").strip()]


def locked_pokemon_for_choice(
    pokemon_name: str,
    *,
    state: Optional[Dict[str, Any]] = None,
    pokemon_pool: Optional[List[str]] = None,
) -> List[str]:
    """Lista de Pokémon que devem sair da pool quando pokemon_name for escolhido."""
    if pokemon_pool is None:
        pokemon_pool = get_lockable_pokemon_pool(state)
    pool_keys = {normalize_name_key(name): name for name in pokemon_pool}
    scope = pokemon_lock_scope(state or {"settings": {}})

    if scope == POKEMON_LOCK_SCOPE_EXACT:
        related = [pokemon_name]
    elif scope == POKEMON_LOCK_SCOPE_SPECIES:
        related = related_pokemon_for_dex_species(pokemon_name, pokemon_pool) or [pokemon_name]
    elif scope == POKEMON_LOCK_SCOPE_LEGACY_GROUP:
        related = related_pokemon_for(pokemon_name)
    else:
        # Linha evolutiva inteira é o padrão. Para nomes que não existem no MegaDex,
        # o TXT legado continua funcionando como fallback.
        related = related_pokemon_for_dex_line(pokemon_name, pokemon_pool) or related_pokemon_for(pokemon_name)

    # Mantém só nomes que existem na pool ativa, mas sempre inclui o escolhido.
    locked: List[str] = []
    for name in related:
        key = normalize_name_key(name)
        if key in pool_keys and key not in {normalize_name_key(item) for item in locked}:
            locked.append(pool_keys[key])
    if normalize_name_key(pokemon_name) not in {normalize_name_key(name) for name in locked}:
        locked.append(pokemon_name)
    return locked


def recompute_used_pokemon(state: Dict[str, Any]) -> List[str]:
    """Reconstrói a lista de Pokémon travados com base nas escolhas atuais."""
    locked: List[str] = []
    locked_keys = set()
    for player in state.get("players", {}).values():
        if not isinstance(player, dict):
            continue
        for pick in player.get("pokemon_picks", []):
            pokemon_name = pick.get("name") if isinstance(pick, dict) else str(pick)
            for related in locked_pokemon_for_choice(pokemon_name, state=state):
                key = normalize_name_key(related)
                if key not in locked_keys:
                    locked_keys.add(key)
                    locked.append(related)
    state["used_pokemon"] = locked
    return locked


def normalize_player(player_id: str, player: Dict[str, Any]) -> Dict[str, Any]:
    nickname = str(player.get("nickname") or player_id).strip() or player_id
    player["player_id"] = str(player.get("player_id") or player_id)
    player["nickname"] = nickname
    player.setdefault("created_at", now_text())
    player.setdefault("pokemon_picks", [])
    player.setdefault("pending", empty_pending())

    pending = player["pending"]
    pending.setdefault("type", None)
    pending.setdefault("pokemon_options", [])
    pending.setdefault("ability_for_index", None)
    pending.setdefault("ability_options", [])
    pending.setdefault("choice_id", None)
    pending.setdefault("round_index", None)
    pending.setdefault("round_name", None)

    fixed_picks = []
    for pick in player["pokemon_picks"]:
        if isinstance(pick, str):
            fixed_picks.append({"name": pick, "ability": None})
        else:
            pick.setdefault("name", "Pokémon")
            pick.setdefault("ability", None)
            pick.setdefault("round_index", None)
            pick.setdefault("round_name", None)
            fixed_picks.append(pick)
    player["pokemon_picks"] = fixed_picks
    player.setdefault("choice_history", [])
    if not isinstance(player.get("choice_history"), list):
        player["choice_history"] = []
    return player


def migrate_state_shape(state: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    changed = False
    state.setdefault("used_pokemon", [])
    state.setdefault("players", {})
    default_settings = default_state()["settings"]
    settings = state.setdefault("settings", {})
    if not isinstance(settings, dict):
        settings = {}
        state["settings"] = settings
        changed = True
    for key, value in default_settings.items():
        if key not in settings:
            settings[key] = value
            changed = True
    if "pokemon_options_per_draw" not in settings and "options_per_draw" in settings:
        settings["pokemon_options_per_draw"] = settings.get("options_per_draw", POKEMON_OPTIONS_PER_DRAW)
        changed = True
    settings["flag_karma"] = normalize_flag_karma(settings.get("flag_karma", default_settings.get("flag_karma", {})))
    settings["pokemon_lock_scope"] = normalize_pokemon_lock_scope(settings.get("pokemon_lock_scope"))
    settings["rounds_enabled"] = bool(settings.get("rounds_enabled", False))
    settings["draft_rounds"] = normalize_draft_rounds(settings.get("draft_rounds", []), max_slots=setting_int({"settings": settings}, "max_pokemon", MAX_POKEMON, 1, 30))
    state.setdefault("version", 0)

    players = state.get("players", {})
    new_players: Dict[str, Any] = {}
    existing_ids = set()

    for old_key, raw_player in players.items():
        if not isinstance(raw_player, dict):
            continue

        raw_id = str(raw_player.get("player_id") or "")
        if raw_id.isdigit() and len(raw_id) >= 6 and raw_id not in existing_ids:
            player_id = raw_id
        elif str(old_key).isdigit() and len(str(old_key)) >= 6 and str(old_key) not in existing_ids:
            player_id = str(old_key)
        else:
            player_id = generate_player_id(existing_ids)
            changed = True

        existing_ids.add(player_id)
        player = normalize_player(player_id, raw_player)
        if old_key != player_id:
            changed = True
        new_players[player_id] = player

    if new_players != players:
        state["players"] = new_players
        changed = True

    return state, changed


def load_state() -> Dict[str, Any]:
    ensure_files_exist()

    if not STATE_FILE.exists():
        state = default_state()
        write_state(state, increment_version=False)
        return state

    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        backup = BASE_DIR / f"draft_state_broken_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        STATE_FILE.rename(backup)
        state = default_state()
        write_state(state, increment_version=False)
        return state

    state, changed = migrate_state_shape(state)
    if changed:
        write_state(state, increment_version=True)
    return state


def write_state(state: Dict[str, Any], increment_version: bool = True) -> None:
    if increment_version:
        state["version"] = int(state.get("version", 0)) + 1
    state["updated_at"] = now_text()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def save_state(state: Dict[str, Any]) -> None:
    write_state(state, increment_version=True)


def get_player_by_id(state: Dict[str, Any], player_id: str) -> Optional[Dict[str, Any]]:
    player = state.get("players", {}).get(str(player_id))
    if not isinstance(player, dict):
        return None
    return normalize_player(str(player_id), player)


def find_player_id_by_nickname(state: Dict[str, Any], nickname: str) -> Optional[str]:
    wanted = nickname.strip().lower()
    for player_id, player in state.get("players", {}).items():
        if str(player.get("nickname", "")).strip().lower() == wanted:
            return str(player_id)
    return None


def create_player(state: Dict[str, Any], nickname: str) -> Dict[str, Any]:
    player_id = generate_player_id(set(state.setdefault("players", {}).keys()))
    player = {
        "player_id": player_id,
        "nickname": nickname,
        "created_at": now_text(),
        "pokemon_picks": [],
        "pending": empty_pending(),
    }
    state["players"][player_id] = player
    return player


AUTH_SESSION_KEY = "mega_draft_auth_role"
AUTH_ROLE_ADMIN = "admin"
AUTH_ROLE_MASTER = "master"

PUBLIC_ENDPOINTS = {
    "index",
    "join",
    "player_page",
    "choose_pokemon",
    "choose_ability",
    "state_version",
    "login",
    "logout",
    "static",
}

MASTER_ENDPOINTS = {
    "master_page",
    "master_draw_pokemon",
    "master_draw_ability",
}


def request_key() -> Optional[str]:
    key = request.args.get("key") or request.form.get("key")
    if key:
        return str(key).strip()
    if request.is_json:
        data = request.get_json(silent=True) or {}
        value = data.get("key")
        return str(value).strip() if value else None
    return None


def current_auth_role() -> Optional[str]:
    role = session.get(AUTH_SESSION_KEY)
    if role in {AUTH_ROLE_ADMIN, AUTH_ROLE_MASTER}:
        return str(role)
    return None


def authenticate_from_key() -> Optional[str]:
    key = request_key()
    if key == ADMIN_KEY:
        session[AUTH_SESSION_KEY] = AUTH_ROLE_ADMIN
        return AUTH_ROLE_ADMIN
    if key == MASTER_KEY:
        session[AUTH_SESSION_KEY] = AUTH_ROLE_MASTER
        return AUTH_ROLE_MASTER
    return None


def is_admin_authenticated() -> bool:
    return current_auth_role() == AUTH_ROLE_ADMIN or authenticate_from_key() == AUTH_ROLE_ADMIN


def is_master_authenticated() -> bool:
    role = current_auth_role() or authenticate_from_key()
    return role in {AUTH_ROLE_ADMIN, AUTH_ROLE_MASTER}




def safe_next_url(value: Any, fallback_endpoint: str = "admin_page") -> str:
    text = str(value or "").strip()
    if not text or not text.startswith("/") or text.startswith("//"):
        return url_for(fallback_endpoint)
    return text

def locked_response(title: str, required_role: str) -> Any:
    requested_url = request.full_path if request.query_string else request.path
    fallback = "master_page" if required_role == AUTH_ROLE_MASTER else "admin_page"
    return render_template(
        "locked.html",
        title=title,
        required_role=required_role,
        next_url=safe_next_url(requested_url, fallback),
    ), 403


def require_master() -> Optional[Any]:
    if not is_master_authenticated():
        return locked_response("Mestre", AUTH_ROLE_MASTER)
    return None


def require_admin() -> Optional[Any]:
    if not is_admin_authenticated():
        return locked_response("Admin", AUTH_ROLE_ADMIN)
    return None


@app.before_request
def protect_private_routes():
    endpoint = request.endpoint
    if endpoint in PUBLIC_ENDPOINTS or endpoint is None:
        return None
    if endpoint in MASTER_ENDPOINTS:
        return require_master()
    return require_admin()


@app.route("/login", methods=["GET", "POST"])
def login():
    role_hint = request.values.get("role") or AUTH_ROLE_ADMIN
    fallback = "master_page" if role_hint == AUTH_ROLE_MASTER else "admin_page"
    next_url = safe_next_url(request.values.get("next"), fallback)

    if request.method == "POST":
        access_key = request.form.get("access_key", "").strip()
        if access_key == ADMIN_KEY:
            session[AUTH_SESSION_KEY] = AUTH_ROLE_ADMIN
            flash("Acesso admin liberado.", "success")
            return redirect(next_url or url_for("admin_page"))
        if access_key == MASTER_KEY:
            session[AUTH_SESSION_KEY] = AUTH_ROLE_MASTER
            flash("Acesso do mestre liberado.", "success")
            target = next_url or url_for("master_page")
            # A chave de mestre não abre áreas administrativas.
            if not target.startswith("/master"):
                target = url_for("master_page")
            return redirect(target)
        flash("Senha/chave inválida.", "error")

    return render_template(
        "locked.html",
        title="Acesso restrito",
        required_role=role_hint,
        next_url=next_url,
    )


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.pop(AUTH_SESSION_KEY, None)
    flash("Sessão encerrada.", "success")
    return redirect(url_for("index"))


def draw_options(pool: List[str], amount: int, excluded: List[str]) -> Tuple[List[str], Optional[str]]:
    excluded_lower = {item.lower() for item in excluded}
    available = [item for item in pool if item.lower() not in excluded_lower]

    if len(available) < amount:
        return [], f"Pool insuficiente: só existem {len(available)} opções disponíveis."

    return random.sample(available, amount), None


def setting_int(state: Dict[str, Any], key: str, default: int, min_value: int = 1, max_value: int = 999) -> int:
    settings = state.setdefault("settings", {})
    try:
        value = int(settings.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(max_value, value))


def get_pokemon_options_per_draw(state: Dict[str, Any]) -> int:
    settings = state.setdefault("settings", {})
    fallback = settings.get("options_per_draw", POKEMON_OPTIONS_PER_DRAW)
    try:
        fallback_int = int(fallback)
    except (TypeError, ValueError):
        fallback_int = POKEMON_OPTIONS_PER_DRAW
    return setting_int(state, "pokemon_options_per_draw", fallback_int, 1, 20)


def get_ability_options_per_draw(state: Dict[str, Any]) -> int:
    return setting_int(state, "ability_options_per_draw", ABILITY_OPTIONS_PER_DRAW, 1, 20)


def normalize_flag_karma(raw: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    cleaned: Dict[str, Dict[str, Any]] = {}
    for raw_flag, raw_config in raw.items():
        flag = str(raw_flag).strip()
        if not flag:
            continue
        if isinstance(raw_config, dict):
            enabled = bool(raw_config.get("enabled", True))
            raw_draw = raw_config.get("guarantee_draw", 0)
        else:
            enabled = True
            raw_draw = raw_config
        try:
            guarantee_draw = int(raw_draw)
        except (TypeError, ValueError):
            continue
        if guarantee_draw <= 0:
            continue
        cleaned[flag] = {"enabled": enabled, "guarantee_draw": max(1, guarantee_draw), "mode": "linear"}
    return cleaned


def parse_flag_karma_text(text: str) -> Dict[str, Dict[str, Any]]:
    karma: Dict[str, Dict[str, Any]] = {}
    for raw_line in str(text or "").replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            flag, value = line.split("=", 1)
        elif ":" in line:
            flag, value = line.split(":", 1)
        else:
            continue
        flag = flag.strip()
        if not flag:
            continue
        try:
            guarantee_draw = int(value.strip())
        except ValueError:
            continue
        if guarantee_draw > 0:
            karma[flag] = {"enabled": True, "guarantee_draw": guarantee_draw, "mode": "linear"}
    return karma


def flag_karma_text(settings: Dict[str, Any]) -> str:
    karma = normalize_flag_karma(settings.get("flag_karma", {}))
    return "\n".join(f"{flag}={config.get('guarantee_draw', 0)}" for flag, config in karma.items() if config.get("enabled", True))


def pokemon_options_have_flag(options: List[str], flag: str, config: Optional[Dict[str, Any]] = None) -> bool:
    flag_key = str(flag).strip().lower()
    return any(any(str(item).strip().lower() == flag_key for item in flags_for_pokemon(option, config)) for option in options)


def player_has_reached_flag_limit(player: Dict[str, Any], flag: str, config: Dict[str, Any]) -> bool:
    limits = config.get("flag_limits", {})
    if flag not in limits:
        return False
    try:
        limit = int(limits.get(flag, 0))
    except (TypeError, ValueError):
        return False
    if limit < 0:
        return False
    return player_flag_counts(player, config).get(flag, 0) >= limit


def flag_was_already_offered_or_chosen(player: Dict[str, Any], flag: str, config: Dict[str, Any]) -> bool:
    if player_flag_counts(player, config).get(flag, 0) > 0:
        return True
    for entry in player.get("choice_history", []):
        if entry.get("type") != "pokemon":
            continue
        options = entry.get("options", [])
        if isinstance(options, list) and pokemon_options_have_flag(options, flag, config):
            return True
    return False


def pokemon_draw_count(player: Dict[str, Any]) -> int:
    return sum(1 for entry in player.get("choice_history", []) if entry.get("type") == "pokemon")


def choose_karma_flag_for_draw(player: Dict[str, Any], state: Dict[str, Any], pokemon_pool: List[str], excluded: List[str], flag_config: Dict[str, Any]) -> Optional[str]:
    karma = normalize_flag_karma(state.setdefault("settings", {}).get("flag_karma", {}))
    if not karma:
        return None

    excluded_lower = {item.lower() for item in excluded}
    candidates_by_flag: Dict[str, List[str]] = {}
    for flag, config in karma.items():
        if not config.get("enabled", True):
            continue
        if flag_was_already_offered_or_chosen(player, flag, flag_config):
            continue
        if player_has_reached_flag_limit(player, flag, flag_config):
            continue
        candidates = [
            pokemon for pokemon in pokemon_pool
            if pokemon.lower() not in excluded_lower and pokemon_options_have_flag([pokemon], flag, flag_config)
        ]
        if candidates:
            candidates_by_flag[flag] = candidates

    if not candidates_by_flag:
        return None

    next_draw_number = pokemon_draw_count(player) + 1
    triggered: List[str] = []
    for flag, config in karma.items():
        if flag not in candidates_by_flag:
            continue
        guarantee_draw = max(1, int(config.get("guarantee_draw", 1)))
        if next_draw_number >= guarantee_draw:
            triggered.append(flag)
            continue
        # Chance linear: se garante na 6ª, a 1ª tem 0%, 2ª 20%, 3ª 40%, 4ª 60%, 5ª 80%, 6ª 100%.
        chance = (next_draw_number - 1) / max(1, guarantee_draw - 1)
        if random.random() < chance:
            triggered.append(flag)

    if not triggered:
        return None
    return random.choice(triggered)


def draw_pokemon_options_for_player(player: Dict[str, Any], state: Dict[str, Any]) -> Tuple[List[str], Optional[str], Optional[Dict[str, Any]]]:
    round_config = get_next_pokemon_round(player, state)
    pokemon_pool = get_pokemon_pool_for_round(state, round_config)
    flag_config = load_flag_config()
    amount = get_pokemon_options_per_draw_for_round(state, round_config)
    already_in_team = [pick["name"] for pick in player.get("pokemon_picks", [])]
    globally_used = state.get("used_pokemon", []) if state.setdefault("settings", {}).get("lock_chosen_pokemon_globally", True) else []
    flag_blocked = excluded_by_flag_limits(player, pokemon_pool, flag_config)
    budget_blocked = excluded_by_budget_limits(player, pokemon_pool, state)
    excluded = already_in_team + globally_used + flag_blocked + budget_blocked
    budget_summary = player_budget_summary(player, state)

    forced_flag = choose_karma_flag_for_draw(player, state, pokemon_pool, excluded, flag_config)
    metadata: Dict[str, Any] = {
        "forced_flag": forced_flag,
        "karma_applied": False,
        "round_index": round_config.get("index") if round_config else None,
        "round_name": pokemon_round_label(round_config) if round_config else None,
        "round_source": round_config.get("pokemon_pool_source") if round_config else None,
        "budget_enabled": budget_enabled(state),
        "budget_remaining": budget_summary.get("remaining"),
        "budget_blocked_count": len(budget_blocked),
    }

    if forced_flag:
        excluded_lower = {item.lower() for item in excluded}
        forced_candidates = [
            pokemon for pokemon in pokemon_pool
            if pokemon.lower() not in excluded_lower and pokemon_options_have_flag([pokemon], forced_flag, flag_config)
        ]
        if forced_candidates:
            forced = random.choice(forced_candidates)
            remaining_excluded = excluded + [forced]
            remaining, error = draw_options(pokemon_pool, amount - 1, remaining_excluded) if amount > 1 else ([], None)
            if error:
                return [], error, metadata
            options = [forced] + remaining
            random.shuffle(options)
            metadata["karma_applied"] = True
            metadata["option_costs"] = budget_costs_for_pokemon_names(options, state) if budget_enabled(state) else {}
            return options, None, metadata

    options, error = draw_options(pokemon_pool, amount, excluded)
    if options and not error:
        metadata["option_costs"] = budget_costs_for_pokemon_names(options, state) if budget_enabled(state) else {}
    return options, error, metadata


def command_token(value: str) -> str:
    """Converte nomes para o formato simples usado no comando.

    Ex.: "Parental Bond" -> "parentalbond".
    Para Pokémon com formas/nomes especiais, o jogador pode ajustar manualmente no comando gerado.
    """
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def pokegive_command(nickname: str, pokemon_name: str, ability_name: str) -> str:
    return f"/pokegiveother {nickname} {command_token(pokemon_name)} ability={command_token(ability_name)}"


def new_choice_id() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S%f") + "-" + "".join(random.choice("0123456789") for _ in range(4))


def register_choice_history(player: Dict[str, Any], choice_type: str, options: List[str], slot_index: Optional[int] = None) -> str:
    choice_id = new_choice_id()
    history = player.setdefault("choice_history", [])
    history.append({
        "choice_id": choice_id,
        "type": choice_type,
        "slot_index": slot_index,
        "slot_label": slot_label(slot_index) if isinstance(slot_index, int) else None,
        "options": list(options),
        "chosen": None,
        "created_at": now_text(),
        "chosen_at": None,
    })
    return choice_id


def mark_choice_history(player: Dict[str, Any], choice_id: Optional[str], chosen: str) -> None:
    if not choice_id:
        return
    for entry in reversed(player.setdefault("choice_history", [])):
        if entry.get("choice_id") == choice_id:
            entry["chosen"] = chosen
            entry["chosen_at"] = now_text()
            return


def player_history_export_payload(state: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "exported_at": now_text(),
        "version": state.get("version", 0),
        "players": {},
    }
    for player_id, player in sorted_players(state).items():
        payload["players"][player_id] = {
            "nickname": player.get("nickname"),
            "pokemon_picks": player.get("pokemon_picks", []),
            "choice_history": player.get("choice_history", []),
        }
    return payload


def history_text_export(state: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"Cobblemon Random Draft - Export de escolhas")
    lines.append(f"Gerado em: {now_text()}")
    lines.append("")
    for _, player in sorted_players(state).items():
        lines.append(f"=== {player.get('nickname')} ===")
        if not player.get("choice_history"):
            lines.append("Sem histórico de escolhas.")
        for entry in player.get("choice_history", []):
            label = entry.get("slot_label") or "Pokémon"
            tipo = "Pokémon" if entry.get("type") == "pokemon" else f"Ability ({label})"
            lines.append(f"[{tipo}] {entry.get('created_at', '')}")
            lines.append("Opções: " + ", ".join(entry.get("options", [])))
            chosen = entry.get("chosen") or "pendente/não escolhido"
            lines.append(f"Escolha: {chosen}")
            lines.append("")
        lines.append("")
    return "\n".join(lines)


def slot_label(index: int) -> str:
    return f"Slot {index + 1}"


def master_pending_label(player: Dict[str, Any]) -> str:
    pending_type = player["pending"].get("type")
    if pending_type == "pokemon":
        round_name = str(player["pending"].get("round_name") or "").strip()
        return f"Aguardando escolha de Pokémon ({round_name})" if round_name else "Aguardando escolha de Pokémon"
    if pending_type == "ability":
        index = player["pending"].get("ability_for_index")
        if isinstance(index, int):
            return f"Aguardando ability para {slot_label(index)}"
        return "Aguardando escolha de ability"
    return "Pronto"

def player_pending_label(player: Dict[str, Any]) -> str:
    pending_type = player["pending"].get("type")
    if pending_type == "pokemon":
        round_name = str(player["pending"].get("round_name") or "").strip()
        return f"Aguardando escolha de Pokémon ({round_name})" if round_name else "Aguardando escolha de Pokémon"
    if pending_type == "ability":
        index = player["pending"].get("ability_for_index")
        picks = player.get("pokemon_picks", [])
        if isinstance(index, int) and 0 <= index < len(picks):
            return f"Aguardando ability para {picks[index]['name']}"
        return "Aguardando escolha de ability"
    return "Pronto"


def player_can_draw_pokemon(player: Dict[str, Any], state: Dict[str, Any]) -> bool:
    return (
        player["pending"].get("type") is None
        and len(player["pokemon_picks"]) < state["settings"].get("max_pokemon", MAX_POKEMON)
    )


def player_can_draw_ability(player: Dict[str, Any]) -> bool:
    return player["pending"].get("type") is None and any(pick.get("ability") is None for pick in player["pokemon_picks"])


def sorted_players(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return dict(
        sorted(
            state.get("players", {}).items(),
            key=lambda item: str(item[1].get("created_at", "")),
        )
    )


@app.context_processor
def inject_helpers():
    return {
        "player_pending_label": player_pending_label,
        "master_pending_label": master_pending_label,
        "slot_label": slot_label,
        "pokegive_command": pokegive_command,
        "command_token": command_token,
        "player_can_draw_pokemon": player_can_draw_pokemon,
        "player_can_draw_ability": player_can_draw_ability,
        "get_pokemon_options_per_draw": get_pokemon_options_per_draw,
        "get_ability_options_per_draw": get_ability_options_per_draw,
        "next_pokemon_options_per_draw": next_pokemon_options_per_draw,
        "next_pokemon_round_summary": next_pokemon_round_summary,
        "pokemon_round_label_for_pick": pokemon_round_label_for_pick,
        "draft_rounds_enabled": draft_rounds_enabled,
        "budget_enabled": budget_enabled,
        "budget_total_points": budget_total_points,
        "budget_unknown_pokemon_cost": budget_unknown_pokemon_cost,
        "budget_cost_mode": budget_cost_mode,
        "budget_cost_mode_label": budget_cost_mode_label,
        "budget_flag_costs_text": budget_flag_costs_text,
        "budget_cost_payload": budget_cost_payload,
        "budget_cost_for_pick": budget_cost_for_pick,
        "player_budget_summary": player_budget_summary,
        "flag_karma_text": flag_karma_text,
        "pokemon_lock_scope": pokemon_lock_scope,
        "pokemon_lock_scope_label": pokemon_lock_scope_label,
        "pokemon_lock_scope_options": pokemon_lock_scope_options,
        "pokemon_pool_source_label": pokemon_pool_source_label,
        "ability_pool_source_label": ability_pool_source_label,
        "auth_role": current_auth_role(),
        "is_admin_authenticated": is_admin_authenticated(),
        "is_master_authenticated": is_master_authenticated(),
        "master_key": "",
        "admin_key": "",
        "POKEMON_POOL_SOURCE_TXT": POKEMON_POOL_SOURCE_TXT,
        "POKEMON_POOL_SOURCE_DEX_PRESET": POKEMON_POOL_SOURCE_DEX_PRESET,
        "ROUND_POKEMON_POOL_SOURCE_GLOBAL": ROUND_POKEMON_POOL_SOURCE_GLOBAL,
        "POKEMON_LOCK_SCOPE_EXACT": POKEMON_LOCK_SCOPE_EXACT,
        "POKEMON_LOCK_SCOPE_SPECIES": POKEMON_LOCK_SCOPE_SPECIES,
        "POKEMON_LOCK_SCOPE_EVOLUTION_LINE": POKEMON_LOCK_SCOPE_EVOLUTION_LINE,
        "POKEMON_LOCK_SCOPE_LEGACY_GROUP": POKEMON_LOCK_SCOPE_LEGACY_GROUP,
        "BUDGET_COST_MODE_POKEMON_BST": BUDGET_COST_MODE_POKEMON_BST,
        "BUDGET_COST_MODE_SPECIES_MAX_BST": BUDGET_COST_MODE_SPECIES_MAX_BST,
        "BUDGET_COST_MODE_LINE_MAX_BST": BUDGET_COST_MODE_LINE_MAX_BST,
        "ABILITY_POOL_SOURCE_TXT": ABILITY_POOL_SOURCE_TXT,
        "ABILITY_POOL_SOURCE_DEX": ABILITY_POOL_SOURCE_DEX,
        "ABILITY_POOL_SOURCE_DEX_TAG": ABILITY_POOL_SOURCE_DEX_TAG,
        "ABILITY_POOL_SOURCE_DEX_PRESET": ABILITY_POOL_SOURCE_DEX_PRESET,
    }





def parse_optional_int(value: str) -> Optional[int]:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


DEX_FILTER_KEYS = [
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
]


def dex_filters_from_request() -> Dict[str, str]:
    filters = {key: request.args.get(key, "").strip() for key in DEX_FILTER_KEYS}
    # Checkboxes desmarcados não aparecem no request. Por padrão a Dex mostra tudo.
    legendary_values = request.args.getlist("include_legendary")
    mythical_values = request.args.getlist("include_mythical")
    if legendary_values:
        filters["include_legendary"] = "1" if "1" in legendary_values else "0"
    else:
        filters["include_legendary"] = "1"

    if mythical_values:
        filters["include_mythical"] = "1" if "1" in mythical_values else "0"
    else:
        filters["include_mythical"] = "1"
    return filters


def filters_from_form() -> Dict[str, str]:
    filters = {key: request.form.get(key, "").strip() for key in DEX_FILTER_KEYS}
    for key in ["include_legendary", "include_mythical"]:
        values = request.form.getlist(key)
        if values:
            filters[key] = "1" if "1" in values else "0"
    return filters


@app.route("/dex", methods=["GET"])
def dex() -> str:
    filters = dex_filters_from_request()

    try:
        summary = dex_summary(DEX_DB_FILE)
        pokemon = search_pokemon_from_filters(filters, db_path=DEX_DB_FILE)
        presets = list_presets(DEX_DB_FILE)
        unavailable = False
    except DexUnavailable:
        summary = {}
        pokemon = []
        presets = []
        unavailable = True

    return render_template(
        "dex.html",
        filters=filters,
        pokemon=pokemon,
        presets=presets,
        summary=summary,
        unavailable=unavailable,
    )




def ability_filters_from_request() -> Dict[str, str]:
    return {
        "q": request.args.get("q", "").strip(),
        "tag": request.args.get("tag", "").strip(),
        "include_banned": "1" if request.args.get("include_banned", "1") == "1" else "0",
    }


@app.route("/abilities", methods=["GET"])
def abilities_page() -> str:
    filters = ability_filters_from_request()
    try:
        summary = dex_summary(DEX_DB_FILE)
        ability_tags = list_ability_tags(db_path=DEX_DB_FILE)
        abilities = search_abilities(
            q=filters["q"],
            tag=filters["tag"],
            include_banned=filters["include_banned"] == "1",
            db_path=DEX_DB_FILE,
            limit=300,
        )
        unavailable = False
    except DexUnavailable:
        summary = {}
        ability_tags = []
        abilities = []
        unavailable = True

    return render_template(
        "abilities.html",
        filters=filters,
        summary=summary,
        ability_tags=ability_tags,
        abilities=abilities,
        unavailable=unavailable,
        admin_key="",
    )


@app.route("/abilities/update", methods=["POST"])
def update_ability_route():
    locked = require_admin()
    if locked:
        return locked

    ability_id = safe_int_value(request.form.get("ability_id"))
    if ability_id is None:
        flash("Ability inválida.", "error")
        return redirect(url_for("abilities_page"))

    try:
        update_ability_metadata(
            ability_id=ability_id,
            tags=request.form.get("tags", ""),
            is_banned=request.form.get("is_banned") == "on",
            is_battle_relevant=request.form.get("is_battle_relevant") == "on",
            notes=request.form.get("notes", ""),
            db_path=DEX_DB_FILE,
        )
        flash("Ability atualizada com sucesso.", "success")
    except (DexUnavailable, ValueError) as exc:
        flash(str(exc), "error")

    return redirect(url_for(
        "abilities_page",
        q=request.form.get("return_q", ""),
        tag=request.form.get("return_tag", ""),
        include_banned=request.form.get("return_include_banned", "1"),
    ))




@app.route("/ability-presets", methods=["GET"])
def ability_presets_page() -> str:
    selected_id = parse_optional_int(request.args.get("preset_id", ""))
    try:
        summary = dex_summary(DEX_DB_FILE)
        ability_tags = list_ability_tags(db_path=DEX_DB_FILE)
        presets = list_ability_presets(DEX_DB_FILE)
        selected = get_ability_preset(selected_id, DEX_DB_FILE) if selected_id else (presets[0] if presets else None)
        abilities = search_abilities_from_preset(selected, db_path=DEX_DB_FILE, limit=300) if selected else []
        unavailable = False
    except DexUnavailable:
        summary = {}
        ability_tags = []
        presets = []
        selected = None
        abilities = []
        unavailable = True

    return render_template(
        "ability_presets.html",
        summary=summary,
        ability_tags=ability_tags,
        presets=presets,
        selected=selected,
        abilities=abilities,
        unavailable=unavailable,
        admin_key="",
    )


@app.route("/ability-presets/save", methods=["POST"])
def save_ability_preset_route():
    locked = require_admin()
    if locked:
        return locked

    try:
        preset_id = save_ability_preset(
            name=request.form.get("preset_name", ""),
            description=request.form.get("preset_description", ""),
            required_tags=request.form.get("required_tags", ""),
            excluded_tags=request.form.get("excluded_tags", ""),
            required_mode=request.form.get("required_mode", "any"),
            include_banned=request.form.get("include_banned") == "on",
            db_path=DEX_DB_FILE,
        )
        flash("Preset de ability salvo com sucesso.", "success")
        return redirect(url_for("ability_presets_page", preset_id=preset_id))
    except (DexUnavailable, ValueError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("ability_presets_page"))


@app.route("/ability-presets/delete", methods=["POST"])
def delete_ability_preset_route():
    locked = require_admin()
    if locked:
        return locked

    preset_id = parse_optional_int(request.form.get("preset_id", ""))
    if preset_id is None:
        flash("Preset de ability inválido.", "error")
        return redirect(url_for("ability_presets_page"))
    try:
        deleted = delete_ability_preset(preset_id, DEX_DB_FILE)
    except DexUnavailable as exc:
        flash(str(exc), "error")
        return redirect(url_for("ability_presets_page"))
    flash("Preset de ability apagado." if deleted else "Preset de ability não encontrado.", "success" if deleted else "error")
    return redirect(url_for("ability_presets_page"))


@app.route("/rulesets", methods=["GET"])
def rulesets_page() -> str:
    selected_id = parse_optional_int(request.args.get("ruleset_id", ""))
    state = load_state()
    try:
        summary = dex_summary(DEX_DB_FILE)
        pokemon_presets = list_presets(DEX_DB_FILE)
        ability_tags = list_ability_tags(db_path=DEX_DB_FILE)
        ability_presets = list_ability_presets(DEX_DB_FILE)
        rulesets = list_draft_rulesets(DEX_DB_FILE)
        selected = get_draft_ruleset(selected_id, DEX_DB_FILE) if selected_id else (rulesets[0] if rulesets else None)
        selected_summary = ruleset_pool_summary(selected.get("settings", {})) if selected else None
        unavailable = False
    except DexUnavailable:
        summary = {}
        pokemon_presets = []
        ability_tags = []
        ability_presets = []
        rulesets = []
        selected = None
        selected_summary = None
        unavailable = True

    return render_template(
        "rulesets.html",
        summary=summary,
        state=state,
        pokemon_presets=pokemon_presets,
        ability_tags=ability_tags,
        ability_presets=ability_presets,
        rulesets=rulesets,
        selected=selected,
        selected_summary=selected_summary,
        unavailable=unavailable,
        admin_key="",
        key="",
    )


@app.route("/rulesets/save", methods=["POST"])
def save_ruleset_route():
    locked = require_admin()
    if locked:
        return locked

    try:
        ruleset_id = save_draft_ruleset(
            name=request.form.get("ruleset_name", ""),
            description=request.form.get("ruleset_description", ""),
            settings=settings_from_ruleset_form(request.form),
            db_path=DEX_DB_FILE,
        )
        flash("Ruleset salvo com sucesso.", "success")
        return redirect(url_for("rulesets_page", ruleset_id=ruleset_id))
    except (DexUnavailable, ValueError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("rulesets_page"))


@app.route("/rulesets/delete", methods=["POST"])
def delete_ruleset_route():
    locked = require_admin()
    if locked:
        return locked

    ruleset_id = parse_optional_int(request.form.get("ruleset_id", ""))
    if ruleset_id is None:
        flash("Ruleset inválido.", "error")
        return redirect(url_for("rulesets_page"))
    try:
        deleted = delete_draft_ruleset(ruleset_id, DEX_DB_FILE)
    except DexUnavailable as exc:
        flash(str(exc), "error")
        return redirect(url_for("rulesets_page"))
    flash("Ruleset apagado." if deleted else "Ruleset não encontrado.", "success" if deleted else "error")
    return redirect(url_for("rulesets_page"))


@app.route("/rulesets/apply", methods=["POST"])
def apply_ruleset_route():
    locked = require_admin()
    if locked:
        return locked

    ruleset_id = parse_optional_int(request.form.get("ruleset_id", ""))
    if ruleset_id is None:
        flash("Selecione um ruleset para aplicar.", "error")
        return redirect(url_for("rulesets_page"))
    try:
        ruleset = get_draft_ruleset(ruleset_id, DEX_DB_FILE)
    except DexUnavailable as exc:
        flash(str(exc), "error")
        return redirect(url_for("rulesets_page"))
    if not ruleset:
        flash("Ruleset não encontrado.", "error")
        return redirect(url_for("rulesets_page"))

    state = load_state()
    apply_ruleset_settings_to_state(state, ruleset.get("settings", {}))
    recompute_used_pokemon(state)
    save_state(state)
    flash(f"Ruleset aplicado no draft atual: {ruleset['name']}", "success")
    return redirect(url_for("admin_page"))


@app.route("/rounds", methods=["GET"])
def rounds_page() -> str:
    locked = require_admin()
    if locked:
        return locked

    state = load_state()
    try:
        presets = list_presets(DEX_DB_FILE)
        summary = dex_summary(DEX_DB_FILE)
        unavailable = False
    except DexUnavailable:
        presets = []
        summary = {}
        unavailable = True

    rounds = draft_rounds_preview(state)
    return render_template(
        "rounds.html",
        state=state,
        rounds=rounds,
        presets=presets,
        summary=summary,
        unavailable=unavailable,
        key="",
    )


@app.route("/rounds/save", methods=["POST"])
def save_rounds_route():
    locked = require_admin()
    if locked:
        return locked

    state = load_state()
    settings = state.setdefault("settings", {})
    max_slots = setting_int(state, "max_pokemon", MAX_POKEMON, 1, 30)

    rounds: List[Dict[str, Any]] = []
    for index in range(max_slots):
        source = normalize_round_pokemon_source(request.form.get(f"round_source_{index}", ROUND_POKEMON_POOL_SOURCE_GLOBAL))
        preset_id = safe_int_value(request.form.get(f"round_preset_id_{index}")) if source == POKEMON_POOL_SOURCE_DEX_PRESET else None
        options = safe_int_value(request.form.get(f"round_options_{index}"))
        if options is not None:
            options = max(1, min(20, options))
        rounds.append({
            "index": index,
            "slot": index + 1,
            "name": request.form.get(f"round_name_{index}", f"Rodada {index + 1}").strip() or f"Rodada {index + 1}",
            "pokemon_pool_source": source,
            "pokemon_preset_id": preset_id,
            "pokemon_options_per_draw": options,
        })

    settings["rounds_enabled"] = request.form.get("rounds_enabled") == "on"
    settings["draft_rounds"] = normalize_draft_rounds(rounds, max_slots=max_slots)
    recompute_used_pokemon(state)
    save_state(state)
    flash("Rodadas de draft salvas. Os próximos sorteios de Pokémon já usam essas regras.", "success")
    return redirect(url_for("rounds_page"))


@app.route("/rounds/disable", methods=["POST"])
def disable_rounds_route():
    locked = require_admin()
    if locked:
        return locked
    state = load_state()
    state.setdefault("settings", {})["rounds_enabled"] = False
    save_state(state)
    flash("Rodadas desativadas. O sorteio voltou a usar a configuração global.", "success")
    return redirect(url_for("rounds_page"))


@app.route("/evolution-lines", methods=["GET"])
def evolution_lines_page() -> str:
    q = request.args.get("q", "").strip()
    try:
        lines = search_evolution_lines(q=q, db_path=DEX_DB_FILE, limit=400)
        error = None
    except DexUnavailable as exc:
        lines = []
        error = str(exc)
    return render_template(
        "evolution_lines.html",
        lines=lines,
        q=q,
        error=error,
        key="",
    )


@app.route("/budget", methods=["GET"])
def budget_page() -> str:
    locked = require_admin()
    if locked:
        return locked

    state = load_state()
    players = sorted_players(state)
    player_summaries = {
        player_id: player_budget_summary(player, state)
        for player_id, player in players.items()
    }
    return render_template(
        "budget.html",
        state=state,
        players=players,
        player_summaries=player_summaries,
        key="",
    )


@app.route("/budget/save", methods=["POST"])
def save_budget_route():
    locked = require_admin()
    if locked:
        return locked

    state = load_state()
    settings = state.setdefault("settings", {})
    settings["budget_enabled"] = request.form.get("budget_enabled") == "on"
    settings["budget_cost_mode"] = normalize_budget_cost_mode(request.form.get("budget_cost_mode"))
    settings["budget_points_per_player"] = clamp_int(
        request.form.get("budget_points_per_player"),
        DEFAULT_BUDGET_POINTS_PER_PLAYER,
        1,
        20000,
    )
    settings["budget_unknown_pokemon_cost"] = clamp_int(
        request.form.get("budget_unknown_pokemon_cost"),
        DEFAULT_UNKNOWN_POKEMON_COST,
        0,
        20000,
    )
    settings["budget_flag_costs"] = parse_budget_flag_costs_text(request.form.get("budget_flag_costs", "")) or dict(DEFAULT_BUDGET_FLAG_COSTS)
    save_state(state)
    flash("Orçamento do draft salvo. Os próximos sorteios de Pokémon já respeitam o saldo dos jogadores.", "success")
    return redirect(url_for("budget_page"))


@app.route("/budget/reprice", methods=["POST"])
def reprice_budget_route():
    locked = require_admin()
    if locked:
        return locked

    confirm = request.form.get("confirm", "").strip()
    if confirm != "RECALCULAR":
        flash('Digite exatamente "RECALCULAR" para recalcular custos já escolhidos.', "error")
        return redirect(url_for("budget_page"))

    state = load_state()
    reprice_all_picks(state)
    save_state(state)
    flash("Custos dos Pokémon já escolhidos foram recalculados com as regras atuais.", "success")
    return redirect(url_for("budget_page"))


@app.route("/presets", methods=["GET"])
def presets_page() -> str:
    selected_id = parse_optional_int(request.args.get("preset_id", ""))
    try:
        summary = dex_summary(DEX_DB_FILE)
        presets = list_presets(DEX_DB_FILE)
        selected = get_preset(selected_id, DEX_DB_FILE) if selected_id else (presets[0] if presets else None)
        pokemon = search_pokemon_from_filters(selected.get("filters", {}), db_path=DEX_DB_FILE) if selected else []
        unavailable = False
    except DexUnavailable:
        summary = {}
        presets = []
        selected = None
        pokemon = []
        unavailable = True

    return render_template(
        "presets.html",
        summary=summary,
        presets=presets,
        selected=selected,
        pokemon=pokemon,
        unavailable=unavailable,
        admin_key="",
    )


@app.route("/presets/save", methods=["POST"])
def save_preset_route():
    locked = require_admin()
    if locked:
        return locked

    name = request.form.get("preset_name", "").strip()
    description = request.form.get("preset_description", "").strip()
    filters = filters_from_form()
    try:
        preset_id = save_preset(name=name, description=description, filters=filters, db_path=DEX_DB_FILE)
        flash("Preset salvo com sucesso.", "success")
        return redirect(url_for("presets_page", preset_id=preset_id))
    except (DexUnavailable, ValueError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("dex"))


@app.route("/presets/delete", methods=["POST"])
def delete_preset_route():
    locked = require_admin()
    if locked:
        return locked

    preset_id = parse_optional_int(request.form.get("preset_id", ""))
    if preset_id is None:
        flash("Preset inválido.", "error")
        return redirect(url_for("presets_page"))
    try:
        deleted = delete_preset(preset_id, DEX_DB_FILE)
    except DexUnavailable as exc:
        flash(str(exc), "error")
        return redirect(url_for("presets_page"))
    flash("Preset apagado." if deleted else "Preset não encontrado.", "success" if deleted else "error")
    return redirect(url_for("presets_page"))

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/join", methods=["POST"])
def join():
    nickname = request.form.get("nickname", "").strip()
    if not nickname:
        flash("Digite um apelido.", "error")
        return redirect(url_for("index"))

    state = load_state()
    existing_id = find_player_id_by_nickname(state, nickname)
    if existing_id:
        flash("Esse apelido já está cadastrado. Use o link que foi gerado para esse jogador ou peça ajuda no Admin.", "error")
        return redirect(url_for("index"))

    player = create_player(state, nickname)
    save_state(state)
    return redirect(url_for("player_page", player_id=player["player_id"]))


@app.route("/p/<player_id>", methods=["GET"])
def player_page(player_id: str):
    state = load_state()
    player = get_player_by_id(state, player_id)
    if not player:
        return render_template("locked.html", title="Jogador"), 404

    return render_template("player.html", state=state, player=player, auto_refresh=True, state_version=state.get("version", 0))


@app.route("/choose-pokemon", methods=["POST"])
def choose_pokemon():
    player_id = request.form.get("player_id", "").strip()
    chosen = request.form.get("pokemon", "").strip()

    state = load_state()
    player = get_player_by_id(state, player_id)
    if not player:
        flash("Jogador não encontrado.", "error")
        return redirect(url_for("index"))

    pending = player["pending"]
    if pending.get("type") != "pokemon":
        flash("Você não tem escolha de Pokémon pendente.", "error")
        return redirect(url_for("player_page", player_id=player_id))

    if chosen not in pending.get("pokemon_options", []):
        flash("Escolha inválida.", "error")
        return redirect(url_for("player_page", player_id=player_id))

    used_lower = {name.lower() for name in state.get("used_pokemon", [])}
    if state["settings"].get("lock_chosen_pokemon_globally", True) and chosen.lower() in used_lower:
        flash("Esse Pokémon já foi travado por outro jogador. Peça para o mestre sortear novamente.", "error")
        return redirect(url_for("player_page", player_id=player_id))

    budget_payload = budget_cost_payload(chosen, state)
    if budget_enabled(state) and budget_payload["cost"] > player_budget_summary(player, state)["remaining"]:
        flash(
            f"{chosen} custa {budget_payload['cost']} pts e ultrapassa seu orçamento restante. Peça novo sorteio ao mestre.",
            "error",
        )
        return redirect(url_for("player_page", player_id=player_id))

    mark_choice_history(player, pending.get("choice_id"), chosen)
    pick = {
        "name": chosen,
        "ability": None,
        "round_index": pending.get("round_index"),
        "round_name": pending.get("round_name"),
    }
    stamp_budget_on_pick(pick, chosen, state)
    player["pokemon_picks"].append(pick)
    player["pending"] = empty_pending()

    if state["settings"].get("lock_chosen_pokemon_globally", True):
        locked_names = locked_pokemon_for_choice(chosen, state=state)
        used_keys = {normalize_name_key(name) for name in state.setdefault("used_pokemon", [])}
        for name in locked_names:
            if normalize_name_key(name) not in used_keys:
                state["used_pokemon"].append(name)
                used_keys.add(normalize_name_key(name))
    else:
        locked_names = [chosen]

    save_state(state)
    if len(locked_names) > 1:
        flash(f"{chosen} escolhido. Grupo bloqueado: {', '.join(locked_names)}.", "success")
    else:
        flash(f"{chosen} escolhido e travado no seu draft.", "success")
    return redirect(url_for("player_page", player_id=player_id))


@app.route("/choose-ability", methods=["POST"])
def choose_ability():
    player_id = request.form.get("player_id", "").strip()
    ability = request.form.get("ability", "").strip()

    state = load_state()
    player = get_player_by_id(state, player_id)
    if not player:
        flash("Jogador não encontrado.", "error")
        return redirect(url_for("index"))

    pending = player["pending"]
    if pending.get("type") != "ability":
        flash("Você não tem escolha de ability pendente.", "error")
        return redirect(url_for("player_page", player_id=player_id))

    if ability not in pending.get("ability_options", []):
        flash("Escolha inválida.", "error")
        return redirect(url_for("player_page", player_id=player_id))

    index = pending.get("ability_for_index")
    if not isinstance(index, int) or index < 0 or index >= len(player["pokemon_picks"]):
        flash("Índice do Pokémon inválido. Peça para o mestre sortear novamente.", "error")
        player["pending"] = empty_pending()
        save_state(state)
        return redirect(url_for("player_page", player_id=player_id))

    mark_choice_history(player, pending.get("choice_id"), ability)
    player["pokemon_picks"][index]["ability"] = ability
    pokemon_name = player["pokemon_picks"][index]["name"]
    player["pending"] = empty_pending()

    save_state(state)
    flash(f"{pokemon_name} recebeu {ability}.", "success")
    return redirect(url_for("player_page", player_id=player_id))


@app.route("/master", methods=["GET"])
def master_page():
    locked = require_master()
    if locked:
        return locked

    state = load_state()
    return render_template(
        "master.html",
        state=state,
        players=sorted_players(state),
        pool_summary=pool_summary(state),
        key="",
        auto_refresh=True,
        state_version=state.get("version", 0),
    )


@app.route("/master/draw-pokemon", methods=["POST"])
def master_draw_pokemon():
    locked = require_master()
    if locked:
        return locked

    player_id = request.form.get("player_id", "").strip()
    state = load_state()
    player = get_player_by_id(state, player_id)
    if not player:
        flash("Jogador não encontrado.", "error")
        return redirect(url_for("master_page"))

    nickname = player["nickname"]
    if player["pending"].get("type") is not None:
        flash(f"{nickname} já tem uma escolha pendente.", "error")
        return redirect(url_for("master_page"))

    max_pokemon = state["settings"].get("max_pokemon", MAX_POKEMON)
    if len(player["pokemon_picks"]) >= max_pokemon:
        flash(f"{nickname} já fechou os {max_pokemon} Pokémon.", "error")
        return redirect(url_for("master_page"))

    flag_config = load_flag_config()
    options, error, draw_meta = draw_pokemon_options_for_player(player, state)

    if error:
        counts = player_flag_counts(player, flag_config)
        limits = flag_config.get("flag_limits", {})
        flag_status = ", ".join(f"{flag}: {counts.get(flag, 0)}/{limit}" for flag, limit in limits.items())
        extra_parts = []
        if flag_status:
            extra_parts.append(f"Limites de flags: {flag_status}.")
        if budget_enabled(state):
            summary = player_budget_summary(player, state)
            extra_parts.append(f"Orçamento restante de {nickname}: {summary['remaining']}/{summary['total']} pts.")
        flash(error + (" " + " ".join(extra_parts) if extra_parts else ""), "error")
        return redirect(url_for("master_page"))

    choice_id = register_choice_history(player, "pokemon", options)
    if draw_meta:
        player.setdefault("choice_history", [])[-1]["metadata"] = draw_meta
    player["pending"] = {
        "type": "pokemon",
        "pokemon_options": options,
        "ability_for_index": None,
        "ability_options": [],
        "choice_id": choice_id,
        "round_index": draw_meta.get("round_index") if draw_meta else None,
        "round_name": draw_meta.get("round_name") if draw_meta else None,
    }
    save_state(state)

    flash(f"{len(options)} Pokémon foram sorteados para {nickname}. Você não viu as opções.", "success")
    return redirect(url_for("master_page"))


@app.route("/master/draw-ability", methods=["POST"])
def master_draw_ability():
    locked = require_master()
    if locked:
        return locked

    player_id = request.form.get("player_id", "").strip()
    index_raw = request.form.get("pokemon_index", "")

    state = load_state()
    player = get_player_by_id(state, player_id)
    if not player:
        flash("Jogador não encontrado.", "error")
        return redirect(url_for("master_page"))

    nickname = player["nickname"]
    try:
        pokemon_index = int(index_raw)
    except ValueError:
        flash("Índice inválido.", "error")
        return redirect(url_for("master_page"))

    if player["pending"].get("type") is not None:
        flash(f"{nickname} já tem uma escolha pendente.", "error")
        return redirect(url_for("master_page"))

    if pokemon_index < 0 or pokemon_index >= len(player["pokemon_picks"]):
        flash("Pokémon inválido.", "error")
        return redirect(url_for("master_page"))

    if player["pokemon_picks"][pokemon_index].get("ability") is not None:
        flash("Esse Pokémon já tem ability escolhida.", "error")
        return redirect(url_for("master_page"))

    ability_pool = get_current_ability_pool(state)
    excluded_abilities = used_abilities_for_state(state) if state.setdefault("settings", {}).get("lock_abilities_globally", False) else []
    options, error = draw_options(ability_pool, get_ability_options_per_draw(state), excluded_abilities)

    if error:
        flash(error, "error")
        return redirect(url_for("master_page"))

    choice_id = register_choice_history(player, "ability", options, pokemon_index)
    player["pending"] = {
        "type": "ability",
        "pokemon_options": [],
        "ability_for_index": pokemon_index,
        "ability_options": options,
        "choice_id": choice_id,
    }
    save_state(state)

    flash(f"{len(options)} abilities foram sorteadas para {slot_label(pokemon_index)} de {nickname}. Você não viu as opções.", "success")
    return redirect(url_for("master_page"))


def groups_to_text(groups: List[List[str]]) -> str:
    return "\n".join(", ".join(str(item).strip() for item in group if str(item).strip()) for group in groups if len(group) >= 2)


def parseGroupsText_for_python(text: str) -> List[List[str]]:
    groups: List[List[str]] = []
    for raw_line in str(text or "").replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        group = split_group_line(line)
        if len(group) >= 2:
            groups.append(group)
    return groups


def normalize_groups(groups: Any) -> List[List[str]]:
    normalized: List[List[str]] = []
    used_keys = set()
    pokemon_pool = load_pool(POKEMON_FILE, POKEMON_BANLIST_FILE)
    canonical = {normalize_name_key(name): name for name in pokemon_pool}

    if not isinstance(groups, list):
        return normalized

    for raw_group in groups:
        if not isinstance(raw_group, list):
            continue
        group: List[str] = []
        local_keys = set()
        for raw_name in raw_group:
            name = str(raw_name).strip()
            key = normalize_name_key(name)
            if not key or key in local_keys or key in used_keys:
                continue
            group.append(canonical.get(key, name))
            local_keys.add(key)
        if len(group) >= 2:
            for name in group:
                used_keys.add(normalize_name_key(name))
            normalized.append(group)
    return normalized


def ensure_group_editor(state: Dict[str, Any]) -> Dict[str, Any]:
    editor = state.setdefault("group_editor", {})
    if not isinstance(editor, dict):
        editor = {}
        state["group_editor"] = editor

    if not isinstance(editor.get("groups"), list):
        editor["groups"] = load_pokemon_groups()
    else:
        editor["groups"] = normalize_groups(editor.get("groups"))

    if not isinstance(editor.get("collaborators"), dict):
        editor["collaborators"] = {}

    editor.setdefault("version", 0)
    editor.setdefault("updated_at", now_text())
    return editor


def touch_group_editor(state: Dict[str, Any]) -> None:
    editor = ensure_group_editor(state)
    editor["version"] = int(editor.get("version", 0)) + 1
    editor["updated_at"] = now_text()


def get_editor_payload(state: Dict[str, Any]) -> Dict[str, Any]:
    editor = ensure_group_editor(state)
    return {
        "version": int(editor.get("version", 0)),
        "updated_at": editor.get("updated_at"),
        "groups": editor.get("groups", []),
        "collaborators": editor.get("collaborators", {}),
        "pokemon_pool": get_current_pokemon_pool(state),
        "groups_text": groups_to_text(editor.get("groups", [])),
    }


def parse_flag_limits_text(flag_limits_text: str) -> Dict[str, int]:
    limits: Dict[str, int] = {}
    for raw_line in str(flag_limits_text or "").replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            flag, value = line.split("=", 1)
        elif ":" in line:
            flag, value = line.split(":", 1)
        else:
            continue
        flag = flag.strip()
        if not flag:
            continue
        try:
            limit = int(value.strip())
        except ValueError:
            continue
        limits[flag] = max(0, limit)
    return limits


def normalize_pokemon_flags(raw_flags: Any, allowed_flags: Optional[List[str]] = None) -> Dict[str, List[str]]:
    cleaned_flags: Dict[str, List[str]] = {}
    if not isinstance(raw_flags, dict):
        return cleaned_flags

    pokemon_pool = load_pool(POKEMON_FILE, POKEMON_BANLIST_FILE)
    canonical = {normalize_name_key(name): name for name in pokemon_pool}
    allowed_map = {str(flag).strip().lower(): str(flag).strip() for flag in (allowed_flags or []) if str(flag).strip()}

    for raw_pokemon, raw_flag_list in raw_flags.items():
        key = normalize_name_key(raw_pokemon)
        pokemon = canonical.get(key, str(raw_pokemon).strip())
        if not pokemon:
            continue
        if isinstance(raw_flag_list, str):
            raw_flag_list = [raw_flag_list]
        if not isinstance(raw_flag_list, list):
            continue
        flags: List[str] = []
        seen = set()
        for raw_flag in raw_flag_list:
            flag_key = str(raw_flag).strip().lower()
            flag = allowed_map.get(flag_key, str(raw_flag).strip())
            if flag and flag_key not in seen:
                flags.append(flag)
                seen.add(flag_key)
        if flags:
            cleaned_flags[pokemon] = flags

    return cleaned_flags


def ensure_flag_editor(state: Dict[str, Any]) -> Dict[str, Any]:
    editor = state.setdefault("flag_editor", {})
    if not isinstance(editor, dict):
        editor = {}
        state["flag_editor"] = editor

    file_config = load_flag_config()

    if not isinstance(editor.get("flag_limits"), dict):
        editor["flag_limits"] = file_config.get("flag_limits", {"Lendario": 1})
    else:
        cleaned_limits = {}
        for raw_flag, raw_limit in editor.get("flag_limits", {}).items():
            flag = str(raw_flag).strip()
            if not flag:
                continue
            try:
                cleaned_limits[flag] = max(0, int(raw_limit))
            except (TypeError, ValueError):
                continue
        editor["flag_limits"] = cleaned_limits or file_config.get("flag_limits", {"Lendario": 1})

    if not isinstance(editor.get("pokemon_flags"), dict):
        editor["pokemon_flags"] = file_config.get("pokemon_flags", {})
    editor["pokemon_flags"] = normalize_pokemon_flags(editor.get("pokemon_flags"), list(editor["flag_limits"].keys()))

    if not isinstance(editor.get("collaborators"), dict):
        editor["collaborators"] = {}

    editor.setdefault("version", 0)
    editor.setdefault("updated_at", now_text())
    return editor


def touch_flag_editor(state: Dict[str, Any]) -> None:
    editor = ensure_flag_editor(state)
    editor["version"] = int(editor.get("version", 0)) + 1
    editor["updated_at"] = now_text()


def get_flag_editor_payload(state: Dict[str, Any]) -> Dict[str, Any]:
    editor = ensure_flag_editor(state)
    flag_config = {
        "flag_limits": editor.get("flag_limits", {}),
        "pokemon_flags": editor.get("pokemon_flags", {}),
    }
    return {
        "version": int(editor.get("version", 0)),
        "updated_at": editor.get("updated_at"),
        "flag_limits": editor.get("flag_limits", {}),
        "flag_limits_text": flag_limits_text(flag_config),
        "available_flags": available_flags(flag_config),
        "pokemon_flags": editor.get("pokemon_flags", {}),
        "collaborators": editor.get("collaborators", {}),
        "pokemon_pool": get_current_pokemon_pool(state),
    }


@app.route("/admin", methods=["GET"])
def admin_page():
    locked = require_admin()
    if locked:
        return locked

    state = load_state()
    editor = ensure_group_editor(state)
    flag_editor = ensure_flag_editor(state)
    try:
        presets = list_presets(DEX_DB_FILE)
        active_preset = get_active_pokemon_preset(state)
        ability_tags = list_ability_tags(db_path=DEX_DB_FILE)
        ability_presets = list_ability_presets(DEX_DB_FILE)
        active_ability_preset = get_active_ability_preset(state)
        draft_rulesets = list_draft_rulesets(DEX_DB_FILE)
    except DexUnavailable:
        presets = []
        active_preset = None
        ability_tags = []
        ability_presets = []
        active_ability_preset = None
        draft_rulesets = []
    current_summary = pool_summary(state)
    return render_template(
        "admin.html",
        state=state,
        players=sorted_players(state),
        pokemon_count=current_summary["pokemon_count"],
        ability_count=current_summary["ability_count"],
        pokemon_pool=get_current_pokemon_pool(state),
        pokemon_groups=editor.get("groups", []),
        pokemon_groups_text=groups_to_text(editor.get("groups", [])),
        flag_config=load_flag_config(),
        flag_limits_text=flag_limits_text(load_flag_config()),
        available_flags=available_flags(load_flag_config()),
        flag_editor_payload=get_flag_editor_payload(state),
        presets=presets,
        active_preset=active_preset,
        ability_tags=ability_tags,
        ability_presets=ability_presets,
        active_ability_preset=active_ability_preset,
        draft_rulesets=draft_rulesets,
        pool_summary=current_summary,
        key="",
        auto_refresh=False,
        state_version=state.get("version", 0),
    )


@app.route("/admin/clear-pending", methods=["POST"])
def admin_clear_pending():
    locked = require_admin()
    if locked:
        return locked

    player_id = request.form.get("player_id", "").strip()
    state = load_state()
    player = get_player_by_id(state, player_id)
    if not player:
        flash("Jogador não encontrado.", "error")
        return redirect(url_for("admin_page"))

    player["pending"] = empty_pending()
    save_state(state)

    flash(f"Pendência de {player['nickname']} limpa.", "success")
    return redirect(url_for("admin_page"))


@app.route("/admin/remove-last-pick", methods=["POST"])
def admin_remove_last_pick():
    locked = require_admin()
    if locked:
        return locked

    player_id = request.form.get("player_id", "").strip()
    state = load_state()
    player = get_player_by_id(state, player_id)
    if not player:
        flash("Jogador não encontrado.", "error")
        return redirect(url_for("admin_page"))

    if not player["pokemon_picks"]:
        flash("Esse jogador não tem Pokémon para remover.", "error")
        return redirect(url_for("admin_page"))

    removed = player["pokemon_picks"].pop()
    removed_name = removed["name"]
    recompute_used_pokemon(state)
    save_state(state)

    flash(f"Último Pokémon de {player['nickname']} removido: {removed_name}. Bloqueios globais recalculados.", "success")
    return redirect(url_for("admin_page"))


@app.route("/admin/save-groups", methods=["POST"])
def admin_save_groups():
    locked = require_admin()
    if locked:
        return locked

    groups_text = request.form.get("pokemon_groups", "")
    groups = normalize_groups(parseGroupsText_for_python(groups_text))
    POKEMON_GROUPS_FILE.write_text(groups_to_text(groups) + ("\n" if groups else ""), encoding="utf-8")

    # Recalcula bloqueios já existentes para refletir grupos novos/editados.
    state = load_state()
    editor = ensure_group_editor(state)
    editor["groups"] = groups
    touch_group_editor(state)
    recompute_used_pokemon(state)
    save_state(state)

    flash("Grupos de Pokémon salvos e bloqueios globais recalculados.", "success")
    return redirect(url_for("admin_page"))


@app.route("/admin/group-editor-state", methods=["GET"])
def admin_group_editor_state():
    locked = require_admin()
    if locked:
        return {"error": "Acesso negado"}, 403

    state = load_state()
    ensure_group_editor(state)
    return get_editor_payload(state)


@app.route("/admin/group-editor-update", methods=["POST"])
def admin_group_editor_update():
    locked = require_admin()
    if locked:
        return {"error": "Acesso negado"}, 403

    data = request.get_json(silent=True) or {}
    action = str(data.get("action") or "").strip()
    editor_id = str(data.get("editor_id") or "").strip()
    editor_name = str(data.get("editor_name") or "").strip() or "Editor"

    state = load_state()
    editor = ensure_group_editor(state)
    collaborators = editor.setdefault("collaborators", {})

    if editor_id:
        collaborator = collaborators.setdefault(editor_id, {"name": editor_name, "selected": [], "updated_at": now_text()})
        collaborator["name"] = editor_name
        collaborator["updated_at"] = now_text()

    groups = normalize_groups(editor.get("groups", []))
    editor["groups"] = groups

    if action == "identify":
        pass

    elif action == "select":
        if not editor_id:
            return {"error": "editor_id obrigatório"}, 400
        selected = data.get("selected", [])
        if not isinstance(selected, list):
            selected = []
        collaborator = collaborators.setdefault(editor_id, {"name": editor_name, "selected": [], "updated_at": now_text()})
        collaborator["selected"] = [str(item).strip() for item in selected if str(item).strip()]
        collaborator["updated_at"] = now_text()

    elif action == "clear_selection":
        if not editor_id:
            return {"error": "editor_id obrigatório"}, 400
        collaborator = collaborators.setdefault(editor_id, {"name": editor_name, "selected": [], "updated_at": now_text()})
        collaborator["selected"] = []
        collaborator["updated_at"] = now_text()

    elif action == "add_group":
        if not editor_id:
            return {"error": "editor_id obrigatório"}, 400
        selected = data.get("selected", [])
        if not isinstance(selected, list):
            selected = []
        selected_group = normalize_groups([selected])
        if not selected_group:
            return {"error": "Selecione pelo menos 2 Pokémon para criar um grupo."}, 400

        selected_keys = {normalize_name_key(name) for name in selected_group[0]}
        grouped_keys = {normalize_name_key(name) for group in groups for name in group}
        conflict = selected_keys.intersection(grouped_keys)
        if conflict:
            return {"error": "Algum Pokémon selecionado já está em outro grupo. Atualize a tela e confira."}, 400

        groups.append(selected_group[0])
        editor["groups"] = groups
        collaborator = collaborators.setdefault(editor_id, {"name": editor_name, "selected": [], "updated_at": now_text()})
        collaborator["selected"] = []
        collaborator["updated_at"] = now_text()

    elif action == "remove_group":
        index_raw = data.get("index")
        try:
            index = int(index_raw)
        except (TypeError, ValueError):
            return {"error": "Índice inválido."}, 400
        if index < 0 or index >= len(groups):
            return {"error": "Grupo não encontrado."}, 404
        groups.pop(index)
        editor["groups"] = groups

    elif action == "apply_raw":
        raw_text = str(data.get("groups_text") or "")
        editor["groups"] = normalize_groups(parseGroupsText_for_python(raw_text))
        if editor_id and editor_id in collaborators:
            collaborators[editor_id]["selected"] = []
            collaborators[editor_id]["updated_at"] = now_text()

    elif action == "save_to_file":
        groups = normalize_groups(editor.get("groups", []))
        editor["groups"] = groups
        POKEMON_GROUPS_FILE.write_text(groups_to_text(groups) + ("\n" if groups else ""), encoding="utf-8")
        recompute_used_pokemon(state)

    else:
        return {"error": "Ação inválida."}, 400

    touch_group_editor(state)
    save_state(state)
    return get_editor_payload(state)


@app.route("/admin/flag-editor-state", methods=["GET"])
def admin_flag_editor_state():
    locked = require_admin()
    if locked:
        return {"error": "Acesso negado"}, 403

    state = load_state()
    ensure_flag_editor(state)
    return get_flag_editor_payload(state)


@app.route("/admin/flag-editor-update", methods=["POST"])
def admin_flag_editor_update():
    locked = require_admin()
    if locked:
        return {"error": "Acesso negado"}, 403

    data = request.get_json(silent=True) or {}
    action = str(data.get("action") or "").strip()
    editor_id = str(data.get("editor_id") or "").strip()
    editor_name = str(data.get("editor_name") or "").strip() or "Editor"

    state = load_state()
    editor = ensure_flag_editor(state)
    collaborators = editor.setdefault("collaborators", {})

    if editor_id:
        collaborator = collaborators.setdefault(
            editor_id,
            {"name": editor_name, "active_flag": None, "selected": [], "updated_at": now_text()},
        )
        collaborator["name"] = editor_name
        collaborator["updated_at"] = now_text()

    limits = editor.get("flag_limits", {})
    pokemon_flags = normalize_pokemon_flags(editor.get("pokemon_flags", {}), list(limits.keys()))
    editor["pokemon_flags"] = pokemon_flags

    if action == "identify":
        active_flag = str(data.get("active_flag") or "").strip()
        if editor_id and active_flag:
            collaborators[editor_id]["active_flag"] = active_flag

    elif action == "set_limits":
        limits_text = str(data.get("flag_limits_text") or "")
        parsed_limits = parse_flag_limits_text(limits_text)
        if not parsed_limits:
            return {"error": "Adicione pelo menos uma flag no formato Flag=quantidade."}, 400
        editor["flag_limits"] = parsed_limits
        allowed = list(parsed_limits.keys())
        editor["pokemon_flags"] = normalize_pokemon_flags(editor.get("pokemon_flags", {}), allowed)
        for collaborator in collaborators.values():
            if collaborator.get("active_flag") not in allowed:
                collaborator["active_flag"] = allowed[0] if allowed else None
            collaborator["updated_at"] = now_text()

    elif action == "select":
        if not editor_id:
            return {"error": "editor_id obrigatório"}, 400
        active_flag = str(data.get("active_flag") or "").strip()
        if active_flag not in editor.get("flag_limits", {}):
            return {"error": "Flag inválida. Aplique os limites primeiro."}, 400
        selected = data.get("selected", [])
        if not isinstance(selected, list):
            selected = []
        collaborator = collaborators.setdefault(
            editor_id,
            {"name": editor_name, "active_flag": active_flag, "selected": [], "updated_at": now_text()},
        )
        collaborator["active_flag"] = active_flag
        collaborator["selected"] = [str(item).strip() for item in selected if str(item).strip()]
        collaborator["updated_at"] = now_text()

    elif action == "clear_selection":
        if not editor_id:
            return {"error": "editor_id obrigatório"}, 400
        collaborator = collaborators.setdefault(
            editor_id,
            {"name": editor_name, "active_flag": None, "selected": [], "updated_at": now_text()},
        )
        collaborator["selected"] = []
        collaborator["updated_at"] = now_text()

    elif action == "add_to_flag":
        if not editor_id:
            return {"error": "editor_id obrigatório"}, 400
        active_flag = str(data.get("active_flag") or "").strip()
        if active_flag not in editor.get("flag_limits", {}):
            return {"error": "Flag inválida. Aplique os limites primeiro."}, 400
        selected = data.get("selected", [])
        if not isinstance(selected, list):
            selected = []
        pokemon_pool = load_pool(POKEMON_FILE, POKEMON_BANLIST_FILE)
        canonical = {normalize_name_key(name): name for name in pokemon_pool}
        changed_any = False
        for raw_name in selected:
            name = canonical.get(normalize_name_key(raw_name), str(raw_name).strip())
            if not name:
                continue
            current = list(editor.setdefault("pokemon_flags", {}).get(name, []))
            if active_flag not in current:
                current.append(active_flag)
                editor["pokemon_flags"][name] = current
                changed_any = True
        collaborator = collaborators.setdefault(
            editor_id,
            {"name": editor_name, "active_flag": active_flag, "selected": [], "updated_at": now_text()},
        )
        collaborator["active_flag"] = active_flag
        collaborator["selected"] = []
        collaborator["updated_at"] = now_text()
        if not changed_any:
            # Ainda sincroniza para limpar seleção e mostrar estado atualizado.
            pass

    elif action == "remove_flag":
        pokemon = str(data.get("pokemon") or "").strip()
        flag = str(data.get("flag") or "").strip()
        if not pokemon or not flag:
            return {"error": "Pokémon e flag são obrigatórios."}, 400
        wanted = normalize_name_key(pokemon)
        found_name = None
        for configured_name in list(editor.get("pokemon_flags", {}).keys()):
            if normalize_name_key(configured_name) == wanted:
                found_name = configured_name
                break
        if found_name:
            next_flags = [item for item in editor["pokemon_flags"].get(found_name, []) if str(item).lower() != flag.lower()]
            if next_flags:
                editor["pokemon_flags"][found_name] = next_flags
            else:
                editor["pokemon_flags"].pop(found_name, None)

    elif action == "clear_flag":
        flag = str(data.get("flag") or "").strip()
        if not flag:
            return {"error": "Flag obrigatória."}, 400
        for pokemon in list(editor.get("pokemon_flags", {}).keys()):
            next_flags = [item for item in editor["pokemon_flags"].get(pokemon, []) if str(item).lower() != flag.lower()]
            if next_flags:
                editor["pokemon_flags"][pokemon] = next_flags
            else:
                editor["pokemon_flags"].pop(pokemon, None)

    elif action == "save_to_file":
        config = {
            "flag_limits": editor.get("flag_limits", {}),
            "pokemon_flags": normalize_pokemon_flags(editor.get("pokemon_flags", {}), list(editor.get("flag_limits", {}).keys())),
        }
        editor["pokemon_flags"] = config["pokemon_flags"]
        save_flag_config(config)

    else:
        return {"error": "Ação inválida."}, 400

    touch_flag_editor(state)
    save_state(state)
    return get_flag_editor_payload(state)


@app.route("/admin/save-flags", methods=["POST"])
def admin_save_flags():
    locked = require_admin()
    if locked:
        return locked

    limits_text = request.form.get("flag_limits", "")
    raw_pokemon_flags: Dict[str, List[str]] = {}
    for key, values in request.form.lists():
        if key.startswith("flags__"):
            pokemon_name = key[len("flags__"):].strip()
            raw_pokemon_flags[pokemon_name] = [str(value).strip() for value in values if str(value).strip()]

    config = normalize_flag_config_from_form(limits_text, raw_pokemon_flags)
    save_flag_config(config)
    flash("Flags e limites salvos. Os próximos sorteios já respeitam esses limites.", "success")
    return redirect(url_for("admin_page"))


@app.route("/admin/save-settings", methods=["POST"])
def admin_save_settings():
    locked = require_admin()
    if locked:
        return locked

    state = load_state()
    settings = state.setdefault("settings", {})

    def form_int(name: str, default: int, min_value: int, max_value: int) -> int:
        try:
            value = int(request.form.get(name, default))
        except (TypeError, ValueError):
            value = default
        return max(min_value, min(max_value, value))

    settings["max_pokemon"] = form_int("max_pokemon", MAX_POKEMON, 1, 30)
    settings["pokemon_options_per_draw"] = form_int("pokemon_options_per_draw", POKEMON_OPTIONS_PER_DRAW, 1, 20)
    settings["ability_options_per_draw"] = form_int("ability_options_per_draw", ABILITY_OPTIONS_PER_DRAW, 1, 20)
    settings["options_per_draw"] = settings["pokemon_options_per_draw"]

    # UI profissional: o fluxo principal agora é sempre MegaDex.
    # Fontes TXT antigas ficam apenas para compatibilidade de estados/routes antigas.
    pokemon_pool_source = POKEMON_POOL_SOURCE_DEX_PRESET
    settings["pokemon_pool_source"] = pokemon_pool_source
    preset_id = safe_int_value(request.form.get("pokemon_preset_id"))
    settings["pokemon_preset_id"] = preset_id

    ability_pool_source = request.form.get("ability_pool_source", ABILITY_POOL_SOURCE_DEX_PRESET)
    if ability_pool_source not in {ABILITY_POOL_SOURCE_DEX, ABILITY_POOL_SOURCE_DEX_TAG, ABILITY_POOL_SOURCE_DEX_PRESET}:
        ability_pool_source = ABILITY_POOL_SOURCE_DEX_PRESET
    settings["ability_pool_source"] = ability_pool_source
    settings["ability_tag_filter"] = request.form.get("ability_tag_filter", "").strip() or "Metronome Boa"
    ability_preset_id = safe_int_value(request.form.get("ability_preset_id"))
    settings["ability_preset_id"] = ability_preset_id if ability_pool_source == ABILITY_POOL_SOURCE_DEX_PRESET else None

    settings["lock_chosen_pokemon_globally"] = request.form.get("lock_chosen_pokemon_globally") == "on"
    settings["pokemon_lock_scope"] = normalize_pokemon_lock_scope(request.form.get("pokemon_lock_scope"))
    settings["lock_abilities_globally"] = request.form.get("lock_abilities_globally") == "on"
    settings["flag_karma"] = parse_flag_karma_text(request.form.get("flag_karma", ""))

    recompute_used_pokemon(state)
    save_state(state)
    flash("Configurações do draft salvas. Os próximos sorteios já usam esses valores.", "success")
    return redirect(url_for("admin_page"))


@app.route("/admin/reset", methods=["POST"])
def admin_reset():
    locked = require_admin()
    if locked:
        return locked

    confirm = request.form.get("confirm", "").strip()
    if confirm != "RESETAR":
        flash('Digite exatamente "RESETAR" para resetar o draft.', "error")
        return redirect(url_for("admin_page"))

    backup_path = BASE_DIR / f"draft_state_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    if STATE_FILE.exists():
        backup_path.write_text(STATE_FILE.read_text(encoding="utf-8"), encoding="utf-8")

    save_state(default_state())
    flash("Draft resetado. Um backup do estado anterior foi criado.", "success")
    return redirect(url_for("admin_page"))


@app.route("/export-history.json", methods=["GET"])
def export_history_json():
    locked = require_admin()
    if locked:
        return locked
    payload = player_history_export_payload(load_state())
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=cobblemon-draft-escolhas.json"},
    )


@app.route("/export-history.txt", methods=["GET"])
def export_history_txt():
    locked = require_admin()
    if locked:
        return locked
    return Response(
        history_text_export(load_state()),
        mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=cobblemon-draft-escolhas.txt"},
    )


@app.route("/export.json", methods=["GET"])
def export_json():
    locked = require_admin()
    if locked:
        return locked
    return load_state()


@app.route("/state-version", methods=["GET"])
def state_version():
    state = load_state()
    return {"version": state.get("version", 0)}


if __name__ == "__main__":
    ensure_files_exist()
    load_state()
    app.run(host="0.0.0.0", port=5000, debug=True)
