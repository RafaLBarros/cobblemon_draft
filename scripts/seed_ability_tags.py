from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Dict, Iterable, Set, Tuple

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from services.dex_db import DEFAULT_DB_PATH, init_database, upsert_tag

TAG_DEFINITIONS: Dict[str, Tuple[str, str]] = {
    "Metronome Boa": ("ability", "Ability que tende a gerar valor mesmo quando o único golpe clicável é Metronome."),
    "Metronome Ruim": ("ability", "Ability que tende a gerar pouco valor em batalhas só com Metronome."),
    "Funciona em singles": ("ability", "Ability com efeito útil em singles sem depender de aliado em campo."),
    "Depende de contato": ("ability", "Ability que depende do usuário ou adversário usar golpes de contato."),
    "Depende de item": ("ability", "Ability que depende de item, consumo, roubo, perda ou interação específica com item."),
    "Depende de switch": ("ability", "Ability que ganha valor ao entrar/sair de campo ou copiar algo no switch-in."),
    "Depende de clima/campo": ("ability", "Ability que depende de clima, terreno, sala ou condição de campo."),
    "Depende de doubles": ("ability", "Ability voltada para aliados ou interações típicas de duplas."),
    "Precisa de golpe específico": ("ability", "Ability que só brilha quando o golpe chamado possui propriedade específica."),
    "Ofensiva": ("ability", "Ability que aumenta dano, stats ofensivos ou pressão de KO."),
    "Defensiva": ("ability", "Ability que aumenta sobrevivência, imunidades, resistências ou recuperação."),
    "Utilidade": ("ability", "Ability com utilidade indireta, controle, informação ou proteção contra status."),
    "Banível": ("ability", "Ability potencialmente forte demais ou anti-jogo. A tag não bane automaticamente."),
    "Inútil em singles": ("ability", "Ability que normalmente não faz nada relevante em singles."),
}

