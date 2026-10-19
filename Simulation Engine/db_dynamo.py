"""
db_dynamo.py - Amazon DynamoDB backend. Same interface as db_sqlite.py.

Tables (names get a prefix, default "p2p_"):
  p2p_meter   PK node (S)   SK slot (N = day*24+hour)   one item per home per hour (readings, P2P units, money)
  p2p_ledger  PK pk (S)="TX"  SK sk (S) "000012#A#B"      one item per seller->buyer transaction
  p2p_events  PK pk (S)="EVT" SK sk (S) "000012#<ns>"     live event log
  p2p_config  PK k (S)="state"                           engine state as JSON (houses, appliances, scenario, clock)
Writes are idempotent (same key = overwrite), so a replayed slot never double-counts.
Env: AWS_REGION (default: region from `aws configure`, else ap-south-1), DDB_TABLE_PREFIX (default p2p_), DDB_ENDPOINT (DynamoDB Local), credentials via
     `aws configure`, env vars, or an IAM role.
NOTE: "TX" / "EVT" are single partitions - perfectly fine at demo scale; shard by day/feeder for production.
"""
import json, os, time
from decimal import Decimal
import boto3
from boto3.dynamodb.conditions import Key

# order: AWS_REGION env var -> AWS_DEFAULT_REGION env var -> region saved by `aws configure` -> ap-south-1
REGION = (os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
          or boto3.session.Session().region_name or "ap-south-1")
print(f"[db] DynamoDB region: {REGION}")
PREFIX = os.environ.get("DDB_TABLE_PREFIX", "p2p_")
ENDPOINT = os.environ.get("DDB_ENDPOINT") or None

_ddb = boto3.resource("dynamodb", region_name=REGION, endpoint_url=ENDPOINT)
T_METER, T_LEDGER, T_EVENTS, T_CONFIG = PREFIX + "meter", PREFIX + "ledger", PREFIX + "events", PREFIX + "config"

SCHEMAS = {
    T_METER: [("node", "S", "HASH"), ("slot", "N", "RANGE")],
    T_LEDGER: [("pk", "S", "HASH"), ("sk", "S", "RANGE")],
    T_EVENTS: [("pk", "S", "HASH"), ("sk", "S", "RANGE")],
    T_CONFIG: [("k", "S", "HASH")],
}


def create_tables():
    existing = {t.name for t in _ddb.tables.all()}
    for name, keys in SCHEMAS.items():
        if name in existing: continue
        _ddb.create_table(
            TableName=name,
            AttributeDefinitions=[{"AttributeName": a, "AttributeType": t} for a, t, _ in keys],
            KeySchema=[{"AttributeName": a, "KeyType": k} for a, _, k in keys],
            BillingMode="PAY_PER_REQUEST")
        _ddb.Table(name).wait_until_exists()


create_tables()
_meter, _ledger, _events, _config = _ddb.Table(T_METER), _ddb.Table(T_LEDGER), _ddb.Table(T_EVENTS), _ddb.Table(T_CONFIG)


# ---- DynamoDB stores numbers as Decimal, so convert both ways ----
def _to_ddb(v):
    if isinstance(v, bool) or v is None: return v
    if isinstance(v, (int, float)): return Decimal(str(v))
    return v


def _from_ddb(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def _clean(item, drop=()):
    return {k: _from_ddb(v) for k, v in item.items() if k not in drop}


def _slot(r): return int(r["day"]) * 24 + int(r["hour"])


def _put(table, items):
    with table.batch_writer(overwrite_by_pkeys=[k["AttributeName"] for k in table.key_schema]) as b:
        for it in items: b.put_item(Item={k: _to_ddb(v) for k, v in it.items()})


def insert_meter(rows):
    _put(_meter, [{**r, "slot": _slot(r)} for r in rows])


def insert_ledger(rows):
    _put(_ledger, [{**r, "pk": "TX", "sk": f"{_slot(r):06d}#{r['seller']}#{r['buyer']}"} for r in rows])


def insert_events(rows):
    _put(_events, [{**r, "pk": "EVT", "sk": f"{_slot(r):06d}#{time.time_ns()}"} for r in rows])


def _query_all(table, cond, forward=True, limit=None):
    out, kwargs = [], dict(KeyConditionExpression=cond, ScanIndexForward=forward)
    if limit: kwargs["Limit"] = limit
    while True:
        r = table.query(**kwargs)
        out.extend(r["Items"])
        if limit and len(out) >= limit: return out[:limit]
        if "LastEvaluatedKey" not in r: return out
        kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]


def meter_rows(node, limit=None):
    if limit is None:
        items = _query_all(_meter, Key("node").eq(node), forward=True)
        return [_clean(i, ("slot",)) for i in items]
    items = _query_all(_meter, Key("node").eq(node), forward=False, limit=limit)
    return [_clean(i, ("slot",)) for i in items][::-1]


def ledger_all(limit=100):
    items = _query_all(_ledger, Key("pk").eq("TX"), forward=False, limit=limit)
    return [_clean(i, ("pk", "sk")) for i in items][::-1]


def events(limit=50):
    items = _query_all(_events, Key("pk").eq("EVT"), forward=False, limit=limit)
    return [_clean(i, ("pk", "sk", "slot")) for i in items]


def reset():
    for table in (_meter, _ledger, _events):
        keys = [k["AttributeName"] for k in table.key_schema]
        with table.batch_writer(overwrite_by_pkeys=keys) as b:
            for page in _scan_pages(table):
                for it in page: b.delete_item(Key={k: it[k] for k in keys})


def _scan_pages(table):
    kwargs = {}
    while True:
        r = table.scan(**kwargs)
        yield r["Items"]
        if "LastEvaluatedKey" not in r: return
        kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]


def save_config(state):
    """Persist the engine state so a restart continues where it stopped."""
    _config.put_item(Item={"k": "state", "v": json.dumps(state)})


def load_config():
    r = _config.get_item(Key={"k": "state"})
    return json.loads(r["Item"]["v"]) if "Item" in r else None


def clear_config():
    _config.delete_item(Key={"k": "state"})
