#!/usr/bin/env python3
"""
seed_data.py — Aria London warehouse data seeder
Generates realistic operational data directly into Supabase.

Usage:
  python seed_data.py --days 1      # 1-day test (default)
  python seed_data.py --days 90     # full 90-day dataset
  python seed_data.py --wipe        # truncate all seeded tables first
  python seed_data.py --days 90 --wipe
"""

import os, sys, random, math, argparse
from datetime import datetime, timedelta, date, time, timezone
from uuid import uuid4
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv()

# ── Connection ─────────────────────────────────────────────────────────────────

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

# ── Global constants ───────────────────────────────────────────────────────────

TENANT_ID  = "00000000-0000-0000-0000-000000000001"
RNG        = random.Random(42)

# "Today" for the seed — the end of the 90-day window
END_DATE   = date(2026, 4, 23)
START_DATE = END_DATE - timedelta(days=89)   # 90 days inclusive

# New joiner — hired 6 weeks (42 days) before end
NEW_JOINER_ID       = "OP-041"
NEW_JOINER_NAME     = "Callum Osei"
NEW_JOINER_HIRE     = END_DATE - timedelta(weeks=6)   # 2026-03-12

ORDERS_PER_DAY      = 1_000
RETURN_RATE_BASE    = 0.20
RETURN_RATE_HIGH    = 0.30

# ── Seeded problem SKUs ────────────────────────────────────────────────────────

# Problem 1 — high-return SKUs (sizing/quality issues)
HIGH_RETURN_SKUS = [
    "AL-TOP-0001-BLK-XS",    # Classic Tee — sizing complaints
    "AL-DRS-0002-RED-S",     # Midi Wrap — colour not as pictured
    "AL-TOP-0002-BLK-M",     # Ribbed Tank — fabric quality
    "AL-TOP-0004-WHT-L",     # Oxford Shirt — sizing complaints
    "AL-DRS-0005-PNK-XXL",   # Maxi Linen — fit/sizing
]

# Return lag distribution — peak at 7–10 days, range 3–21
# Indices correspond to lag days 3, 4, 5, ..., 21
_LAG_DAYS    = list(range(3, 22))
_LAG_WEIGHTS = [1, 2, 4, 6, 10, 12, 12, 10, 8, 6, 5, 4, 3, 2, 2, 2, 1, 1, 1]

# Problem 2 — replenishment-delayed A-band SKUs (frequent pickface OOS)
REPLEN_DELAYED_SKUS = [
    "AL-TOP-0005-BLK-S",
    "AL-TOP-0006-BLK-M",
    "AL-DRS-0007-BLU-S",
]

# ── Master-data builders ───────────────────────────────────────────────────────

OPERATOR_NAMES = [
    # Day shift (OP-001 – OP-020)
    ("OP-001","Sarah Mitchell","Picker","AM"),
    ("OP-002","James O'Brien","Picker","AM"),
    ("OP-003","Priya Patel","Packer","AM"),
    ("OP-004","Marcus Thompson","Packer","AM"),
    ("OP-005","Fatima Al-Rashid","Team Leader","AM"),
    ("OP-006","Daniel Hughes","Picker","AM"),
    ("OP-007","Amara Okonkwo","Picker","AM"),
    ("OP-008","Tom Greenfield","Packer","AM"),
    ("OP-009","Zoe Chambers","Packer","AM"),
    ("OP-010","Ravi Sharma","Goods In","AM"),
    ("OP-011","Claire Donovan","Picker","AM"),
    ("OP-012","Kwame Asante","Picker","AM"),
    ("OP-013","Emma Larsson","Packer","AM"),
    ("OP-014","Jack Wilson","Returns","AM"),
    ("OP-015","Nadia Hassan","Picker","AM"),
    ("OP-016","Ben Cartwright","Goods In","AM"),
    ("OP-017","Yemi Adeyemi","Picker","AM"),
    ("OP-018","Lucy Park","Packer","AM"),
    ("OP-019","Oliver Byrne","Team Leader","AM"),
    ("OP-020","Ingrid Svensson","Returns","AM"),
    # Back shift (OP-021 – OP-040)
    ("OP-021","Tariq Mahmood","Picker","PM"),
    ("OP-022","Sophie Ellis","Picker","PM"),
    ("OP-023","Kofi Mensah","Packer","PM"),
    ("OP-024","Hannah Brooks","Packer","PM"),
    ("OP-025","Deon Petersen","Team Leader","PM"),
    ("OP-026","Chioma Eze","Picker","PM"),
    ("OP-027","Aleksei Volkov","Picker","PM"),
    ("OP-028","Moira Flanagan","Packer","PM"),
    ("OP-029","Samuel Osei","Picker","PM"),
    ("OP-030","Anya Kowalski","Packer","PM"),
    ("OP-031","Liam Brennan","Goods In","PM"),
    ("OP-032","Mei-Lin Chen","Picker","PM"),
    ("OP-033","Tobias Richter","Picker","PM"),
    ("OP-034","Adaeze Nwosu","Packer","PM"),
    ("OP-035","Connor Daly","Returns","PM"),
    ("OP-036","Hana Nakamura","Picker","PM"),
    ("OP-037","Freddie Osei","Picker","PM"),
    ("OP-038","Latoya Grant","Packer","PM"),
    ("OP-039","Ewan Fraser","Team Leader","PM"),
    ("OP-040","Beatriz Santos","Picker","PM"),
    # New joiner — starts NEW_JOINER_HIRE
    ("OP-041","Callum Osei","Picker","AM"),
]

