"""db.py - tiny SQLite store so the website can query ledger / meter history (swap for DynamoDB on AWS)."""
import sqlite3, threading

_lock = threading.Lock()
_conn = sqlite3.connect("p2p.db", check_same_thread=False)
_conn.row_factory = sqlite3.Row

SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger(day INT, hour INT, seller TEXT, buyer TEXT, kwh REAL, price REAL,
                                  amount REAL, grid_fee REAL, mode TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS meter(day INT, hour INT, node TEXT, load REAL, solar REAL, role TEXT,
                                 pred_load REAL, pred_solar REAL, planned_p2p REAL, p2p_bought REAL,
                                 p2p_sold REAL, grid_import REAL, grid_export REAL, batt_charge REAL,
                                 soc REAL, feeder TEXT);
CREATE TABLE IF NOT EXISTS events(day INT, hour INT, text TEXT);
CREATE INDEX IF NOT EXISTS ix_meter_node ON meter(node, day, hour);
"""
with _lock:
    _conn.executescript(SCHEMA)


def insert_many(table, rows):
    if not rows: return
    cols = list(rows[0].keys())
    q = f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))})"
    with _lock:
        _conn.executemany(q, [tuple(r[c] for c in cols) for r in rows])
        _conn.commit()


def query(sql, args=()):
    with _lock:
        return [dict(r) for r in _conn.execute(sql, args).fetchall()]


def reset():
    with _lock:
        for t in ("ledger", "meter", "events"):
            _conn.execute(f"DELETE FROM {t}")
        _conn.commit()
