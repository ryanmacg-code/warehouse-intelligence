#!/usr/bin/env python3
"""
patch_fixes.py — four targeted patches to the 90-day seed
Run once. Safe to re-run (deletes before re-inserting).

Fix 1: Populate packing_stations snapshot (8 stations)
Fix 2: Add bulk + store inventory (schema change + new rows)
Fix 3: Regenerate returns with 20% baseline (was 5%)
Fix 4: Regenerate cycle count adjustments at 35/day (was 15)
"""

import os, random
from datetime import datetime, date, timedelta, timezone
from uuid import uuid4
import psycopg2
from psycopg2.extras import execute_values, RealDictCursor
from dotenv import load_dotenv

load_dotenv()

TENANT_ID  = "00000000-0000-0000-0000-000000000001"
RNG        = random.Random(77)          # independent seed for patch data
END_DATE   = date(2026, 4, 23)
START_DATE = date(2026, 1, 24)

NEW_JOINER_ID   = "OP-041"
NEW_JOINER_HIRE = date(2026, 3, 12)

REPLEN_DELAYED_SKUS = [
    "AL-TOP-0005-BLK-S",
    "AL-TOP-0006-BLK-M",
    "AL-DRS-0007-BLU-S",
]


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

def upsert(cur, table, rows, conflict_cols):
    if not rows:
        return
    cols     = list(rows[0].keys())
    values   = [[r[c] for c in cols] for r in rows]
    tmpl     = "(" + ", ".join(["%s"] * len(cols)) + ")"
    conflict = ", ".join(conflict_cols)
    sql      = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s "
                f"ON CONFLICT ({conflict}) DO NOTHING")
    execute_values(cur, sql, values, template=tmpl, page_size=500)


# ── Fix 1: packing_stations snapshot ──────────────────────────────────────────

def fix_packing_stations(conn):
    now = datetime.now(timezone.utc)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("DELETE FROM packing_stations WHERE tenant_id = %s", (TENANT_ID,))

        # Pull today's AM sessions for the 6 active stations
        cur.execute("""
            SELECT station_id, operator_id, operator_name, shift, shift_start,
                   orders_packed, units_packed, avg_pack_time_secs, errors,
                   void_fill_bags_used, labels_printed
            FROM   packing_station_sessions
            WHERE  tenant_id    = %s
            AND    session_date = '2026-04-23'
            AND    shift        = 'AM'
            AND    station_id  IN ('PS-01','PS-02','PS-03','PS-04','PS-05','PS-06')
            ORDER  BY station_id
        """, (TENANT_ID,))
        sessions = cur.fetchall()

    snapshot_rows = []
    for s in sessions:
        last_activity = (s["shift_start"] + timedelta(
            seconds=int(s["orders_packed"]) * int(s["avg_pack_time_secs"] or 120)
        )) if s["shift_start"] else now

        snapshot_rows.append({
            "id":                 uid(),
            "tenant_id":          TENANT_ID,
            "station_id":         s["station_id"],
            "operator_id":        s["operator_id"],
            "operator_name":      s["operator_name"],
            "shift":              s["shift"],
            "shift_start":        s["shift_start"],
            "status":             "Active",
            "orders_packed_today": s["orders_packed"],
            "units_packed_today":  s["units_packed"],
            "avg_pack_time_secs":  s["avg_pack_time_secs"],
            "last_order_packed":   None,
            "last_activity":       last_activity,
            "void_fill_bags_used": s["void_fill_bags_used"],
            "labels_printed":      s["labels_printed"],
            "errors_today":        s["errors"],
            "synced_at":           now,
        })

    # PS-07: Maintenance  PS-08: Idle
    for station_id, status in [("PS-07", "Maintenance"), ("PS-08", "Idle")]:
        snapshot_rows.append({
            "id": uid(), "tenant_id": TENANT_ID,
            "station_id": station_id, "operator_id": None,
            "operator_name": None, "shift": None, "shift_start": None,
            "status": status,
            "orders_packed_today": 0, "units_packed_today": 0,
            "avg_pack_time_secs": None, "last_order_packed": None,
            "last_activity": None, "void_fill_bags_used": None,
            "labels_printed": None, "errors_today": 0,
            "synced_at": now,
        })

    with conn.cursor() as cur:
        upsert(cur, "packing_stations", snapshot_rows, ["tenant_id", "station_id"])
    conn.commit()
    print(f"  Inserted {len(snapshot_rows)} packing station rows "
          f"(6 Active/Idle/Maintenance).")


