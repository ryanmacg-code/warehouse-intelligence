-- ============================================================
-- Warehouse Intelligence — Migration v2
-- Apply in Supabase SQL Editor after schema.sql is in place
-- ============================================================

-- ── 1. ADD site column to locations, inventory, stock_movements ───────────────

ALTER TABLE locations       ADD COLUMN IF NOT EXISTS site TEXT NOT NULL DEFAULT 'pickface';
ALTER TABLE inventory       ADD COLUMN IF NOT EXISTS site TEXT NOT NULL DEFAULT 'pickface';
ALTER TABLE stock_movements ADD COLUMN IF NOT EXISTS site TEXT NOT NULL DEFAULT 'pickface';

CREATE INDEX IF NOT EXISTS idx_locations_site       ON locations       (tenant_id, site);
CREATE INDEX IF NOT EXISTS idx_inventory_site       ON inventory       (tenant_id, site);
CREATE INDEX IF NOT EXISTS idx_stock_movements_site ON stock_movements (tenant_id, site);

-- ── 2. pick_job_lines — replaces pick_jobs.lines JSONB ───────────────────────

CREATE TABLE IF NOT EXISTS pick_job_lines (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id),
    job_id          TEXT        NOT NULL,
    line_number     INTEGER     NOT NULL,
    sku             TEXT,
    item_name       TEXT,
    location        TEXT,
    qty_required    INTEGER,
    qty_picked      INTEGER     NOT NULL DEFAULT 0,
    status          TEXT,       -- Pending | Picked | Short | Skipped
    pick_start_at   TIMESTAMPTZ,
    pick_end_at     TIMESTAMPTZ,
    seconds_to_pick INTEGER,    -- derived, stored for analytics
    tote_id         TEXT,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, job_id, line_number),
    FOREIGN KEY (tenant_id, job_id) REFERENCES pick_jobs (tenant_id, job_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pjl_job ON pick_job_lines (tenant_id, job_id);
CREATE INDEX IF NOT EXISTS idx_pjl_sku ON pick_job_lines (tenant_id, sku);

-- ── 3. packing_station_sessions — historical companion ────────────────────────

CREATE TABLE IF NOT EXISTS packing_station_sessions (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID        NOT NULL REFERENCES tenants(id),
    station_id          TEXT        NOT NULL,
    operator_id         TEXT,
    operator_name       TEXT,
    shift               TEXT,       -- AM | PM
    session_date        DATE        NOT NULL,
    shift_start         TIMESTAMPTZ,
    shift_end           TIMESTAMPTZ,
    orders_packed       INTEGER     NOT NULL DEFAULT 0,
    units_packed        INTEGER     NOT NULL DEFAULT 0,
    avg_pack_time_secs  INTEGER,
    errors              INTEGER     NOT NULL DEFAULT 0,
    void_fill_bags_used INTEGER,
    labels_printed      INTEGER,
    synced_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, station_id, session_date, shift)
);

CREATE INDEX IF NOT EXISTS idx_pss_date     ON packing_station_sessions (tenant_id, session_date DESC);
CREATE INDEX IF NOT EXISTS idx_pss_operator ON packing_station_sessions (tenant_id, operator_id);

-- ── 4. return_events — lifecycle stages for returns ───────────────────────────

CREATE TABLE IF NOT EXISTS return_events (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id),
    return_number   TEXT        NOT NULL,
    event_type      TEXT        NOT NULL,   -- Registered | Received | QC | Graded | Processed | Restocked | Written_Off
    event_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    operator_id     TEXT,
    operator_name   TEXT,
    notes           TEXT,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (tenant_id, return_number) REFERENCES returns (tenant_id, return_number) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_return_events_return ON return_events (tenant_id, return_number);
CREATE INDEX IF NOT EXISTS idx_return_events_date   ON return_events (tenant_id, event_at DESC);

-- ── 5. goods_in_receipts — detailed receipt against inbound shipments ─────────

