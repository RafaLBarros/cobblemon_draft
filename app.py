from __future__ import annotations

import json
import os
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, Response, flash, redirect, render_template, request, url_for

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
STATE_FILE = BASE_DIR / "draft_state.json"

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
            "lock_chosen_pokemon_globally": True,
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


def locked_pokemon_for_choice(pokemon_name: str) -> List[str]:
    """Lista de Pokémon que devem sair da pool quando pokemon_name for escolhido."""
    pokemon_pool = load_pool(POKEMON_FILE, POKEMON_BANLIST_FILE)
    pool_keys = {normalize_name_key(name): name for name in pokemon_pool}
    related = related_pokemon_for(pokemon_name)

    # Mantém só nomes que existem na pool principal, mas sempre inclui o escolhido.
    locked: List[str] = []
    for name in related:
        key = normalize_name_key(name)
        if key in pool_keys:
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
            for related in locked_pokemon_for_choice(pokemon_name):
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

    fixed_picks = []
    for pick in player["pokemon_picks"]:
        if isinstance(pick, str):
            fixed_picks.append({"name": pick, "ability": None})
        else:
            pick.setdefault("name", "Pokémon")
            pick.setdefault("ability", None)
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


def require_master() -> Optional[Any]:
    key = request.args.get("key") or request.form.get("key")
    if key != MASTER_KEY:
        return render_template("locked.html", title="Mestre"), 403
    return None


def request_key() -> Optional[str]:
    key = request.args.get("key") or request.form.get("key")
    if key:
        return key
    if request.is_json:
        data = request.get_json(silent=True) or {}
        return data.get("key")
    return None


def require_admin() -> Optional[Any]:
    key = request_key()
    if key != ADMIN_KEY:
        return render_template("locked.html", title="Admin"), 403
    return None


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
    pokemon_pool = load_pool(POKEMON_FILE, POKEMON_BANLIST_FILE)
    flag_config = load_flag_config()
    amount = get_pokemon_options_per_draw(state)
    already_in_team = [pick["name"] for pick in player.get("pokemon_picks", [])]
    globally_used = state.get("used_pokemon", []) if state.setdefault("settings", {}).get("lock_chosen_pokemon_globally", True) else []
    flag_blocked = excluded_by_flag_limits(player, pokemon_pool, flag_config)
    excluded = already_in_team + globally_used + flag_blocked

    forced_flag = choose_karma_flag_for_draw(player, state, pokemon_pool, excluded, flag_config)
    metadata: Dict[str, Any] = {"forced_flag": forced_flag, "karma_applied": False}

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
            return options, None, metadata

    options, error = draw_options(pokemon_pool, amount, excluded)
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
        return "Aguardando escolha de Pokémon"
    if pending_type == "ability":
        index = player["pending"].get("ability_for_index")
        if isinstance(index, int):
            return f"Aguardando ability para {slot_label(index)}"
        return "Aguardando escolha de ability"
    return "Pronto"

def player_pending_label(player: Dict[str, Any]) -> str:
    pending_type = player["pending"].get("type")
    if pending_type == "pokemon":
        return "Aguardando escolha de Pokémon"
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
        "flag_karma_text": flag_karma_text,
        "master_key": MASTER_KEY,
        "admin_key": ADMIN_KEY,
    }


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

    mark_choice_history(player, pending.get("choice_id"), chosen)
    player["pokemon_picks"].append({"name": chosen, "ability": None})
    player["pending"] = empty_pending()

    if state["settings"].get("lock_chosen_pokemon_globally", True):
        locked_names = locked_pokemon_for_choice(chosen)
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
        key=MASTER_KEY,
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
        return redirect(url_for("master_page", key=MASTER_KEY))

    nickname = player["nickname"]
    if player["pending"].get("type") is not None:
        flash(f"{nickname} já tem uma escolha pendente.", "error")
        return redirect(url_for("master_page", key=MASTER_KEY))

    max_pokemon = state["settings"].get("max_pokemon", MAX_POKEMON)
    if len(player["pokemon_picks"]) >= max_pokemon:
        flash(f"{nickname} já fechou os {max_pokemon} Pokémon.", "error")
        return redirect(url_for("master_page", key=MASTER_KEY))

    flag_config = load_flag_config()
    options, error, draw_meta = draw_pokemon_options_for_player(player, state)

    if error:
        counts = player_flag_counts(player, flag_config)
        limits = flag_config.get("flag_limits", {})
        flag_status = ", ".join(f"{flag}: {counts.get(flag, 0)}/{limit}" for flag, limit in limits.items())
        flash(error + (f" Limites de flags: {flag_status}." if flag_status else ""), "error")
        return redirect(url_for("master_page", key=MASTER_KEY))

    choice_id = register_choice_history(player, "pokemon", options)
    if draw_meta:
        player.setdefault("choice_history", [])[-1]["metadata"] = draw_meta
    player["pending"] = {
        "type": "pokemon",
        "pokemon_options": options,
        "ability_for_index": None,
        "ability_options": [],
        "choice_id": choice_id,
    }
    save_state(state)

    flash(f"{len(options)} Pokémon foram sorteados para {nickname}. Você não viu as opções.", "success")
    return redirect(url_for("master_page", key=MASTER_KEY))


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
        return redirect(url_for("master_page", key=MASTER_KEY))

    nickname = player["nickname"]
    try:
        pokemon_index = int(index_raw)
    except ValueError:
        flash("Índice inválido.", "error")
        return redirect(url_for("master_page", key=MASTER_KEY))

    if player["pending"].get("type") is not None:
        flash(f"{nickname} já tem uma escolha pendente.", "error")
        return redirect(url_for("master_page", key=MASTER_KEY))

    if pokemon_index < 0 or pokemon_index >= len(player["pokemon_picks"]):
        flash("Pokémon inválido.", "error")
        return redirect(url_for("master_page", key=MASTER_KEY))

    if player["pokemon_picks"][pokemon_index].get("ability") is not None:
        flash("Esse Pokémon já tem ability escolhida.", "error")
        return redirect(url_for("master_page", key=MASTER_KEY))

    ability_pool = load_pool(ABILITIES_FILE, ABILITIES_BANLIST_FILE)
    options, error = draw_options(ability_pool, get_ability_options_per_draw(state), [])

    if error:
        flash(error, "error")
        return redirect(url_for("master_page", key=MASTER_KEY))

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
    return redirect(url_for("master_page", key=MASTER_KEY))


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
        "pokemon_pool": load_pool(POKEMON_FILE, POKEMON_BANLIST_FILE),
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
        "pokemon_pool": load_pool(POKEMON_FILE, POKEMON_BANLIST_FILE),
    }