ABILITY_TAGS: Dict[str, Set[str]] = {
    "Metronome Boa": {
        "adaptability", "anger-shell", "beast-boost", "battle-armor", "bulletproof", "cheek-pouch", "clear-body",
        "competitive", "cursed-body", "dauntless-shield", "defiant", "disguise", "dry-skin",
        "filter", "flame-body", "flash-fire", "fluffy", "fur-coat", "good-as-gold", "guts",
        "huge-power", "ice-scales", "immunity", "insomnia", "intimidate", "iron-barbs", "levitate", "magic-bounce",
        "magic-guard", "marvel-scale", "mirror-armor", "overcoat", "mold-breaker", "multiscale", "mummy",
        "natural-cure", "no-guard", "poison-heal", "poison-point", "poison-touch", "prankster",
        "pressure", "protean", "libero", "pure-power", "quick-draw", "regenerator", "rough-skin", "serene-grace",
        "shadow-shield", "shell-armor", "shield-dust", "solid-rock", "speed-boost", "stamina", "static", "sturdy",
        "synchronize", "tangling-hair", "thick-fat", "trace", "unaware", "volt-absorb", "wandering-spirit",
        "water-absorb", "water-bubble", "toxic-chain", "weak-armor", "well-baked-body", "wonder-skin",
    },
    "Metronome Ruim": {
        "air-lock", "anticipation", "ball-fetch", "battery", "big-pecks", "blaze",
        "chilling-neigh", "chlorophyll", "color-change", "commander", "corrosion", "costar", "damp",
        "dancer", "delta-stream", "desolate-land", "early-bird", "emergency-exit", "flower-gift",
        "flower-veil", "forecast", "forewarn", "friend-guard", "frisk", "gluttony", "grass-pelt",
        "gulp-missile", "harvest", "healer", "honey-gather", "hunger-switch", "hustle", "hydrate",
        "hyper-cutter", "illuminate", "illusion", "imposter", "innards-out", "insomnia", "iron-fist",
        "justified", "keen-eye", "klutz", "leaf-guard", "light-metal", "liquid-voice", "long-reach",
        "magician", "mega-launcher", "minus", "moxie", "mycelium-might", "neutralizing-gas",
        "overcoat", "overgrow", "parental-bond", "pastel-veil", "pickpocket", "pickup", "plus",
        "power-of-alchemy", "power-spot", "primordial-sea", "punk-rock", "queenly-majesty", "receiver",
        "reckless", "ripen", "rock-head", "sand-force", "sand-rush", "sand-spit", "sand-stream",
        "sand-veil", "sap-sipper", "scrappy", "sharpness", "sheer-force", "skill-link", "slow-start",
        "slush-rush", "sniper", "snow-cloak", "snow-warning", "solar-power", "soundproof", "stakeout",
        "stall", "steam-engine", "steelworker", "steely-spirit", "storm-drain", "strong-jaw",
        "suction-cups", "super-luck", "supreme-overlord", "surge-surfer", "swarm", "swift-swim", "symbiosis",
        "telepathy", "torrent", "tough-claws", "toxic-boost", "truant", "unburden", "victory-star",
        "water-compaction", "wind-power", "wind-rider", "zen-mode",
    },
    "Funciona em singles": {
        "adaptability", "beast-boost", "bulletproof", "clear-body", "competitive", "cursed-body", "defiant",
        "disguise", "filter", "flame-body", "flash-fire", "fluffy", "fur-coat", "good-as-gold", "guts",
        "huge-power", "ice-scales", "immunity", "insomnia", "intimidate", "iron-barbs", "levitate", "magic-bounce",
        "magic-guard", "marvel-scale", "mirror-armor", "overcoat", "mold-breaker", "multiscale", "natural-cure",
        "no-guard", "poison-heal", "poison-touch", "prankster", "pressure", "pure-power", "quick-draw",
        "regenerator", "rough-skin", "serene-grace", "solid-rock", "speed-boost", "stamina", "static",
        "sturdy", "synchronize", "tangling-hair", "thick-fat", "trace", "unaware", "volt-absorb",
        "water-absorb", "weak-armor", "well-baked-body",
    },
    "Depende de contato": {
        "cute-charm", "effect-spore", "flame-body", "gooey", "iron-barbs", "mummy", "pickpocket",
        "poison-point", "poison-touch", "rough-skin", "static", "tangling-hair", "wandering-spirit",
    },
    "Depende de item": {
        "cheek-pouch", "cud-chew", "frisk", "gluttony", "harvest", "klutz", "magician", "pickpocket",
        "pickup", "ripen", "sticky-hold", "symbiosis", "unburden",
    },
    "Depende de switch": {
        "download", "drizzle", "drought", "frisk", "imposter", "intimidate", "natural-cure", "neutralizing-gas",
        "regenerator", "sand-stream", "snow-warning", "trace",
    },
    "Depende de clima/campo": {
        "chlorophyll", "dry-skin", "forecast", "flower-gift", "grass-pelt", "harvest", "hydrate",
        "ice-body", "leaf-guard", "protosynthesis", "quark-drive", "rain-dish", "sand-force", "sand-rush",
        "sand-spit", "sand-stream", "sand-veil", "slush-rush", "snow-cloak", "snow-warning", "solar-power",
        "surge-surfer", "swift-swim", "wind-power", "wind-rider",
    },
    "Depende de doubles": {
        "battery", "commander", "costar", "flower-gift", "flower-veil", "friend-guard", "healer",
        "hospitality", "minus", "plus", "power-of-alchemy", "power-spot", "receiver", "steely-spirit",
        "symbiosis", "telepathy",
    },
    "Precisa de golpe específico": {
        "aerilate", "analytical", "blaze", "corrosion", "galvanize", "gorilla-tactics", "iron-fist",
        "liquid-voice", "long-reach", "mega-launcher", "merciless", "normalize", "overgrow", "pixilate",
        "punk-rock", "reckless", "refrigerate", "rock-head", "scrappy", "sharpness", "sheer-force",
        "skill-link", "sniper", "strong-jaw", "swarm", "technician", "torrent", "tough-claws", "toxic-boost",
        "transistor", "water-bubble",
    },
    "Ofensiva": {
        "adaptability", "beast-boost", "chilling-neigh", "competitive", "defiant", "gorilla-tactics",
        "grim-neigh", "guts", "huge-power", "mold-breaker", "moxie", "no-guard", "parental-bond",
        "pure-power", "speed-boost", "technician", "tinted-lens", "tough-claws", "transistor",
    },
    "Defensiva": {
        "battle-armor", "bulletproof", "clear-body", "filter", "fluffy", "fur-coat", "good-as-gold", "ice-scales",
        "immunity", "levitate", "magic-bounce", "magic-guard", "marvel-scale", "mirror-armor", "overcoat", "multiscale",
        "poison-heal", "regenerator", "shadow-shield", "shell-armor", "solid-rock", "stamina", "sturdy", "thick-fat",
        "unaware", "volt-absorb", "water-absorb", "well-baked-body",
    },
    "Utilidade": {
        "cursed-body", "frisk", "intimidate", "natural-cure", "poison-touch", "prankster", "pressure",
        "quick-draw", "serene-grace", "toxic-chain", "synchronize", "trace", "wonder-skin",
    },
    "Banível": {
        "arena-trap", "huge-power", "imposter", "moody", "parental-bond", "pure-power", "shadow-tag",
        "speed-boost", "wonder-guard",
    },
    "Inútil em singles": {
        "battery", "commander", "costar", "flower-gift", "flower-veil", "friend-guard", "healer",
        "hospitality", "minus", "plus", "power-of-alchemy", "power-spot", "receiver", "symbiosis", "telepathy",
    },
}


def apply_tag(connection: sqlite3.Connection, tag_name: str, ability_slugs: Iterable[str]) -> int:
    tag_id = int(connection.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()[0])
    count = 0
    for slug in sorted(set(ability_slugs)):
        row = connection.execute("SELECT id FROM abilities WHERE slug = ?", (slug,)).fetchone()
        if not row:
            continue
        connection.execute(
            "INSERT OR IGNORE INTO ability_tags (ability_id, tag_id) VALUES (?, ?)",
            (int(row[0]), tag_id),
        )
        count += 1
    return count


def seed_ability_tags(db_path: Path = DEFAULT_DB_PATH) -> None:
    init_database(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for name, (category, description) in TAG_DEFINITIONS.items():
            upsert_tag(connection, name, category=category, description=description)

        counts: Dict[str, int] = {}
        for tag_name, ability_slugs in ABILITY_TAGS.items():
            counts[tag_name] = apply_tag(connection, tag_name, ability_slugs)

        connection.commit()

    print("Tags de abilities atualizadas:")
    for name, count in counts.items():
        print(f"- {name}: {count} abilities")


def main() -> None:
    seed_ability_tags(DEFAULT_DB_PATH)


if __name__ == "__main__":
    main()
