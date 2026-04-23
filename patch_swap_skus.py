#!/usr/bin/env python3
"""
patch_swap_skus.py — swap the two noisy problem SKUs for high-volume replacements.

Removes elevated returns for:
  AL-BTM-0003-NAV-M  (revert to 20% baseline)
  AL-OUT-0001-GRY-XL (revert to 20% baseline)

Adds elevated returns for:
  AL-TOP-0002-BLK-M  (30% — Ribbed Tank)
  AL-DRS-0005-PNK-XXL (30% — Maxi Linen)

The three existing good problem SKUs are untouched.
"""

import os, random
from datetime import datetime, timedelta, date, timezone
from uuid import uuid4
import psycopg2
from psycopg2.extras import execute_values, RealDictCursor
from dotenv import load_dotenv

load_dotenv()

TENANT_ID = "00000000-0000-0000-0000-000000000001"
END_DATE  = date(2026, 4, 23)
RNG       = random.Random(55)

# Rates
RATE_HIGH     = 0.30
RATE_BASELINE = 0.20

# SKUs being touched
OLD_NOISY  = ["AL-BTM-0003-NAV-M", "AL-OUT-0001-GRY-XL"]
NEW_PROBLEM = ["AL-TOP-0002-BLK-M", "AL-DRS-0005-PNK-XXL"]
ALL_TOUCHED = OLD_NOISY + NEW_PROBLEM

# Lag distribution (3-21 days, peak 7-10) — matches seed_data
_LAG_DAYS    = list(range(3, 22))
_LAG_WEIGHTS = [1, 2, 4, 6, 10, 12, 12, 10, 8, 6, 5, 4, 3, 2, 2, 2, 1, 1, 1]

RETURN_REASONS_HIGH = ["Too small", "Too large", "Not as described", "Faulty/damaged"]
RETURN_REASONS_BASE = [
    "Too small", "Too large", "Not as described", "Faulty/damaged",
    "Changed mind", "Wrong item received", "Poor quality", "Arrived too late",
]

RETURN_GRADES      = {"Good": "A", "Fair": "B", "Poor": "C", "Damaged": "D"}
RETURN_DISPOSITIONS = {"A": "Restock", "B": "Restock", "C": "Clearance", "D": "Write Off"}
OP_LOOKUP          = {
    "OP-014": "Jack Wilson",
    "OP-020": "Ingrid Svensson",
    "OP-035": "Connor Daly",
}


def get_conn():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        sslmode="require",
        connect_timeout=30,
        options="-c statement_timeout=120000",
    )

def uid(): return str(uuid4())


