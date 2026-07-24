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

MAX_POKEMON = 6
OPTIONS_PER_DRAW = 3
ADMIN_KEY = os.environ.get("DRAFT_ADMIN_KEY", "cobbleverse")
MASTER_KEY = os.environ.get("DRAFT_MASTER_KEY", "mestre")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")


def default_state() -> Dict[str, Any]:
    return {
        "created_at": now_text(),
        "updated_at": now_text(),
        "used_pokemon": [],
        "players": {},
        "settings": {
            "max_pokemon": MAX_POKEMON,
            "options_per_draw": OPTIONS_PER_DRAW,
            "lock_chosen_pokemon_globally": True,
            "lock_abilities_globally": False,
        },
    }


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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


def load_state() -> Dict[str, Any]:
    ensure_files_exist()

    if not STATE_FILE.exists():
        state = default_state()
        save_state(state)
        return state

    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        backup = BASE_DIR / f"draft_state_broken_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        STATE_FILE.rename(backup)
        state = default_state()
        save_state(state)
        return state

    state.setdefault("used_pokemon", [])
    state.setdefault("players", {})
    state.setdefault("settings", default_state()["settings"])
    return state


def save_state(state: Dict[str, Any]) -> None:
    state["updated_at"] = now_text()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def empty_pending() -> Dict[str, Any]:
    return {
        "type": None,
        "pokemon_options": [],
        "ability_for_index": None,
        "ability_options": [],
    }


def get_player(state: Dict[str, Any], nickname: str) -> Dict[str, Any]:
    players = state.setdefault("players", {})

    if nickname not in players:
        players[nickname] = {
            "nickname": nickname,
            "created_at": now_text(),
            "pokemon_picks": [],
            "pending": empty_pending(),
        }

    player = players[nickname]
    player.setdefault("nickname", nickname)
    player.setdefault("pokemon_picks", [])
    player.setdefault("pending", empty_pending())
    player["pending"].setdefault("type", None)
    player["pending"].setdefault("pokemon_options", [])
    player["pending"].setdefault("ability_for_index", None)
    player["pending"].setdefault("ability_options", [])

    # Migração defensiva caso algum Pokémon antigo esteja salvo como string.
    fixed_picks = []
    for pick in player["pokemon_picks"]:
        if isinstance(pick, str):
            fixed_picks.append({"name": pick, "ability": None})
        else:
            pick.setdefault("ability", None)
            fixed_picks.append(pick)
    player["pokemon_picks"] = fixed_picks

    return player


def require_master() -> Optional[Any]:
    key = request.args.get("key") or request.form.get("key")
    if key != MASTER_KEY:
        return render_template("locked.html", title="Mestre", key_name="DRAFT_MASTER_KEY", default_key=MASTER_KEY), 403
    return None


def require_admin() -> Optional[Any]:
    key = request.args.get("key") or request.form.get("key")
    if key != ADMIN_KEY:
        return render_template("locked.html", title="Admin", key_name="DRAFT_ADMIN_KEY", default_key=ADMIN_KEY), 403
    return None


def draw_options(pool: List[str], amount: int, excluded: List[str]) -> Tuple[List[str], Optional[str]]:
    excluded_lower = {item.lower() for item in excluded}
    available = [item for item in pool if item.lower() not in excluded_lower]

    if len(available) < amount:
        return [], f"Pool insuficiente: só existem {len(available)} opções disponíveis."

    return random.sample(available, amount), None


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


def first_without_ability(player: Dict[str, Any]) -> Optional[int]:
    for index, pick in enumerate(player["pokemon_picks"]):
        if pick.get("ability") is None:
            return index
    return None


