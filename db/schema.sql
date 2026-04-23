-- ============================================================
-- Warehouse Intelligence — canonical schema
-- Run once in Supabase SQL Editor (Dashboard → SQL Editor → New query)
-- ============================================================

-- ── Tenants ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tenants (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT        NOT NULL,
    slug        TEXT        NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO tenants (id, name, slug)
VALUES ('00000000-0000-0000-0000-000000000001', 'Aria London', 'aria-london')
ON CONFLICT (id) DO NOTHING;

-- ── Operators ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS operators (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID        NOT NULL REFERENCES tenants(id),
    operator_id  TEXT        NOT NULL,
    name         TEXT        NOT NULL,
    role         TEXT,
    shift        TEXT,
    synced_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, operator_id)
);

-- ── Locations ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS locations (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id),
    reference       TEXT        NOT NULL,
    zone            TEXT        NOT NULL,
    aisle           TEXT,
    bay             TEXT,
    level           TEXT,
    location_type   TEXT,
    pick_sequence   INTEGER,
    max_weight_kg   NUMERIC(8,2),
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, reference)
);

CREATE INDEX IF NOT EXISTS idx_locations_zone ON locations (tenant_id, zone);

-- ── Inventory ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS inventory (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID        NOT NULL REFERENCES tenants(id),
    sku                 TEXT        NOT NULL,
    style_code          TEXT,
    style_name          TEXT,
    colour              TEXT,
    size                TEXT,
    size_type           TEXT,
    category            TEXT,
    barcode             TEXT,
    weight_kg           NUMERIC(6,3),
    selling_price_gbp   NUMERIC(10,2),
    available_qty       INTEGER     NOT NULL DEFAULT 0,
    allocated_qty       INTEGER     NOT NULL DEFAULT 0,
    total_qty           INTEGER     GENERATED ALWAYS AS (available_qty + allocated_qty) STORED,
    on_order_qty        INTEGER     NOT NULL DEFAULT 0,
    primary_location    TEXT,
    reorder_point       INTEGER     NOT NULL DEFAULT 12,
    synced_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, sku)
);

CREATE INDEX IF NOT EXISTS idx_inventory_category  ON inventory (tenant_id, category);
CREATE INDEX IF NOT EXISTS idx_inventory_sku        ON inventory (tenant_id, sku);
CREATE INDEX IF NOT EXISTS idx_inventory_low_stock  ON inventory (tenant_id, available_qty)
    WHERE available_qty <= reorder_point;

-- ── Orders ────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS orders (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID        NOT NULL REFERENCES tenants(id),
    order_number        TEXT        NOT NULL,
    channel             TEXT,
    order_date          TIMESTAMPTZ,
    dispatch_date       TIMESTAMPTZ,
    customer_name       TEXT,
    customer_email      TEXT,
    customer_phone      TEXT,
    shipping_address1   TEXT,
    shipping_city       TEXT,
    shipping_postcode   TEXT,
    shipping_country    TEXT,
    carrier             TEXT,
    tracking_number     TEXT,
    status              TEXT,
    total_value_gbp     NUMERIC(10,2),
    line_count          INTEGER,
    synced_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, order_number)
);

CREATE INDEX IF NOT EXISTS idx_orders_date    ON orders (tenant_id, order_date DESC);
CREATE INDEX IF NOT EXISTS idx_orders_status  ON orders (tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_orders_channel ON orders (tenant_id, channel);
CREATE INDEX IF NOT EXISTS idx_orders_email   ON orders (tenant_id, customer_email);

-- ── Order lines ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS order_lines (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID        NOT NULL REFERENCES tenants(id),
    order_number            TEXT        NOT NULL,
    line_number             TEXT        NOT NULL,
    sku                     TEXT,
    item_name               TEXT,
    qty_ordered             INTEGER,
    qty_despatched          INTEGER,
    unit_price_gbp          NUMERIC(10,2),
    total_line_value_gbp    NUMERIC(10,2),
    synced_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, order_number, line_number),
    FOREIGN KEY (tenant_id, order_number) REFERENCES orders (tenant_id, order_number) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_order_lines_order ON order_lines (tenant_id, order_number);
CREATE INDEX IF NOT EXISTS idx_order_lines_sku   ON order_lines (tenant_id, sku);

-- ── Stock movements ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS stock_movements (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id),
    reference       TEXT        NOT NULL,
    movement_type   TEXT,
    sku             TEXT,
    item_name       TEXT,
    quantity        INTEGER,
    from_location   TEXT,
    to_location     TEXT,
    movement_date   TIMESTAMPTZ,
    operator_id     TEXT,
    operator_name   TEXT,
    notes           TEXT,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, reference)
);

CREATE INDEX IF NOT EXISTS idx_movements_date ON stock_movements (tenant_id, movement_date DESC);
CREATE INDEX IF NOT EXISTS idx_movements_sku  ON stock_movements (tenant_id, sku);
CREATE INDEX IF NOT EXISTS idx_movements_type ON stock_movements (tenant_id, movement_type);

-- ── Returns ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS returns (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID        NOT NULL REFERENCES tenants(id),
    return_number           TEXT        NOT NULL,
    original_order_number   TEXT,
    return_date             TIMESTAMPTZ,
    sku                     TEXT,
    item_name               TEXT,
    qty_returned            INTEGER,
    return_reason           TEXT,
    item_condition          TEXT,
    grade                   TEXT,
    grade_description       TEXT,
    disposition             TEXT,
    processing_bay          TEXT,
    processing_operator_id  TEXT,
    processing_minutes      INTEGER,
    status                  TEXT,
    customer_name           TEXT,
    customer_email          TEXT,
    refund_amount_gbp       NUMERIC(10,2),
    tracking_number         TEXT,
    synced_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, return_number)
);

