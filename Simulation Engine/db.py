"""
db.py - picks the storage backend. The rest of the code only imports `db`.
  DB_BACKEND=sqlite    (default) local file p2p.db, no setup
  DB_BACKEND=dynamodb  Amazon DynamoDB (see AWS_DYNAMODB_SETUP.md)
"""
import os

BACKEND = os.environ.get("DB_BACKEND", "sqlite").lower()
if BACKEND == "dynamodb":
    from db_dynamo import *          # noqa: F401,F403
else:
    from db_sqlite import *          # noqa: F401,F403


def statement_totals(node):
    """Totals for one node, computed from its meter rows (works identically on every backend)."""
    rows = meter_rows(node)
    s = lambda k: sum(r.get(k, 0) or 0 for r in rows)
    return dict(discom_import_kwh=round(s("grid_import"), 2), discom_export_kwh=round(s("grid_export"), 2),
                p2p_sold_kwh=round(s("p2p_sold"), 2), p2p_earned_rs=round(s("p2p_earned_rs"), 2),
                p2p_bought_kwh=round(s("p2p_bought"), 2), p2p_owed_rs=round(s("p2p_owed_rs"), 2),
                grid_fee_on_discom_bill_rs=round(s("grid_fee_rs"), 2),
                p2p_benefit_rs=round(s("benefit_rs"), 2), unserved_kwh=round(s("unserved"), 2),
                total_load_kwh=round(s("load"), 2), total_solar_kwh=round(s("solar"), 2))
