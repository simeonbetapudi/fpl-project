"""
Build the players dimension table and write it to parquet via DuckDB.

Usage:
    uv run scripts/build_players_table.py

Output:
    data/processed/players.parquet

Paths are resolved relative to the project root (this file's parent's
parent), not the caller's working directory - so this script writes to
the same place regardless of where it's invoked from.
"""

from pathlib import Path
import requests
import pandas as pd
import duckdb

BASE_URL = "https://fantasy.premierleague.com/api/"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "processed"
DB_PATH = PROJECT_ROOT / "fpl.duckdb"


def fetch_bootstrap():
    r = requests.get(BASE_URL + "bootstrap-static/")
    r.raise_for_status()
    return r.json()


def build_players_df(data):
    # element_types is the tiny lookup table mapping position_id -> label
    positions = {p["id"]: p["singular_name_short"] for p in data["element_types"]}

    rows = []
    for r in data["elements"]:
        rows.append({
            "player_id": r["id"],
            "first_name": r["first_name"],
            "last_name": r["second_name"],
            "name": r["web_name"],
            "position_id": r["element_type"],
            "position": positions[r["element_type"]],
        })

    return pd.DataFrame(rows)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    players_path = DATA_DIR / "players.parquet"

    data = fetch_bootstrap()
    players_df = build_players_df(data)

    con = duckdb.connect(str(DB_PATH))
    con.register("players_staging", players_df)  # expose the DataFrame to SQL

    con.execute(f"""
        COPY players_staging TO '{players_path}' (FORMAT PARQUET)
    """)

    # sanity check: read the file back rather than trusting the write blindly
    count = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{players_path}')"
    ).fetchone()[0]
    print(f"Wrote {count} players to {players_path}")

    con.close()


if __name__ == "__main__":
    main()