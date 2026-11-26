#!/usr/bin/env python3
"""
Board Game Arena scraper for Catan (or any other BGA game).

Uses your own logged-in browser session (cookie) to call the same internal
JSON endpoints the BGA website uses. Everything is stored in a local SQLite
database so the crawl can be stopped and resumed at any time.

Pipeline:
  seed     -> pull the game's leaderboard(s) into the player queue
  history  -> for each queued player, page through their game history
              (filtered to this game); every new table is saved and its other
              players are added to the queue ("snowball" crawl)
  logs     -> download the full move log of each saved table (this is the step
              limited by BGA's daily replay quota; just re-run it tomorrow)
  export   -> write CSVs for analysis
  status   -> show progress

Run `python bga_scraper.py --help` for options. See README.md.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import random
import re
import sqlite3
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    sys.exit("Missing dependency: pip install requests")

BASE = "https://boardgamearena.com"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


class BGAError(Exception):
    pass


class LimitReached(BGAError):
    """BGA refused because a quota (usually the daily replay limit) was hit."""


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# --------------------------------------------------------------------------
# HTTP client
# --------------------------------------------------------------------------
class BGA:
    def __init__(self, cookie: str, delay: float, verbose: bool = False):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA,
            "Cookie": cookie.strip(),
            "Referer": BASE + "/",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        })
        self.delay = delay
        self.verbose = verbose
        self._last = 0.0
        self.player_id = None

    def _throttle(self):
        wait = self.delay * random.uniform(0.8, 1.5) - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    def _request(self, path, params=None, xhr=True, retries=6):
        params = dict(params or {})
        headers = {"X-Requested-With": "XMLHttpRequest"} if xhr else {}
        if xhr:
            params.setdefault("dojo.preventCache", str(int(time.time() * 1000)))
        backoff = 10.0
        for attempt in range(1, retries + 1):
            self._throttle()
            try:
                r = self.s.get(BASE + path, params=params, headers=headers, timeout=45)
            except requests.RequestException as e:
                log(f"  network error ({e}); retry {attempt}/{retries} in {backoff:.0f}s")
                time.sleep(backoff); backoff *= 2
                continue
            if self.verbose:
                log("  GET", r.url, r.status_code)
            if r.status_code == 429 or r.status_code >= 500:
                log(f"  HTTP {r.status_code}; backing off {backoff:.0f}s")
                time.sleep(backoff); backoff *= 2
                continue
            if r.status_code != 200:
                raise BGAError(f"HTTP {r.status_code} for {r.url}")
            return r
        raise BGAError(f"giving up on {path} after {retries} attempts")

    def html(self, path, params=None) -> str:
        return self._request(path, params, xhr=False).text

    def json(self, path, params=None):
        r = self._request(path, params, xhr=True)
        try:
            j = r.json()
        except ValueError:
            snippet = r.text[:200].replace("\n", " ")
            raise BGAError(f"non-JSON response (session expired?): {snippet}")
        if isinstance(j, dict) and str(j.get("status")) == "1":
            return j.get("data")
        msg = json.dumps(j)[:400] if not isinstance(j, dict) else str(
            j.get("error") or j.get("message") or j)[:400]
        if re.search(r"limit|quota|too many|premium", msg, re.I):
            raise LimitReached(msg)
        raise BGAError(msg)

    # ---- session -------------------------------------------------------
    def init_session(self):
        """Load the homepage to grab the request token and check login."""
        page = self.html("/")
        m = re.search(r"requestToken['\"]?\s*[:=]\s*['\"]([A-Za-z0-9_\-]+)['\"]", page)
        if m:
            self.s.headers["X-Request-Token"] = m.group(1)
        m = re.search(r"current_player_id['\"]?\s*[:=]\s*['\"]?(\d+)", page)
        self.player_id = int(m.group(1)) if m else None
        if not self.player_id:
            log("WARNING: could not confirm you are logged in. If requests fail, "
                "re-copy your BGA cookie (see README).")
        else:
            log(f"Logged in as player id {self.player_id}")

    # ---- endpoints -----------------------------------------------------
    def resolve_game_id(self, game_name: str) -> int | None:
        page = self.html("/gamepanel", {"game": game_name})
        for pat in (r"[\"']?game_id[\"']?\s*[:=]\s*[\"']?(\d+)",
                    r"gameId[\"']?\s*[:=]\s*[\"']?(\d+)",
                    r"game_id=(\d+)",
                    r"getRanking\.html\?game=(\d+)"):
            m = re.search(pat, page)
            if m:
                return int(m.group(1))
        return None

    def ranking(self, game_id: int, start: int, mode: str):
        return self.json("/gamepanel/gamepanel/getRanking.html",
                         {"game": game_id, "start": start, "mode": mode})

    def game_history(self, player_id: int, game_id: int, page: int):
        return self.json("/gamestats/gamestats/getGames.html", {
            "player": player_id, "opponent_id": 0, "game_id": game_id,
            "finished": 1, "updateStats": 0, "page": page})

    def table_info(self, table_id: int):
        return self.json("/table/table/tableinfos.html", {"id": table_id})

    def table_logs(self, table_id: int):
        return self.json("/archive/archive/logs.html",
                         {"table": table_id, "translated": "true"})


# --------------------------------------------------------------------------
# Helpers for tolerant parsing (BGA's internal JSON is undocumented)
# --------------------------------------------------------------------------
def find_dict_list(obj, required_key):
    """Return the first list of dicts (anywhere in obj) whose items have key."""
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj) and required_key in obj[0]:
            return obj
        for x in obj:
            r = find_dict_list(x, required_key)
            if r is not None:
                return r
    elif isinstance(obj, dict):
        # dict keyed by id -> dict values
        vals = list(obj.values())
        if vals and all(isinstance(v, dict) for v in vals) and required_key in vals[0]:
            return vals
        for v in vals:
            r = find_dict_list(v, required_key)
            if r is not None:
                return r
    return None


def split_csv(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v]
    return [x.strip() for x in str(v).split(",")] if str(v) else []


def as_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def first(d, *keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY,
    name TEXT,
    elo REAL,
    games_played INTEGER,
    source TEXT,
    next_page INTEGER DEFAULT 1,
    history_done INTEGER DEFAULT 0,
    added_at REAL
);
CREATE TABLE IF NOT EXISTS tables (
    id INTEGER PRIMARY KEY,
    game_id INTEGER,
    game_name TEXT,
    start_ts INTEGER,
    end_ts INTEGER,
    normalend INTEGER,
    unranked INTEGER,
    concede INTEGER,
    arena INTEGER,
    n_players INTEGER,
    discovered_via INTEGER,
    raw TEXT,
    info_raw TEXT,
    log_status TEXT,
    log_path TEXT
);
CREATE TABLE IF NOT EXISTS table_players (
    table_id INTEGER,
    player_id INTEGER,
    name TEXT,
    rank INTEGER,
    score TEXT,
    PRIMARY KEY (table_id, player_id)
);
CREATE INDEX IF NOT EXISTS ix_players_queue ON players(history_done, elo);
CREATE INDEX IF NOT EXISTS ix_tables_log ON tables(log_status);
"""


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db


