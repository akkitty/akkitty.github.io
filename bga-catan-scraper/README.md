# BGA Catan scraper

Collects as many Catan games from Board Game Arena (BGA) as possible, using **your own logged-in session**.
BGA has no public API, so this script calls the same internal JSON endpoints the website uses.
Those endpoints are undocumented and can change. If a step breaks, see *Troubleshooting*.

## 1. Setup (on your own computer)

```bash
cd bga-catan-scraper
pip install -r requirements.txt
```

## 2. Give it your BGA session cookie

1. Log in to boardgamearena.com in your browser.
2. Open DevTools (F12) → **Network** tab, then reload the page.
3. Click any request to `boardgamearena.com` → **Headers** → **Request Headers** → `Cookie`.
4. Copy the whole value into a file named `cookie.txt` in this folder. It is git-ignored.

Treat this cookie like a password: anyone who has it is logged in as you.
If you log out of BGA, the cookie stops working, and you'll need to copy a fresh one.

## 3. Run

```bash
python bga_scraper.py seed                 # top 1000 of the Catan ELO leaderboard -> player queue
python bga_scraper.py history              # crawl their game histories (+ opponents, snowball)
python bga_scraper.py logs --with-info     # full move logs (limited by the daily replay quota)
python bga_scraper.py export               # CSVs in data/export/
python bga_scraper.py status               # progress at any time
```

Every step saves its progress to `data/bga.sqlite`, so you can **Ctrl+C at any time and re-run the same command to resume**.

- `history` is cheap (one request returns 10 games) and can collect tens of thousands of game *results*.
  Use `--max-tables 50000` or `--max-players 2000` to bound a run.
- `logs` is the expensive step. BGA limits how many replays you can open per day, and the limit is higher with Premium.
  When the script hits the limit, it stops cleanly. Run `logs` again the next day.
  It downloads logs for the games with the highest average player ELO first.
- `seed --modes elo arena` also seeds from the arena leaderboard.
- The default delay is 2 seconds between requests, with random jitter. Please keep it there.
  Hammering BGA risks getting your account flagged.

## Output

| File | Contents |
|---|---|
| `data/export/tables.csv` | one row per game: id, start/end time, normal end, ranked?, #players, log status |
| `data/export/table_players.csv` | one row per player per game: rank, score |
| `data/export/players.csv` | players seen, with leaderboard ELO where known |
| `data/logs/<table_id>.json.gz` | raw move log: every notification (dice rolls, builds, trades, robber, ...) |
| `data/bga.sqlite` | everything above, plus the raw JSON of each history row and table info |

The raw logs need a Catan-specific parser to become analysis-ready data such as dice rolls, settlement placements and trades.
Write that parser once you've seen a real log.

## Troubleshooting

- **"non-JSON response (session expired?)"**: copy a fresh cookie.
- **Game id not detected**: on the Catan game page, find the `getRanking` request in DevTools → Network.
  Then run with `--game-id <the game=NNNN value>`.
- **A step returns nothing**: run with `--verbose`, open the printed URL in your logged-in browser, and compare the JSON with what the script expects.
  The parsing is deliberately tolerant, but BGA does rename things.