PICKERS_AM = [o[0] for o in OPERATOR_NAMES if o[3]=="AM" and o[2]=="Picker"]
PICKERS_PM = [o[0] for o in OPERATOR_NAMES if o[3]=="PM" and o[2]=="Picker"]
PACKERS_AM = [o[0] for o in OPERATOR_NAMES if o[3]=="AM" and o[2]=="Packer"]
PACKERS_PM = [o[0] for o in OPERATOR_NAMES if o[3]=="PM" and o[2]=="Packer"]
OP_LOOKUP  = {o[0]: o[1] for o in OPERATOR_NAMES}

CATEGORIES = ["Tops","Dresses","Bottoms","Outerwear","Accessories"]
COLOURS    = ["BLK","WHT","NAV","RED","GRY","BLU","GRN","PNK","CRM","TAN"]
SIZES      = ["XS","S","M","L","XL","XXL"]
SIZE_TYPES = {"Tops":"Apparel","Dresses":"Apparel","Bottoms":"Apparel",
              "Outerwear":"Apparel","Accessories":"One Size"}

CAT_PREFIXES = {"Tops":"TOP","Dresses":"DRS","Bottoms":"BTM",
                "Outerwear":"OUT","Accessories":"ACC"}

STYLE_NAMES = {
    "Tops":["Classic Tee","Ribbed Tank","Wrap Blouse","Oxford Shirt","Linen Top",
            "Cropped Knit","Puff Sleeve Blouse","Fitted Cami","Utility Top","Sheer Blouse"],
    "Dresses":["Slip Dress","Midi Wrap","Shirt Dress","Mini A-Line","Maxi Linen",
               "Bodycon Dress","Floral Tea Dress","Denim Dress","Knit Dress","Pleated Midi"],
    "Bottoms":["Slim Jeans","Wide Leg Trousers","Mini Skirt","Midi Skirt","Cargo Pants",
               "Tailored Shorts","Pleated Trousers","Denim Shorts","Leggings","Joggers"],
    "Outerwear":["Trench Coat","Padded Jacket","Blazer","Denim Jacket","Wool Coat",
                 "Raincoat","Leather Jacket","Bomber Jacket","Cardigan","Gilet"],
    "Accessories":["Canvas Tote","Leather Belt","Silk Scarf","Baseball Cap","Knit Beanie",
                   "Crossbody Bag","Sunglasses","Ankle Socks","Leather Wallet","Hair Clip"],
}

COURIERS = [
    ("DPD","DPD UK"),
    ("ROYAL_MAIL","Royal Mail"),
    ("EVRI","Evri"),
    ("UPS","UPS"),
]

COURIER_SERVICES = [
    ("DPD","DPD_NEXT","DPD Next Day",time(15,30),1),
    ("DPD","DPD_2DAY","DPD 2 Day",time(16,0),2),
    ("ROYAL_MAIL","RM_1ST","Royal Mail 1st Class",time(14,0),1),
    ("ROYAL_MAIL","RM_48","Royal Mail 48hr",time(14,0),2),
    ("EVRI","EVRI_STD","Evri Standard",time(16,0),3),
    ("UPS","UPS_EXPRESS","UPS Express",time(14,0),1),
]

CARRIER_WEIGHTS = [
    ("DPD",0.55),
    ("ROYAL_MAIL",0.25),
    ("EVRI",0.15),
    ("UPS",0.05),
]

RETURN_REASONS = [
    "Too small","Too large","Not as described","Faulty/damaged",
    "Changed mind","Wrong item received","Poor quality","Arrived too late",
]

RETURN_CONDITIONS = ["Good","Fair","Poor","Damaged"]
RETURN_GRADES     = {"Good":"A","Fair":"B","Poor":"C","Damaged":"D"}
RETURN_DISPOSITIONS = {
    "A":"Restock","B":"Restock","C":"Clearance","D":"Write Off"
}

MOVEMENT_TYPES = ["Pick","Replenishment","Transfer","Goods In","Return","Adjustment"]

ZONES_PICKFACE = ["A","B","C","D","E","F","G","H","I","J"]
ZONES_BULK     = ["BULK-A","BULK-B","BULK-C","BULK-D"]


# ── Helper utilities ───────────────────────────────────────────────────────────

def uid(): return str(uuid4())

def rdt(d: date, hour_min=6, hour_max=22) -> datetime:
    """Random datetime on a given date within business-ish hours."""
    h = RNG.randint(hour_min, hour_max - 1)
    m = RNG.randint(0, 59)
    s = RNG.randint(0, 59)
    return datetime(d.year, d.month, d.day, h, m, s, tzinfo=timezone.utc)

def wc(rows, cur, table, cols):
    """Batch upsert helper using execute_values."""
    if not rows:
        return
    placeholders = "(" + ",".join(["%s"] * len(cols)) + ")"
    sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES %s ON CONFLICT DO NOTHING"
    execute_values(cur, sql, rows, template=placeholders, page_size=500)

def pick_operator(shift, d, op_id_list, include_new_joiner=True):
    pool = list(op_id_list)
    if include_new_joiner and shift == "AM" and d >= NEW_JOINER_HIRE and NEW_JOINER_ID not in pool:
        pool.append(NEW_JOINER_ID)
    return RNG.choice(pool)