def meta_get(db, k):
    row = db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return row[0] if row else None


def meta_set(db, k, v):
    db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, str(v)))
    db.commit()


def add_player(db, pid, name=None, elo=None, games=None, source="opponent"):
    if not pid:
        return False
    cur = db.execute(
        "INSERT OR IGNORE INTO players (id, name, elo, games_played, source, added_at)"
        " VALUES (?,?,?,?,?,?)", (pid, name, elo, games, source, time.time()))
    if cur.rowcount == 0 and (elo is not None or name):
        db.execute("UPDATE players SET name=COALESCE(name,?), elo=COALESCE(?,elo),"
                   " games_played=COALESCE(?,games_played) WHERE id=?",
                   (name, elo, games, pid))
    return cur.rowcount > 0


def save_table(db, t: dict, via: int, snowball: bool) -> bool:
    tid = as_int(first(t, "table_id", "id", "table"))
    if not tid:
        return False
    if db.execute("SELECT 1 FROM tables WHERE id=?", (tid,)).fetchone():
        return False
    pids = split_csv(first(t, "players", "player_ids"))
    names = split_csv(first(t, "player_names", "names"))
    scores = split_csv(first(t, "scores", "score"))
    ranks = split_csv(first(t, "ranks", "rank"))
    db.execute(
        "INSERT INTO tables (id, game_id, game_name, start_ts, end_ts, normalend,"
        " unranked, concede, arena, n_players, discovered_via, raw)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (tid, as_int(t.get("game_id")), t.get("game_name"),
         as_int(t.get("start")), as_int(t.get("end")),
         as_int(t.get("normalend")), as_int(t.get("unranked")),
         as_int(t.get("concede")), 1 if t.get("arena_win") not in (None, "") else 0,
         len(pids) or None, via, json.dumps(t)))
    for i, pid in enumerate(pids):
        pid_i = as_int(pid)
        if not pid_i:
            continue
        name = names[i] if i < len(names) else None
        db.execute("INSERT OR IGNORE INTO table_players VALUES (?,?,?,?,?)",
                   (tid, pid_i, name,
                    as_int(ranks[i]) if i < len(ranks) else None,
                    scores[i] if i < len(scores) else None))
        if snowball:
            add_player(db, pid_i, name=name)
    return True


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------
def get_game_id(args, bga, db) -> int:
    if args.game_id:
        meta_set(db, "game_id", args.game_id)
        return args.game_id
    gid = meta_get(db, "game_id")
    if gid:
        return int(gid)
    log(f"Resolving numeric game id for '{args.game}' ...")
    gid = bga.resolve_game_id(args.game)
    if not gid:
        sys.exit("Could not find the game id automatically. Open the game's page on "
                 "BGA, watch DevTools > Network for 'getRanking' and pass its "
                 "game=NNNN value with --game-id NNNN.")
    log(f"Game id = {gid}")
    meta_set(db, "game_id", gid)
    return gid