@app.route("/admin", methods=["GET"])
def admin_page():
    locked = require_admin()
    if locked:
        return locked

    state = load_state()
    editor = ensure_group_editor(state)
    flag_editor = ensure_flag_editor(state)
    return render_template(
        "admin.html",
        state=state,
        players=sorted_players(state),
        pokemon_count=len(load_pool(POKEMON_FILE, POKEMON_BANLIST_FILE)),
        ability_count=len(load_pool(ABILITIES_FILE, ABILITIES_BANLIST_FILE)),
        pokemon_pool=load_pool(POKEMON_FILE, POKEMON_BANLIST_FILE),
        pokemon_groups=editor.get("groups", []),
        pokemon_groups_text=groups_to_text(editor.get("groups", [])),
        flag_config=load_flag_config(),
        flag_limits_text=flag_limits_text(load_flag_config()),
        available_flags=available_flags(load_flag_config()),
        flag_editor_payload=get_flag_editor_payload(state),
        key=ADMIN_KEY,
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
        return redirect(url_for("admin_page", key=ADMIN_KEY))

    player["pending"] = empty_pending()
    save_state(state)

    flash(f"Pendência de {player['nickname']} limpa.", "success")
    return redirect(url_for("admin_page", key=ADMIN_KEY))


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
        return redirect(url_for("admin_page", key=ADMIN_KEY))

    if not player["pokemon_picks"]:
        flash("Esse jogador não tem Pokémon para remover.", "error")
        return redirect(url_for("admin_page", key=ADMIN_KEY))

    removed = player["pokemon_picks"].pop()
    removed_name = removed["name"]
    recompute_used_pokemon(state)
    save_state(state)

    flash(f"Último Pokémon de {player['nickname']} removido: {removed_name}. Bloqueios globais recalculados.", "success")
    return redirect(url_for("admin_page", key=ADMIN_KEY))


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
    return redirect(url_for("admin_page", key=ADMIN_KEY))


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
    return redirect(url_for("admin_page", key=ADMIN_KEY))


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
    settings["lock_chosen_pokemon_globally"] = request.form.get("lock_chosen_pokemon_globally") == "on"
    settings["lock_abilities_globally"] = request.form.get("lock_abilities_globally") == "on"
    settings["flag_karma"] = parse_flag_karma_text(request.form.get("flag_karma", ""))

    save_state(state)
    flash("Configurações do draft salvas. Os próximos sorteios já usam esses valores.", "success")
    return redirect(url_for("admin_page", key=ADMIN_KEY))


@app.route("/admin/reset", methods=["POST"])
def admin_reset():
    locked = require_admin()
    if locked:
        return locked

    confirm = request.form.get("confirm", "").strip()
    if confirm != "RESETAR":
        flash('Digite exatamente "RESETAR" para resetar o draft.', "error")
        return redirect(url_for("admin_page", key=ADMIN_KEY))

    backup_path = BASE_DIR / f"draft_state_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    if STATE_FILE.exists():
        backup_path.write_text(STATE_FILE.read_text(encoding="utf-8"), encoding="utf-8")

    save_state(default_state())
    flash("Draft resetado. Um backup do estado anterior foi criado.", "success")
    return redirect(url_for("admin_page", key=ADMIN_KEY))


@app.route("/export-history.json", methods=["GET"])
def export_history_json():
    key = request.args.get("key")
    if key != ADMIN_KEY:
        return {"error": "Acesso negado"}, 403
    payload = player_history_export_payload(load_state())
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=cobblemon-draft-escolhas.json"},
    )


@app.route("/export-history.txt", methods=["GET"])
def export_history_txt():
    key = request.args.get("key")
    if key != ADMIN_KEY:
        return {"error": "Acesso negado"}, 403
    return Response(
        history_text_export(load_state()),
        mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=cobblemon-draft-escolhas.txt"},
    )


@app.route("/export.json", methods=["GET"])
def export_json():
    key = request.args.get("key")
    if key != ADMIN_KEY:
        return {"error": "Acesso negado"}, 403
    return load_state()


@app.route("/state-version", methods=["GET"])
def state_version():
    state = load_state()
    return {"version": state.get("version", 0)}


if __name__ == "__main__":
    ensure_files_exist()
    load_state()
    app.run(host="0.0.0.0", port=5000, debug=True)
