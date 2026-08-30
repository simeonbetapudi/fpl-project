# FPL Project

Investigating two questions about Fantasy Premier League:

1. **Hindsight best XI** — what was the objectively best possible lineup each gameweek, given known results?
2. **Season-long strategy** — how should transfers, captaincy, and chip timing (wildcard, bench boost, triple captain, free hit) actually be played across a season, accounting for form, budget, and price movement?

Data is pulled from FPL's public (unofficial, undocumented) API and published here as a growing, open dataset.

## Project structure

```
fpl-project/
├── scripts/
│   ├── build_players_table.py     # players dimension table (run once, or to pick up new signings)
│   └── build_gameweek_stats.py    # gameweek_stats fact table (run after each gameweek finishes)
├── data/
│   ├── raw/                       # reserved for future immutable JSON snapshots (not yet populated)
│   └── processed/                 # the published dataset: players.parquet, gw_NN.parquet, ...
├── fpl.duckdb                     # DuckDB views over the parquet files, for querying
├── pyproject.toml
├── uv.lock
├── .python-version
├── README.md
├── LICENSE
└── .gitignore
```

## Setup

This project uses [uv](https://docs.astral.sh/uv/) for dependency and environment management.

```bash
git clone <your-repo-url>
cd fpl-project
uv sync
```

## Usage

```bash
# Build the players dimension table (run once at season start; safe to re-run)
uv run scripts/build_players_table.py

# Build the gameweek_stats fact table for any newly completed gameweek
# (only fetches gameweeks that are finished AND have finalized bonus points,
#  and only writes gameweeks not already saved)
uv run scripts/build_gameweek_stats.py

# Query the data directly
duckdb fpl.duckdb
```

## Data dictionary

**`players.parquet`** — one row per player, ever.

| Field | Description |
|---|---|
| `player_id` | Primary key, matches FPL's own player id |
| `first_name`, `last_name`, `name` | Identity fields (`name` is FPL's short "web name") |
| `position_id`, `position` | Static for the season — position label resolved from FPL's lookup table |
| `starting_cost` | Price at the true start of the season, derived as `now_cost − cost_change_start` (safe to recompute at any point, not just captured once) |

**`gw_NN.parquet`** (one file per gameweek) — one row per player per gameweek.

Every field FPL's API returns per player per round is captured (not a hand-picked subset), including `total_points`, `minutes`, `goals_scored`, `assists`, `bonus`, `bps`, `value` (price during that gameweek), `opponent_team`, `was_home`, and the expected-stats fields (`expected_goals`, `expected_assists`, etc.). `team` is added separately (see limitations below).

**`price_changes`** — planned, not yet implemented. Will log day-level price movements (not just gameweek-level), since the price you actually pay for a transfer is set at the moment you execute it, not fixed for the whole gameweek.

## Known limitations

- **`team` reflects each player's *current* club**, not necessarily their club during that historical gameweek. Correct for the vast majority of players; wrong only for the rare mid-season transfer between two Premier League clubs. This will be resolved properly once fixture data is incorporated for opponent analysis.
- **`data/raw/` is currently unused.** It's reserved for immutable raw JSON snapshots, which aren't being captured yet.
- **Price is currently tracked only at gameweek granularity** via each row's `value` field. Day-level price tracking is planned (see `price_changes` above) but not yet built.

## A note on reproducibility

This project pulls from a **live** API. Running these scripts today gives you *your own current snapshot* (today's prices, the latest finished gameweek) — it does not regenerate the exact historical values that were true when this repo's committed data was captured. The parquet files in `data/processed/` are the canonical historical record; the scripts are how that record gets extended forward each week, not how it gets reconstructed from scratch.

## License

- **Code** (everything under `scripts/`) is licensed under MIT — see [LICENSE](./LICENSE).
- **Data** (everything under `data/processed/`) is released under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) — free to use for any purpose, no attribution required.

This project relies on FPL's public API, which is unofficial and undocumented — FPL does not publish explicit terms of use for it. Other open community projects use it the same way this one does, but this isn't a legal determination of your specific rights to redistribute derived data; worth checking FPL's own terms yourself if you plan on wide redistribution.