# ── Master data ────────────────────────────────────────────────────────────────

def build_operators():
    rows = []
    now = datetime.now(timezone.utc)
    for op_id, name, role, shift in OPERATOR_NAMES:
        rows.append((uid(), TENANT_ID, op_id, name, role, shift, now))
    cols = ["id","tenant_id","operator_id","name","role","shift","synced_at"]
    return rows, cols

def build_skus():
    """Generate ~500 active SKUs with velocity bands A/B/C."""
    skus = []
    idx  = 1
    for cat in CATEGORIES:
        prefix = CAT_PREFIXES[cat]
        names  = STYLE_NAMES[cat]
        for style_idx, style_name in enumerate(names):
            style_code = f"AL-{prefix}-{style_idx+1:04d}"
            col_count  = 3 if cat == "Accessories" else len(COLOURS)
            sz_list    = ["OS"] if cat == "Accessories" else SIZES
            for col in COLOURS[:col_count]:
                for sz in sz_list:
                    sku = f"{style_code}-{col}-{sz}"
                    skus.append({
                        "sku":        sku,
                        "style_code": style_code,
                        "style_name": style_name,
                        "colour":     col,
                        "size":       sz,
                        "size_type":  SIZE_TYPES[cat],
                        "category":   cat,
                        "barcode":    f"500{idx:09d}",
                        "weight_kg":  round(RNG.uniform(0.1, 1.5), 3),
                        "price":      round(RNG.uniform(12, 180), 2),
                    })
                    idx += 1

    # Ensure seeded problem SKUs exist
    for sku in HIGH_RETURN_SKUS + REPLEN_DELAYED_SKUS:
        if not any(s["sku"] == sku for s in skus):
            parts = sku.split("-")
            cat = "Tops"
            skus.append({
                "sku": sku, "style_code": "-".join(parts[:3]),
                "style_name": "Special Tee", "colour": parts[-2],
                "size": parts[-1], "size_type": "Apparel", "category": cat,
                "barcode": f"500{idx:09d}", "weight_kg": 0.3, "price": 35.0,
            })
            idx += 1

    # Assign velocity bands
    n = len(skus)
    a_cut = int(n * 0.20)
    b_cut = int(n * 0.50)
    for i, s in enumerate(skus):
        s["band"] = "A" if i < a_cut else ("B" if i < b_cut else "C")

    return skus

def build_locations(skus):
    locs = []
    seq  = 1
    now  = datetime.now(timezone.utc)

    # Pickface — aisles A-J, bays 01-10, levels 1-5
    for zone in ZONES_PICKFACE:
        for bay in range(1, 11):
            for level in range(1, 6):
                ref = f"{zone}{bay:02d}-L{level}"
                locs.append((uid(), TENANT_ID, ref, zone, zone, f"{bay:02d}",
                              f"L{level}", "Pickface", seq, 50.0, True, "pickface", now))
                seq += 1

    # Bulk storage
    for zone in ZONES_BULK:
        short = zone.replace("BULK-","")
        for bay in range(1, 26):
            ref = f"{zone}-{bay:03d}"
            locs.append((uid(), TENANT_ID, ref, zone, zone, f"{bay:03d}",
                          None, "Bulk", 99999, 500.0, True, "bulk", now))

    # Stores
    for s in range(1, 6):
        for bay in range(1, 21):
            ref = f"STORE-{s:02d}-{bay:02d}"
            locs.append((uid(), TENANT_ID, ref, f"STORE-{s:02d}", f"STORE-{s:02d}",
                          f"{bay:02d}", None, "Store", None, 200.0, True,
                          f"store_{s:02d}", now))

    cols = ["id","tenant_id","reference","zone","aisle","bay","level",
            "location_type","pick_sequence","max_weight_kg","is_active","site","synced_at"]
    return locs, cols

def build_inventory(skus):
    rows = []
    now  = datetime.now(timezone.utc)
    # Pickface locations for primary_location lookup (A-band gets front aisles)
    pf_aisles = {"A":["A","B"],"B":["C","D","E"],"C":["F","G","H","I","J"]}

    for s in skus:
        band = s["band"]
        aisle_opts = pf_aisles[band]
        aisle = RNG.choice(aisle_opts)
        bay   = RNG.randint(1,10)
        level = RNG.randint(1,5)
        loc   = f"{aisle}{bay:02d}-L{level}"

        # Base stock levels
        if band == "A":
            avail = RNG.randint(20, 120)
            alloc = RNG.randint(5, 30)
        elif band == "B":
            avail = RNG.randint(5, 60)
            alloc = RNG.randint(0, 15)
        else:
            avail = RNG.randint(0, 30)
            alloc = RNG.randint(0, 5)

        # Replenishment-delayed SKUs — end up with critically low pickface stock
        if s["sku"] in REPLEN_DELAYED_SKUS:
            avail = RNG.randint(0, 4)
            alloc = 0

        reorder = 12 if band == "A" else (8 if band == "B" else 4)

        rows.append((
            uid(), TENANT_ID, s["sku"], s["style_code"], s["style_name"],
            s["colour"], s["size"], s["size_type"], s["category"],
            s["barcode"], s["weight_kg"], s["price"],
            avail, alloc, RNG.randint(0,50), loc, reorder, "pickface", now
        ))

    cols = [
        "id","tenant_id","sku","style_code","style_name","colour","size",
        "size_type","category","barcode","weight_kg","selling_price_gbp",
        "available_qty","allocated_qty","on_order_qty","primary_location",
        "reorder_point","site","synced_at"
    ]
    return rows, cols