def cmd_seed(args, bga, db):
    gid = get_game_id(args, bga, db)
    if bga.player_id:
        add_player(db, bga.player_id, source="me")
    for mode in args.modes:
        start, added, seen_ids = 0, 0, set()
        while start < args.top:
            try:
                data = bga.ranking(gid, start, mode)
            except BGAError as e:
                log(f"ranking ({mode}) stopped at {start}: {e}")
                break
            ranks = find_dict_list(data, "id") or []
            new_ids = {as_int(r.get("id")) for r in ranks} - seen_ids
            if not ranks or not new_ids:
                break
            for r in ranks:
                pid = as_int(r.get("id"))
                seen_ids.add(pid)
                added += add_player(
                    db, pid, name=first(r, "name", "fullname"),
                    elo=as_int(first(r, "ranking", "elo", "score")),
                    games=as_int(first(r, "nbr_game", "games", "nbr")),
                    source=f"leaderboard:{mode}")
            db.commit()
            start += len(ranks)
            log(f"leaderboard {mode}: {start} players read, {added} new")
    total = db.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    log(f"Seeding done. Players in queue: {total}")


def cmd_history(args, bga, db):
    gid = get_game_id(args, bga, db)
    t0 = db.execute("SELECT COUNT(*) FROM tables").fetchone()[0]
    players_done = 0
    while True:
        n_tables = db.execute("SELECT COUNT(*) FROM tables").fetchone()[0]
        if args.max_tables and n_tables >= args.max_tables:
            log(f"Reached --max-tables {args.max_tables}"); break
        if args.max_players and players_done >= args.max_players:
            log(f"Reached --max-players {args.max_players}"); break
        row = db.execute(
            "SELECT id, name, next_page FROM players WHERE history_done=0"
            " ORDER BY (elo IS NULL), elo DESC, added_at LIMIT 1").fetchone()
        if not row:
            log("Player queue empty."); break
        pid, name, page = row
        new_for_player = 0
        while True:
            if args.max_pages and page > args.max_pages:
                break
            try:
                data = bga.game_history(pid, gid, page)
            except LimitReached as e:
                log(f"Limit reached: {e}. Stopping; re-run later."); return
            except BGAError as e:
                log(f"  player {pid}: error on page {page}: {e}")
                break
            tabs = find_dict_list(data, "table_id") or []
            if not tabs:
                break
            for t in tabs:
                # Safety net in case BGA ignores the game filter.
                if as_int(t.get("game_id")) not in (None, gid):
                    continue
                new_for_player += save_table(db, t, via=pid, snowball=not args.no_snowball)
            page += 1
            db.execute("UPDATE players SET next_page=? WHERE id=?", (page, pid))
            db.commit()
            if len(tabs) < 10:  # BGA pages are 10 tables; short page = last page
                break
        db.execute("UPDATE players SET history_done=1, next_page=? WHERE id=?", (page, pid))
        db.commit()
        players_done += 1
        n_tables = db.execute("SELECT COUNT(*) FROM tables").fetchone()[0]
        queue = db.execute("SELECT COUNT(*) FROM players WHERE history_done=0").fetchone()[0]
        log(f"player {pid} ({name or '?'}): +{new_for_player} tables | "
            f"total tables {n_tables} | players left in queue {queue}")
    t1 = db.execute("SELECT COUNT(*) FROM tables").fetchone()[0]
    log(f"History done: {t1 - t0} new tables this run, {t1} total.")


