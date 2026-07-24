from __future__ import annotations

import json
import os
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, flash, redirect, render_template, request, url_for

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
STATE_FILE = BASE_DIR / "draft_state.json"

POKEMON_FILE = DATA_DIR / "pokemon.txt"
ABILITIES_FILE = DATA_DIR / "abilities.txt"
POKEMON_BANLIST_FILE = DATA_DIR / "pokemon_banlist.txt"
ABILITIES_BANLIST_FILE = DATA_DIR / "abilities_banlist.txt"
POKEMON_GROUPS_FILE = DATA_DIR / "pokemon_groups.txt"

MAX_POKEMON = 6
OPTIONS_PER_DRAW = 3
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
            "options_per_draw": OPTIONS_PER_DRAW,
            "lock_chosen_pokemon_globally": True,
            "lock_abilities_globally": False,
        },
    }


def empty_pending() -> Dict[str, Any]:
    return {
        "type": None,
        "pokemon_options": [],
        "ability_for_index": None,
        "ability_options": [],
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

    fixed_picks = []
    for pick in player["pokemon_picks"]:
        if isinstance(pick, str):
            fixed_picks.append({"name": pick, "ability": None})
        else:
            pick.setdefault("name", "Pokémon")
            pick.setdefault("ability", None)
            fixed_picks.append(pick)
    player["pokemon_picks"] = fixed_picks
    return player


def migrate_state_shape(state: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    changed = False
    state.setdefault("used_pokemon", [])
    state.setdefault("players", {})
    state.setdefault("settings", default_state()["settings"])
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


def require_admin() -> Optional[Any]:
    key = request.args.get("key") or request.form.get("key")
    if key != ADMIN_KEY:
        return render_template("locked.html", title="Admin"), 403
    return None


def draw_options(pool: List[str], amount: int, excluded: List[str]) -> Tuple[List[str], Optional[str]]:
    excluded_lower = {item.lower() for item in excluded}
    available = [item for item in pool if item.lower() not in excluded_lower]

    if len(available) < amount:
        return [], f"Pool insuficiente: só existem {len(available)} opções disponíveis."

    return random.sample(available, amount), None



def command_token(value: str) -> str:
    """Converte nomes para o formato simples usado no comando.

    Ex.: "Parental Bond" -> "parentalbond".
    Para Pokémon com formas/nomes especiais, o jogador pode ajustar manualmente no comando gerado.
    """
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def pokegive_command(nickname: str, pokemon_name: str, ability_name: str) -> str:
    return f"/pokegiveother {nickname} {command_token(pokemon_name)} ability={command_token(ability_name)}"


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

    pokemon_pool = load_pool(POKEMON_FILE, POKEMON_BANLIST_FILE)
    already_in_team = [pick["name"] for pick in player["pokemon_picks"]]
    globally_used = state.get("used_pokemon", []) if state["settings"].get("lock_chosen_pokemon_globally", True) else []
    options, error = draw_options(pokemon_pool, state["settings"].get("options_per_draw", OPTIONS_PER_DRAW), already_in_team + globally_used)

    if error:
        flash(error, "error")
        return redirect(url_for("master_page", key=MASTER_KEY))

    player["pending"] = {
        "type": "pokemon",
        "pokemon_options": options,
        "ability_for_index": None,
        "ability_options": [],
    }
    save_state(state)

    flash(f"3 Pokémon foram sorteados para {nickname}. Você não viu as opções.", "success")
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
    options, error = draw_options(ability_pool, state["settings"].get("options_per_draw", OPTIONS_PER_DRAW), [])

    if error:
        flash(error, "error")
        return redirect(url_for("master_page", key=MASTER_KEY))

    player["pending"] = {
        "type": "ability",
        "pokemon_options": [],
        "ability_for_index": pokemon_index,
        "ability_options": options,
    }
    save_state(state)

    flash(f"3 abilities foram sorteadas para {slot_label(pokemon_index)} de {nickname}. Você não viu as opções.", "success")
    return redirect(url_for("master_page", key=MASTER_KEY))


@app.route("/admin", methods=["GET"])
def admin_page():
    locked = require_admin()
    if locked:
        return locked

    state = load_state()
    return render_template(
        "admin.html",
        state=state,
        players=sorted_players(state),
        pokemon_count=len(load_pool(POKEMON_FILE, POKEMON_BANLIST_FILE)),
        ability_count=len(load_pool(ABILITIES_FILE, ABILITIES_BANLIST_FILE)),
        pokemon_pool=load_pool(POKEMON_FILE, POKEMON_BANLIST_FILE),
        pokemon_groups=load_pokemon_groups(),
        pokemon_groups_text=POKEMON_GROUPS_FILE.read_text(encoding="utf-8") if POKEMON_GROUPS_FILE.exists() else "",
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
    POKEMON_GROUPS_FILE.write_text(groups_text.replace("\r\n", "\n"), encoding="utf-8")

    # Recalcula bloqueios já existentes para refletir grupos novos/editados.
    state = load_state()
    recompute_used_pokemon(state)
    save_state(state)

    flash("Grupos de Pokémon salvos e bloqueios globais recalculados.", "success")
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