def build_couriers_and_services():
    now = datetime.now(timezone.utc)
    c_rows = [(uid(), TENANT_ID, code, name, True, now)
              for code, name in COURIERS]
    c_cols = ["id","tenant_id","code","name","is_active","synced_at"]

    s_rows = []
    for courier_code, svc_code, svc_name, cutoff, transit in COURIER_SERVICES:
        s_rows.append((uid(), TENANT_ID, courier_code, svc_code, svc_name,
                        cutoff, transit, True, now))
    s_cols = ["id","tenant_id","courier_code","service_code","service_name",
              "cut_off_time","transit_days","is_tracked","synced_at"]

    return c_rows, c_cols, s_rows, s_cols


# ── Daily data generators ──────────────────────────────────────────────────────

def carrier_for_order():
    r = RNG.random()
    cumul = 0
    for carrier, w in CARRIER_WEIGHTS:
        cumul += w
        if r < cumul:
            return carrier
    return "DPD"

def service_for_carrier(carrier):
    services = [s for s in COURIER_SERVICES if s[0] == carrier]
    return RNG.choice(services)[1] if services else "STD"

ORDER_STATUSES_HISTORICAL = ["Dispatched"] * 92 + ["Cancelled"] * 5 + ["On Hold"] * 3

def build_orders_for_day(d: date, skus, n=None):
    if n is None:
        # slight weekday variation
        wd = d.weekday()
        mult = {0:1.1,1:1.05,2:1.0,3:0.95,4:1.15,5:1.2,6:0.8}.get(wd, 1.0)
        n = max(1, int(ORDERS_PER_DAY * mult * RNG.uniform(0.92, 1.08)))

    # Most recent 2 days have in-flight orders
    is_today = d == END_DATE
    is_yesterday = d == END_DATE - timedelta(days=1)

    orders = []
    order_lines_all = []
    order_num = int(d.strftime("%Y%m%d")) * 10000  # base number for the day

    sku_list = [s["sku"] for s in skus]
    sku_prices = {s["sku"]: s["price"] for s in skus}
    # Weight velocity: A-band more likely to be ordered
    sku_weights = [3.0 if s["band"]=="A" else (1.5 if s["band"]=="B" else 0.5) for s in skus]

    for i in range(n):
        order_num += 1
        order_no = f"WEB-{order_num}"
        carrier   = carrier_for_order()
        service   = service_for_carrier(carrier)
        order_dt  = rdt(d, 0, 23)

        if is_today:
            status = RNG.choice(["Awaiting Pick","Picking in progress","Picked","Packing","Packed","Dispatched"])
        elif is_yesterday:
            status = RNG.choice(["Dispatched"]*8 + ["On Hold"])
        else:
            status = RNG.choice(ORDER_STATUSES_HISTORICAL)

        dispatch_dt = None
        if status == "Dispatched":
            dispatch_dt = datetime(d.year, d.month, d.day,
                                   RNG.randint(11, 16), RNG.randint(0, 59), 0,
                                   tzinfo=timezone.utc)

        n_lines = RNG.choices([1,2,3,4,5], weights=[30,30,20,12,8])[0]
        chosen_skus = RNG.choices(sku_list, weights=sku_weights, k=n_lines)
        total_val = 0
        o_lines = []
        for ln, sku in enumerate(chosen_skus, 1):
            qty = RNG.choices([1,2,3], weights=[70,22,8])[0]
            unit_price = sku_prices.get(sku, 35.0)
            line_val = round(unit_price * qty, 2)
            total_val += line_val
            o_lines.append({
                "line_number": str(ln),
                "sku": sku,
                "qty_ordered": qty,
                "qty_despatched": qty if status=="Dispatched" else 0,
                "unit_price_gbp": unit_price,
                "total_line_value_gbp": line_val,
            })
        total_val = round(total_val, 2)

        orders.append({
            "id": uid(), "tenant_id": TENANT_ID,
            "order_number": order_no, "channel": "Website",
            "order_date": order_dt, "dispatch_date": dispatch_dt,
            "customer_name": f"Customer {order_num}",
            "customer_email": f"customer{order_num}@example.com",
            "carrier": carrier,
            "tracking_number": f"{carrier[:3].upper()}{order_num:010d}" if status=="Dispatched" else None,
            "status": status,
            "total_value_gbp": total_val,
            "line_count": n_lines,
            "synced_at": datetime.now(timezone.utc),
        })
        for l in o_lines:
            order_lines_all.append({
                "id": uid(), "tenant_id": TENANT_ID,
                "order_number": order_no,
                "line_number": l["line_number"],
                "sku": l["sku"], "item_name": l["sku"],
                "qty_ordered": l["qty_ordered"],
                "qty_despatched": l["qty_despatched"],
                "unit_price_gbp": l["unit_price_gbp"],
                "total_line_value_gbp": l["total_line_value_gbp"],
                "synced_at": datetime.now(timezone.utc),
            })

    return orders, order_lines_all


