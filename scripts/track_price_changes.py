"""
Track daily FPL price changes (rises and drops) into a growing parquet file.

Run this once a day. For every player whose cost_change_event is nonzero
(their price has moved since the current gameweek started), records the
player id, the cost_change_event value, the current gameweek, and the
date of this scrape.

cost_change_event is CUMULATIVE within a gameweek and resets to 0 when a
new gameweek starts. That means a player's price move shows up with the
same cost_change_event value on every subsequent day of that gameweek
until it moves again - without dedup this would write a redundant row
every day for every player who has ever moved price that gameweek. To
avoid that, a row is only written if its exact (player_id, gameweek,
cost_change_event) combination has never been saved before. A genuinely
new move (the cumulative value changes further) or the same value
recurring in a later gameweek is still logged as a new row.

The script is idempotent per day: running it twice on the same day, with
no change in FPL's data, produces no new rows the second time.

Usage:
    uv run scripts/track_price_changes.py

Output:
    data/processed/price_changes.parquet   (appended to, not overwritten)

Paths are resolved relative to the project root (this file's parent's
parent), not the caller's working directory - so this script writes to
the same place regardless of where it's invoked from.
"""

from datetime import date
from pathlib import Path

import requests
import pandas as pd
import duckdb

BASE_URL = "https://fantasy.premierleague.com/api/"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "processed"
DB_PATH = PROJECT_ROOT / "fpl.duckdb"
OUT_PATH = DATA_DIR / "price_changes.parquet"

ROW_COLUMNS = ["player_id", "gameweek", "cost_change_event", "scrape_date"]


def fetch_bootstrap():
    r = requests.get(BASE_URL + "bootstrap-static/")
    r.raise_for_status()
    return r.json()


def current_gameweek(events):
    """The gameweek whose cost_change_event values are currently accumulating."""
    for e in events:
        if e.get("is_current"):
            return e["id"]
    for e in events:
        if e.get("is_next"):
            return e["id"]
    raise RuntimeError("Could not determine current gameweek from bootstrap-static events")


def build_candidate_rows(data, gw, scrape_date):
    """One row per player whose price has moved this gameweek so far."""
    rows = []
    for p in data["elements"]:
        change = p["cost_change_event"]
        if change == 0:
            continue
        rows.append({
            "player_id": p["id"],
            "gameweek": gw,
            "cost_change_event": change,
            "scrape_date": scrape_date,
        })
    return pd.DataFrame(rows, columns=ROW_COLUMNS)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    data = fetch_bootstrap()
    gw = current_gameweek(data["events"])
    scrape_date = date.today().isoformat()

    candidates = build_candidate_rows(data, gw, scrape_date)
    if candidates.empty:
        print(f"No players with a nonzero cost_change_event (gameweek {gw}).")
        return

    con = duckdb.connect(str(DB_PATH))

    if OUT_PATH.exists():
        existing = con.execute(f"SELECT * FROM read_parquet('{OUT_PATH}')").df()
        seen = set(zip(existing["player_id"], existing["gameweek"], existing["cost_change_event"]))
    else:
        existing = None
        seen = set()

    is_new = ~candidates.apply(
        lambda r: (r["player_id"], r["gameweek"], r["cost_change_event"]) in seen, axis=1
    )
    new_rows = candidates[is_new]

    if new_rows.empty:
        print(
            f"No new price-change events to record (gameweek {gw}, "
            f"{len(candidates)} candidate(s), all already saved)."
        )
        con.close()
        return

    combined = pd.concat([existing, new_rows], ignore_index=True) if existing is not None else new_rows

    con.register("price_changes_staging", combined)
    con.execute(f"""
        COPY price_changes_staging TO '{OUT_PATH}' (FORMAT PARQUET)
    """)

    # sanity check: read the file back rather than trusting the write blindly
    count = con.execute(f"SELECT COUNT(*) FROM read_parquet('{OUT_PATH}')").fetchone()[0]
    con.close()

    print(
        f"Wrote {len(new_rows)} new row(s) for gameweek {gw}. "
        f"File now has {count} total row(s) at {OUT_PATH}"
    )


if __name__ == "__main__":
    main()