# ── Fix 2: multi-site inventory ────────────────────────────────────────────────

def fix_inventory_multisite(conn):
    now = datetime.now(timezone.utc)

    # ── 2a. Change unique constraint so multi-site rows are allowed ────────────
    with conn.cursor() as cur:
        # Find and drop the old single-column unique constraint
        cur.execute("""
            SELECT constraint_name
            FROM   information_schema.table_constraints
            WHERE  table_name       = 'inventory'
            AND    constraint_type  = 'UNIQUE'
            AND    constraint_name  LIKE '%sku%'
            AND    constraint_name  NOT LIKE '%site%'
        """)
        old_constraints = [r[0] for r in cur.fetchall()]

    with conn.cursor() as cur:
        for name in old_constraints:
            cur.execute(f"ALTER TABLE inventory DROP CONSTRAINT IF EXISTS {name}")
            print(f"  Dropped constraint: {name}")
        cur.execute("""
            ALTER TABLE inventory
            ADD CONSTRAINT inventory_tenant_id_sku_site_key
            UNIQUE (tenant_id, sku, site)
        """)
    conn.commit()
    print("  Added constraint: inventory_tenant_id_sku_site_key")

    # ── 2b. Build bulk inventory (3–4.5× pickface, high on replen-delayed SKUs) ─
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT sku, style_code, style_name, colour, size, size_type,
                   category, barcode, weight_kg, selling_price_gbp,
                   available_qty, on_order_qty, reorder_point
            FROM   inventory
            WHERE  tenant_id = %s AND site = 'pickface'
        """, (TENANT_ID,))
        pickface = cur.fetchall()

    bulk_rows = []
    for p in pickface:
        sku      = p["sku"]
        if sku in REPLEN_DELAYED_SKUS:
            avail = RNG.randint(200, 500)   # plentiful in bulk — delay is the story
        else:
            avail = int((p["available_qty"] or 0) * RNG.uniform(3.0, 4.5))

        zone = RNG.choice(["A", "B", "C", "D"])
        loc  = f"BULK-{zone}-{RNG.randint(1,25):03d}"

        bulk_rows.append({
            "id":                 uid(),
            "tenant_id":          TENANT_ID,
            "sku":                sku,
            "style_code":         p["style_code"],
            "style_name":         p["style_name"],
            "colour":             p["colour"],
            "size":               p["size"],
            "size_type":          p["size_type"],
            "category":           p["category"],
            "barcode":            p["barcode"],
            "weight_kg":          p["weight_kg"],
            "selling_price_gbp":  p["selling_price_gbp"],
            "available_qty":      avail,
            "allocated_qty":      0,
            "on_order_qty":       p["on_order_qty"],
            "primary_location":   loc,
            "reorder_point":      p["reorder_point"],
            "site":               "bulk",
            "synced_at":          now,
        })

    with conn.cursor() as cur:
        upsert(cur, "inventory", bulk_rows, ["tenant_id", "sku", "site"])
    conn.commit()
    print(f"  Bulk inventory: {len(bulk_rows):,} rows inserted.")

    # ── 2c. Store inventory — top 500 SKUs by order frequency, 5 stores ────────
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT ol.sku
            FROM   order_lines ol
            WHERE  ol.tenant_id = %s
            GROUP  BY ol.sku
            ORDER  BY COUNT(*) DESC
            LIMIT  500
        """, (TENANT_ID,))
        top_skus = [r["sku"] for r in cur.fetchall()]

        cur.execute("""
            SELECT sku, style_code, style_name, colour, size, size_type,
                   category, barcode, weight_kg, selling_price_gbp, reorder_point
            FROM   inventory
            WHERE  tenant_id = %s AND site = 'pickface' AND sku = ANY(%s)
        """, (TENANT_ID, top_skus))
        sku_data = {r["sku"]: r for r in cur.fetchall()}

    store_rows = []
    for store_num in range(1, 6):
        site = f"store_{store_num:02d}"
        for sku in top_skus:
            if sku not in sku_data:
                continue
            p   = sku_data[sku]
            loc = f"STORE-{store_num:02d}-{RNG.randint(1,20):02d}"
            store_rows.append({
                "id":                uid(),
                "tenant_id":         TENANT_ID,
                "sku":               sku,
                "style_code":        p["style_code"],
                "style_name":        p["style_name"],
                "colour":            p["colour"],
                "size":              p["size"],
                "size_type":         p["size_type"],
                "category":          p["category"],
                "barcode":           p["barcode"],
                "weight_kg":         p["weight_kg"],
                "selling_price_gbp": p["selling_price_gbp"],
                "available_qty":     RNG.randint(2, 20),
                "allocated_qty":     0,
                "on_order_qty":      0,
                "primary_location":  loc,
                "reorder_point":     max(2, (p["reorder_point"] or 4) // 4),
                "site":              site,
                "synced_at":         now,
            })

    with conn.cursor() as cur:
        upsert(cur, "inventory", store_rows, ["tenant_id", "sku", "site"])
    conn.commit()
    print(f"  Store inventory: {len(store_rows):,} rows inserted "
          f"(500 SKUs × 5 stores).")


# ── Fix 3: returns — baseline 20% ─────────────────────────────────────────────

def fix_returns(conn):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM return_events WHERE tenant_id = %s", (TENANT_ID,))
        cur.execute("DELETE FROM returns       WHERE tenant_id = %s", (TENANT_ID,))
    conn.commit()
    print("  Existing returns deleted.")

    # seed_data.py now has RETURN_RATE_BASE=0.20 — import fresh
    import importlib, seed_data as sd
    importlib.reload(sd)
    sd.seed_returns(conn)


# ── Fix 4: cycle counts — 35/day ──────────────────────────────────────────────

def fix_cycle_counts(conn):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM stock_adjustments WHERE tenant_id = %s", (TENANT_ID,))
    conn.commit()
    print("  Existing stock adjustments deleted.")

    import importlib, seed_data as sd
    importlib.reload(sd)

    # Build minimal skus list from DB (band not needed, just sku string)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT sku FROM inventory WHERE tenant_id=%s AND site='pickface'",
                    (TENANT_ID,))
        skus = [{"sku": r["sku"]} for r in cur.fetchall()]

    all_adjs = []
    total = 0
    for i in range(90):
        d    = END_DATE - timedelta(days=89 - i)
        adjs = sd.build_stock_adjustments_for_day(d, skus)
        all_adjs.extend(adjs)
        total += len(adjs)

    with conn.cursor() as cur:
        upsert(cur, "stock_adjustments", all_adjs, ["tenant_id","adjustment_number"])
    conn.commit()
    print(f"  {total:,} stock adjustments inserted ({total//90} per day across 90 days).")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    conn = get_conn()

    print("Fix 1: packing_stations snapshot...")
    fix_packing_stations(conn)

    print("Fix 2: multi-site inventory...")
    fix_inventory_multisite(conn)

    print("Fix 3: returns (baseline 20%)...")
    fix_returns(conn)

    print("Fix 4: cycle counts (35/day)...")
    fix_cycle_counts(conn)

    conn.close()
    print("All fixes applied.")


if __name__ == "__main__":
    main()