CREATE INDEX IF NOT EXISTS idx_returns_date         ON returns (tenant_id, return_date DESC);
CREATE INDEX IF NOT EXISTS idx_returns_sku          ON returns (tenant_id, sku);
CREATE INDEX IF NOT EXISTS idx_returns_grade        ON returns (tenant_id, grade);
CREATE INDEX IF NOT EXISTS idx_returns_disposition  ON returns (tenant_id, disposition);

-- ── Inbound shipments ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS inbound_shipments (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID        NOT NULL REFERENCES tenants(id),
    asn_number              TEXT        NOT NULL,
    po_number               TEXT,
    supplier_code           TEXT,
    supplier_name           TEXT,
    supplier_country        TEXT,
    expected_date           DATE,
    actual_date             DATE,
    status                  TEXT,
    dock_door               TEXT,
    handling_units          INTEGER,
    total_cartons           INTEGER,
    total_units_ordered     INTEGER,
    total_units_received    INTEGER,
    operator_id             TEXT,
    operator_name           TEXT,
    line_count              INTEGER,
    synced_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, asn_number)
);

CREATE INDEX IF NOT EXISTS idx_inbound_expected ON inbound_shipments (tenant_id, expected_date DESC);
CREATE INDEX IF NOT EXISTS idx_inbound_status   ON inbound_shipments (tenant_id, status);

-- ── Inbound shipment lines ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS inbound_shipment_lines (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id),
    asn_number      TEXT        NOT NULL,
    line_number     TEXT        NOT NULL,
    sku             TEXT,
    item_name       TEXT,
    colour          TEXT,
    size            TEXT,
    qty_ordered     INTEGER,
    qty_received    INTEGER,
    variance        INTEGER,
    unit_cost_gbp   NUMERIC(10,2),
    put_away_location TEXT,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, asn_number, line_number),
    FOREIGN KEY (tenant_id, asn_number) REFERENCES inbound_shipments (tenant_id, asn_number) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_inbound_lines_asn ON inbound_shipment_lines (tenant_id, asn_number);
CREATE INDEX IF NOT EXISTS idx_inbound_lines_sku ON inbound_shipment_lines (tenant_id, sku);

-- ── Packing stations ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS packing_stations (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID        NOT NULL REFERENCES tenants(id),
    station_id              TEXT        NOT NULL,
    operator_id             TEXT,
    operator_name           TEXT,
    shift                   TEXT,
    shift_start             TIMESTAMPTZ,
    status                  TEXT,
    orders_packed_today     INTEGER     NOT NULL DEFAULT 0,
    units_packed_today      INTEGER     NOT NULL DEFAULT 0,
    avg_pack_time_secs      INTEGER,
    last_order_packed       TEXT,
    last_activity           TIMESTAMPTZ,
    void_fill_bags_used     INTEGER,
    labels_printed          INTEGER,
    errors_today            INTEGER     NOT NULL DEFAULT 0,
    synced_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, station_id)
);

-- ── Pick jobs ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS pick_jobs (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id),
    job_id          TEXT        NOT NULL,
    order_number    TEXT,
    channel         TEXT,
    picker_id       TEXT,
    picker_name     TEXT,
    status          TEXT,
    total_lines     INTEGER,
    lines_picked    INTEGER     NOT NULL DEFAULT 0,
    assigned_at     TIMESTAMPTZ,
    started_at      TIMESTAMPTZ,
    carrier         TEXT,
    pick_zone       TEXT,
    lines           JSONB,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, job_id)
);

CREATE INDEX IF NOT EXISTS idx_pick_jobs_status ON pick_jobs (tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_pick_jobs_picker ON pick_jobs (tenant_id, picker_id);

-- ── Sync log ──────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sync_log (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID        NOT NULL REFERENCES tenants(id),
    run_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    template            TEXT        NOT NULL,
    records_upserted    INTEGER     NOT NULL DEFAULT 0,
    duration_ms         INTEGER,
    status              TEXT        NOT NULL,
    error_message       TEXT
);

CREATE INDEX IF NOT EXISTS idx_sync_log_run ON sync_log (run_at DESC);

-- ── Row Level Security (scaffold — policies added when multi-tenancy is live) ─

ALTER TABLE tenants             ENABLE ROW LEVEL SECURITY;
ALTER TABLE operators           ENABLE ROW LEVEL SECURITY;
ALTER TABLE locations           ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory           ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders              ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_lines         ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_movements     ENABLE ROW LEVEL SECURITY;
ALTER TABLE returns             ENABLE ROW LEVEL SECURITY;
ALTER TABLE inbound_shipments   ENABLE ROW LEVEL SECURITY;
ALTER TABLE inbound_shipment_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE packing_stations    ENABLE ROW LEVEL SECURITY;
ALTER TABLE pick_jobs           ENABLE ROW LEVEL SECURITY;
ALTER TABLE sync_log            ENABLE ROW LEVEL SECURITY;

-- Service role bypasses RLS — all backend access uses the service role key.
-- Add tenant-scoped policies here when you add a user auth layer.