def build_pick_jobs_for_day(orders, d: date):
    jobs = []
    lines = []
    now = datetime.now(timezone.utc)

    # Active pickers on this day
    pickers_am = list(PICKERS_AM)
    pickers_pm = list(PICKERS_PM)
    if d >= NEW_JOINER_HIRE:
        pickers_am.append(NEW_JOINER_ID)

    dispatched_statuses = {"Picked","Packing","Packed","Dispatched"}

    for o in orders:
        status_map = {
            "Awaiting Pick": "Pending",
            "Picking in progress": "In Progress",
            "Picked": "Complete",
            "Packing": "Complete",
            "Packed": "Complete",
            "Dispatched": "Complete",
            "Cancelled": "Cancelled",
            "On Hold": "Pending",
        }
        job_status = status_map.get(o["status"], "Complete")
        order_dt = o["order_date"]
        hour = order_dt.hour if hasattr(order_dt, "hour") else 8
        shift = "AM" if hour < 14 else "PM"
        pickers = pickers_am if shift == "AM" else pickers_pm
        picker_id = RNG.choice(pickers)
        picker_name = OP_LOOKUP.get(picker_id, picker_id)

        assigned_at = order_dt + timedelta(minutes=RNG.randint(5, 45))
        started_at  = None
        if job_status in ("In Progress","Complete"):
            started_at = assigned_at + timedelta(minutes=RNG.randint(2, 20))

        job_id = f"PJ-{o['order_number']}"
        lines_picked = o["line_count"] if job_status == "Complete" else (
            RNG.randint(0, o["line_count"]) if job_status == "In Progress" else 0
        )

        jobs.append({
            "id": uid(), "tenant_id": TENANT_ID,
            "job_id": job_id, "order_number": o["order_number"],
            "channel": "Website",
            "picker_id": picker_id, "picker_name": picker_name,
            "status": job_status,
            "total_lines": o["line_count"], "lines_picked": lines_picked,
            "assigned_at": assigned_at, "started_at": started_at,
            "carrier": o["carrier"], "pick_zone": "A",
            "synced_at": now,
        })

    return jobs, lines


def build_stock_movements_for_day(orders, order_lines, d: date):
    movements = []
    now = datetime.now(timezone.utc)
    ref_base = int(d.strftime("%Y%m%d")) * 100000

    for i, ol in enumerate(order_lines):
        # Only create movements for dispatched/picked orders
        parent_order = next((o for o in orders if o["order_number"] == ol["order_number"]), None)
        if not parent_order or parent_order["status"] not in ("Dispatched","Picked","Packing","Packed"):
            continue

        ref_base += 1
        ref = f"SM-{ref_base}"
        move_dt = rdt(d, 6, 16)

        movements.append({
            "id": uid(), "tenant_id": TENANT_ID,
            "reference": ref, "movement_type": "Pick",
            "sku": ol["sku"], "item_name": ol["sku"],
            "quantity": ol["qty_ordered"],
            "from_location": None, "to_location": "DESPATCH",
            "movement_date": move_dt,
            "operator_id": None, "operator_name": None,
            "notes": ol["order_number"],
            "site": "pickface",
            "synced_at": now,
        })

    # Replenishment movements from bulk → pickface (A-band SKUs daily)
    for sku in REPLEN_DELAYED_SKUS:
        ref_base += 1
        ref = f"SM-{ref_base}"
        # Delayed replen — only happens in afternoon, and sometimes not at all
        if RNG.random() < 0.4:  # 40% chance replen arrives that day
            movements.append({
                "id": uid(), "tenant_id": TENANT_ID,
                "reference": ref, "movement_type": "Replenishment",
                "sku": sku, "item_name": sku,
                "quantity": RNG.randint(20, 60),
                "from_location": f"BULK-A-{RNG.randint(1,25):03d}",
                "to_location": f"A{RNG.randint(1,10):02d}-L{RNG.randint(1,5)}",
                "movement_date": rdt(d, 13, 18),
                "operator_id": None, "operator_name": None,
                "notes": "Replenishment",
                "site": "pickface",
                "synced_at": now,
            })

    return movements


