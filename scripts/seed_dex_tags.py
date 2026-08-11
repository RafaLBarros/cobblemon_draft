from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Iterable, Set

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from services.dex_db import DEFAULT_DB_PATH, init_database

STARTER_SPECIES: Set[str] = {
    # Kanto
    "bulbasaur", "ivysaur", "venusaur",
    "charmander", "charmeleon", "charizard",
    "squirtle", "wartortle", "blastoise",
    "pikachu", "eevee",
    # Johto
    "chikorita", "bayleef", "meganium",
    "cyndaquil", "quilava", "typhlosion",
    "totodile", "croconaw", "feraligatr",
    # Hoenn
    "treecko", "grovyle", "sceptile",
    "torchic", "combusken", "blaziken",
    "mudkip", "marshtomp", "swampert",
    # Sinnoh
    "turtwig", "grotle", "torterra",
    "chimchar", "monferno", "infernape",
    "piplup", "prinplup", "empoleon",
    # Unova
    "snivy", "servine", "serperior",
    "tepig", "pignite", "emboar",
    "oshawott", "dewott", "samurott",
    # Kalos
    "chespin", "quilladin", "chesnaught",
    "fennekin", "braixen", "delphox",
    "froakie", "frogadier", "greninja",
    # Alola
    "rowlet", "dartrix", "decidueye",
    "litten", "torracat", "incineroar",
    "popplio", "brionne", "primarina",
    # Galar
    "grookey", "thwackey", "rillaboom",
    "scorbunny", "raboot", "cinderace",
    "sobble", "drizzile", "inteleon",
    # Hisui starters use the same species_slug as their base species/final forms.
    # Paldea
    "sprigatito", "floragato", "meowscarada",
    "fuecoco", "crocalor", "skeledirge",
    "quaxly", "quaxwell", "quaquaval",
}

PSEUDO_SPECIES: Set[str] = {
    "dragonite",
    "tyranitar",
    "salamence",
    "metagross",
    "garchomp",
    "hydreigon",
    "goodra",
    "kommo-o",
    "dragapult",
    "baxcalibur",
}

ULTRA_BEAST_SPECIES: Set[str] = {
    "nihilego",
    "buzzwole",
    "pheromosa",
    "xurkitree",
    "celesteela",
    "kartana",
    "guzzlord",
    "poipole",
    "naganadel",
    "stakataka",
    "blacephalon",
}

PARADOX_SPECIES: Set[str] = {
    "great-tusk",
    "scream-tail",
    "brute-bonnet",
    "flutter-mane",
    "slither-wing",
    "sandy-shocks",
    "roaring-moon",
    "walking-wake",
    "gouging-fire",
    "raging-bolt",
    "iron-treads",
    "iron-bundle",
    "iron-hands",
    "iron-jugulis",
    "iron-moth",
    "iron-thorns",
    "iron-valiant",
    "iron-leaves",
    "iron-boulder",
    "iron-crown",
}

TAG_DEFINITIONS = {
    "Inicial": ("categoria", "Linha de Pokémon inicial de jogos principais ou Let's Go."),
    "Pseudo": ("categoria", "Pseudo-lendário ou forma da mesma espécie."),
    "Ultra Beast": ("categoria", "Ultra Beast."),
    "Paradox": ("categoria", "Pokémon Paradox."),
    "Lendario": ("categoria", "Marcado pela PokéAPI como lendário."),
    "Mitico": ("categoria", "Marcado pela PokéAPI como mítico."),
}


def upsert_tag(connection: sqlite3.Connection, name: str, category: str, description: str) -> int:
    connection.execute(
        """
        INSERT INTO tags (name, category, description)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            category = excluded.category,
            description = excluded.description
        """,
        (name, category, description),
    )
    return int(connection.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()[0])


def apply_tag_to_species(connection: sqlite3.Connection, tag_name: str, species_slugs: Iterable[str], flag_column: str | None = None) -> int:
    tag_id = int(connection.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()[0])
    species = set(species_slugs)
    count = 0
    rows = connection.execute(
        "SELECT id FROM pokemon WHERE slug IN ({}) OR species_slug IN ({})".format(
            ",".join("?" for _ in species),
            ",".join("?" for _ in species),
        ),
        tuple(species) + tuple(species),
    ).fetchall() if species else []
    for row in rows:
        connection.execute(
            "INSERT OR IGNORE INTO pokemon_tags (pokemon_id, tag_id) VALUES (?, ?)",
            (row[0], tag_id),
        )
        count += 1
    if flag_column and species:
        connection.execute(
            f"UPDATE pokemon SET {flag_column} = 1 WHERE slug IN ({','.join('?' for _ in species)}) OR species_slug IN ({','.join('?' for _ in species)})",
            tuple(species) + tuple(species),
        )
    return count


def apply_boolean_tag(connection: sqlite3.Connection, tag_name: str, column: str) -> int:
    tag_id = int(connection.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()[0])
    rows = connection.execute(f"SELECT id FROM pokemon WHERE {column} = 1").fetchall()
    for row in rows:
        connection.execute(
            "INSERT OR IGNORE INTO pokemon_tags (pokemon_id, tag_id) VALUES (?, ?)",
            (row[0], tag_id),
        )
    return len(rows)


def seed_tags(db_path: Path = DEFAULT_DB_PATH) -> None:
    init_database(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for name, (category, description) in TAG_DEFINITIONS.items():
            upsert_tag(connection, name, category, description)

        # Recalcula apenas as flags manuais controladas por este script.
        connection.execute("UPDATE pokemon SET is_starter = 0, is_pseudo = 0, is_ultra_beast = 0, is_paradox = 0")
        counts = {
            "Inicial": apply_tag_to_species(connection, "Inicial", STARTER_SPECIES, "is_starter"),
            "Pseudo": apply_tag_to_species(connection, "Pseudo", PSEUDO_SPECIES, "is_pseudo"),
            "Ultra Beast": apply_tag_to_species(connection, "Ultra Beast", ULTRA_BEAST_SPECIES, "is_ultra_beast"),
            "Paradox": apply_tag_to_species(connection, "Paradox", PARADOX_SPECIES, "is_paradox"),
            "Lendario": apply_boolean_tag(connection, "Lendario", "is_legendary"),
            "Mitico": apply_boolean_tag(connection, "Mitico", "is_mythical"),
        }
        connection.commit()

    print("Tags atualizadas:")
    for name, count in counts.items():
        print(f"- {name}: {count} Pokémon/forms")


def main() -> None:
    seed_tags(DEFAULT_DB_PATH)


if __name__ == "__main__":
    main()
