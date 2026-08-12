from __future__ import annotations

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from services.dex_db import DEFAULT_DB_PATH, init_database, list_draft_rulesets, seed_default_draft_rulesets


def main() -> None:
    init_database(DEFAULT_DB_PATH)
    seed_default_draft_rulesets(DEFAULT_DB_PATH)
    rulesets = list_draft_rulesets(DEFAULT_DB_PATH)
    print(f"Rulesets disponíveis: {len(rulesets)}")
    for ruleset in rulesets:
        print(f"- {ruleset['name']}")


if __name__ == "__main__":
    main()