def build_all_returns(conn):
    """
    Two-phase returns generation.
    Called after all 90 days of orders are inserted.
    Queries every dispatched order line, assigns a lag-weighted return date,
    and returns (returns_list, events_list) ready to bulk-insert.

    Distribution: lag 3-21 days, peak 7-10 days.
    Days 1-3 of the seed window get zero returns naturally (no prior dispatch
    history). Days 4-21 scale up as the available window widens.
    """
    returns_list = []
    events_list  = []
    now          = datetime.now(timezone.utc)
    counter      = 0

    with conn.cursor() as cur:
        cur.execute("""
            SELECT ol.order_number, ol.line_number, ol.sku,
                   ol.qty_ordered, ol.unit_price_gbp, ol.total_line_value_gbp,
                   o.dispatch_date, o.customer_name, o.customer_email
            FROM   order_lines ol
            JOIN   orders o
                   ON o.tenant_id = ol.tenant_id
                   AND o.order_number = ol.order_number
            WHERE  ol.tenant_id = %s
            AND    o.status = 'Dispatched'
            AND    o.dispatch_date IS NOT NULL
            ORDER  BY o.dispatch_date
        """, (TENANT_ID,))
        rows = cur.fetchall()

    for row in rows:
        (order_number, line_number, sku, qty_ordered,
         unit_price, line_value, dispatch_dt,
         customer_name, customer_email) = row

        is_high_return = sku in HIGH_RETURN_SKUS
        rate = RETURN_RATE_HIGH if is_high_return else RETURN_RATE_BASE
        if RNG.random() > rate:
            continue

        lag    = RNG.choices(_LAG_DAYS, weights=_LAG_WEIGHTS)[0]
        ret_dt = dispatch_dt + timedelta(days=lag)
        if ret_dt.date() > END_DATE:
            continue  # return hasn't happened yet in our window

        counter  += 1
        ret_num   = f"RET-{counter:08d}"
        reason    = RNG.choice(
            ["Too small","Too large","Not as described","Faulty/damaged"]
            if is_high_return else RETURN_REASONS
        )
        cond  = RNG.choice(["Fair","Poor","Damaged"] if is_high_return else ["Good","Good","Fair"])
        grade = RETURN_GRADES[cond]
        disp  = RETURN_DISPOSITIONS[grade]

        proc_op   = RNG.choice(["OP-014","OP-020","OP-035"])
        proc_name = OP_LOOKUP.get(proc_op, proc_op)

        returns_list.append({
            "id": uid(), "tenant_id": TENANT_ID,
            "return_number":         ret_num,
            "original_order_number": order_number,
            "return_date":           ret_dt,
            "sku":                   sku,
            "item_name":             sku,
            "qty_returned":          qty_ordered,
            "return_reason":         reason,
            "item_condition":        cond,
            "grade":                 grade,
            "grade_description":     cond,
            "disposition":           disp,
            "processing_bay":        f"RET-BAY-{RNG.randint(1,6)}",
            "processing_operator_id": proc_op,
            "processing_minutes":    RNG.randint(5, 25),
            "status":                "Processed",
            "customer_name":         customer_name,
            "customer_email":        customer_email,
            "refund_amount_gbp":     line_value,
            "tracking_number":       None,
            "synced_at":             now,
        })

        for evt_type, offset_h in [("Registered",0),("Received",4),("Graded",6),("Processed",8)]:
            events_list.append({
                "id": uid(), "tenant_id": TENANT_ID,
                "return_number": ret_num,
                "event_type":    evt_type,
                "event_at":      ret_dt + timedelta(hours=offset_h),
                "operator_id":   proc_op,
                "operator_name": proc_name,
                "notes":         None,
                "synced_at":     now,
            })

    return returns_list, events_list


def build_stock_adjustments_for_day(d: date, skus):
    """Cycle count adjustments — Callum Osei causes discrepancies after hire date."""
    adjustments = []
    now = datetime.now(timezone.utc)
    ref_base = int(d.strftime("%Y%m%d")) * 1000

    # Daily cycle count: ~15 adjustments baseline
    zones_to_count = RNG.choices(ZONES_PICKFACE, k=2)
    sku_list = [s["sku"] for s in skus]

    for i in range(35):
        ref_base += 1
        ref = f"ADJ-{ref_base}"
        sku = RNG.choice(sku_list)

        # After new joiner hired, assign ~40% of cycle counts to Callum
        is_callum_day = d >= NEW_JOINER_HIRE and RNG.random() < 0.40
        op_id   = NEW_JOINER_ID if is_callum_day else RNG.choice(PICKERS_AM[:4])
        op_name = OP_LOOKUP.get(op_id)

        # Callum's counts: larger variance due to training gap
        if is_callum_day:
            sys_qty = RNG.randint(5, 80)
            variance = RNG.choices(
                [-5,-4,-3,-2,-1,0,1,2,3,4,5],
                weights=[3,5,8,10,8,30,5,8,8,8,7]
            )[0]
        else:
            sys_qty = RNG.randint(5, 80)
            variance = RNG.choices(
                [-2,-1,0,1,2],
                weights=[5,15,60,15,5]
            )[0]

        zone = RNG.choice(zones_to_count)
        bay  = RNG.randint(1,10)
        lvl  = RNG.randint(1,5)
        loc  = f"{zone}{bay:02d}-L{lvl}"

        adjustments.append({
            "id": uid(), "tenant_id": TENANT_ID,
            "adjustment_number": ref,
            "adjustment_type": "CycleCount",
            "sku": sku, "item_name": sku,
            "location": loc, "site": "pickface",
            "qty_system": sys_qty,
            "qty_counted": sys_qty + variance,
            "variance": variance,
            "reason": "Cycle count" if variance == 0 else "Discrepancy found",
            "operator_id": op_id, "operator_name": op_name,
            "adjusted_at": rdt(d, 7, 15),
            "approved_by": "OP-005" if variance != 0 else None,
            "synced_at": now,
        })

    return adjustments


