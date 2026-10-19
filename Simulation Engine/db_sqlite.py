"""db_sqlite.py - SQLite backend (default, zero setup). Same interface as db_dynamo.py."""
import json, sqlite3, threading, os

_lock = threading.Lock()
_conn = sqlite3.connect(os.environ.get("SQLITE_PATH", "p2p.db"), check_same_thread=False)
_conn.row_factory = sqlite3.Row

SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger(day INT, hour INT, seller TEXT, buyer TEXT, kwh REAL, price REAL,
                                  amount REAL, grid_fee REAL, mode TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS meter(day INT, hour INT, node TEXT, load REAL, solar REAL, role TEXT,
                                 pred_load REAL, pred_solar REAL, planned_p2p REAL, p2p_bought REAL,
                                 p2p_sold REAL, grid_import REAL, grid_export REAL, batt_charge REAL,
                                 soc REAL, feeder TEXT, p2p_earned_rs REAL, p2p_owed_rs REAL, grid_fee_rs REAL,
                                 unserved REAL, curtailed REAL, benefit_rs REAL);
CREATE TABLE IF NOT EXISTS events(day INT, hour INT, text TEXT);
CREATE TABLE IF NOT EXISTS config(k TEXT PRIMARY KEY, v TEXT);
CREATE INDEX IF NOT EXISTS ix_meter_node ON meter(node, day, hour);
"""
with _lock:
    _conn.executescript(SCHEMA)
    # A p2p.db created by an older version has old columns; CREATE TABLE IF NOT EXISTS would not fix it.
    _cols = {r[1] for r in _conn.execute("PRAGMA table_info(meter)")}
    if "benefit_rs" not in _cols:
        for _t in ("meter", "ledger", "events"):             # config table is kept
            _conn.execute(f"DROP TABLE IF EXISTS {_t}")
        _conn.executescript(SCHEMA)
        print("[db] old p2p.db schema detected -> tables recreated (old demo data cleared)")


def _insert(table, rows):
    if not rows: return
    cols = list(rows[0].keys())
    q = f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))})"
    with _lock:
        _conn.executemany(q, [tuple(r[c] for c in cols) for r in rows])
        _conn.commit()


def _query(sql, args=()):
    with _lock:
        return [dict(r) for r in _conn.execute(sql, args).fetchall()]


def insert_meter(rows): _insert("meter", rows)
def insert_ledger(rows): _insert("ledger", rows)
def insert_events(rows): _insert("events", rows)


def meter_rows(node, limit=None):
    """Rows of one node, OLDEST first. limit -> only the latest `limit` rows."""
    if limit is None:
        return _query("SELECT * FROM meter WHERE node=? ORDER BY day, hour", (node,))
    return _query("SELECT * FROM meter WHERE node=? ORDER BY day DESC, hour DESC LIMIT ?", (node, limit))[::-1]


def ledger_all(limit=100):
    """Latest `limit` P2P transactions, OLDEST first."""
    return _query("SELECT * FROM ledger ORDER BY day DESC, hour DESC, seller DESC, buyer DESC LIMIT ?", (limit,))[::-1]


def events(limit=50):
    """Latest events, NEWEST first."""
    return _query("SELECT * FROM events ORDER BY rowid DESC LIMIT ?", (limit,))


def reset():
    with _lock:
        for t in ("ledger", "meter", "events"):
            _conn.execute(f"DELETE FROM {t}")
        _conn.commit()


def save_config(state):
    """Persist the engine state (houses, appliances, scenario, settings, clock) so a restart continues where it stopped."""
    with _lock:
        _conn.execute("INSERT OR REPLACE INTO config(k, v) VALUES('state', ?)", (json.dumps(state),))
        _conn.commit()


def load_config():
    rows = _query("SELECT v FROM config WHERE k='state'")
    return json.loads(rows[0]["v"]) if rows else None


def clear_config():
    with _lock:
        _conn.execute("DELETE FROM config")
        _conn.commit()