def cmd_logs(args, bga, db):
    logdir = Path(args.data) / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    where = "log_status IS NULL"
    if not args.include_abandoned:
        where += " AND COALESCE(normalend,1)=1"
    if args.retry_errors:
        where = f"({where}) OR log_status LIKE 'error%'"
    # Prioritise games with strong players (avg elo of known participants).
    rows = db.execute(f"""
        SELECT t.id FROM tables t
        LEFT JOIN table_players tp ON tp.table_id=t.id
        LEFT JOIN players p ON p.id=tp.player_id
        WHERE {where}
        GROUP BY t.id
        ORDER BY AVG(p.elo) DESC, t.end_ts DESC
        LIMIT ?""", (args.max_logs,)).fetchall()
    log(f"{len(rows)} tables queued for log download")
    ok = 0
    for (tid,) in rows:
        try:
            if args.with_info:
                info = bga.table_info(tid)
                db.execute("UPDATE tables SET info_raw=? WHERE id=?", (json.dumps(info), tid))
            data = bga.table_logs(tid)
        except LimitReached as e:
            log(f"Replay limit reached after {ok} logs: {e}\n"
                "Run the 'logs' command again tomorrow; it resumes where it stopped.")
            break
        except BGAError as e:
            db.execute("UPDATE tables SET log_status=? WHERE id=?", (f"error: {e}"[:300], tid))
            db.commit()
            log(f"  table {tid}: {e}")
            continue
        path = logdir / f"{tid}.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(data, f)
        db.execute("UPDATE tables SET log_status='ok', log_path=? WHERE id=?",
                   (str(path), tid))
        db.commit()
        ok += 1
        if ok % 25 == 0:
            log(f"  {ok} logs downloaded")
    log(f"Logs done: {ok} downloaded this run.")