def build_packing_sessions_for_day(d: date):
    sessions = []
    now = datetime.now(timezone.utc)
    stations = [f"PS-{i:02d}" for i in range(1, 21)]  # 20 stations

    for station_id in stations:
        for shift, packers, start_hour, end_hour in [
            ("AM", PACKERS_AM, 6, 14),
            ("PM", PACKERS_PM, 14, 22),
        ]:
            pool = list(packers)
            # Callum cross-trains on packing occasionally after hire
            if d >= NEW_JOINER_HIRE and shift == "AM" and RNG.random() < 0.15:
                pool.append(NEW_JOINER_ID)

            op_id   = RNG.choice(pool)
            op_name = OP_LOOKUP.get(op_id, op_id)

            shift_start = datetime(d.year, d.month, d.day, start_hour, 0, 0, tzinfo=timezone.utc)
            shift_end   = datetime(d.year, d.month, d.day, end_hour, 0, 0, tzinfo=timezone.utc)

            orders_packed = RNG.randint(30, 60)

            # Callum packs slower and makes more errors
            if op_id == NEW_JOINER_ID:
                avg_time = RNG.randint(180, 360)   # 3-6 min vs baseline 90-150s
                errors   = RNG.randint(3, 8)
            else:
                avg_time = RNG.randint(90, 150)
                errors   = RNG.randint(0, 2)

            units_packed = orders_packed * RNG.randint(2, 5)

            sessions.append({
                "id": uid(), "tenant_id": TENANT_ID,
                "station_id": station_id, "operator_id": op_id,
                "operator_name": op_name, "shift": shift,
                "session_date": d, "shift_start": shift_start,
                "shift_end": shift_end,
                "orders_packed": orders_packed, "units_packed": units_packed,
                "avg_pack_time_secs": avg_time, "errors": errors,
                "void_fill_bags_used": orders_packed,
                "labels_printed": orders_packed + errors,
                "synced_at": now,
            })

    return sessions


def build_inbound_shipments_for_day(d: date, skus):
    """~3 ASNs per week — generate one if today is Mon/Wed/Fri."""
    if d.weekday() not in (0, 2, 4):  # Mon, Wed, Fri only
        return [], [], [], []

    now = datetime.now(timezone.utc)
    asn_num = f"ASN-{d.strftime('%Y%m%d')}"

    suppliers = [
        ("SUP-001","Elite Garment Co","GB"),
        ("SUP-002","Fabrique Mode","FR"),
        ("SUP-003","Textile House","PT"),
        ("SUP-004","Nordic Apparel","SE"),
    ]
    supplier = RNG.choice(suppliers)
    op_id    = RNG.choice(["OP-010","OP-016","OP-031"])
    op_name  = OP_LOOKUP.get(op_id)

    total_units_ordered   = RNG.randint(500, 3000)
    total_units_received  = total_units_ordered - RNG.randint(0, int(total_units_ordered * 0.05))
    n_lines               = RNG.randint(20, 80)

    shipment = {
        "id": uid(), "tenant_id": TENANT_ID,
        "asn_number": asn_num,
        "po_number": f"PO-{asn_num}",
        "supplier_code": supplier[0], "supplier_name": supplier[1],
        "supplier_country": supplier[2],
        "expected_date": d - timedelta(days=RNG.randint(0,2)),
        "actual_date": d, "status": "Received",
        "dock_door": f"DOCK-{RNG.randint(1,4)}",
        "handling_units": RNG.randint(5, 30),
        "total_cartons": RNG.randint(20, 100),
        "total_units_ordered": total_units_ordered,
        "total_units_received": total_units_received,
        "operator_id": op_id, "operator_name": op_name,
        "line_count": n_lines,
        "synced_at": now,
    }

    a_skus = [s["sku"] for s in skus if s["band"] in ("A","B")]
    chosen = RNG.choices(a_skus, k=n_lines)

    ship_lines = []
    for ln, sku in enumerate(chosen, 1):
        qty_ord = RNG.randint(10, 80)
        qty_rcv = qty_ord - RNG.randint(0, max(1, int(qty_ord * 0.05)))
        ship_lines.append({
            "id": uid(), "tenant_id": TENANT_ID,
            "asn_number": asn_num, "line_number": str(ln),
            "sku": sku, "item_name": sku,
            "colour": None, "size": None,
            "qty_ordered": qty_ord, "qty_received": qty_rcv,
            "variance": qty_rcv - qty_ord,
            "unit_cost_gbp": round(RNG.uniform(4, 60), 2),
            "put_away_location": f"BULK-A-{RNG.randint(1,25):03d}",
            "synced_at": now,
        })

    # Goods-in receipt
    receipt_num = f"GIN-{d.strftime('%Y%m%d')}"
    receipt = {
        "id": uid(), "tenant_id": TENANT_ID,
        "receipt_number": receipt_num,
        "asn_number": asn_num,
        "receipt_date": d,
        "dock_door": shipment["dock_door"],
        "operator_id": op_id, "operator_name": op_name,
        "status": "Complete",
        "total_cartons": shipment["total_cartons"],
        "total_units": total_units_received,
        "discrepancy_units": total_units_ordered - total_units_received,
        "notes": None, "synced_at": now,
    }

    return [shipment], ship_lines, [receipt], []


# ── Upsert helpers ─────────────────────────────────────────────────────────────

def upsert_dicts(cur, table, rows, conflict_cols):
    if not rows:
        return
    cols = list(rows[0].keys())
    values = [[r[c] for c in cols] for r in rows]
    col_str = ", ".join(cols)
    placeholder = "(" + ", ".join(["%s"] * len(cols)) + ")"
    conflict = ", ".join(conflict_cols)
    sql = (f"INSERT INTO {table} ({col_str}) VALUES %s "
           f"ON CONFLICT ({conflict}) DO NOTHING")
    execute_values(cur, sql, values, template=placeholder, page_size=500)


# ── Main ───────────────────────────────────────────────────────────────────────

