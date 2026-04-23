#!/usr/bin/env python3
"""
Peoplevox → Supabase sync job.

Pulls every template from the mock server and upserts into the canonical
database. Run directly for a one-off sync; use scheduler.py for the
recurring 15-minute job.

  py -3 sync_pvx.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import date, datetime

import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

from db_client import ARIA_TENANT_ID, get_conn
from pvx_connector import PeoplevoxConnector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _pvx() -> PeoplevoxConnector:
    return PeoplevoxConnector(
        base_url=os.environ["PVX_BASE_URL"],
        company_id=os.environ["PVX_COMPANY_ID"],
        username=os.environ["PVX_USERNAME"],
        password=os.environ["PVX_PASSWORD"],
    )


def _fetch_all(pvx: PeoplevoxConnector, template: str, **kwargs) -> list[dict]:
    items, page = [], 1
    while True:
        r = pvx.get_data(template, page_size=500, page_number=page, **kwargs)
        items.extend(r["items"])
        if len(items) >= r["total"]:
            break
        page += 1
    return items


def _int(v) -> int | None:
    try:
        return int(v) if v not in (None, "", "None") else None
    except (TypeError, ValueError):
        return None


def _float(v) -> float | None:
    try:
        return float(v) if v not in (None, "", "None") else None
    except (TypeError, ValueError):
        return None


def _dt(v: str) -> datetime | None:
    if not v:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(v[:19], fmt)
        except ValueError:
            pass
    return None


def _date(v: str) -> date | None:
    if not v:
        return None
    try:
        return datetime.strptime(v[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _log_sync(conn, template: str, records: int, ms: int, status: str, error: str | None = None):
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO sync_log
                   (tenant_id, template, records_upserted, duration_ms, status, error_message)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (ARIA_TENANT_ID, template, records, ms, status, error),
        )
    conn.commit()


def _upsert(conn, sql: str, rows: list[tuple], batch: int = 500) -> int:
    """Bulk upsert in batches; returns total rows processed."""
    total = 0
    with conn.cursor() as cur:
        for i in range(0, len(rows), batch):
            chunk = rows[i : i + batch]
            psycopg2.extras.execute_values(cur, sql, chunk, page_size=batch)
            total += len(chunk)
    conn.commit()
    return total


# ── Sync functions ─────────────────────────────────────────────────────────────

def sync_operators(pvx: PeoplevoxConnector, conn) -> int:
    t0    = time.monotonic()
    items = _fetch_all(pvx, "Operators")
    rows  = [
        (
            ARIA_TENANT_ID,
            o.get("OperatorId", ""),
            o.get("OperatorName", ""),
            o.get("Role", ""),
            o.get("Shift", ""),
        )
        for o in items
    ]
    sql = """
        INSERT INTO operators (tenant_id, operator_id, name, role, shift)
        VALUES %s
        ON CONFLICT (tenant_id, operator_id) DO UPDATE SET
            name      = EXCLUDED.name,
            role      = EXCLUDED.role,
            shift     = EXCLUDED.shift,
            synced_at = NOW()
    """
    n = _upsert(conn, sql, rows)
    _log_sync(conn, "Operators", n, int((time.monotonic() - t0) * 1000), "success")
    log.info("operators        %4d upserted", n)
    return n


def sync_locations(pvx: PeoplevoxConnector, conn) -> int:
    t0    = time.monotonic()
    items = _fetch_all(pvx, "Locations")
    rows  = [
        (
            ARIA_TENANT_ID,
            l.get("LocationReference", ""),
            l.get("Zone", ""),
            l.get("Aisle", ""),
            l.get("Bay", ""),
            l.get("Level", ""),
            l.get("LocationType", ""),
            _int(l.get("PickSequence")),
            _float(l.get("MaxWeightKg")),
            l.get("IsActive", "true").lower() == "true",
        )
        for l in items
    ]
    sql = """
        INSERT INTO locations
            (tenant_id, reference, zone, aisle, bay, level,
             location_type, pick_sequence, max_weight_kg, is_active)
        VALUES %s
        ON CONFLICT (tenant_id, reference) DO UPDATE SET
            zone          = EXCLUDED.zone,
            aisle         = EXCLUDED.aisle,
            bay           = EXCLUDED.bay,
            level         = EXCLUDED.level,
            location_type = EXCLUDED.location_type,
            pick_sequence = EXCLUDED.pick_sequence,
            max_weight_kg = EXCLUDED.max_weight_kg,
            is_active     = EXCLUDED.is_active,
            synced_at     = NOW()
    """
    n = _upsert(conn, sql, rows)
    _log_sync(conn, "Locations", n, int((time.monotonic() - t0) * 1000), "success")
    log.info("locations        %4d upserted", n)
    return n


def sync_inventory(pvx: PeoplevoxConnector, conn) -> int:
    t0    = time.monotonic()
    items = _fetch_all(pvx, "ItemStock")
    rows  = [
        (
            ARIA_TENANT_ID,
            i.get("ItemCode", ""),
            i.get("StyleCode", ""),
            i.get("ItemName", "").split("—")[0].strip(),
            i.get("Colour", ""),
            i.get("Size", ""),
            i.get("SizeType", ""),
            i.get("Category", ""),
            i.get("Barcode", ""),
            _float(i.get("WeightKg")),
            _float(i.get("SellingPrice")),
            _int(i.get("AvailableQuantity")) or 0,
            _int(i.get("AllocatedQuantity")) or 0,
            _int(i.get("OnOrderQuantity")) or 0,
            i.get("PrimaryLocation", ""),
            _int(i.get("ReorderPoint")) or 12,
            "pickface",
        )
        for i in items
    ]
    sql = """
        INSERT INTO inventory
            (tenant_id, sku, style_code, style_name, colour, size, size_type,
             category, barcode, weight_kg, selling_price_gbp,
             available_qty, allocated_qty, on_order_qty,
             primary_location, reorder_point, site)
        VALUES %s
        ON CONFLICT (tenant_id, sku, site) DO UPDATE SET
            style_code        = EXCLUDED.style_code,
            style_name        = EXCLUDED.style_name,
            colour            = EXCLUDED.colour,
            size              = EXCLUDED.size,
            size_type         = EXCLUDED.size_type,
            category          = EXCLUDED.category,
            barcode           = EXCLUDED.barcode,
            weight_kg         = EXCLUDED.weight_kg,
            selling_price_gbp = EXCLUDED.selling_price_gbp,
            available_qty     = EXCLUDED.available_qty,
            allocated_qty     = EXCLUDED.allocated_qty,
            on_order_qty      = EXCLUDED.on_order_qty,
            primary_location  = EXCLUDED.primary_location,
            reorder_point     = EXCLUDED.reorder_point,
            synced_at         = NOW()
    """
    n = _upsert(conn, sql, rows)
    _log_sync(conn, "ItemStock", n, int((time.monotonic() - t0) * 1000), "success")
    log.info("inventory        %4d upserted", n)
    return n


def sync_orders(pvx: PeoplevoxConnector, conn) -> int:
    t0    = time.monotonic()
    items = _fetch_all(pvx, "SalesOrders")

    order_rows = [
        (
            ARIA_TENANT_ID,
            o.get("OrderNumber", ""),
            o.get("SalesChannel", ""),
            _dt(o.get("OrderDate", "")),
            _dt(o.get("DespatchDate", "")),
            o.get("CustomerName", ""),
            o.get("CustomerEmail", ""),
            o.get("CustomerPhone", ""),
            o.get("ShippingAddress1", ""),
            o.get("ShippingCity", ""),
            o.get("ShippingPostcode", ""),
            o.get("ShippingCountry", ""),
            o.get("CarrierName", ""),
            o.get("TrackingNumber", ""),
            o.get("OrderStatus", ""),
            _float(o.get("TotalOrderValue")) or 0.0,
            _int(o.get("NumberOfLines")) or 0,
        )
        for o in items
    ]
    order_sql = """
        INSERT INTO orders
            (tenant_id, order_number, channel, order_date, dispatch_date,
             customer_name, customer_email, customer_phone,
             shipping_address1, shipping_city, shipping_postcode, shipping_country,
             carrier, tracking_number, status, total_value_gbp, line_count)
        VALUES %s
        ON CONFLICT (tenant_id, order_number) DO UPDATE SET
            channel           = EXCLUDED.channel,
            order_date        = EXCLUDED.order_date,
            dispatch_date     = EXCLUDED.dispatch_date,
            customer_name     = EXCLUDED.customer_name,
            customer_email    = EXCLUDED.customer_email,
            customer_phone    = EXCLUDED.customer_phone,
            shipping_address1 = EXCLUDED.shipping_address1,
            shipping_city     = EXCLUDED.shipping_city,
            shipping_postcode = EXCLUDED.shipping_postcode,
            shipping_country  = EXCLUDED.shipping_country,
            carrier           = EXCLUDED.carrier,
            tracking_number   = EXCLUDED.tracking_number,
            status            = EXCLUDED.status,
            total_value_gbp   = EXCLUDED.total_value_gbp,
            line_count        = EXCLUDED.line_count,
            synced_at         = NOW()
    """
    n_orders = _upsert(conn, order_sql, order_rows)

    # Order lines — flatten from nested SalesOrderLines
    line_rows = []
    for o in items:
        order_num = o.get("OrderNumber", "")
        raw_lines = o.get("SalesOrderLines", [])
        if not isinstance(raw_lines, list):
            raw_lines = [raw_lines] if raw_lines else []
        for ln in raw_lines:
            if not isinstance(ln, dict):
                continue
            line_rows.append((
                ARIA_TENANT_ID,
                order_num,
                ln.get("LineNumber", ""),
                ln.get("ItemCode", ""),
                ln.get("ItemName", ""),
                _int(ln.get("QuantityOrdered")),
                _int(ln.get("QuantityDespatched")),
                _float(ln.get("UnitSellingPrice")),
                _float(ln.get("TotalLineValue")),
            ))
    line_sql = """
        INSERT INTO order_lines
            (tenant_id, order_number, line_number, sku, item_name,
             qty_ordered, qty_despatched, unit_price_gbp, total_line_value_gbp)
        VALUES %s
        ON CONFLICT (tenant_id, order_number, line_number) DO UPDATE SET
            sku                  = EXCLUDED.sku,
            item_name            = EXCLUDED.item_name,
            qty_ordered          = EXCLUDED.qty_ordered,
            qty_despatched       = EXCLUDED.qty_despatched,
            unit_price_gbp       = EXCLUDED.unit_price_gbp,
            total_line_value_gbp = EXCLUDED.total_line_value_gbp,
            synced_at            = NOW()
    """
    n_lines = _upsert(conn, line_sql, line_rows)
    ms      = int((time.monotonic() - t0) * 1000)
    _log_sync(conn, "SalesOrders", n_orders, ms, "success")
    log.info("orders           %4d upserted  (%d lines)", n_orders, n_lines)
    return n_orders


def sync_movements(pvx: PeoplevoxConnector, conn) -> int:
    t0    = time.monotonic()
    items = _fetch_all(pvx, "StockMovements")
    rows  = [
        (
            ARIA_TENANT_ID,
            m.get("Reference", ""),
            m.get("MovementType", ""),
            m.get("ItemCode", ""),
            m.get("ItemName", ""),
            _int(m.get("Quantity")),
            m.get("FromLocation", ""),
            m.get("ToLocation", ""),
            _dt(m.get("MovementDate", "")),
            m.get("Operator", ""),
            m.get("OperatorName", ""),
            m.get("Notes", ""),
        )
        for m in items
    ]
    sql = """
        INSERT INTO stock_movements
            (tenant_id, reference, movement_type, sku, item_name,
             quantity, from_location, to_location, movement_date,
             operator_id, operator_name, notes)
        VALUES %s
        ON CONFLICT (tenant_id, reference) DO UPDATE SET
            movement_type = EXCLUDED.movement_type,
            sku           = EXCLUDED.sku,
            item_name     = EXCLUDED.item_name,
            quantity      = EXCLUDED.quantity,
            from_location = EXCLUDED.from_location,
            to_location   = EXCLUDED.to_location,
            movement_date = EXCLUDED.movement_date,
            operator_id   = EXCLUDED.operator_id,
            operator_name = EXCLUDED.operator_name,
            notes         = EXCLUDED.notes,
            synced_at     = NOW()
    """
    n = _upsert(conn, sql, rows)
    _log_sync(conn, "StockMovements", n, int((time.monotonic() - t0) * 1000), "success")
    log.info("stock_movements  %4d upserted", n)
    return n


def sync_returns(pvx: PeoplevoxConnector, conn) -> int:
    t0    = time.monotonic()
    items = _fetch_all(pvx, "Returns")
    rows  = [
        (
            ARIA_TENANT_ID,
            r.get("ReturnNumber", ""),
            r.get("OriginalOrderNumber", ""),
            _dt(r.get("ReturnDate", "")),
            r.get("ItemCode", ""),
            r.get("ItemName", ""),
            _int(r.get("QuantityReturned")),
            r.get("ReturnReason", ""),
            r.get("ItemCondition", ""),
            r.get("Grade", ""),
            r.get("GradeDescription", ""),
            r.get("Disposition", ""),
            r.get("ProcessingBay", ""),
            r.get("ProcessingOperator", ""),
            _int(r.get("ProcessingMinutes")),
            r.get("Status", ""),
            r.get("CustomerName", ""),
            r.get("CustomerEmail", ""),
            _float(r.get("RefundAmount")),
            r.get("TrackingNumber", ""),
        )
        for r in items
    ]
    sql = """
        INSERT INTO returns
            (tenant_id, return_number, original_order_number, return_date,
             sku, item_name, qty_returned, return_reason, item_condition,
             grade, grade_description, disposition,
             processing_bay, processing_operator_id, processing_minutes,
             status, customer_name, customer_email, refund_amount_gbp, tracking_number)
        VALUES %s
        ON CONFLICT (tenant_id, return_number) DO UPDATE SET
            return_date            = EXCLUDED.return_date,
            sku                    = EXCLUDED.sku,
            item_name              = EXCLUDED.item_name,
            qty_returned           = EXCLUDED.qty_returned,
            return_reason          = EXCLUDED.return_reason,
            item_condition         = EXCLUDED.item_condition,
            grade                  = EXCLUDED.grade,
            grade_description      = EXCLUDED.grade_description,
            disposition            = EXCLUDED.disposition,
            processing_bay         = EXCLUDED.processing_bay,
            processing_operator_id = EXCLUDED.processing_operator_id,
            processing_minutes     = EXCLUDED.processing_minutes,
            status                 = EXCLUDED.status,
            customer_name          = EXCLUDED.customer_name,
            customer_email         = EXCLUDED.customer_email,
            refund_amount_gbp      = EXCLUDED.refund_amount_gbp,
            tracking_number        = EXCLUDED.tracking_number,
            synced_at              = NOW()
    """
    n = _upsert(conn, sql, rows)
    _log_sync(conn, "Returns", n, int((time.monotonic() - t0) * 1000), "success")
    log.info("returns          %4d upserted", n)
    return n


def sync_inbound_shipments(pvx: PeoplevoxConnector, conn) -> int:
    t0    = time.monotonic()
    items = _fetch_all(pvx, "InboundShipments")

    shipment_rows = [
        (
            ARIA_TENANT_ID,
            s.get("ASNNumber", ""),
            s.get("PONumber", ""),
            s.get("SupplierCode", ""),
            s.get("SupplierName", ""),
            s.get("SupplierCountry", ""),
            _date(s.get("ExpectedDate", "")),
            _date(s.get("ActualDate", "")),
            s.get("Status", ""),
            s.get("DockDoor", ""),
            _int(s.get("HandlingUnits")),
            _int(s.get("TotalCartons")),
            _int(s.get("TotalUnitsOrdered")),
            _int(s.get("TotalUnitsReceived")),
            s.get("Operator", ""),
            s.get("OperatorName", ""),
            _int(s.get("NumberOfLines")),
        )
        for s in items
    ]
    shipment_sql = """
        INSERT INTO inbound_shipments
            (tenant_id, asn_number, po_number, supplier_code, supplier_name,
             supplier_country, expected_date, actual_date, status, dock_door,
             handling_units, total_cartons, total_units_ordered,
             total_units_received, operator_id, operator_name, line_count)
        VALUES %s
        ON CONFLICT (tenant_id, asn_number) DO UPDATE SET
            po_number            = EXCLUDED.po_number,
            supplier_code        = EXCLUDED.supplier_code,
            supplier_name        = EXCLUDED.supplier_name,
            supplier_country     = EXCLUDED.supplier_country,
            expected_date        = EXCLUDED.expected_date,
            actual_date          = EXCLUDED.actual_date,
            status               = EXCLUDED.status,
            dock_door            = EXCLUDED.dock_door,
            handling_units       = EXCLUDED.handling_units,
            total_cartons        = EXCLUDED.total_cartons,
            total_units_ordered  = EXCLUDED.total_units_ordered,
            total_units_received = EXCLUDED.total_units_received,
            operator_id          = EXCLUDED.operator_id,
            operator_name        = EXCLUDED.operator_name,
            line_count           = EXCLUDED.line_count,
            synced_at            = NOW()
    """
    n_shipments = _upsert(conn, shipment_sql, shipment_rows)

    # Shipment lines
    line_rows = []
    for s in items:
        asn = s.get("ASNNumber", "")
        raw = s.get("ShipmentLines", [])
        if not isinstance(raw, list):
            raw = [raw] if raw else []
        for ln in raw:
            if not isinstance(ln, dict):
                continue
            line_rows.append((
                ARIA_TENANT_ID,
                asn,
                ln.get("LineNumber", ""),
                ln.get("ItemCode", ""),
                ln.get("ItemName", ""),
                ln.get("Colour", ""),
                ln.get("Size", ""),
                _int(ln.get("QuantityOrdered")),
                _int(ln.get("QuantityReceived")),
                _int(ln.get("Variance")),
                _float(ln.get("UnitCostGBP")),
                ln.get("PutAwayLocation", ""),
            ))
    line_sql = """
        INSERT INTO inbound_shipment_lines
            (tenant_id, asn_number, line_number, sku, item_name, colour, size,
             qty_ordered, qty_received, variance, unit_cost_gbp, put_away_location)
        VALUES %s
        ON CONFLICT (tenant_id, asn_number, line_number) DO UPDATE SET
            sku               = EXCLUDED.sku,
            item_name         = EXCLUDED.item_name,
            colour            = EXCLUDED.colour,
            size              = EXCLUDED.size,
            qty_ordered       = EXCLUDED.qty_ordered,
            qty_received      = EXCLUDED.qty_received,
            variance          = EXCLUDED.variance,
            unit_cost_gbp     = EXCLUDED.unit_cost_gbp,
            put_away_location = EXCLUDED.put_away_location,
            synced_at         = NOW()
    """
    n_lines = _upsert(conn, line_sql, line_rows)
    ms      = int((time.monotonic() - t0) * 1000)
    _log_sync(conn, "InboundShipments", n_shipments, ms, "success")
    log.info("inbound_shipments %3d upserted  (%d lines)", n_shipments, n_lines)
    return n_shipments


def sync_packing_stations(pvx: PeoplevoxConnector, conn) -> int:
    t0    = time.monotonic()
    items = _fetch_all(pvx, "PackingStations")
    rows  = [
        (
            ARIA_TENANT_ID,
            s.get("StationId", ""),
            s.get("OperatorId", ""),
            s.get("OperatorName", ""),
            s.get("Shift", ""),
            _dt(s.get("ShiftStart", "")),
            s.get("Status", ""),
            _int(s.get("OrdersPackedToday")) or 0,
            _int(s.get("UnitsPackedToday")) or 0,
            _int(s.get("AvgPackTimeSecs")),
            s.get("LastOrderPacked", ""),
            _dt(s.get("LastActivity", "")),
            _int(s.get("VoidFillBagsUsed")),
            _int(s.get("LabelsPrinted")),
            _int(s.get("ErrorsToday")) or 0,
        )
        for s in items
    ]
    sql = """
        INSERT INTO packing_stations
            (tenant_id, station_id, operator_id, operator_name, shift, shift_start,
             status, orders_packed_today, units_packed_today, avg_pack_time_secs,
             last_order_packed, last_activity, void_fill_bags_used,
             labels_printed, errors_today)
        VALUES %s
        ON CONFLICT (tenant_id, station_id) DO UPDATE SET
            operator_id         = EXCLUDED.operator_id,
            operator_name       = EXCLUDED.operator_name,
            shift               = EXCLUDED.shift,
            shift_start         = EXCLUDED.shift_start,
            status              = EXCLUDED.status,
            orders_packed_today = EXCLUDED.orders_packed_today,
            units_packed_today  = EXCLUDED.units_packed_today,
            avg_pack_time_secs  = EXCLUDED.avg_pack_time_secs,
            last_order_packed   = EXCLUDED.last_order_packed,
            last_activity       = EXCLUDED.last_activity,
            void_fill_bags_used = EXCLUDED.void_fill_bags_used,
            labels_printed      = EXCLUDED.labels_printed,
            errors_today        = EXCLUDED.errors_today,
            synced_at           = NOW()
    """
    n = _upsert(conn, sql, rows)
    _log_sync(conn, "PackingStations", n, int((time.monotonic() - t0) * 1000), "success")
    log.info("packing_stations  %3d upserted", n)
    return n


def sync_pick_jobs(pvx: PeoplevoxConnector, conn) -> int:
    t0    = time.monotonic()
    items = _fetch_all(pvx, "PickJobs")
    rows  = []
    for j in items:
        raw_lines = j.get("PickLines", [])
        if not isinstance(raw_lines, list):
            raw_lines = [raw_lines] if raw_lines else []
        # Normalise each line dict (string values from XML)
        lines_json = json.dumps([
            {
                "line":      ln.get("Line", ""),
                "sku":       ln.get("ItemCode", ""),
                "qty":       _int(ln.get("Quantity")),
                "location":  ln.get("Location", ""),
                "pick_seq":  _int(ln.get("PickSequence")),
                "picked":    ln.get("Picked", "false").lower() == "true",
            }
            for ln in raw_lines if isinstance(ln, dict)
        ])
        rows.append((
            ARIA_TENANT_ID,
            j.get("JobId", ""),
            j.get("OrderNumber", ""),
            j.get("Channel", ""),
            j.get("PickerId", ""),
            j.get("PickerName", ""),
            j.get("Status", ""),
            _int(j.get("TotalLines")),
            _int(j.get("LinesPicked")) or 0,
            _dt(j.get("AssignedAt", "")),
            _dt(j.get("StartedAt", "")),
            j.get("Carrier", ""),
            j.get("PickZone", ""),
            lines_json,
        ))
    sql = """
        INSERT INTO pick_jobs
            (tenant_id, job_id, order_number, channel, picker_id, picker_name,
             status, total_lines, lines_picked, assigned_at, started_at,
             carrier, pick_zone, lines)
        VALUES %s
        ON CONFLICT (tenant_id, job_id) DO UPDATE SET
            order_number = EXCLUDED.order_number,
            channel      = EXCLUDED.channel,
            picker_id    = EXCLUDED.picker_id,
            picker_name  = EXCLUDED.picker_name,
            status       = EXCLUDED.status,
            total_lines  = EXCLUDED.total_lines,
            lines_picked = EXCLUDED.lines_picked,
            assigned_at  = EXCLUDED.assigned_at,
            started_at   = EXCLUDED.started_at,
            carrier      = EXCLUDED.carrier,
            pick_zone    = EXCLUDED.pick_zone,
            lines        = EXCLUDED.lines::JSONB,
            synced_at    = NOW()
    """
    n = _upsert(conn, sql, rows)
    _log_sync(conn, "PickJobs", n, int((time.monotonic() - t0) * 1000), "success")
    log.info("pick_jobs         %3d upserted", n)
    return n


# ── Orchestrator ───────────────────────────────────────────────────────────────

def sync_all() -> dict[str, int]:
    log.info("── sync started ──────────────────────────────")
    t0  = time.monotonic()
    pvx = _pvx()
    conn = get_conn()
    try:
        results = {
            "operators":         sync_operators(pvx, conn),
            "locations":         sync_locations(pvx, conn),
            "inventory":         sync_inventory(pvx, conn),
            "orders":            sync_orders(pvx, conn),
            "stock_movements":   sync_movements(pvx, conn),
            "returns":           sync_returns(pvx, conn),
            "inbound_shipments": sync_inbound_shipments(pvx, conn),
            "packing_stations":  sync_packing_stations(pvx, conn),
            "pick_jobs":         sync_pick_jobs(pvx, conn),
        }
    except Exception as exc:
        log.error("sync failed: %s", exc, exc_info=True)
        try:
            _log_sync(conn, "ALL", 0, int((time.monotonic() - t0) * 1000), "error", str(exc))
        except Exception:
            pass
        raise
    finally:
        conn.close()

    total = sum(results.values())
    log.info("── sync complete  %d records  %.1fs ──────────",
             total, time.monotonic() - t0)
    return results


if __name__ == "__main__":
    sync_all()