CREATE TABLE IF NOT EXISTS goods_in_receipts (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID        NOT NULL REFERENCES tenants(id),
    receipt_number      TEXT        NOT NULL,
    asn_number          TEXT,
    receipt_date        DATE,
    dock_door           TEXT,
    operator_id         TEXT,
    operator_name       TEXT,
    status              TEXT,       -- In Progress | Complete | Discrepancy
    total_cartons       INTEGER,
    total_units         INTEGER,
    discrepancy_units   INTEGER     NOT NULL DEFAULT 0,
    notes               TEXT,
    synced_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, receipt_number),
    FOREIGN KEY (tenant_id, asn_number) REFERENCES inbound_shipments (tenant_id, asn_number) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_gin_date ON goods_in_receipts (tenant_id, receipt_date DESC);
CREATE INDEX IF NOT EXISTS idx_gin_asn  ON goods_in_receipts (tenant_id, asn_number);

-- ── 6. qc_results — quality inspection on goods-in ────────────────────────────

CREATE TABLE IF NOT EXISTS qc_results (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id),
    receipt_number  TEXT,
    sku             TEXT,
    item_name       TEXT,
    qty_inspected   INTEGER,
    qty_passed      INTEGER,
    qty_failed      INTEGER,
    failure_reason  TEXT,
    inspector_id    TEXT,
    inspector_name  TEXT,
    inspected_at    TIMESTAMPTZ,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qc_receipt ON qc_results (tenant_id, receipt_number);
CREATE INDEX IF NOT EXISTS idx_qc_sku     ON qc_results (tenant_id, sku);

-- ── 7. stock_adjustments — cycle counts and manual adjustments ────────────────

CREATE TABLE IF NOT EXISTS stock_adjustments (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID        NOT NULL REFERENCES tenants(id),
    adjustment_number   TEXT        NOT NULL,
    adjustment_type     TEXT,       -- CycleCount | ManualAdjust | WriteOff | DamageWrite
    sku                 TEXT,
    item_name           TEXT,
    location            TEXT,
    site                TEXT,
    qty_system          INTEGER,    -- what the system thought was there
    qty_counted         INTEGER,    -- what was physically found
    variance            INTEGER,    -- counted - system
    reason              TEXT,
    operator_id         TEXT,
    operator_name       TEXT,
    adjusted_at         TIMESTAMPTZ,
    approved_by         TEXT,
    synced_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, adjustment_number)
);

CREATE INDEX IF NOT EXISTS idx_adj_date     ON stock_adjustments (tenant_id, adjusted_at DESC);
CREATE INDEX IF NOT EXISTS idx_adj_sku      ON stock_adjustments (tenant_id, sku);
CREATE INDEX IF NOT EXISTS idx_adj_operator ON stock_adjustments (tenant_id, operator_id);
CREATE INDEX IF NOT EXISTS idx_adj_site     ON stock_adjustments (tenant_id, site);

-- ── 8. write_offs ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS write_offs (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id),
    writeoff_number TEXT        NOT NULL,
    sku             TEXT,
    item_name       TEXT,
    qty             INTEGER,
    reason          TEXT,       -- Damage | Lost | Expired | Return_Destroyed | QC_Fail
    cost_gbp        NUMERIC(10,2),
    operator_id     TEXT,
    written_off_at  TIMESTAMPTZ,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, writeoff_number)
);

CREATE INDEX IF NOT EXISTS idx_writeoffs_date ON write_offs (tenant_id, written_off_at DESC);
CREATE INDEX IF NOT EXISTS idx_writeoffs_sku  ON write_offs (tenant_id, sku);

-- ── 9. couriers ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS couriers (
    id          UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID    NOT NULL REFERENCES tenants(id),
    code        TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    synced_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code)
);

-- ── 10. courier_services ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS courier_services (
    id                  UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID    NOT NULL REFERENCES tenants(id),
    courier_code        TEXT    NOT NULL,
    service_code        TEXT    NOT NULL,
    service_name        TEXT,
    cut_off_time        TIME,
    transit_days        INTEGER,
    is_tracked          BOOLEAN NOT NULL DEFAULT TRUE,
    synced_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, courier_code, service_code)
);

-- ── 11. pick_lists — wave/batch picking ───────────────────────────────────────

CREATE TABLE IF NOT EXISTS pick_lists (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id),
    list_id         TEXT        NOT NULL,
    wave_number     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    released_at     TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    status          TEXT,       -- Draft | Released | In Progress | Complete
    total_orders    INTEGER,
    total_lines     INTEGER,
    zone            TEXT,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, list_id)
);

