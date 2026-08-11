PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS pokemon (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pokeapi_id INTEGER UNIQUE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    species_slug TEXT,
    form_name TEXT,
    generation TEXT,
    type1 TEXT,
    type2 TEXT,
    hp INTEGER NOT NULL DEFAULT 0,
    attack INTEGER NOT NULL DEFAULT 0,
    defense INTEGER NOT NULL DEFAULT 0,
    sp_attack INTEGER NOT NULL DEFAULT 0,
    sp_defense INTEGER NOT NULL DEFAULT 0,
    speed INTEGER NOT NULL DEFAULT 0,
    bst INTEGER NOT NULL DEFAULT 0,
    height_dm INTEGER,
    weight_hg INTEGER,
    base_experience INTEGER,
    is_default INTEGER NOT NULL DEFAULT 0,
    is_baby INTEGER NOT NULL DEFAULT 0,
    is_legendary INTEGER NOT NULL DEFAULT 0,
    is_mythical INTEGER NOT NULL DEFAULT 0,
    is_pseudo INTEGER NOT NULL DEFAULT 0,
    is_ultra_beast INTEGER NOT NULL DEFAULT 0,
    is_paradox INTEGER NOT NULL DEFAULT 0,
    is_starter INTEGER NOT NULL DEFAULT 0,
    is_implemented INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pokemon_name ON pokemon(name);
CREATE INDEX IF NOT EXISTS idx_pokemon_types ON pokemon(type1, type2);
CREATE INDEX IF NOT EXISTS idx_pokemon_bst ON pokemon(bst);
CREATE INDEX IF NOT EXISTS idx_pokemon_stats ON pokemon(hp, attack, defense, sp_attack, sp_defense, speed);

CREATE TABLE IF NOT EXISTS abilities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pokeapi_id INTEGER UNIQUE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    effect TEXT,
    short_effect TEXT,
    is_battle_relevant INTEGER NOT NULL DEFAULT 1,
    is_banned INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pokemon_abilities (
    pokemon_id INTEGER NOT NULL REFERENCES pokemon(id) ON DELETE CASCADE,
    ability_id INTEGER NOT NULL REFERENCES abilities(id) ON DELETE CASCADE,
    slot INTEGER NOT NULL DEFAULT 0,
    is_hidden INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (pokemon_id, ability_id)
);

CREATE INDEX IF NOT EXISTS idx_pokemon_abilities_hidden ON pokemon_abilities(is_hidden);

CREATE TABLE IF NOT EXISTS moves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pokeapi_id INTEGER UNIQUE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    type TEXT,
    category TEXT,
    power INTEGER,
    accuracy INTEGER,
    pp INTEGER,
    priority INTEGER NOT NULL DEFAULT 0,
    effect TEXT,
    short_effect TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_moves_name ON moves(name);
CREATE INDEX IF NOT EXISTS idx_moves_type_category ON moves(type, category);

CREATE TABLE IF NOT EXISTS pokemon_moves (
    pokemon_id INTEGER NOT NULL REFERENCES pokemon(id) ON DELETE CASCADE,
    move_id INTEGER NOT NULL REFERENCES moves(id) ON DELETE CASCADE,
    learn_method TEXT NOT NULL,
    version_group TEXT NOT NULL,
    level_learned_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (pokemon_id, move_id, learn_method, version_group, level_learned_at)
);

CREATE INDEX IF NOT EXISTS idx_pokemon_moves_method ON pokemon_moves(learn_method);
CREATE INDEX IF NOT EXISTS idx_pokemon_moves_version ON pokemon_moves(version_group);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL DEFAULT 'geral',
    description TEXT
);

CREATE TABLE IF NOT EXISTS pokemon_tags (
    pokemon_id INTEGER NOT NULL REFERENCES pokemon(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (pokemon_id, tag_id)
);

CREATE TABLE IF NOT EXISTS ability_tags (
    ability_id INTEGER NOT NULL REFERENCES abilities(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (ability_id, tag_id)
);

CREATE TABLE IF NOT EXISTS move_tags (
    move_id INTEGER NOT NULL REFERENCES moves(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (move_id, tag_id)
);

CREATE TABLE IF NOT EXISTS import_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_detail TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    imported_pokemon INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    error TEXT
);

CREATE TABLE IF NOT EXISTS draft_presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    description TEXT,
    filters_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_draft_presets_name ON draft_presets(name);

CREATE TABLE IF NOT EXISTS ability_presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    description TEXT,
    required_tags_json TEXT NOT NULL DEFAULT '[]',
    excluded_tags_json TEXT NOT NULL DEFAULT '[]',
    required_mode TEXT NOT NULL DEFAULT 'any',
    include_banned INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ability_presets_name ON ability_presets(name);