def cmd_export(args, bga, db):
    out = Path(args.data) / "export"
    out.mkdir(parents=True, exist_ok=True)
    for name, sql in {
        "tables.csv": "SELECT id, game_id, game_name, start_ts, end_ts, normalend,"
                      " unranked, concede, arena, n_players, log_status FROM tables",
        "table_players.csv": "SELECT table_id, player_id, name, rank, score FROM table_players",
        "players.csv": "SELECT id, name, elo, games_played, source, history_done FROM players",
    }.items():
        cur = db.execute(sql)
        with open(out / name, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([d[0] for d in cur.description])
            w.writerows(cur)
        log(f"wrote {out / name}")


def cmd_status(args, bga, db):
    q = lambda s: db.execute(s).fetchone()[0]
    print(f"game_id:               {meta_get(db, 'game_id')}")
    print(f"players known:         {q('SELECT COUNT(*) FROM players')}")
    print(f"  histories crawled:   {q('SELECT COUNT(*) FROM players WHERE history_done=1')}")
    print(f"tables (games) found:  {q('SELECT COUNT(*) FROM tables')}")
    print(f"  finished normally:   {q('SELECT COUNT(*) FROM tables WHERE normalend=1')}")
    n_ok = q("SELECT COUNT(*) FROM tables WHERE log_status='ok'")
    n_err = q("SELECT COUNT(*) FROM tables WHERE log_status LIKE 'error%'")
    print(f"  logs downloaded:     {n_ok}")
    print(f"  log errors:          {n_err}")


# --------------------------------------------------------------------------
def load_cookie(args) -> str:
    if args.cookie_file:
        return Path(args.cookie_file).read_text(encoding="utf-8").strip()
    c = os.environ.get("BGA_COOKIE")
    if c:
        return c
    default = Path(__file__).with_name("cookie.txt")
    if default.exists():
        return default.read_text(encoding="utf-8").strip()
    sys.exit("No BGA cookie found. Put it in cookie.txt next to this script, "
             "or set BGA_COOKIE, or pass --cookie-file. See README.md.")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["seed", "history", "logs", "export", "status", "all"])
    p.add_argument("--game", default="catan", help="BGA game slug (default: catan)")
    p.add_argument("--game-id", type=int, help="numeric BGA game id (auto-detected if omitted)")
    p.add_argument("--data", default="data", help="output folder (default: ./data)")
    p.add_argument("--cookie-file", help="file containing your BGA Cookie header")
    p.add_argument("--delay", type=float, default=2.0,
                   help="seconds between requests (default 2; please don't go lower)")
    p.add_argument("--verbose", action="store_true")
    # seed
    p.add_argument("--top", type=int, default=1000,
                   help="seed: how many leaderboard players to read per mode (default 1000)")
    p.add_argument("--modes", nargs="+", default=["elo"],
                   help="seed: leaderboard modes, e.g. elo arena (default: elo)")
    # history
    p.add_argument("--max-tables", type=int, default=0, help="history: stop after N tables")
    p.add_argument("--max-players", type=int, default=0,
                   help="history: stop after crawling N players this run")
    p.add_argument("--max-pages", type=int, default=0,
                   help="history: max pages (10 games each) per player; 0 = all")
    p.add_argument("--no-snowball", action="store_true",
                   help="history: don't add opponents to the queue")
    # logs
    p.add_argument("--max-logs", type=int, default=100000, help="logs: max per run")
    p.add_argument("--with-info", action="store_true",
                   help="logs: also fetch table info (options, settings) per table")
    p.add_argument("--include-abandoned", action="store_true",
                   help="logs: also fetch games that did not end normally")
    p.add_argument("--retry-errors", action="store_true", help="logs: retry failed tables")
    args = p.parse_args()

    db = open_db(Path(args.data) / "bga.sqlite")
    if args.command in ("export", "status"):
        {"export": cmd_export, "status": cmd_status}[args.command](args, None, db)
        return

    if args.delay < 1.0:
        log("Delay below 1s is not allowed (be kind to BGA); using 1s.")
        args.delay = 1.0
    bga = BGA(load_cookie(args), args.delay, args.verbose)
    bga.init_session()
    try:
        if args.command in ("seed", "all"):
            cmd_seed(args, bga, db)
        if args.command in ("history", "all"):
            cmd_history(args, bga, db)
        if args.command in ("logs", "all"):
            cmd_logs(args, bga, db)
        if args.command == "all":
            cmd_export(args, bga, db)
    except KeyboardInterrupt:
        log("Interrupted; progress is saved. Re-run the same command to resume.")
    finally:
        db.commit()
        db.close()


if __name__ == "__main__":
    main()