CREATE INDEX IF NOT EXISTS idx_pick_lists_date   ON pick_lists (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pick_lists_status ON pick_lists (tenant_id, status);

-- ── 12. carts + totes ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS carts (
    id          UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID    NOT NULL REFERENCES tenants(id),
    cart_id     TEXT    NOT NULL,
    cart_type   TEXT,
    status      TEXT,   -- Available | In Use | Maintenance
    location    TEXT,
    synced_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, cart_id)
);

CREATE TABLE IF NOT EXISTS totes (
    id          UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID    NOT NULL REFERENCES tenants(id),
    tote_id     TEXT    NOT NULL,
    cart_id     TEXT,
    tote_type   TEXT,
    status      TEXT,   -- Empty | Picking | Full | Packing | Done
    synced_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, tote_id)
);

-- ── 13. despatch_notes ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS despatch_notes (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id),
    note_number     TEXT        NOT NULL,
    order_number    TEXT,
    despatch_date   DATE,
    carrier         TEXT,
    service_code    TEXT,
    tracking_number TEXT,
    operator_id     TEXT,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, note_number)
);

CREATE INDEX IF NOT EXISTS idx_dn_order ON despatch_notes (tenant_id, order_number);
CREATE INDEX IF NOT EXISTS idx_dn_date  ON despatch_notes (tenant_id, despatch_date DESC);

-- ── 14. manifests + consignments ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS manifests (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id),
    manifest_number TEXT        NOT NULL,
    manifest_date   DATE,
    courier_code    TEXT,
    service_code    TEXT,
    status          TEXT,       -- Open | Closed | Collected
    total_parcels   INTEGER,
    total_weight_kg NUMERIC(8,2),
    collected_at    TIMESTAMPTZ,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, manifest_number)
);

CREATE TABLE IF NOT EXISTS consignments (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID        NOT NULL REFERENCES tenants(id),
    consignment_number  TEXT        NOT NULL,
    manifest_number     TEXT,
    order_number        TEXT,
    tracking_number     TEXT,
    courier_code        TEXT,
    service_code        TEXT,
    weight_kg           NUMERIC(6,3),
    status              TEXT,
    synced_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, consignment_number)
);

CREATE INDEX IF NOT EXISTS idx_consignments_manifest ON consignments (tenant_id, manifest_number);
CREATE INDEX IF NOT EXISTS idx_consignments_order    ON consignments (tenant_id, order_number);

-- ── 15. audit_trail ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS audit_trail (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id),
    entity_type     TEXT        NOT NULL,   -- Order | Return | StockAdjustment | ...
    entity_id       TEXT        NOT NULL,
    action          TEXT        NOT NULL,   -- Created | Updated | Deleted | StatusChange
    old_value       JSONB,
    new_value       JSONB,
    operator_id     TEXT,
    actioned_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_entity  ON audit_trail (tenant_id, entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_date    ON audit_trail (tenant_id, actioned_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_operator ON audit_trail (tenant_id, operator_id);

-- ── RLS on new tables ─────────────────────────────────────────────────────────

ALTER TABLE pick_job_lines          ENABLE ROW LEVEL SECURITY;
ALTER TABLE packing_station_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE return_events           ENABLE ROW LEVEL SECURITY;
ALTER TABLE goods_in_receipts       ENABLE ROW LEVEL SECURITY;
ALTER TABLE qc_results              ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_adjustments       ENABLE ROW LEVEL SECURITY;
ALTER TABLE write_offs              ENABLE ROW LEVEL SECURITY;
ALTER TABLE couriers                ENABLE ROW LEVEL SECURITY;
ALTER TABLE courier_services        ENABLE ROW LEVEL SECURITY;
ALTER TABLE pick_lists              ENABLE ROW LEVEL SECURITY;
ALTER TABLE carts                   ENABLE ROW LEVEL SECURITY;
ALTER TABLE totes                   ENABLE ROW LEVEL SECURITY;
ALTER TABLE despatch_notes          ENABLE ROW LEVEL SECURITY;
ALTER TABLE manifests               ENABLE ROW LEVEL SECURITY;
ALTER TABLE consignments            ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_trail             ENABLE ROW LEVEL SECURITY;