def patch(conn):
    now = datetime.now(timezone.utc)

    # ── Step 1: delete existing returns for all 4 affected SKUs ───────────────
    with conn.cursor() as cur:
        cur.execute("""
            DELETE FROM return_events re
            USING returns r
            WHERE re.tenant_id = r.tenant_id
              AND re.return_number = r.return_number
              AND r.tenant_id = %s
              AND r.sku = ANY(%s)
        """, (TENANT_ID, ALL_TOUCHED))
        cur.execute("""
            DELETE FROM returns
            WHERE tenant_id = %s AND sku = ANY(%s)
        """, (TENANT_ID, ALL_TOUCHED))
    conn.commit()
    print(f"  Deleted existing returns for {ALL_TOUCHED}")

    # ── Step 2: get a counter baseline so new RET numbers don't collide ───────
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COALESCE(MAX(CAST(SUBSTRING(return_number FROM 5) AS INTEGER)), 0)
            FROM returns WHERE tenant_id = %s
        """, (TENANT_ID,))
        counter = cur.fetchone()[0]
    print(f"  Starting return counter at {counter:,}")

    # ── Step 3: query dispatched order lines for all 4 SKUs ───────────────────
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT ol.order_number, ol.sku,
                   ol.qty_ordered, ol.unit_price_gbp, ol.total_line_value_gbp,
                   o.dispatch_date, o.customer_name, o.customer_email
            FROM   order_lines ol
            JOIN   orders o ON o.tenant_id=ol.tenant_id
                           AND o.order_number=ol.order_number
            WHERE  ol.tenant_id = %s
            AND    ol.sku = ANY(%s)
            AND    o.status = 'Dispatched'
            AND    o.dispatch_date IS NOT NULL
            ORDER  BY o.dispatch_date
        """, (TENANT_ID, ALL_TOUCHED))
        lines = cur.fetchall()

    print(f"  Found {len(lines):,} dispatched lines across 4 SKUs.")

    # ── Step 4: roll returns ───────────────────────────────────────────────────
    returns_list = []
    events_list  = []

    for row in lines:
        sku         = row["sku"]
        is_elevated = sku in NEW_PROBLEM
        rate        = RATE_HIGH if is_elevated else RATE_BASELINE

        if RNG.random() > rate:
            continue

        lag    = RNG.choices(_LAG_DAYS, weights=_LAG_WEIGHTS)[0]
        ret_dt = row["dispatch_date"] + timedelta(days=lag)
        if ret_dt.date() > END_DATE:
            continue

        counter   += 1
        ret_num    = f"RET-{counter:08d}"
        reason     = RNG.choice(RETURN_REASONS_HIGH if is_elevated else RETURN_REASONS_BASE)
        cond       = RNG.choice(["Fair", "Poor", "Damaged"] if is_elevated
                                else ["Good", "Good", "Fair"])
        grade      = RETURN_GRADES[cond]
        disp       = RETURN_DISPOSITIONS[grade]
        proc_op    = RNG.choice(["OP-014", "OP-020", "OP-035"])
        proc_name  = OP_LOOKUP[proc_op]

        returns_list.append({
            "id":                     uid(),
            "tenant_id":              TENANT_ID,
            "return_number":          ret_num,
            "original_order_number":  row["order_number"],
            "return_date":            ret_dt,
            "sku":                    sku,
            "item_name":              sku,
            "qty_returned":           row["qty_ordered"],
            "return_reason":          reason,
            "item_condition":         cond,
            "grade":                  grade,
            "grade_description":      cond,
            "disposition":            disp,
            "processing_bay":         f"RET-BAY-{RNG.randint(1,6)}",
            "processing_operator_id": proc_op,
            "processing_minutes":     RNG.randint(5, 25),
            "status":                 "Processed",
            "customer_name":          row["customer_name"],
            "customer_email":         row["customer_email"],
            "refund_amount_gbp":      row["total_line_value_gbp"],
            "tracking_number":        None,
            "synced_at":              now,
        })
        for evt_type, offset_h in [("Registered",0),("Received",4),("Graded",6),("Processed",8)]:
            events_list.append({
                "id":            uid(),
                "tenant_id":     TENANT_ID,
                "return_number": ret_num,
                "event_type":    evt_type,
                "event_at":      ret_dt + timedelta(hours=offset_h),
                "operator_id":   proc_op,
                "operator_name": proc_name,
                "notes":         None,
                "synced_at":     now,
            })

    # ── Step 5: insert ─────────────────────────────────────────────────────────
    def bulk_insert(cur, table, rows, conflict_cols):
        if not rows:
            return
        cols   = list(rows[0].keys())
        values = [[r[c] for c in cols] for r in rows]
        tmpl   = "(" + ", ".join(["%s"] * len(cols)) + ")"
        sql    = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s "
                  f"ON CONFLICT ({', '.join(conflict_cols)}) DO NOTHING")
        execute_values(cur, sql, values, template=tmpl, page_size=500)

    with conn.cursor() as cur:
        bulk_insert(cur, "returns",       returns_list, ["tenant_id","return_number"])
        bulk_insert(cur, "return_events", events_list,  ["id"])
    conn.commit()

    print(f"  Inserted {len(returns_list):,} returns, {len(events_list):,} events.")
    print(f"  Breakdown by SKU:")
    from collections import Counter
    counts = Counter(r["sku"] for r in returns_list)
    for sku in ALL_TOUCHED:
        print(f"    {sku:<30} {counts.get(sku, 0):>4} returns")


if __name__ == "__main__":
    conn = get_conn()
    patch(conn)
    conn.close()
    print("Patch complete.")
