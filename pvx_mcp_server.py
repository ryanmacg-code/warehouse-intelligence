#!/usr/bin/env python3
"""
Aria London WMS — MCP server (database-backed)

All tools query the canonical Supabase database populated by sync_pvx.py.
The Peoplevox mock server is no longer called directly from here.

Configure in .claude/settings.json:
  "mcpServers": {
    "peoplevox": {
      "command": "py",
      "args": ["-3", "C:/Users/Ryan_/warehouse-intelligence/pvx_mcp_server.py"]
    }
  }
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from typing import Annotated

import psycopg2.extras
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

from context import tenant_id_var
from db_client import ARIA_TENANT_ID, dict_cursor, get_conn

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _effective_tenant_id() -> str:
    """Return the tenant ID for the current request.

    In HTTP mode, reads X-Tenant-Id from the request context (set by the
    tenant_scoping middleware in app.py). Falls back to ARIA_TENANT_ID env var
    so the module still works under stdio transport for local dev.
    """
    tid = tenant_id_var.get("") or ARIA_TENANT_ID
    if not _UUID_RE.match(tid):
        raise ValueError(f"Invalid tenant_id format: {tid!r}")
    return tid

mcp = FastMCP(
    name="Aria London WMS",
    streamable_http_path="/",
    instructions=(
        "Tools for querying the Aria London warehouse management system. "
        "Data is sourced from the canonical Supabase database, synced from Peoplevox every 15 minutes. "
        "PRIMARY TOOLS: "
        "get_warehouse_health — proactive health check, use this first for open-ended ops questions. "
        "analyse_returns — SKU-level return rate analysis with £ impact, use for returns investigations. "
        "get_stock_adjustments — cycle count data ranked by operator discrepancy rate, use for stock integrity. "
        "get_inventory — stock levels by site (pickface/bulk/store_XX), use site= param for replenishment analysis. "
        "SUPPORTING TOOLS: "
        "get_orders, get_returns, get_stock_movements, get_inbound_shipments, "
        "get_packing_stations, get_pick_jobs, get_locations, get_operators, get_sync_status."
    ),
    # HTTP transport config — used when mounted in app.py via streamable_http_app().
    # streamable_http_path="/" means the sub-app's MCP handler is at its root;
    # when app.py mounts it at /mcp, the client-facing endpoint is POST /mcp.
    # host="0.0.0.0" prevents the SDK's localhost-only DNS rebinding protection
    # from activating (that protection is for local dev only, not production).
    streamable_http_path="/",
    stateless_http=True,
    host="0.0.0.0",
)


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _conn():
    return get_conn()


def _where(clauses: list[str]) -> str:
    base = f"tenant_id = '{_effective_tenant_id()}'"
    if clauses:
        return "WHERE " + base + " AND " + " AND ".join(clauses)
    return "WHERE " + base


def _count(cur, table: str, where: str, params: list) -> int:
    cur.execute(f"SELECT COUNT(*) FROM {table} {where}", params)
    return cur.fetchone()["count"]


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_orders(
    date_from:   Annotated[str, "Start date YYYY-MM-DD. Defaults to 30 days ago."] = "",
    date_to:     Annotated[str, "End date YYYY-MM-DD. Defaults to today."] = "",
    status:      Annotated[str, "Filter by status: 'Dispatched', 'Awaiting picking', "
                                "'Picking in progress', 'Packed', 'On hold', 'Cancelled'."] = "",
    search:      Annotated[str, "Search order number, customer name, or email."] = "",
    page_size:   Annotated[int, "Records per page (1–200)."] = 25,
    page_number: Annotated[int, "Page number starting from 1."] = 1,
) -> str:
    """Fetch sales orders from the canonical database."""
    if not date_from:
        date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not date_to:
        date_to = datetime.now().strftime("%Y-%m-%d")

    page_size = max(1, min(page_size, 200))
    offset    = (page_number - 1) * page_size

    clauses, params = [], []
    clauses.append("order_date >= %s::date")
    params.append(date_from)
    clauses.append("order_date < %s::date + INTERVAL '1 day'")
    params.append(date_to)
    if status:
        clauses.append("LOWER(status) = LOWER(%s)")
        params.append(status)
    if search:
        clauses.append(
            "(order_number ILIKE %s OR customer_name ILIKE %s OR customer_email ILIKE %s)"
        )
        like = f"%{search}%"
        params += [like, like, like]

    where = _where(clauses)

    with _conn() as conn, dict_cursor(conn) as cur:
        # Total count
        cur.execute(f"SELECT COUNT(*) FROM orders {where}", params)
        total = cur.fetchone()["count"]

        # Page of orders
        cur.execute(
            f"SELECT * FROM orders {where} "
            f"ORDER BY order_date DESC LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        order_rows = cur.fetchall()

        # Lines for this page
        order_nums = [r["order_number"] for r in order_rows]
        lines_by_order: dict[str, list] = {n: [] for n in order_nums}
        if order_nums:
            cur.execute(
                f"SELECT * FROM order_lines "
                f"WHERE tenant_id = '{_effective_tenant_id()}' "
                f"AND order_number = ANY(%s) "
                f"ORDER BY order_number, line_number",
                [order_nums],
            )
            for ln in cur.fetchall():
                lines_by_order[ln["order_number"]].append({
                    "sku":         ln["sku"],
                    "name":        ln["item_name"],
                    "ordered":     ln["qty_ordered"],
                    "despatched":  ln["qty_despatched"],
                    "unit_price":  float(ln["unit_price_gbp"] or 0),
                })

    summary = []
    for r in order_rows:
        summary.append({
            "order_number":  r["order_number"],
            "date":          r["order_date"].strftime("%Y-%m-%d") if r["order_date"] else None,
            "dispatch_date": r["dispatch_date"].strftime("%Y-%m-%d") if r["dispatch_date"] else None,
            "channel":       r["channel"],
            "status":        r["status"],
            "customer":      r["customer_name"],
            "email":         r["customer_email"],
            "city":          r["shipping_city"],
            "postcode":      r["shipping_postcode"],
            "carrier":       r["carrier"],
            "tracking":      r["tracking_number"] or None,
            "total_gbp":     float(r["total_value_gbp"] or 0),
            "line_count":    r["line_count"],
            "lines":         lines_by_order.get(r["order_number"], []),
        })

    total_value = sum(o["total_gbp"] for o in summary)
    status_counts: dict[str, int] = {}
    for o in summary:
        s = o["status"] or "Unknown"
        status_counts[s] = status_counts.get(s, 0) + 1

    return json.dumps({
        "query": {
            "date_from":  date_from,
            "date_to":    date_to,
            "status":     status or None,
            "search":     search or None,
            "page":       page_number,
            "page_size":  page_size,
        },
        "total_matching":    total,
        "returned":          len(summary),
        "total_value_gbp":   round(total_value, 2),
        "status_breakdown":  status_counts,
        "orders":            summary,
    }, indent=2, default=str)


@mcp.tool()
def get_inventory(
    search:        Annotated[str, "Search by SKU, style name, colour, or size."] = "",
    category:      Annotated[str, "Filter by category: 'Dresses', 'Tops', 'Bottoms', "
                                  "'Outerwear', 'Accessories'."] = "",
    site:          Annotated[str, "Filter by site: 'pickface', 'bulk', 'store_01' "
                                  "through 'store_05'. Leave blank for all sites."] = "",
    in_stock_only: Annotated[bool, "Only return items with available stock > 0."] = False,
    low_stock:     Annotated[bool, "Only return items at or below their reorder point."] = False,
    page_size:     Annotated[int, "Records per page (1–500)."] = 50,
    page_number:   Annotated[int, "Page number starting from 1."] = 1,
) -> str:
    """Fetch current stock levels from the canonical database, optionally filtered by site
    (pickface, bulk, or individual store). Use site='pickface' for live picking stock,
    site='bulk' for reserve stock, site='store_01'..'store_05' for retail store stock."""
    page_size = max(1, min(page_size, 500))
    offset    = (page_number - 1) * page_size

    clauses, params = [], []
    if search:
        clauses.append(
            "(sku ILIKE %s OR style_name ILIKE %s OR colour ILIKE %s OR size ILIKE %s)"
        )
        like = f"%{search}%"
        params += [like, like, like, like]
    if category:
        clauses.append("LOWER(category) = LOWER(%s)")
        params.append(category)
    if site:
        clauses.append("LOWER(site) = LOWER(%s)")
        params.append(site)
    if in_stock_only:
        clauses.append("available_qty > 0")
    if low_stock:
        clauses.append("available_qty <= reorder_point")

    where = _where(clauses)

    with _conn() as conn, dict_cursor(conn) as cur:
        cur.execute(f"SELECT COUNT(*) FROM inventory {where}", params)
        total = cur.fetchone()["count"]

        cur.execute(
            f"SELECT * FROM inventory {where} "
            f"ORDER BY site, category, style_name, colour, size "
            f"LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        rows = cur.fetchall()

    records = []
    for i in rows:
        records.append({
            "sku":           i["sku"],
            "style_code":    i["style_code"],
            "name":          i["style_name"],
            "category":      i["category"],
            "colour":        i["colour"],
            "size":          i["size"],
            "site":          i["site"],
            "price_gbp":     float(i["selling_price_gbp"] or 0),
            "available":     i["available_qty"],
            "allocated":     i["allocated_qty"],
            "total":         i["total_qty"],
            "on_order":      i["on_order_qty"],
            "reorder_point": i["reorder_point"],
            "location":      i["primary_location"],
            "below_reorder": i["available_qty"] <= i["reorder_point"],
        })

    total_available = sum(r["available"] for r in records)
    total_allocated = sum(r["allocated"] for r in records)
    below_reorder   = sum(1 for r in records if r["below_reorder"])

    by_site:     dict[str, int]   = {}
    by_category: dict[str, dict]  = {}
    by_colour:   dict[str, int]   = {}
    for r in records:
        by_site[r["site"]] = by_site.get(r["site"], 0) + r["available"]
        cat = r["category"] or "Other"
        by_category.setdefault(cat, {"sku_count": 0, "available_units": 0})
        by_category[cat]["sku_count"]       += 1
        by_category[cat]["available_units"] += r["available"]
        c = r["colour"] or "Unknown"
        by_colour[c] = by_colour.get(c, 0) + r["available"]

    return json.dumps({
        "query": {
            "search":        search or None,
            "category":      category or None,
            "site":          site or None,
            "in_stock_only": in_stock_only,
            "low_stock":     low_stock,
            "page":          page_number,
            "page_size":     page_size,
        },
        "total_matching": total,
        "returned":       len(records),
        "stock_summary": {
            "total_available_units": total_available,
            "total_allocated_units": total_allocated,
            "skus_below_reorder":    below_reorder,
        },
        "by_site":     dict(sorted(by_site.items())),
        "by_category": by_category,
        "by_colour":   dict(sorted(by_colour.items(), key=lambda x: -x[1])),
        "items":       records,
    }, indent=2)


@mcp.tool()
def get_returns(
    date_from:   Annotated[str, "Start date YYYY-MM-DD."] = "",
    date_to:     Annotated[str, "End date YYYY-MM-DD."] = "",
    grade:       Annotated[str, "Filter by grade: A, B, C, or D."] = "",
    disposition: Annotated[str, "Filter by disposition: 'Restock', 'Liquidate', "
                                "'Repair', 'Write Off', 'Rework then Restock'."] = "",
    search:      Annotated[str, "Search return number, order number, SKU, or reason."] = "",
    page_size:   Annotated[int, "Records per page (1–200)."] = 50,
    page_number: Annotated[int, "Page number starting from 1."] = 1,
) -> str:
    """Fetch customer returns with grade and disposition from the canonical database."""
    if not date_from:
        date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not date_to:
        date_to = datetime.now().strftime("%Y-%m-%d")

    page_size = max(1, min(page_size, 200))
    offset    = (page_number - 1) * page_size

    clauses, params = [], []
    clauses.append("return_date >= %s::date")
    params.append(date_from)
    clauses.append("return_date < %s::date + INTERVAL '1 day'")
    params.append(date_to)
    if grade:
        clauses.append("UPPER(grade) = UPPER(%s)")
        params.append(grade)
    if disposition:
        clauses.append("LOWER(disposition) = LOWER(%s)")
        params.append(disposition)
    if search:
        like = f"%{search}%"
        clauses.append(
            "(return_number ILIKE %s OR original_order_number ILIKE %s "
            "OR sku ILIKE %s OR return_reason ILIKE %s OR customer_name ILIKE %s)"
        )
        params += [like, like, like, like, like]

    where = _where(clauses)

    with _conn() as conn, dict_cursor(conn) as cur:
        cur.execute(f"SELECT COUNT(*) FROM returns {where}", params)
        total = cur.fetchone()["count"]

        cur.execute(
            f"SELECT * FROM returns {where} ORDER BY return_date DESC LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        rows = cur.fetchall()

    grade_counts:   dict[str, int]   = {}
    reason_counts:  dict[str, int]   = {}
    dispo_counts:   dict[str, int]   = {}
    total_refunds = 0.0
    records = []
    for r in rows:
        g = r["grade"] or "?"
        grade_counts[g]  = grade_counts.get(g, 0) + 1
        rs = r["return_reason"] or "Unknown"
        reason_counts[rs] = reason_counts.get(rs, 0) + 1
        d = r["disposition"] or "Unknown"
        dispo_counts[d]  = dispo_counts.get(d, 0) + 1
        total_refunds   += float(r["refund_amount_gbp"] or 0)
        records.append({
            "return_number":    r["return_number"],
            "original_order":   r["original_order_number"],
            "return_date":      r["return_date"].strftime("%Y-%m-%d") if r["return_date"] else None,
            "sku":              r["sku"],
            "item_name":        r["item_name"],
            "qty_returned":     r["qty_returned"],
            "reason":           r["return_reason"],
            "condition":        r["item_condition"],
            "grade":            r["grade"],
            "grade_description":r["grade_description"],
            "disposition":      r["disposition"],
            "processing_bay":   r["processing_bay"],
            "processing_mins":  r["processing_minutes"],
            "status":           r["status"],
            "customer":         r["customer_name"],
            "refund_gbp":       float(r["refund_amount_gbp"] or 0),
            "tracking":         r["tracking_number"],
        })

    return json.dumps({
        "query": {
            "date_from": date_from, "date_to": date_to,
            "grade": grade or None, "disposition": disposition or None,
            "search": search or None, "page": page_number, "page_size": page_size,
        },
        "total_matching":    total,
        "returned":          len(records),
        "total_refunds_gbp": round(total_refunds, 2),
        "grade_breakdown":   dict(sorted(grade_counts.items())),
        "reason_breakdown":  dict(sorted(reason_counts.items(), key=lambda x: -x[1])),
        "disposition_breakdown": dict(sorted(dispo_counts.items(), key=lambda x: -x[1])),
        "returns":           records,
    }, indent=2, default=str)


@mcp.tool()
def get_stock_movements(
    date_from:     Annotated[str, "Start date YYYY-MM-DD."] = "",
    date_to:       Annotated[str, "End date YYYY-MM-DD."] = "",
    movement_type: Annotated[str, "Filter by type: 'Receipt', 'Pick', 'Replenishment', "
                                  "'Stock Count Adjustment', 'Return to Stock', 'Transfer'."] = "",
    search:        Annotated[str, "Search by SKU, reference, or operator."] = "",
    page_size:     Annotated[int, "Records per page (1–200)."] = 50,
    page_number:   Annotated[int, "Page number starting from 1."] = 1,
) -> str:
    """Fetch stock movement history from the canonical database."""
    if not date_from:
        date_from = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    if not date_to:
        date_to = datetime.now().strftime("%Y-%m-%d")

    page_size = max(1, min(page_size, 200))
    offset    = (page_number - 1) * page_size

    clauses, params = [], []
    clauses.append("movement_date >= %s::date")
    params.append(date_from)
    clauses.append("movement_date < %s::date + INTERVAL '1 day'")
    params.append(date_to)
    if movement_type:
        clauses.append("LOWER(movement_type) = LOWER(%s)")
        params.append(movement_type)
    if search:
        like = f"%{search}%"
        clauses.append("(sku ILIKE %s OR reference ILIKE %s OR operator_name ILIKE %s)")
        params += [like, like, like]

    where = _where(clauses)

    with _conn() as conn, dict_cursor(conn) as cur:
        cur.execute(f"SELECT COUNT(*) FROM stock_movements {where}", params)
        total = cur.fetchone()["count"]

        cur.execute(
            f"SELECT * FROM stock_movements {where} "
            f"ORDER BY movement_date DESC LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        rows = cur.fetchall()

    type_counts: dict[str, int] = {}
    records = []
    for m in rows:
        t = m["movement_type"] or "Unknown"
        type_counts[t] = type_counts.get(t, 0) + 1
        records.append({
            "reference":     m["reference"],
            "type":          m["movement_type"],
            "sku":           m["sku"],
            "item_name":     m["item_name"],
            "quantity":      m["quantity"],
            "from_location": m["from_location"],
            "to_location":   m["to_location"],
            "date":          m["movement_date"].strftime("%Y-%m-%d %H:%M") if m["movement_date"] else None,
            "operator_id":   m["operator_id"],
            "operator_name": m["operator_name"],
        })

    return json.dumps({
        "query": {
            "date_from": date_from, "date_to": date_to,
            "movement_type": movement_type or None,
            "search": search or None, "page": page_number, "page_size": page_size,
        },
        "total_matching":  total,
        "returned":        len(records),
        "type_breakdown":  dict(sorted(type_counts.items(), key=lambda x: -x[1])),
        "movements":       records,
    }, indent=2, default=str)


@mcp.tool()
def get_inbound_shipments(
    date_from:  Annotated[str, "Start date YYYY-MM-DD (expected_date)."] = "",
    date_to:    Annotated[str, "End date YYYY-MM-DD."] = "",
    status:     Annotated[str, "Filter by status: 'Expected', 'In Progress', "
                               "'Received', 'Overdue'."] = "",
    search:     Annotated[str, "Search ASN number, PO number, or supplier name."] = "",
    page_size:  Annotated[int, "Records per page (1–100)."] = 25,
    page_number:Annotated[int, "Page number starting from 1."] = 1,
) -> str:
    """Fetch inbound shipments (goods-in / ASNs) from the canonical database."""
    page_size = max(1, min(page_size, 100))
    offset    = (page_number - 1) * page_size

    clauses, params = [], []
    if date_from:
        clauses.append("expected_date >= %s::date")
        params.append(date_from)
    if date_to:
        clauses.append("expected_date <= %s::date")
        params.append(date_to)
    if status:
        clauses.append("LOWER(status) = LOWER(%s)")
        params.append(status)
    if search:
        like = f"%{search}%"
        clauses.append("(asn_number ILIKE %s OR po_number ILIKE %s OR supplier_name ILIKE %s)")
        params += [like, like, like]

    where = _where(clauses)

    with _conn() as conn, dict_cursor(conn) as cur:
        cur.execute(f"SELECT COUNT(*) FROM inbound_shipments {where}", params)
        total = cur.fetchone()["count"]

        cur.execute(
            f"SELECT * FROM inbound_shipments {where} "
            f"ORDER BY expected_date DESC LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        rows = cur.fetchall()

        asn_nums = [r["asn_number"] for r in rows]
        lines_by_asn: dict[str, list] = {n: [] for n in asn_nums}
        if asn_nums:
            cur.execute(
                f"SELECT * FROM inbound_shipment_lines "
                f"WHERE tenant_id = '{_effective_tenant_id()}' AND asn_number = ANY(%s) "
                f"ORDER BY asn_number, line_number",
                [asn_nums],
            )
            for ln in cur.fetchall():
                lines_by_asn[ln["asn_number"]].append({
                    "sku":          ln["sku"],
                    "item_name":    ln["item_name"],
                    "colour":       ln["colour"],
                    "size":         ln["size"],
                    "qty_ordered":  ln["qty_ordered"],
                    "qty_received": ln["qty_received"],
                    "variance":     ln["variance"],
                    "unit_cost":    float(ln["unit_cost_gbp"] or 0),
                    "put_away_loc": ln["put_away_location"],
                })

    status_counts: dict[str, int] = {}
    records = []
    for s in rows:
        st = s["status"] or "Unknown"
        status_counts[st] = status_counts.get(st, 0) + 1
        records.append({
            "asn_number":           s["asn_number"],
            "po_number":            s["po_number"],
            "supplier":             s["supplier_name"],
            "supplier_country":     s["supplier_country"],
            "expected_date":        s["expected_date"].isoformat() if s["expected_date"] else None,
            "actual_date":          s["actual_date"].isoformat() if s["actual_date"] else None,
            "status":               s["status"],
            "dock_door":            s["dock_door"],
            "handling_units":       s["handling_units"],
            "total_cartons":        s["total_cartons"],
            "units_ordered":        s["total_units_ordered"],
            "units_received":       s["total_units_received"],
            "operator_name":        s["operator_name"],
            "lines":                lines_by_asn.get(s["asn_number"], []),
        })

    return json.dumps({
        "query": {
            "date_from": date_from or None, "date_to": date_to or None,
            "status": status or None, "search": search or None,
            "page": page_number, "page_size": page_size,
        },
        "total_matching":  total,
        "returned":        len(records),
        "status_breakdown":status_counts,
        "shipments":       records,
    }, indent=2, default=str)


@mcp.tool()
def get_packing_stations(
    status: Annotated[str, "Filter by status: 'Active', 'Break', 'Idle'."] = "",
    shift:  Annotated[str, "Filter by shift: 'AM', 'PM', 'NIGHT'."] = "",
) -> str:
    """Fetch current packing station throughput from the canonical database."""
    clauses, params = [], []
    if status:
        clauses.append("LOWER(status) = LOWER(%s)")
        params.append(status)
    if shift:
        clauses.append("UPPER(shift) = UPPER(%s)")
        params.append(shift)

    where = _where(clauses)

    with _conn() as conn, dict_cursor(conn) as cur:
        cur.execute(f"SELECT * FROM packing_stations {where} ORDER BY station_id", params)
        rows = cur.fetchall()

    records = []
    total_orders = 0
    total_units  = 0
    for s in rows:
        total_orders += s["orders_packed_today"] or 0
        total_units  += s["units_packed_today"]  or 0
        records.append({
            "station_id":          s["station_id"],
            "operator_id":         s["operator_id"],
            "operator_name":       s["operator_name"],
            "shift":               s["shift"],
            "shift_start":         s["shift_start"].strftime("%H:%M") if s["shift_start"] else None,
            "status":              s["status"],
            "orders_packed_today": s["orders_packed_today"],
            "units_packed_today":  s["units_packed_today"],
            "avg_pack_time_secs":  s["avg_pack_time_secs"],
            "last_order_packed":   s["last_order_packed"],
            "last_activity":       s["last_activity"].strftime("%H:%M") if s["last_activity"] else None,
            "void_fill_bags_used": s["void_fill_bags_used"],
            "labels_printed":      s["labels_printed"],
            "errors_today":        s["errors_today"],
            "synced_at":           s["synced_at"].strftime("%Y-%m-%d %H:%M") if s["synced_at"] else None,
        })

    status_counts = {}
    for s in records:
        st = s["status"] or "Unknown"
        status_counts[st] = status_counts.get(st, 0) + 1

    return json.dumps({
        "query": {"status": status or None, "shift": shift or None},
        "total_stations":      len(records),
        "total_orders_today":  total_orders,
        "total_units_today":   total_units,
        "status_breakdown":    status_counts,
        "stations":            records,
    }, indent=2, default=str)


@mcp.tool()
def get_pick_jobs(
    status:  Annotated[str, "Filter by status: 'Awaiting picking', 'Picking in progress'."] = "",
    picker:  Annotated[str, "Filter by picker name or ID."] = "",
    channel: Annotated[str, "Filter by sales channel."] = "",
) -> str:
    """Fetch active pick jobs from the canonical database."""
    clauses, params = [], []
    if status:
        clauses.append("LOWER(status) = LOWER(%s)")
        params.append(status)
    if picker:
        like = f"%{picker}%"
        clauses.append("(picker_name ILIKE %s OR picker_id ILIKE %s)")
        params += [like, like]
    if channel:
        clauses.append("LOWER(channel) = LOWER(%s)")
        params.append(channel)

    where = _where(clauses)

    with _conn() as conn, dict_cursor(conn) as cur:
        cur.execute(f"SELECT * FROM pick_jobs {where} ORDER BY assigned_at DESC", params)
        rows = cur.fetchall()

    records = []
    for j in rows:
        raw_lines = j["lines"]
        if isinstance(raw_lines, str):
            raw_lines = json.loads(raw_lines)
        records.append({
            "job_id":       j["job_id"],
            "order_number": j["order_number"],
            "channel":      j["channel"],
            "picker_id":    j["picker_id"],
            "picker_name":  j["picker_name"],
            "status":       j["status"],
            "total_lines":  j["total_lines"],
            "lines_picked": j["lines_picked"],
            "pct_complete": round(j["lines_picked"] / j["total_lines"] * 100, 1) if j["total_lines"] else 0,
            "assigned_at":  j["assigned_at"].strftime("%H:%M") if j["assigned_at"] else None,
            "started_at":   j["started_at"].strftime("%H:%M") if j["started_at"] else None,
            "carrier":      j["carrier"],
            "pick_zone":    j["pick_zone"],
            "lines":        raw_lines or [],
        })

    picker_summary: dict[str, dict] = {}
    for j in records:
        p = j["picker_name"] or "Unknown"
        if p not in picker_summary:
            picker_summary[p] = {"jobs": 0, "lines_total": 0, "lines_picked": 0}
        picker_summary[p]["jobs"]         += 1
        picker_summary[p]["lines_total"]  += j["total_lines"] or 0
        picker_summary[p]["lines_picked"] += j["lines_picked"] or 0

    return json.dumps({
        "query": {"status": status or None, "picker": picker or None, "channel": channel or None},
        "total_jobs":     len(records),
        "picker_summary": picker_summary,
        "pick_jobs":      records,
    }, indent=2, default=str)


@mcp.tool()
def get_locations(
    zone:   Annotated[str, "Filter by zone: 'PICK', 'BULK', 'GOODS-IN', "
                           "'RETURNS', 'PACKING', 'DESPATCH', 'QUARANTINE'."] = "",
    search: Annotated[str, "Search by location reference or aisle."] = "",
    page_size:   Annotated[int, "Records per page (1–500)."] = 100,
    page_number: Annotated[int, "Page number starting from 1."] = 1,
) -> str:
    """Fetch warehouse locations with pick sequences from the canonical database."""
    page_size = max(1, min(page_size, 500))
    offset    = (page_number - 1) * page_size

    clauses, params = [], []
    if zone:
        clauses.append("UPPER(zone) = UPPER(%s)")
        params.append(zone)
    if search:
        like = f"%{search}%"
        clauses.append("(reference ILIKE %s OR aisle ILIKE %s)")
        params += [like, like]

    where = _where(clauses)

    with _conn() as conn, dict_cursor(conn) as cur:
        cur.execute(f"SELECT COUNT(*) FROM locations {where}", params)
        total = cur.fetchone()["count"]

        cur.execute(
            f"SELECT * FROM locations {where} ORDER BY zone, pick_sequence LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        rows = cur.fetchall()

    zone_counts: dict[str, int] = {}
    records = []
    for l in rows:
        z = l["zone"] or "Unknown"
        zone_counts[z] = zone_counts.get(z, 0) + 1
        records.append({
            "reference":     l["reference"],
            "zone":          l["zone"],
            "aisle":         l["aisle"],
            "bay":           l["bay"],
            "level":         l["level"],
            "type":          l["location_type"],
            "pick_sequence": l["pick_sequence"],
            "max_weight_kg": float(l["max_weight_kg"] or 0),
            "is_active":     l["is_active"],
        })

    return json.dumps({
        "query": {"zone": zone or None, "search": search or None,
                  "page": page_number, "page_size": page_size},
        "total_matching": total,
        "returned":       len(records),
        "zone_breakdown": zone_counts,
        "locations":      records,
    }, indent=2, default=str)


@mcp.tool()
def get_operators(
    role:  Annotated[str, "Filter by role: 'Picker', 'Packer', 'Returns', "
                          "'Goods In', 'Replenishment', 'Supervisor'."] = "",
    shift: Annotated[str, "Filter by shift: 'AM', 'PM', 'NIGHT'."] = "",
) -> str:
    """Fetch warehouse operators from the canonical database."""
    clauses, params = [], []
    if role:
        clauses.append("LOWER(role) = LOWER(%s)")
        params.append(role)
    if shift:
        clauses.append("UPPER(shift) = UPPER(%s)")
        params.append(shift)

    where = _where(clauses)

    with _conn() as conn, dict_cursor(conn) as cur:
        cur.execute(f"SELECT * FROM operators {where} ORDER BY shift, role, name", params)
        rows = cur.fetchall()

    role_counts:  dict[str, int] = {}
    shift_counts: dict[str, int] = {}
    records = []
    for o in rows:
        r = o["role"] or "Unknown"
        s = o["shift"] or "Unknown"
        role_counts[r]  = role_counts.get(r, 0) + 1
        shift_counts[s] = shift_counts.get(s, 0) + 1
        records.append({
            "operator_id": o["operator_id"],
            "name":        o["name"],
            "role":        o["role"],
            "shift":       o["shift"],
        })

    return json.dumps({
        "query": {"role": role or None, "shift": shift or None},
        "total":          len(records),
        "role_breakdown": role_counts,
        "shift_breakdown":shift_counts,
        "operators":      records,
    }, indent=2, default=str)


@mcp.tool()
def get_sync_status() -> str:
    """Check when each table was last synced and whether any syncs have failed recently."""
    with _conn() as conn, dict_cursor(conn) as cur:
        cur.execute(
            f"""
            SELECT DISTINCT ON (template)
                template, run_at, records_upserted, duration_ms, status, error_message
            FROM sync_log
            WHERE tenant_id = '{_effective_tenant_id()}'
            ORDER BY template, run_at DESC
            """,
        )
        rows = cur.fetchall()

    records = []
    for r in rows:
        records.append({
            "template":          r["template"],
            "last_synced":       r["run_at"].strftime("%Y-%m-%d %H:%M:%S") if r["run_at"] else None,
            "records_upserted":  r["records_upserted"],
            "duration_ms":       r["duration_ms"],
            "status":            r["status"],
            "error":             r["error_message"],
        })

    return json.dumps({"last_sync_per_template": records}, indent=2, default=str)


# ── New analytical tools ───────────────────────────────────────────────────────

@mcp.tool()
def analyse_returns(
    date_from:           Annotated[str, "Start date YYYY-MM-DD. Defaults to 90 days ago."] = "",
    date_to:             Annotated[str, "End date YYYY-MM-DD. Defaults to today."] = "",
    min_dispatched_lines:Annotated[int, "Minimum dispatched lines for a SKU to be included "
                                        "(filters out thin-sample noise). Default 100."] = 100,
    top_n:               Annotated[int, "Return the top N SKUs ranked by return rate. "
                                        "Default 20, max 100."] = 20,
) -> str:
    """Analyse return rates by SKU over a date window. Computes each SKU's return rate
    vs the overall baseline, ranks by elevation, and quantifies the excess refund cost.
    Use this to identify which products are being returned at abnormally high rates and
    what the financial impact is."""
    if not date_from:
        date_from = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    if not date_to:
        date_to = datetime.now().strftime("%Y-%m-%d")
    top_n = max(1, min(top_n, 100))

    with _conn() as conn, dict_cursor(conn) as cur:
        cur.execute("""
            WITH dispatched AS (
                SELECT ol.sku,
                       COUNT(*)::int            AS dispatched_lines,
                       SUM(ol.qty_ordered)::int AS units_dispatched
                FROM   order_lines ol
                JOIN   orders o ON o.tenant_id=ol.tenant_id
                               AND o.order_number=ol.order_number
                WHERE  ol.tenant_id = %s
                AND    o.status     = 'Dispatched'
                AND    o.dispatch_date::date BETWEEN %s AND %s
                GROUP  BY ol.sku
                HAVING COUNT(*) >= %s
            ),
            returned AS (
                SELECT r.sku,
                       COUNT(*)::int                  AS return_count,
                       SUM(r.refund_amount_gbp)       AS refunds_gbp
                FROM   returns r
                WHERE  r.tenant_id = %s
                AND    r.return_date::date BETWEEN %s AND %s
                GROUP  BY r.sku
            ),
            baseline AS (
                SELECT ROUND(
                    SUM(COALESCE(r.return_count,0)) * 100.0 /
                    NULLIF(SUM(d.dispatched_lines), 0), 2
                ) AS baseline_pct,
                SUM(d.dispatched_lines)::int             AS total_dispatched,
                SUM(COALESCE(r.return_count,0))::int     AS total_returns
                FROM dispatched d LEFT JOIN returned r ON r.sku=d.sku
            )
            SELECT
                d.sku,
                COALESCE(i.style_name, d.sku)    AS style_name,
                i.category,
                d.dispatched_lines,
                COALESCE(r.return_count, 0)      AS returns,
                ROUND(COALESCE(r.return_count,0)*100.0/d.dispatched_lines, 1)
                                                 AS return_rate_pct,
                ROUND(COALESCE(r.refunds_gbp,0)::numeric, 2)
                                                 AS refunds_gbp,
                b.baseline_pct,
                b.total_dispatched,
                b.total_returns,
                ROUND(
                    COALESCE(r.return_count,0)*100.0/d.dispatched_lines /
                    NULLIF(b.baseline_pct,0), 2
                ) AS multiple_vs_baseline,
                ROUND(
                    (COALESCE(r.return_count,0)*100.0/d.dispatched_lines - b.baseline_pct)
                    / 100.0 * d.dispatched_lines
                    * COALESCE(r.refunds_gbp,0) / NULLIF(r.return_count,0)
                , 2) AS excess_refunds_gbp
            FROM dispatched d
            CROSS JOIN baseline b
            LEFT JOIN returned r ON r.sku=d.sku
            LEFT JOIN inventory i ON i.tenant_id=%s AND i.sku=d.sku AND i.site='pickface'
            ORDER BY return_rate_pct DESC
            LIMIT %s
        """, [
            _effective_tenant_id(), date_from, date_to, min_dispatched_lines,
            _effective_tenant_id(), date_from, date_to,
            _effective_tenant_id(), top_n,
        ])
        rows = cur.fetchall()

    if not rows:
        return json.dumps({"error": "No data for the specified window."})

    baseline_pct    = float(rows[0]["baseline_pct"] or 0)
    total_dispatched = int(rows[0]["total_dispatched"] or 0)
    total_returns    = int(rows[0]["total_returns"] or 0)

    skus = []
    total_excess = 0.0
    skus_above_2x = 0
    for r in rows:
        rate     = float(r["return_rate_pct"] or 0)
        multiple = float(r["multiple_vs_baseline"] or 0)
        excess   = float(r["excess_refunds_gbp"] or 0)
        total_excess += max(0, excess)
        if multiple >= 2.0:
            skus_above_2x += 1
        skus.append({
            "sku":                  r["sku"],
            "style_name":           r["style_name"],
            "category":             r["category"],
            "dispatched_lines":     int(r["dispatched_lines"]),
            "returns":              int(r["returns"]),
            "return_rate_pct":      rate,
            "refunds_gbp":          float(r["refunds_gbp"] or 0),
            "multiple_vs_baseline": multiple,
            "excess_refunds_gbp":   round(max(0, excess), 2),
            "flag":                 "HIGH" if multiple >= 1.5 else ("ELEVATED" if multiple >= 1.2 else "NORMAL"),
        })

    return json.dumps({
        "analysis_window":    {"date_from": date_from, "date_to": date_to},
        "baseline_return_rate_pct": baseline_pct,
        "total_dispatched_lines":   total_dispatched,
        "total_returns":            total_returns,
        "overall_return_rate_pct":  round(total_returns * 100.0 / total_dispatched, 2) if total_dispatched else 0,
        "skus_above_2x_baseline":   skus_above_2x,
        "total_excess_refunds_gbp": round(total_excess, 2),
        "note": (
            "excess_refunds_gbp = refund cost attributable to returns above the baseline rate. "
            "multiple_vs_baseline = this SKU's rate divided by the overall baseline."
        ),
        "sku_analysis": skus,
    }, indent=2, default=str)


@mcp.tool()
def get_stock_adjustments(
    date_from:   Annotated[str, "Start date YYYY-MM-DD. Defaults to 90 days ago."] = "",
    date_to:     Annotated[str, "End date YYYY-MM-DD. Defaults to today."] = "",
    operator_id: Annotated[str, "Filter to a specific operator ID, e.g. 'OP-041'."] = "",
    site:        Annotated[str, "Filter by site: 'pickface', 'bulk', etc."] = "",
    min_counts:  Annotated[int, "Minimum cycle count records for an operator to appear "
                                "in the ranking (default 10)."] = 10,
    page_size:   Annotated[int, "Individual adjustment records per page (1–200)."] = 50,
    page_number: Annotated[int, "Page number starting from 1."] = 1,
) -> str:
    """Query stock cycle count adjustments. Returns an operator-level discrepancy ranking
    (who is finding the most variance) alongside individual adjustment records.
    Use this to investigate stock integrity issues and identify operators whose counts
    diverge significantly from their peers."""
    if not date_from:
        date_from = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    if not date_to:
        date_to = datetime.now().strftime("%Y-%m-%d")

    page_size = max(1, min(page_size, 200))
    offset    = (page_number - 1) * page_size

    with _conn() as conn, dict_cursor(conn) as cur:
        # ── Operator ranking ───────────────────────────────────────────────────
        op_clauses = [
            "tenant_id = %s",
            "adjustment_type = 'CycleCount'",
            "adjusted_at::date BETWEEN %s AND %s",
        ]
        op_params = [_effective_tenant_id(), date_from, date_to]
        if site:
            op_clauses.append("LOWER(site) = LOWER(%s)")
            op_params.append(site)

        cur.execute(f"""
            WITH op_stats AS (
                SELECT
                    operator_id,
                    operator_name,
                    COUNT(*)::int                                                      AS total_counts,
                    SUM(CASE WHEN variance != 0 THEN 1 ELSE 0 END)::int               AS discrepancies,
                    ROUND(SUM(CASE WHEN variance!=0 THEN 1 ELSE 0 END)*100.0/COUNT(*),1)
                                                                                       AS disc_rate_pct,
                    ROUND(AVG(ABS(variance))::numeric, 2)                             AS avg_abs_variance,
                    SUM(ABS(variance))::int                                            AS total_variance_units,
                    MIN(adjusted_at)::date                                             AS first_count_date,
                    MAX(adjusted_at)::date                                             AS last_count_date
                FROM   stock_adjustments
                WHERE  {' AND '.join(op_clauses)}
                GROUP  BY operator_id, operator_name
                HAVING COUNT(*) >= %s
            ),
            fleet_avg AS (
                SELECT ROUND(AVG(disc_rate_pct), 2) AS avg_disc_rate
                FROM   op_stats
            )
            SELECT s.*, f.avg_disc_rate,
                   ROUND(s.disc_rate_pct / NULLIF(f.avg_disc_rate, 0), 2) AS multiple_vs_avg
            FROM   op_stats s CROSS JOIN fleet_avg f
            ORDER  BY disc_rate_pct DESC
        """, op_params + [min_counts])
        op_rows = cur.fetchall()

        # ── Individual adjustment records ──────────────────────────────────────
        rec_clauses = ["tenant_id = %s", "adjusted_at::date BETWEEN %s AND %s"]
        rec_params  = [_effective_tenant_id(), date_from, date_to]
        if operator_id:
            rec_clauses.append("operator_id = %s")
            rec_params.append(operator_id)
        if site:
            rec_clauses.append("LOWER(site) = LOWER(%s)")
            rec_params.append(site)

        cur.execute(
            f"SELECT COUNT(*) FROM stock_adjustments WHERE {' AND '.join(rec_clauses)}",
            rec_params,
        )
        total_records = cur.fetchone()["count"]

        cur.execute(
            f"SELECT * FROM stock_adjustments "
            f"WHERE {' AND '.join(rec_clauses)} "
            f"ORDER BY adjusted_at DESC LIMIT %s OFFSET %s",
            rec_params + [page_size, offset],
        )
        rec_rows = cur.fetchall()

    fleet_avg = float(op_rows[0]["avg_disc_rate"]) if op_rows else 0

    operator_ranking = []
    for o in op_rows:
        rate     = float(o["disc_rate_pct"] or 0)
        multiple = float(o["multiple_vs_avg"] or 0)
        operator_ranking.append({
            "operator_id":          o["operator_id"],
            "operator_name":        o["operator_name"],
            "total_counts":         int(o["total_counts"]),
            "discrepancies":        int(o["discrepancies"]),
            "discrepancy_rate_pct": rate,
            "avg_abs_variance":     float(o["avg_abs_variance"] or 0),
            "total_variance_units": int(o["total_variance_units"] or 0),
            "first_count_date":     str(o["first_count_date"]) if o["first_count_date"] else None,
            "last_count_date":      str(o["last_count_date"]) if o["last_count_date"] else None,
            "multiple_vs_avg":      multiple,
            "flag":                 "OUTLIER" if multiple >= 1.5 else ("ELEVATED" if multiple >= 1.2 else "NORMAL"),
        })

    records = []
    for a in rec_rows:
        records.append({
            "adjustment_number": a["adjustment_number"],
            "type":              a["adjustment_type"],
            "sku":               a["sku"],
            "location":          a["location"],
            "site":              a["site"],
            "qty_system":        a["qty_system"],
            "qty_counted":       a["qty_counted"],
            "variance":          a["variance"],
            "reason":            a["reason"],
            "operator_id":       a["operator_id"],
            "operator_name":     a["operator_name"],
            "adjusted_at":       a["adjusted_at"].strftime("%Y-%m-%d %H:%M") if a["adjusted_at"] else None,
            "approved_by":       a["approved_by"],
        })

    return json.dumps({
        "query": {
            "date_from": date_from, "date_to": date_to,
            "operator_id": operator_id or None,
            "site": site or None,
            "page": page_number, "page_size": page_size,
        },
        "fleet_avg_discrepancy_rate_pct": fleet_avg,
        "operator_ranking": operator_ranking,
        "total_adjustment_records": total_records,
        "returned": len(records),
        "adjustments": records,
    }, indent=2, default=str)


@mcp.tool()
def get_warehouse_health() -> str:
    """Run a proactive multi-signal health check across the warehouse.
    Returns severity-flagged signals covering return rate anomalies, pickface OOS
    with bulk stock available, cycle count integrity outliers, and today's dispatch
    progress. Use this as a starting point for a daily ops review or to surface
    issues without knowing what to look for."""
    today     = datetime.now().strftime("%Y-%m-%d")
    d90_start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    d7_start  = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    signals = []

    with _conn() as conn, dict_cursor(conn) as cur:

        # ── Signal 1: High-return-rate SKUs ───────────────────────────────────
        cur.execute("""
            WITH dispatched AS (
                SELECT ol.sku, COUNT(*)::int AS lines
                FROM order_lines ol
                JOIN orders o ON o.tenant_id=ol.tenant_id AND o.order_number=ol.order_number
                WHERE ol.tenant_id=%s AND o.status='Dispatched'
                AND o.dispatch_date::date >= %s
                GROUP BY ol.sku HAVING COUNT(*) >= 100
            ),
            returned AS (
                SELECT sku, COUNT(*)::int AS cnt, SUM(refund_amount_gbp) AS refunds
                FROM returns WHERE tenant_id=%s AND return_date::date >= %s
                GROUP BY sku
            ),
            baseline AS (
                SELECT ROUND(SUM(COALESCE(r.cnt,0))*100.0/NULLIF(SUM(d.lines),0),2) AS pct
                FROM dispatched d LEFT JOIN returned r ON r.sku=d.sku
            )
            SELECT d.sku,
                   COALESCE(i.style_name, d.sku)             AS style_name,
                   d.lines                                    AS dispatched_lines,
                   COALESCE(r.cnt, 0)                         AS returns,
                   ROUND(COALESCE(r.cnt,0)*100.0/d.lines, 1) AS rate_pct,
                   COALESCE(r.refunds, 0)                     AS refunds_gbp,
                   b.pct                                      AS baseline_pct
            FROM dispatched d CROSS JOIN baseline b
            LEFT JOIN returned r ON r.sku=d.sku
            LEFT JOIN inventory i ON i.tenant_id=%s AND i.sku=d.sku AND i.site='pickface'
            WHERE COALESCE(r.cnt,0)*100.0/d.lines > b.pct * 1.4
            ORDER BY rate_pct DESC
            LIMIT 5
        """, [_effective_tenant_id(), d90_start, _effective_tenant_id(), d90_start, _effective_tenant_id()])
        hr_rows = cur.fetchall()

        if hr_rows:
            baseline = float(hr_rows[0]["baseline_pct"] or 0)
            worst    = hr_rows[0]
            total_excess = sum(
                max(0, (float(r["rate_pct"])-baseline)/100 * int(r["dispatched_lines"])
                       * float(r["refunds_gbp"])/max(1,int(r["returns"])))
                for r in hr_rows
            )
            signals.append({
                "signal":    "HIGH_RETURN_RATE_SKUS",
                "severity":  "RED" if float(worst["rate_pct"]) > baseline * 1.5 else "AMBER",
                "headline":  (
                    f"{len(hr_rows)} SKU(s) returning at "
                    f"{float(worst['rate_pct']):.0f}% — "
                    f"{float(worst['rate_pct'])/baseline:.1f}x the {baseline:.1f}% baseline"
                ),
                "top_skus": [
                    {
                        "sku":        r["sku"],
                        "style_name": r["style_name"],
                        "rate_pct":   float(r["rate_pct"]),
                        "returns":    int(r["returns"]),
                        "refunds_gbp":float(r["refunds_gbp"]),
                    }
                    for r in hr_rows
                ],
                "estimated_excess_refunds_gbp": round(total_excess, 2),
                "recommended_action": (
                    "Review product descriptions, imagery, and sizing guides for these styles. "
                    "Check returns reason breakdown via analyse_returns for root cause."
                ),
            })

        # ── Signal 2: Pickface OOS with bulk stock available ──────────────────
        cur.execute("""
            SELECT pf.sku,
                   COALESCE(i.style_name, pf.sku)    AS style_name,
                   pf.available_qty                   AS pickface_qty,
                   pf.reorder_point,
                   b.available_qty                    AS bulk_qty,
                   pf.primary_location                AS pickface_loc,
                   (SELECT COUNT(DISTINCT o.order_number)
                    FROM order_lines ol
                    JOIN orders o ON o.tenant_id=ol.tenant_id AND o.order_number=ol.order_number
                    WHERE ol.tenant_id=pf.tenant_id AND ol.sku=pf.sku
                    AND o.status IN ('Awaiting Pick','Picking in progress')
                   ) AS stuck_orders,
                   (SELECT MAX(movement_date)::date
                    FROM stock_movements
                    WHERE tenant_id=pf.tenant_id AND sku=pf.sku
                    AND movement_type='Replenishment'
                   ) AS last_replenishment,
                   (SELECT COUNT(*)
                    FROM stock_movements
                    WHERE tenant_id=pf.tenant_id AND sku=pf.sku
                    AND movement_type='Replenishment'
                    AND movement_date >= NOW() - INTERVAL '90 days'
                   ) AS replen_events_90d
            FROM inventory pf
            JOIN inventory b ON b.tenant_id=pf.tenant_id AND b.sku=pf.sku AND b.site='bulk'
            LEFT JOIN inventory i ON i.tenant_id=pf.tenant_id AND i.sku=pf.sku AND i.site='pickface'
            WHERE pf.tenant_id = %s
            AND   pf.site = 'pickface'
            AND   pf.available_qty <= pf.reorder_point
            AND   b.available_qty >= 50
            ORDER BY pf.available_qty ASC, b.available_qty DESC
            LIMIT 10
        """, [_effective_tenant_id()])
        oos_rows = cur.fetchall()

        if oos_rows:
            total_stuck = sum(int(r["stuck_orders"] or 0) for r in oos_rows)
            signals.append({
                "signal":   "PICKFACE_OOS_BULK_AVAILABLE",
                "severity": "RED" if total_stuck > 0 else "AMBER",
                "headline": (
                    f"{len(oos_rows)} SKU(s) at or below reorder point on pickface "
                    f"with bulk stock available — {total_stuck} order(s) held up"
                ),
                "affected_skus": [
                    {
                        "sku":              r["sku"],
                        "style_name":       r["style_name"],
                        "pickface_qty":     int(r["pickface_qty"]),
                        "bulk_qty":         int(r["bulk_qty"]),
                        "stuck_orders":     int(r["stuck_orders"] or 0),
                        "last_replen":      str(r["last_replenishment"]) if r["last_replenishment"] else "None on record",
                        "replen_events_90d":int(r["replen_events_90d"] or 0),
                    }
                    for r in oos_rows
                ],
                "recommended_action": (
                    "Initiate bulk-to-pickface replenishment for affected SKUs. "
                    "Review replenishment trigger rules — frequency is below expected."
                ),
            })

        # ── Signal 3: Cycle count discrepancy outliers ────────────────────────
        cur.execute("""
            WITH op_stats AS (
                SELECT operator_id, operator_name,
                       COUNT(*)::int                                               AS counts,
                       ROUND(SUM(CASE WHEN variance!=0 THEN 1 ELSE 0 END)*100.0/COUNT(*),1)
                                                                                   AS disc_pct,
                       ROUND(AVG(ABS(variance))::numeric, 2)                      AS avg_var
                FROM   stock_adjustments
                WHERE  tenant_id=%s AND adjustment_type='CycleCount'
                AND    adjusted_at::date >= %s
                GROUP  BY operator_id, operator_name
                HAVING COUNT(*) >= 10
            ),
            avg_rate AS (SELECT ROUND(AVG(disc_pct),2) AS fleet_avg FROM op_stats)
            SELECT s.*, a.fleet_avg,
                   ROUND(s.disc_pct/NULLIF(a.fleet_avg,0),2) AS multiple
            FROM op_stats s CROSS JOIN avg_rate a
            WHERE s.disc_pct > a.fleet_avg * 1.4
            ORDER BY s.disc_pct DESC
        """, [_effective_tenant_id(), d90_start])
        cc_rows = cur.fetchall()

        if cc_rows:
            fleet_avg = float(cc_rows[0]["fleet_avg"] or 0)
            signals.append({
                "signal":   "CYCLE_COUNT_OUTLIERS",
                "severity": "AMBER",
                "headline": (
                    f"{len(cc_rows)} operator(s) with discrepancy rate "
                    f">{1.4:.0%} of the {fleet_avg:.1f}% fleet average"
                ),
                "fleet_avg_discrepancy_rate_pct": fleet_avg,
                "outlier_operators": [
                    {
                        "operator_id":   r["operator_id"],
                        "operator_name": r["operator_name"],
                        "counts":        int(r["counts"]),
                        "disc_pct":      float(r["disc_pct"]),
                        "avg_variance":  float(r["avg_var"]),
                        "multiple_vs_avg": float(r["multiple"]),
                    }
                    for r in cc_rows
                ],
                "recommended_action": (
                    "Review recent adjustments for outlier operators. "
                    "Cross-check affected bin locations against physical stock. "
                    "Consider refresher training if operator is recently hired."
                ),
            })

        # ── Signal 4: Today's dispatch progress ───────────────────────────────
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE status='Dispatched')::int        AS dispatched_today,
                COUNT(*) FILTER (WHERE status != 'Dispatched'
                                  AND status != 'Cancelled'
                                  AND status != 'On Hold')::int          AS in_flight,
                COUNT(*) FILTER (WHERE status='Cancelled')::int          AS cancelled_today,
                COUNT(*)::int                                             AS total_today
            FROM orders
            WHERE tenant_id=%s AND order_date::date = %s
        """, [_effective_tenant_id(), today])
        today_row = cur.fetchone()

        cur.execute("""
            SELECT ROUND(AVG(daily_dispatched),0)::int AS avg_dispatched
            FROM (
                SELECT order_date::date AS d, COUNT(*)::int AS daily_dispatched
                FROM orders
                WHERE tenant_id=%s AND status='Dispatched'
                AND order_date::date BETWEEN %s AND %s
                GROUP BY 1
            ) sub
        """, [_effective_tenant_id(), d7_start, today])
        avg_row = cur.fetchone()

        if today_row:
            dispatched  = int(today_row["dispatched_today"] or 0)
            in_flight   = int(today_row["in_flight"] or 0)
            total_today = int(today_row["total_today"] or 0)
            avg_7d      = int(avg_row["avg_dispatched"] or 0) if avg_row else 0
            pct_done    = round(dispatched / total_today * 100, 1) if total_today else 0
            signals.append({
                "signal":   "DISPATCH_PROGRESS",
                "severity": "GREEN" if pct_done >= 80 else ("AMBER" if pct_done >= 50 else "RED"),
                "headline": (
                    f"{dispatched} of {total_today} today's orders dispatched "
                    f"({pct_done}%) — {in_flight} still in flight"
                ),
                "dispatched_today":  dispatched,
                "in_flight":         in_flight,
                "total_orders_today":total_today,
                "pct_complete":      pct_done,
                "avg_dispatched_last_7d": avg_7d,
                "vs_7d_avg": f"{'+' if dispatched >= avg_7d else ''}{dispatched - avg_7d}",
            })

    red_count   = sum(1 for s in signals if s["severity"] == "RED")
    amber_count = sum(1 for s in signals if s["severity"] == "AMBER")
    green_count = sum(1 for s in signals if s["severity"] == "GREEN")

    return json.dumps({
        "as_of": today,
        "summary": {
            "red":   red_count,
            "amber": amber_count,
            "green": green_count,
            "total_signals": len(signals),
        },
        "signals": signals,
    }, indent=2, default=str)


# Entry point: use `uvicorn app:app` (or `python app.py`) — not this file directly.
# This module defines tools only; app.py wraps them in FastAPI with HTTP transport.