@app.context_processor
def inject_helpers():
    return {
        "max_pokemon_default": MAX_POKEMON,
        "player_pending_label": player_pending_label,
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
    get_player(state, nickname)
    save_state(state)

    return redirect(url_for("player_page", nickname=nickname))


@app.route("/player/<nickname>", methods=["GET"])
def player_page(nickname: str):
    state = load_state()
    player = get_player(state, nickname)
    save_state(state)

    return render_template("player.html", state=state, player=player)


@app.route("/choose-pokemon", methods=["POST"])
def choose_pokemon():
    nickname = request.form.get("nickname", "").strip()
    chosen = request.form.get("pokemon", "").strip()

    state = load_state()
    player = get_player(state, nickname)
    pending = player["pending"]

    if pending.get("type") != "pokemon":
        flash("Você não tem escolha de Pokémon pendente.", "error")
        return redirect(url_for("player_page", nickname=nickname))

    if chosen not in pending.get("pokemon_options", []):
        flash("Escolha inválida.", "error")
        return redirect(url_for("player_page", nickname=nickname))

    used_lower = {name.lower() for name in state.get("used_pokemon", [])}
    if state["settings"].get("lock_chosen_pokemon_globally", True) and chosen.lower() in used_lower:
        flash("Esse Pokémon já foi travado por outro jogador. Peça para o mestre sortear novamente.", "error")
        return redirect(url_for("player_page", nickname=nickname))

    player["pokemon_picks"].append({"name": chosen, "ability": None})
    player["pending"] = empty_pending()

    if state["settings"].get("lock_chosen_pokemon_globally", True):
        state.setdefault("used_pokemon", []).append(chosen)

    save_state(state)
    flash(f"{chosen} escolhido e travado no seu draft.", "success")
    return redirect(url_for("player_page", nickname=nickname))


@app.route("/choose-ability", methods=["POST"])
def choose_ability():
    nickname = request.form.get("nickname", "").strip()
    ability = request.form.get("ability", "").strip()

    state = load_state()
    player = get_player(state, nickname)
    pending = player["pending"]

    if pending.get("type") != "ability":
        flash("Você não tem escolha de ability pendente.", "error")
        return redirect(url_for("player_page", nickname=nickname))

    if ability not in pending.get("ability_options", []):
        flash("Escolha inválida.", "error")
        return redirect(url_for("player_page", nickname=nickname))

    index = pending.get("ability_for_index")
    if not isinstance(index, int) or index < 0 or index >= len(player["pokemon_picks"]):
        flash("Índice do Pokémon inválido. Peça para o mestre sortear novamente.", "error")
        player["pending"] = empty_pending()
        save_state(state)
        return redirect(url_for("player_page", nickname=nickname))

    player["pokemon_picks"][index]["ability"] = ability
    pokemon_name = player["pokemon_picks"][index]["name"]
    player["pending"] = empty_pending()

    save_state(state)
    flash(f"{pokemon_name} recebeu {ability}.", "success")
    return redirect(url_for("player_page", nickname=nickname))


@app.route("/master", methods=["GET"])
def master_page():
    locked = require_master()
    if locked:
        return locked

    state = load_state()
    players = state.get("players", {})

    return render_template("master.html", state=state, players=players, key=MASTER_KEY)


@app.route("/master/draw-pokemon", methods=["POST"])
def master_draw_pokemon():
    locked = require_master()
    if locked:
        return locked

    nickname = request.form.get("nickname", "").strip()
    state = load_state()
    player = get_player(state, nickname)

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

    nickname = request.form.get("nickname", "").strip()
    index_raw = request.form.get("pokemon_index", "")

    state = load_state()
    player = get_player(state, nickname)

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

    pokemon_name = player["pokemon_picks"][pokemon_index]["name"]
    flash(f"3 abilities foram sorteadas para {pokemon_name} de {nickname}. Você não viu as opções.", "success")
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
        players=state.get("players", {}),
        pokemon_count=len(load_pool(POKEMON_FILE, POKEMON_BANLIST_FILE)),
        ability_count=len(load_pool(ABILITIES_FILE, ABILITIES_BANLIST_FILE)),
        key=ADMIN_KEY,
    )


@app.route("/admin/clear-pending", methods=["POST"])
def admin_clear_pending():
    locked = require_admin()
    if locked:
        return locked

    nickname = request.form.get("nickname", "").strip()
    state = load_state()
    player = get_player(state, nickname)
    player["pending"] = empty_pending()
    save_state(state)

    flash(f"Pendência de {nickname} limpa.", "success")
    return redirect(url_for("admin_page", key=ADMIN_KEY))


@app.route("/admin/remove-last-pick", methods=["POST"])
def admin_remove_last_pick():
    locked = require_admin()
    if locked:
        return locked

    nickname = request.form.get("nickname", "").strip()
    state = load_state()
    player = get_player(state, nickname)

    if not player["pokemon_picks"]:
        flash("Esse jogador não tem Pokémon para remover.", "error")
        return redirect(url_for("admin_page", key=ADMIN_KEY))

    removed = player["pokemon_picks"].pop()
    removed_name = removed["name"]
    state["used_pokemon"] = [name for name in state.get("used_pokemon", []) if name.lower() != removed_name.lower()]
    save_state(state)

    flash(f"Último Pokémon de {nickname} removido: {removed_name}.", "success")
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


if __name__ == "__main__":
    ensure_files_exist()
    load_state()
    app.run(host="0.0.0.0", port=5000, debug=True)