def wipe_tables(conn):
    tables = [
        "audit_trail","consignments","manifests","despatch_notes",
        "totes","carts","pick_lists","courier_services","couriers",
        "write_offs","stock_adjustments","qc_results","goods_in_receipts",
        "return_events","packing_station_sessions","pick_job_lines",
        "order_lines","pick_jobs","stock_movements","returns",
        "inbound_shipment_lines","inbound_shipments","packing_stations",
        "orders","inventory","locations","operators","sync_log",
    ]
    with conn.cursor() as cur:
        for t in tables:
            cur.execute(f"DELETE FROM {t} WHERE tenant_id = %s", (TENANT_ID,))
    conn.commit()
    print("  Tables wiped.")


def seed_master_data(conn):
    with conn.cursor() as cur:
        print("  Seeding operators...")
        rows, cols = build_operators()
        wc(rows, cur, "operators", cols)

        print("  Building SKUs...")
        skus = build_skus()
        print(f"    {len(skus)} SKUs generated.")

        print("  Seeding locations...")
        locs, l_cols = build_locations(skus)
        wc(locs, cur, "locations", l_cols)

        print("  Seeding inventory...")
        inv, i_cols = build_inventory(skus)
        wc(inv, cur, "inventory", i_cols)

        print("  Seeding couriers...")
        c_rows, c_cols, s_rows, s_cols = build_couriers_and_services()
        wc(c_rows, cur, "couriers", c_cols)
        wc(s_rows, cur, "courier_services", s_cols)

    conn.commit()
    return skus


def seed_day(conn, d: date, skus, verbose=True):
    if verbose:
        print(f"  Day {d} ...", end=" ", flush=True)

    with conn.cursor() as cur:
        orders, order_lines = build_orders_for_day(d, skus)
        upsert_dicts(cur, "orders",      orders,      ["tenant_id","order_number"])
        upsert_dicts(cur, "order_lines", order_lines, ["tenant_id","order_number","line_number"])

        pick_jobs, _ = build_pick_jobs_for_day(orders, d)
        upsert_dicts(cur, "pick_jobs", pick_jobs, ["tenant_id","job_id"])

        movements = build_stock_movements_for_day(orders, order_lines, d)
        upsert_dicts(cur, "stock_movements", movements, ["tenant_id","reference"])

        adjs = build_stock_adjustments_for_day(d, skus)
        upsert_dicts(cur, "stock_adjustments", adjs, ["tenant_id","adjustment_number"])

        sessions = build_packing_sessions_for_day(d)
        upsert_dicts(cur, "packing_station_sessions", sessions,
                     ["tenant_id","station_id","session_date","shift"])

        shipments, ship_lines, receipts, _ = build_inbound_shipments_for_day(d, skus)
        upsert_dicts(cur, "inbound_shipments",      shipments,  ["tenant_id","asn_number"])
        upsert_dicts(cur, "inbound_shipment_lines", ship_lines, ["tenant_id","asn_number","line_number"])
        upsert_dicts(cur, "goods_in_receipts",      receipts,   ["tenant_id","receipt_number"])

    conn.commit()

    if verbose:
        print(f"  {len(orders)} orders, {len(order_lines)} lines, "
              f"{len(movements)} movements, {len(sessions)} packing sessions.")


def seed_returns(conn):
    print("Seeding returns (two-pass, lag 3-21 days, peak 7-10)...")
    returns_list, events_list = build_all_returns(conn)
    with conn.cursor() as cur:
        upsert_dicts(cur, "returns",       returns_list, ["tenant_id","return_number"])
        upsert_dicts(cur, "return_events", events_list,  ["id"])
    conn.commit()

    # Quick distribution check — print return counts by lag bucket
    if returns_list:
        from collections import Counter
        # Verify high-return SKU concentration
        sku_counts = Counter(r["sku"] for r in returns_list)
        top5 = sku_counts.most_common(5)
        print(f"  {len(returns_list):,} returns, {len(events_list):,} events inserted.")
        print(f"  Top 5 returned SKUs: {top5}")
        problem_hits = sum(sku_counts[s] for s in HIGH_RETURN_SKUS)
        pct = problem_hits / len(returns_list) * 100
        print(f"  Problem SKUs account for {problem_hits:,} returns ({pct:.1f}% of total).")
    else:
        print("  0 returns (expected for 1-day seed — no prior dispatch history).")


def main():
    parser = argparse.ArgumentParser(description="Seed Aria London warehouse data")
    parser.add_argument("--days",  type=int, default=1, help="Number of days to seed (default 1)")
    parser.add_argument("--full",  action="store_true",  help="Seed full 90 days")
    parser.add_argument("--wipe",  action="store_true",  help="Wipe existing seed data first")
    args = parser.parse_args()

    n_days = 90 if args.full else args.days

    print(f"Aria London seeder — {'full ' if args.full else ''}{n_days} day(s)")
    print(f"  Date range: {END_DATE - timedelta(days=n_days-1)} to {END_DATE}")
    print(f"  New joiner (Callum Osei) active from: {NEW_JOINER_HIRE}")

    conn = get_conn()

    if args.wipe:
        print("Wiping existing data...")
        wipe_tables(conn)

    print("Seeding master data...")
    skus = seed_master_data(conn)

    print(f"Seeding {n_days} day(s) of transactional data...")
    for i in range(n_days):
        d = END_DATE - timedelta(days=n_days - 1 - i)
        seed_day(conn, d, skus)

    seed_returns(conn)

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
