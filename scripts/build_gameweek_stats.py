"""
Build the gameweek_stats fact table for each newly-completed gameweek.

Run this once a gameweek is fully finished AND FPL has finalized bonus
points - checked here via the `finished` and `data_checked` flags on
each event in bootstrap-static. `finished` alone can be true before
bonus points (which depend on BPS) are locked in, so both are required.

Captures every field the API returns per player per round, rather than
a hand-picked subset, so newly added stats (FPL has added several over
past seasons - expected goals, defensive contributions, etc.) aren't
silently dropped.

Known limitation: `team` is resolved from each player's CURRENT team
in bootstrap-static, not their team at the time of that historical
round. This is correct for the vast majority of players and wrong only
for the rare mid-season Premier-League-to-Premier-League transfer.
This gets resolved properly once fixtures are joined in for opponent
analysis (fixture home/away + was_home gives the true team-of-record).

The script is idempotent: it only fetches and writes gameweeks that
don't already have a parquet file on disk, so re-running it harmlessly
skips what's already saved. To redo a gameweek, delete its parquet
file first.

Usage:
    uv run scripts/build_gameweek_stats.py

Output:
    data/processed/gw_NN.parquet   (one new file per completed gameweek)
"""

import time
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


def fetch_player_history(player_id):
    r = requests.get(BASE_URL + f"element-summary/{player_id}/")
    r.raise_for_status()
    return r.json()["history"]


def completed_gameweeks(events):
    """Gameweeks that are finished AND have finalized (checked) stats."""
    return {e["id"] for e in events if e["finished"] and e["data_checked"]}


def already_saved_gameweeks():
    """Gameweeks that already have a parquet file on disk."""
    return {
        int(p.stem.split("_")[1])
        for p in DATA_DIR.glob("gw_*.parquet")
    }


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    data = fetch_bootstrap()
    current_team = {p["id"]: p["team"] for p in data["elements"]}
    team_names = {t["id"]: t["name"] for t in data["teams"]}

    to_process = completed_gameweeks(data["events"]) - already_saved_gameweeks()

    if not to_process:
        print("No new completed gameweeks to process.")
        return

    print(f"Gameweeks to fetch: {sorted(to_process)}")

    rows = []
    players = data["elements"]
    for i, p in enumerate(players, start=1):
        pid = p["id"]
        print(f"[{i}/{len(players)}] player {pid}")

        try:
            history = fetch_player_history(pid)
        except Exception as e:
            print(f"  -> failed: {e}")
            continue

        for round_stats in history:
            gw = round_stats["round"]
            if gw not in to_process:
                continue  # already saved, or gameweek not finished/checked yet

            row = dict(round_stats)  # keep every field the API returns
            row["player_id"] = row.pop("element")
            team_id = current_team.get(pid)
            row["team"] = team_names.get(team_id, team_id)
            rows.append(row)

        time.sleep(0.05)

    df = pd.DataFrame(rows)

    con = duckdb.connect(str(DB_PATH))
    con.register("gw_staging", df)

    for gw in sorted(to_process):
        out_path = DATA_DIR / f"gw_{gw:02d}.parquet"
        con.execute(f"""
            COPY (SELECT * FROM gw_staging WHERE round = {gw})
            TO '{out_path}' (FORMAT PARQUET)
        """)
        n = int((df["round"] == gw).sum())
        print(f"Wrote {n} rows to {out_path}")

    con.close()


if __name__ == "__main__":
    main()