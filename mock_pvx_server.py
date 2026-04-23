#!/usr/bin/env python3
"""
Mock Peoplevox WMS SOAP API — Aria London dataset (expanded)
─────────────────────────────────────────────────────────────
~14,000 SKUs · 1,800+ warehouse locations with pick routes
Goods-in / inbound shipments · Returns with grading
12 packing stations · 60 active pick jobs · 20 operators

SOAP endpoint : POST http://localhost:8080/WMSServicesAPI
WSDL          : GET  http://localhost:8080/WMSServicesAPI?wsdl
Health        : GET  http://localhost:8080/
"""

from __future__ import annotations

import uuid
import random
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any

from flask import Flask, Response, request, jsonify

app = Flask(__name__)

SOAP_NS     = "http://schemas.xmlsoap.org/soap/envelope/"
PVX_NS      = "http://www.peoplevox.co.uk/"
SESSION_TTL = timedelta(minutes=30)

SESSIONS: dict[str, dict] = {}


def _validate_session(token: str) -> tuple[bool, str]:
    if not token or token not in SESSIONS:
        return False, "Invalid or missing session token"
    sess = SESSIONS[token]
    if datetime.now() > sess["expires_at"]:
        del SESSIONS[token]
        return False, "Session expired — please call Logon again"
    sess["expires_at"] = datetime.now() + SESSION_TTL
    return True, ""


RNG = random.Random(42)

# ── Product catalogue ──────────────────────────────────────────────────────────
# (code, display_name, category, base_price_gbp, size_scheme)

_STYLES: list[tuple[str, str, str, float, str]] = [
    # Dresses (25)
    ("WRAP-MIDI",       "Wrap Midi Dress",               "Dresses",    89.00, "numeric"),
    ("SHIRT-DRESS",     "Shirt Dress",                   "Dresses",    75.00, "numeric"),
    ("CORD-MINI",       "Cord Mini Dress",               "Dresses",    65.00, "numeric"),
    ("SHIFT-DRESS",     "Shift Dress",                   "Dresses",    79.00, "numeric"),
    ("MAXI-SLIP",       "Maxi Slip Dress",               "Dresses",    95.00, "numeric"),
    ("SATIN-MIDI",      "Satin Bias-Cut Midi Dress",     "Dresses",   110.00, "numeric"),
    ("SMOCK-DRESS",     "Smock Dress",                   "Dresses",    69.00, "numeric"),
    ("BODYCON-MINI",    "Bodycon Mini Dress",            "Dresses",    59.00, "numeric"),
    ("BELTED-SHRT",     "Belted Shirt Dress",            "Dresses",    85.00, "numeric"),
    ("ALINE-MIDI",      "A-Line Midi Dress",             "Dresses",    79.00, "numeric"),
    ("BTN-MIDI",        "Button-Through Midi Dress",     "Dresses",    82.00, "numeric"),
    ("TIERED-MAXI",     "Tiered Maxi Dress",             "Dresses",    99.00, "numeric"),
    ("STRAPPY-MINI",    "Strappy Mini Dress",            "Dresses",    55.00, "numeric"),
    ("OFF-SHLD-MIDI",   "Off-Shoulder Midi Dress",       "Dresses",    89.00, "numeric"),
    ("RUCHED-BCON",     "Ruched Bodycon Dress",          "Dresses",    65.00, "numeric"),
    ("TEA-DRESS",       "Tea Dress",                     "Dresses",    72.00, "numeric"),
    ("SWTR-DRESS",      "Sweater Dress",                 "Dresses",    85.00, "letter"),
    ("CAMI-MIDI",       "Cami Midi Dress",               "Dresses",    75.00, "numeric"),
    ("SEQUIN-MINI",     "Sequin Mini Dress",             "Dresses",   120.00, "numeric"),
    ("HALTER-MIDI",     "Halter Neck Midi Dress",        "Dresses",    89.00, "numeric"),
    ("DENIM-MINI",      "Denim Mini Dress",              "Dresses",    69.00, "numeric"),
    ("PINAFORE",        "Pinafore Dress",                "Dresses",    65.00, "numeric"),
    ("BLAZER-DRESS",    "Blazer Dress",                  "Dresses",   105.00, "numeric"),
    ("LINEN-SHRT-DRS",  "Linen Shirt Dress",             "Dresses",    79.00, "numeric"),
    ("FLORAL-WRAP",     "Floral Wrap Dress",             "Dresses",    89.00, "numeric"),
    # Tops (20)
    ("SILK-BLOUSE",     "Silk Blouse",                   "Tops",       55.00, "numeric"),
    ("KNIT-TOP",        "Ribbed Knit Top",               "Tops",       45.00, "letter"),
    ("CROP-CORSET",     "Structured Corset Top",         "Tops",       49.00, "numeric"),
    ("LACE-TRIM-TOP",   "Lace Trim Cami Top",            "Tops",       35.00, "numeric"),
    ("WRAP-BLOUSE",     "Wrap Blouse",                   "Tops",       49.00, "numeric"),
    ("PUFF-SLV-TOP",    "Puff Sleeve Top",               "Tops",       45.00, "numeric"),
    ("BRODERIE-CAMI",   "Broderie Cami",                 "Tops",       39.00, "numeric"),
    ("OVSZD-SHIRT",     "Oversized Shirt",               "Tops",       55.00, "letter"),
    ("POLO-NECK",       "Polo Neck Top",                 "Tops",       42.00, "letter"),
    ("RUFFLE-BLSE",     "Ruffle Blouse",                 "Tops",       49.00, "numeric"),
    ("SATIN-SLIP-TOP",  "Satin Slip Top",                "Tops",       39.00, "numeric"),
    ("BODYSUIT",        "Bodysuit",                      "Tops",       35.00, "numeric"),
    ("LONGLINE-VEST",   "Longline Vest",                 "Tops",       29.00, "letter"),
    ("TIE-FRONT-BLS",   "Tie-Front Blouse",              "Tops",       45.00, "numeric"),
    ("CUT-OUT-TOP",     "Cut-Out Top",                   "Tops",       52.00, "numeric"),
    ("BARDOT-TOP",      "Bardot Top",                    "Tops",       42.00, "numeric"),
    ("VNECK-BLOUSE",    "V-Neck Blouse",                 "Tops",       45.00, "numeric"),
    ("KNIT-VEST",       "Knit Vest",                     "Tops",       39.00, "letter"),
    ("TAB-FRONT-SHT",   "Tab-Front Shirt",               "Tops",       52.00, "numeric"),
    ("BRALETTE",        "Bralette",                      "Tops",       28.00, "numeric"),
    # Trousers (15)
    ("WIDE-LEG",        "Wide Leg Trousers",             "Trousers",   69.00, "numeric"),
    ("CARGO-TRS",       "Cargo Trousers",                "Trousers",   75.00, "numeric"),
    ("TAILORED-TRS",    "Tailored Trousers",             "Trousers",   79.00, "numeric"),
    ("PAPERBAG-TRS",    "Paperbag Waist Trousers",       "Trousers",   65.00, "numeric"),
    ("FLARED-TRS",      "Flared Trousers",               "Trousers",   72.00, "numeric"),
    ("CIGARETTE-TRS",   "Cigarette Trousers",            "Trousers",   69.00, "numeric"),
    ("PALAZZO",         "Palazzo Pants",                 "Trousers",   75.00, "numeric"),
    ("JOGGERS",         "Joggers",                       "Trousers",   49.00, "letter"),
    ("BARREL-LEG",      "Barrel Leg Trousers",           "Trousers",   72.00, "numeric"),
    ("PINSTRIPE-TRS",   "Pinstripe Trousers",            "Trousers",   79.00, "numeric"),
    ("LINEN-TRS",       "Linen Trousers",                "Trousers",   65.00, "numeric"),
    ("VELVET-TRS",      "Velvet Trousers",               "Trousers",   85.00, "numeric"),
    ("LEATHER-TRS",     "Leather-Look Trousers",         "Trousers",   89.00, "numeric"),
    ("HW-STRAIGHT",     "High-Waist Straight Trousers",  "Trousers",   72.00, "numeric"),
    ("CULOTTE",         "Culotte",                       "Trousers",   59.00, "numeric"),
    # Jackets (12)
    ("BLAZER-DBL",      "Double Breasted Blazer",        "Jackets",   120.00, "numeric"),
    ("TAILORED-JCKT",   "Tailored Jacket",               "Jackets",   135.00, "numeric"),
    ("CROPPED-BLZR",    "Cropped Blazer",                "Jackets",   105.00, "numeric"),
    ("VELVET-BLZR",     "Velvet Blazer",                 "Jackets",   129.00, "numeric"),
    ("OVSZD-BLZR",      "Oversized Blazer",              "Jackets",   115.00, "numeric"),
    ("MILITARY-JCKT",   "Military Jacket",               "Jackets",    99.00, "numeric"),
    ("DENIM-JCKT",      "Denim Jacket",                  "Jackets",    85.00, "letter"),
    ("BOUCLE-JCKT",     "Boucle Jacket",                 "Jackets",   145.00, "numeric"),
    ("SEQUIN-JCKT",     "Sequin Jacket",                 "Jackets",   159.00, "numeric"),
    ("LTHR-BIKER",      "Leather Biker Jacket",          "Jackets",   179.00, "numeric"),
    ("SHACKET",         "Shacket",                       "Jackets",    89.00, "letter"),
    ("QUILTED-JCKT",    "Quilted Jacket",                "Jackets",    95.00, "numeric"),
    # Coats (10)
    ("LINEN-TRENCH",    "Linen Trench Coat",             "Coats",     165.00, "numeric"),
    ("WOOL-OVERCOAT",   "Wool Overcoat",                 "Coats",     225.00, "numeric"),
    ("FAUX-FUR-COAT",   "Faux Fur Coat",                 "Coats",     195.00, "numeric"),
    ("BELTED-TRENCH",   "Belted Trench Coat",            "Coats",     179.00, "numeric"),
    ("DBL-BRST-COAT",   "Double Breasted Coat",          "Coats",     199.00, "numeric"),
    ("MAXI-COAT",       "Maxi Coat",                     "Coats",     215.00, "numeric"),
    ("DUFFLE-COAT",     "Duffle Coat",                   "Coats",     185.00, "numeric"),
    ("PARKA",           "Parka",                         "Coats",     169.00, "numeric"),
    ("COCOON-COAT",     "Cocoon Coat",                   "Coats",     189.00, "numeric"),
    ("BLAZER-COAT",     "Longline Blazer Coat",          "Coats",     195.00, "numeric"),
    # Skirts (10)
    ("MIDI-SKIRT",      "Pleated Midi Skirt",            "Skirts",     59.00, "numeric"),
    ("DENIM-MINI-SK",   "Denim Mini Skirt",              "Skirts",     45.00, "numeric"),
    ("LTHR-MINI-SK",    "Leather-Look Mini Skirt",       "Skirts",     55.00, "numeric"),
    ("MAXI-SLIP-SK",    "Maxi Slip Skirt",               "Skirts",     65.00, "numeric"),
    ("ALINE-MINI-SK",   "A-Line Mini Skirt",             "Skirts",     49.00, "numeric"),
    ("RUCHED-MINI-SK",  "Ruched Mini Skirt",             "Skirts",     45.00, "numeric"),
    ("CARGO-MINI-SK",   "Cargo Mini Skirt",              "Skirts",     52.00, "numeric"),
    ("KILT-SKIRT",      "Kilt Skirt",                    "Skirts",     65.00, "numeric"),
    ("TIERED-MIDI-SK",  "Tiered Midi Skirt",             "Skirts",     59.00, "numeric"),
    ("WRAP-MINI-SK",    "Wrap Mini Skirt",               "Skirts",     49.00, "numeric"),
    # Jumpsuits (5)
    ("WL-JUMPSUIT",     "Wide Leg Jumpsuit",             "Jumpsuits",  95.00, "numeric"),
    ("STRAPLESS-JS",    "Strapless Jumpsuit",            "Jumpsuits",  89.00, "numeric"),
    ("BELTED-JS",       "Belted Jumpsuit",               "Jumpsuits",  99.00, "numeric"),
    ("UTILITY-JS",      "Utility Jumpsuit",              "Jumpsuits",  85.00, "numeric"),
    ("TAILORED-JS",     "Tailored Jumpsuit",             "Jumpsuits", 109.00, "numeric"),
    # Knitwear (3)
    ("CHUNKY-KNIT",     "Chunky Knit Jumper",            "Knitwear",   75.00, "letter"),
    ("CARDIGAN",        "Longline Cardigan",             "Knitwear",   65.00, "letter"),
    ("ROLLNECK-JMP",    "Roll Neck Jumper",              "Knitwear",   69.00, "letter"),
]

_COLOURS: list[tuple[str, str]] = [
    ("BLK",   "Black"),       ("NVY",   "Navy"),         ("BRG",   "Burgundy"),
    ("WHT",   "White"),       ("BLS",   "Blush Pink"),    ("SGE",   "Sage Green"),
    ("CRM",   "Cream"),       ("TAN",   "Tan"),           ("RST",   "Rust"),
    ("TL",    "Teal"),        ("CHRC",  "Charcoal"),      ("MSTD",  "Mustard"),
    ("COBLT", "Cobalt Blue"), ("MUVE",  "Mauve"),         ("OATM",  "Oatmeal"),
    ("RED",   "Red"),         ("EMRLD", "Emerald"),       ("PRPL",  "Purple"),
    ("CORAL", "Coral"),       ("KHKI",  "Khaki"),         ("DNMB",  "Denim Blue"),
    ("CAML",  "Camel"),       ("PEACH", "Peach"),         ("SLATE", "Slate Grey"),
    ("GRPH",  "Graphite"),    ("TMRS",  "Taupe"),         ("INDIG", "Indigo"),
    ("CHLDN", "Chalky Denim"),("WSTRD", "Washed Red"),    ("PDPNK", "Powder Pink"),
]

_COLOUR_MAP     = dict(_COLOURS)
_SIZES_NUMERIC  = ["6", "8", "10", "12", "14", "16", "18"]
_SIZES_LETTER   = ["XS", "S", "M", "L", "XL"]

_STYLE_COLOUR_MAP: dict[str, list[str]] = {}
for _sc, *_ in _STYLES:
    _n = RNG.randint(14, 28)
    _STYLE_COLOUR_MAP[_sc] = [c for c, _ in RNG.sample(_COLOURS, min(_n, len(_COLOURS)))]

SKUS: dict[str, dict] = {}
for _style_code, _style_name, _category, _price, _size_type in _STYLES:
    _sizes = _SIZES_LETTER if _size_type == "letter" else _SIZES_NUMERIC
    for _colour_code in _STYLE_COLOUR_MAP[_style_code]:
        for _size in _sizes:
            _sku = f"{_style_code}-{_colour_code}-{_size}"
            SKUS[_sku] = {
                "sku":         _sku,
                "style_code":  _style_code,
                "style_name":  _style_name,
                "colour_code": _colour_code,
                "colour_name": _COLOUR_MAP[_colour_code],
                "size":        _size,
                "size_type":   _size_type,
                "category":    _category,
                "price":       _price,
                "barcode":     f"50{RNG.randint(10_000_000, 99_999_999)}",
                "weight_kg":   round(RNG.uniform(0.12, 0.95), 2),
            }

_SKU_LIST = list(SKUS.keys())

# ── Warehouse layout ───────────────────────────────────────────────────────────

LOCATIONS: list[dict] = []
_pick_seq = 0

# Pick face — aisles A-L, 24 bays, 4 levels (S-pattern serpentine routing)
_PICK_AISLES = list("ABCDEFGHIJKL")
for _ai, _aisle in enumerate(_PICK_AISLES):
    for _bay in range(1, 25):
        for _level in range(1, 5):
            _pick_seq += 1
            # Serpentine: even-index aisles bay 1→24, odd-index bays 24→1
            _bay_eff = _bay if _ai % 2 == 0 else 25 - _bay
            _seq = (_ai * 24 * 4) + ((_bay_eff - 1) * 4) + (_level - 1) + 1
            LOCATIONS.append({
                "reference":     f"{_aisle}-{_bay:02d}-L{_level}",
                "zone":          "PICK",
                "aisle":         _aisle,
                "bay":           str(_bay),
                "level":         str(_level),
                "type":          "Pick Face",
                "pick_sequence": _seq,
                "max_weight":    120.0,
                "active":        "true",
            })

# Bulk/overstock — aisles M-R, 20 bays, 5 levels
_BULK_AISLES = list("MNOPQR")
for _ai, _aisle in enumerate(_BULK_AISLES):
    for _bay in range(1, 21):
        for _level in range(1, 6):
            LOCATIONS.append({
                "reference":     f"{_aisle}-{_bay:02d}-L{_level}",
                "zone":          "BULK",
                "aisle":         _aisle,
                "bay":           str(_bay),
                "level":         str(_level),
                "type":          "Bulk/Overstock",
                "pick_sequence": 99999,
                "max_weight":    600.0,
                "active":        "true",
            })

# Goods-in dock bays
for _i in range(1, 9):
    LOCATIONS.append({
        "reference": f"GI-{_i:02d}", "zone": "GOODS-IN",
        "aisle": "GI", "bay": str(_i), "level": "1",
        "type": "Goods In Dock Bay", "pick_sequence": 99999,
        "max_weight": 5000.0, "active": "true",
    })

# Returns processing stations
for _i in range(1, 7):
    LOCATIONS.append({
        "reference": f"RET-{_i:02d}", "zone": "RETURNS",
        "aisle": "RET", "bay": str(_i), "level": "1",
        "type": "Returns Processing", "pick_sequence": 99999,
        "max_weight": 200.0, "active": "true",
    })

# Packing stations
for _i in range(1, 13):
    LOCATIONS.append({
        "reference": f"PS-{_i:02d}", "zone": "PACKING",
        "aisle": "PS", "bay": str(_i), "level": "1",
        "type": "Packing Station", "pick_sequence": 99999,
        "max_weight": 50.0, "active": "true",
    })

# Despatch lanes
for _i in range(1, 5):
    LOCATIONS.append({
        "reference": f"DS-{_i:02d}", "zone": "DESPATCH",
        "aisle": "DS", "bay": str(_i), "level": "1",
        "type": "Despatch Lane", "pick_sequence": 99999,
        "max_weight": 10000.0, "active": "true",
    })

# Quarantine
for _i in range(1, 6):
    LOCATIONS.append({
        "reference": f"QR-{_i:02d}", "zone": "QUARANTINE",
        "aisle": "QR", "bay": str(_i), "level": "1",
        "type": "Quarantine Bay", "pick_sequence": 99999,
        "max_weight": 200.0, "active": "true",
    })

_LOC_REFS_PICK = [l["reference"] for l in LOCATIONS if l["zone"] == "PICK"]
_LOC_REFS_BULK = [l["reference"] for l in LOCATIONS if l["zone"] == "BULK"]
_LOC_REFS_ALL  = _LOC_REFS_PICK + _LOC_REFS_BULK

# ── Operators ──────────────────────────────────────────────────────────────────

OPERATORS: list[dict] = [
    {"id": "WH01", "name": "James Okafor",       "role": "Picker",        "shift": "AM"},
    {"id": "WH02", "name": "Sarah Patel",         "role": "Packer",        "shift": "AM"},
    {"id": "WH03", "name": "Liam Brennan",        "role": "Picker",        "shift": "AM"},
    {"id": "WH04", "name": "Priya Sharma",        "role": "Returns",       "shift": "AM"},
    {"id": "WH05", "name": "Tom Whitfield",       "role": "Goods In",      "shift": "AM"},
    {"id": "WH06", "name": "Maria Santos",        "role": "Packer",        "shift": "AM"},
    {"id": "WH07", "name": "Kai Johnson",         "role": "Picker",        "shift": "AM"},
    {"id": "WH08", "name": "Fatima Al-Hassan",    "role": "Supervisor",    "shift": "AM"},
    {"id": "WH09", "name": "Declan Murphy",       "role": "Replenishment", "shift": "AM"},
    {"id": "WH10", "name": "Anita Kowalski",      "role": "Picker",        "shift": "PM"},
    {"id": "WH11", "name": "Marcus Webb",         "role": "Packer",        "shift": "PM"},
    {"id": "WH12", "name": "Nina Osei",           "role": "Picker",        "shift": "PM"},
    {"id": "WH13", "name": "Robert Chen",         "role": "Goods In",      "shift": "PM"},
    {"id": "WH14", "name": "Yemi Adeyemi",        "role": "Picker",        "shift": "PM"},
    {"id": "WH15", "name": "Claire Thornton",     "role": "Packer",        "shift": "PM"},
    {"id": "WH16", "name": "Hassan Ibrahim",      "role": "Returns",       "shift": "PM"},
    {"id": "WH17", "name": "Stephanie Nguyen",    "role": "Supervisor",    "shift": "PM"},
    {"id": "WH18", "name": "Owen Davies",         "role": "Picker",        "shift": "NIGHT"},
    {"id": "WH19", "name": "Blessing Okonkwo",    "role": "Packer",        "shift": "NIGHT"},
    {"id": "WH20", "name": "Ravi Krishnamurthy",  "role": "Replenishment", "shift": "NIGHT"},
]
_OP_IDS   = [o["id"] for o in OPERATORS]
_OP_MAP   = {o["id"]: o for o in OPERATORS}
_PICKERS  = [o["id"] for o in OPERATORS if o["role"] == "Picker"]
_PACKERS  = [o["id"] for o in OPERATORS if o["role"] == "Packer"]
_GI_OPS   = [o["id"] for o in OPERATORS if o["role"] == "Goods In"]
_RET_OPS  = [o["id"] for o in OPERATORS if o["role"] == "Returns"]

# ── Suppliers ──────────────────────────────────────────────────────────────────

_SUPPLIERS = [
    {"code": "SUP001", "name": "Premium Textiles Ltd",   "country": "United Kingdom"},
    {"code": "SUP002", "name": "Lotus Garments Co.",     "country": "China"},
    {"code": "SUP003", "name": "Casa Moda S.r.l.",       "country": "Italy"},
    {"code": "SUP004", "name": "Eastern Fashion Co.",    "country": "Bangladesh"},
    {"code": "SUP005", "name": "Silk Road Textiles",     "country": "China"},
    {"code": "SUP006", "name": "Nordic Knit Co.",        "country": "Denmark"},
    {"code": "SUP007", "name": "Iberian Garments S.A.",  "country": "Portugal"},
    {"code": "SUP008", "name": "Atlas Fabrics Ltd",      "country": "Morocco"},
]

# ── Stock levels ───────────────────────────────────────────────────────────────

STOCK: dict[str, dict] = {}
for _sku in SKUS:
    _avail = RNG.choices(
        [0, RNG.randint(1, 8), RNG.randint(9, 45), RNG.randint(46, 200)],
        weights=[8, 22, 48, 22],
    )[0]
    _alloc = RNG.randint(0, min(_avail, 20)) if _avail > 0 else 0
    STOCK[_sku] = {
        "available":  _avail,
        "allocated":  _alloc,
        "on_order":   RNG.randint(24, 240) if RNG.random() < 0.28 else 0,
        "location":   RNG.choice(_LOC_REFS_PICK) if RNG.random() < 0.65 else RNG.choice(_LOC_REFS_BULK),
        "reorder_pt": RNG.choice([8, 12, 16, 24]),
    }

# ── Reference lists ────────────────────────────────────────────────────────────

_FIRST = [
    "Sophie","Emma","Charlotte","Olivia","Amelia","Isabella","Mia","Poppy",
    "Lily","Grace","Hannah","Ella","Lucy","Zoe","Chloe","Harriet","Alice","Freya",
    "Imogen","Phoebe","Daisy","Rosie","Florence","Matilda","Evie","Millie",
    "Ellie","Jasmine","Ruby","Amber","Jessica","Lauren","Katie","Holly","Naomi",
    "Aisha","Priya","Mei","Fatima","Ingrid","Caitlin","Siobhan","Aoife","Niamh",
]
_LAST = [
    "Williams","Smith","Jones","Brown","Taylor","Davies","Evans","Wilson",
    "Thomas","Roberts","Johnson","Lewis","Walker","Clarke","Hall","Young",
    "Mitchell","Campbell","Stewart","Murray","Anderson","Jackson","Martin",
    "Thompson","White","Harris","Turner","Carter","Phillips","Hughes",
    "Patel","Khan","Singh","Ahmed","Ali","Okafor","Nguyen","Kowalski",
]
_STREETS = [
    "Oak Street","Rose Lane","Victoria Road","Church Street","High Street",
    "Mill Lane","Park Avenue","Manor Road","The Grove","Elm Close",
    "Queens Drive","Birchwood Avenue","Clover Hill","The Crescent","Ashwood Way",
    "Sycamore Close","Kingfisher Road","Lavender Walk","Primrose Hill","Cedar Court",
    "Station Road","Jubilee Avenue","Maple Drive","Willowbrook Lane","Foxglove Court",
]
_CITIES = [
    "London","Manchester","Birmingham","Leeds","Liverpool","Bristol",
    "Edinburgh","Cardiff","Sheffield","Newcastle","Brighton","Oxford",
    "Cambridge","York","Bath","Nottingham","Leicester","Reading","Norwich","Exeter",
    "Southampton","Portsmouth","Plymouth","Coventry","Stoke-on-Trent","Derby",
]
_PC_PREFIXES = [
    "SW1","E1","N1","SE1","W1","EC1","M1","B1","LS1","L1",
    "BS1","EH1","CF10","S1","NE1","BN1","OX1","CB1","YO1","BA1",
]
_CHANNELS = ["Website","ASOS","Zalando","Not On The High Street","TikTok Shop","Wholesale"]
_CARRIERS = [
    "Royal Mail Tracked 48","DPD Next Day","Evri Standard",
    "Royal Mail Special Delivery","UPS Standard",
]
_ORDER_STATUSES = [
    "Awaiting picking","Picking in progress","Packed","Dispatched","On hold","Cancelled",
]
_RETURN_REASONS = [
    "Too Small","Too Large","Not As Described","Changed Mind",
    "Faulty","Wrong Item Received","Better Price Elsewhere","Arrived Too Late",
    "Ordered Multiple Sizes","Style Didn't Suit",
]
_RETURN_CONDITIONS = [
    "Resaleable","Damaged Packaging","Faulty - Manufacturer","Customer Damaged","Missing Tag",
]
_MOVEMENT_TYPES = [
    "Receipt","Pick","Replenishment","Stock Count Adjustment","Return to Stock","Transfer",
]
_RETURN_GRADES = [
    ("A", "Perfect — all tags attached, original packaging intact"),
    ("B", "Good — minor packaging wear, item perfect"),
    ("C", "Fair — tags missing or minor item defect"),
    ("D", "Poor — significant damage or manufacturing fault"),
]
_GRADE_DISPOSITIONS: dict[str, list[str]] = {
    "A": ["Restock", "Restock", "Restock", "Restock"],
    "B": ["Restock", "Restock", "Liquidate", "Rework then Restock"],
    "C": ["Liquidate", "Repair", "Liquidate", "Write Off"],
    "D": ["Write Off", "Write Off", "Return to Supplier", "Repair"],
}
_PACK_BOX_SIZES = ["XS (20x15x10)", "S (30x20x15)", "M (40x30x20)", "L (50x40x30)", "Polybag"]


def _random_customer() -> dict:
    first  = RNG.choice(_FIRST)
    last   = RNG.choice(_LAST)
    domain = RNG.choice(["gmail.com","hotmail.co.uk","outlook.com","icloud.com","yahoo.co.uk"])
    return {
        "name":     f"{first} {last}",
        "email":    f"{first.lower()}.{last.lower()}{RNG.randint(1, 99)}@{domain}",
        "phone":    f"07{RNG.randint(100,999)} {RNG.randint(100,999)} {RNG.randint(1000,9999)}",
        "address1": f"{RNG.randint(1, 250)} {RNG.choice(_STREETS)}",
        "city":     RNG.choice(_CITIES),
        "postcode": (
            f"{RNG.choice(_PC_PREFIXES)}{RNG.randint(1,9)} "
            f"{RNG.randint(1,9)}{chr(RNG.randint(65,72))}{chr(RNG.randint(65,72))}"
        ),
        "country": "United Kingdom",
    }


def _random_dt(days_ago_max: int = 180, days_ago_min: int = 0) -> datetime:
    return datetime.now() - timedelta(
        days    = RNG.randint(days_ago_min, days_ago_max),
        hours   = RNG.randint(0, 23),
        minutes = RNG.randint(0, 59),
        seconds = RNG.randint(0, 59),
    )


# ── Data builders ──────────────────────────────────────────────────────────────

_HOUR_WEIGHTS = [
    2, 1, 1, 1, 1, 2,        # 0–5 AM (low)
    4, 6, 8, 10, 12, 14,     # 6–11 AM (morning ramp)
    16, 15, 13, 11, 10, 9,   # noon–5 PM (afternoon peak)
    10, 14, 16, 14, 12, 8,   # 6–11 PM (evening peak)
]
_CHANNEL_WEIGHTS = [35, 25, 14, 10, 11, 5]


def _build_orders(n: int = 5000) -> list[dict]:
    result  = []
    stocked = [s for s, d in STOCK.items() if d["available"] + d["allocated"] > 0]
    for i in range(1, n + 1):
        days_ago = RNG.randint(0, 180)
        hour     = RNG.choices(range(24), weights=_HOUR_WEIGHTS)[0]
        order_dt = datetime.now() - timedelta(
            days=days_ago, hours=23 - hour, minutes=RNG.randint(0, 59)
        )
        customer = _random_customer()
        status   = RNG.choices(_ORDER_STATUSES, weights=[12, 8, 8, 58, 9, 5])[0]
        channel  = RNG.choices(_CHANNELS, weights=_CHANNEL_WEIGHTS)[0]
        n_lines  = RNG.choices([1, 2, 3, 4, 5], weights=[40, 30, 18, 8, 4])[0]
        lines    = []
        for j in range(1, n_lines + 1):
            sku_code   = RNG.choice(stocked)
            sku        = SKUS[sku_code]
            qty        = RNG.choices([1, 2, 3], weights=[70, 22, 8])[0]
            despatched = (
                qty if status == "Dispatched"
                else 0 if status in ("Awaiting picking", "On hold", "Cancelled")
                else RNG.randint(0, qty)
            )
            lines.append({
                "line_number":         str(j),
                "sku":                 sku_code,
                "item_name":           f"{sku['style_name']} — {sku['colour_name']} / Size {sku['size']}",
                "quantity_ordered":    qty,
                "quantity_despatched": despatched,
                "unit_price":          sku["price"],
                "total_price":         round(sku["price"] * qty, 2),
            })
        dispatch_dt = (
            (order_dt + timedelta(hours=RNG.randint(4, 30))).strftime("%Y-%m-%d %H:%M:%S")
            if status == "Dispatched" else ""
        )
        carrier = RNG.choices(_CARRIERS, weights=[28, 38, 20, 8, 6])[0]
        result.append({
            "order_number":   f"WEB-{10000 + i}",
            "channel":        channel,
            "order_date":     order_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "dispatch_date":  dispatch_dt,
            "customer_name":  customer["name"],
            "customer_email": customer["email"],
            "customer_phone": customer["phone"],
            "address1":       customer["address1"],
            "city":           customer["city"],
            "postcode":       customer["postcode"],
            "country":        customer["country"],
            "carrier":        carrier,
            "tracking":       (
                f"TT{RNG.randint(100_000_000, 999_999_999)}GB"
                if status == "Dispatched" else ""
            ),
            "status":         status,
            "total_value":    round(sum(l["total_price"] for l in lines), 2),
            "lines":          lines,
        })
    return result


def _build_movements(n: int = 20000) -> list[dict]:
    result = []
    for i in range(1, n + 1):
        sku_code = RNG.choice(_SKU_LIST)
        mv_type  = RNG.choices(_MOVEMENT_TYPES, weights=[15, 52, 9, 8, 12, 4])[0]
        qty      = RNG.randint(1, 72) if mv_type == "Receipt" else RNG.randint(1, 6)
        if mv_type == "Receipt":
            from_loc = "GOODS-IN"
            to_loc   = RNG.choice(_LOC_REFS_PICK if RNG.random() < 0.65 else _LOC_REFS_BULK)
        elif mv_type == "Pick":
            from_loc = RNG.choice(_LOC_REFS_PICK)
            to_loc   = "DESPATCH-ZONE"
        elif mv_type == "Replenishment":
            from_loc = RNG.choice(_LOC_REFS_BULK)
            to_loc   = RNG.choice(_LOC_REFS_PICK)
        elif mv_type == "Return to Stock":
            from_loc = "RETURNS"
            to_loc   = RNG.choice(_LOC_REFS_PICK)
        elif mv_type == "Transfer":
            from_loc = RNG.choice(_LOC_REFS_ALL)
            to_loc   = RNG.choice(_LOC_REFS_ALL)
        else:  # Stock Count Adjustment
            from_loc = RNG.choice(_LOC_REFS_PICK)
            to_loc   = from_loc
        result.append({
            "reference":     f"MOV-{20000 + i}",
            "type":          mv_type,
            "sku":           sku_code,
            "item_name":     SKUS[sku_code]["style_name"],
            "quantity":      qty,
            "from_location": from_loc,
            "to_location":   to_loc,
            "date":          _random_dt(180).strftime("%Y-%m-%d %H:%M:%S"),
            "operator":      RNG.choice(_OP_IDS),
            "notes":         "",
        })
    return result


def _build_returns(orders: list[dict], n: int = 1200) -> list[dict]:
    result   = []
    dispatch = [o for o in orders if o["status"] == "Dispatched"]
    if not dispatch:
        return result
    for i in range(1, n + 1):
        order   = RNG.choice(dispatch)
        line    = RNG.choice(order["lines"])
        ret_qty = RNG.randint(1, max(1, line["quantity_ordered"]))
        base_dt = datetime.strptime(order["dispatch_date"], "%Y-%m-%d %H:%M:%S")
        ret_dt  = base_dt + timedelta(days=RNG.randint(2, 45))
        grade_code, grade_desc = RNG.choices(_RETURN_GRADES, weights=[45, 30, 18, 7])[0]
        disposition = RNG.choice(_GRADE_DISPOSITIONS[grade_code])
        result.append({
            "return_number":        f"RET-{30000 + i}",
            "original_order":       order["order_number"],
            "return_date":          ret_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "sku":                  line["sku"],
            "item_name":            line["item_name"],
            "quantity":             ret_qty,
            "reason":               RNG.choice(_RETURN_REASONS),
            "condition":            RNG.choices(_RETURN_CONDITIONS, weights=[55, 20, 10, 10, 5])[0],
            "grade":                grade_code,
            "grade_description":    grade_desc,
            "disposition":          disposition,
            "processing_bay":       f"RET-{RNG.randint(1, 6):02d}",
            "processing_operator":  RNG.choice(_RET_OPS),
            "processing_minutes":   RNG.randint(3, 28),
            "status":               RNG.choice(["Received", "Processed", "Restocked", "Written Off"]),
            "customer_name":        order["customer_name"],
            "customer_email":       order["customer_email"],
            "refund_amount":        round(SKUS[line["sku"]]["price"] * ret_qty, 2),
            "tracking_number":      f"RT{RNG.randint(100_000_000, 999_999_999)}GB",
        })
    return result


def _build_inbound_shipments(n: int = 80) -> list[dict]:
    result = []
    for i in range(1, n + 1):
        supplier    = RNG.choice(_SUPPLIERS)
        expected_dt = _random_dt(90, 0)
        overdue     = expected_dt < datetime.now() - timedelta(days=3)
        arrived     = RNG.random() < (0.55 if overdue else 0.80)
        actual_dt   = expected_dt + timedelta(days=RNG.randint(-1, 7)) if arrived else None
        if arrived:
            status = "Received" if RNG.random() < 0.72 else "In Progress"
        elif overdue:
            status = "Overdue"
        else:
            status = "Expected"
        n_lines      = RNG.randint(4, 28)
        lines        = []
        total_ordered = 0
        total_received = 0
        for j in range(1, n_lines + 1):
            sku_code    = RNG.choice(_SKU_LIST)
            qty_ordered = RNG.randint(24, 144)
            if status == "Received":
                qty_received = qty_ordered + RNG.choices(
                    [-RNG.randint(0, 6), 0, 0, 0, RNG.randint(0, 4)],
                    weights=[8, 55, 20, 12, 5]
                )[0]
                qty_received = max(0, qty_received)
            elif status == "In Progress":
                qty_received = RNG.randint(0, qty_ordered)
            else:
                qty_received = 0
            lines.append({
                "line":          str(j),
                "sku":           sku_code,
                "item_name":     SKUS[sku_code]["style_name"],
                "colour":        SKUS[sku_code]["colour_name"],
                "size":          SKUS[sku_code]["size"],
                "qty_ordered":   qty_ordered,
                "qty_received":  qty_received,
                "variance":      qty_received - qty_ordered,
                "unit_cost_gbp": round(SKUS[sku_code]["price"] * RNG.uniform(0.24, 0.46), 2),
                "put_away_loc":  RNG.choice(_LOC_REFS_BULK) if qty_received > 0 else "",
            })
            total_ordered  += qty_ordered
            total_received += qty_received
        result.append({
            "asn_number":           f"ASN-{40000 + i}",
            "po_number":            f"PO-{50000 + RNG.randint(1, 9999)}",
            "supplier_code":        supplier["code"],
            "supplier_name":        supplier["name"],
            "supplier_country":     supplier["country"],
            "expected_date":        expected_dt.strftime("%Y-%m-%d"),
            "actual_date":          actual_dt.strftime("%Y-%m-%d") if actual_dt else "",
            "status":               status,
            "dock_door":            f"GI-{RNG.randint(1, 8):02d}",
            "handling_units":       RNG.randint(4, 48),
            "total_cartons":        RNG.randint(8, 140),
            "total_units_ordered":  total_ordered,
            "total_units_received": total_received,
            "operator":             RNG.choice(_GI_OPS),
            "lines":                lines,
        })
    return result


def _build_packing_stations() -> list[dict]:
    stations = []
    packers  = [o for o in OPERATORS if o["role"] == "Packer"]
    for i in range(1, 13):
        op           = packers[(i - 1) % len(packers)]
        orders_today = RNG.randint(38, 98)
        units_today  = RNG.randint(orders_today, orders_today * 3)
        avg_secs     = RNG.randint(52, 185)
        # Carrier split
        carrier_split: dict[str, int] = {}
        rem = orders_today
        for ci, carrier in enumerate(_CARRIERS):
            n = rem if ci == len(_CARRIERS) - 1 else RNG.randint(0, rem // max(1, len(_CARRIERS) - ci))
            carrier_split[carrier] = n
            rem -= n
        # Box usage
        box_usage = {b: RNG.randint(2, 35) for b in _PACK_BOX_SIZES}
        shift      = "AM" if i <= 6 else "PM"
        shift_hour = 6 if shift == "AM" else 14
        shift_start = datetime.now().replace(hour=shift_hour, minute=0, second=0, microsecond=0)
        last_act    = datetime.now() - timedelta(minutes=RNG.randint(1, 40))
        stations.append({
            "station_id":          f"PS-{i:02d}",
            "operator_id":         op["id"],
            "operator_name":       op["name"],
            "shift":               shift,
            "shift_start":         shift_start.strftime("%Y-%m-%d %H:%M:%S"),
            "status":              RNG.choices(["Active","Active","Active","Break","Idle"], weights=[65,10,10,10,5])[0],
            "orders_packed_today": orders_today,
            "units_packed_today":  units_today,
            "avg_pack_time_secs":  avg_secs,
            "last_order_packed":   f"WEB-{RNG.randint(10001, 15000)}",
            "last_activity":       last_act.strftime("%Y-%m-%d %H:%M:%S"),
            "carrier_split":       carrier_split,
            "box_usage":           box_usage,
            "void_fill_bags_used": RNG.randint(15, 110),
            "labels_printed":      orders_today + RNG.randint(0, 4),
            "errors_today":        RNG.randint(0, 3),
        })
    return stations


def _build_pick_jobs(orders: list[dict], n: int = 60) -> list[dict]:
    result  = []
    active  = [o for o in orders if o["status"] in ("Awaiting picking", "Picking in progress")]
    sample  = RNG.sample(active, min(n, len(active)))
    for i, order in enumerate(sample):
        picker      = _OP_MAP[_PICKERS[i % len(_PICKERS)]]
        total_lines = len(order["lines"])
        picked      = RNG.randint(0, total_lines) if order["status"] == "Picking in progress" else 0
        assigned_dt = datetime.now() - timedelta(minutes=RNG.randint(10, 150))
        started_dt  = assigned_dt + timedelta(minutes=RNG.randint(1, 10)) if picked > 0 else None
        result.append({
            "job_id":        f"PICK-{60000 + i + 1}",
            "order_number":  order["order_number"],
            "channel":       order["channel"],
            "picker_id":     picker["id"],
            "picker_name":   picker["name"],
            "status":        order["status"],
            "total_lines":   total_lines,
            "lines_picked":  picked,
            "assigned_at":   assigned_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "started_at":    started_dt.strftime("%Y-%m-%d %H:%M:%S") if started_dt else "",
            "carrier":       order["carrier"],
            "pick_zone":     RNG.choice(["PICK-A-F", "PICK-G-L"]),
            "lines": [
                {
                    "line":     ln["line_number"],
                    "sku":      ln["sku"],
                    "qty":      ln["quantity_ordered"],
                    "location": STOCK.get(ln["sku"], {}).get("location", "UNKNOWN"),
                    "pick_seq": next(
                        (l["pick_sequence"] for l in LOCATIONS
                         if l["reference"] == STOCK.get(ln["sku"], {}).get("location")), 99999
                    ),
                    "picked":   j < picked,
                }
                for j, ln in enumerate(order["lines"])
            ],
        })
    return result


# Pre-generate all data at startup (seeded → deterministic)
SALES_ORDERS       = _build_orders(5000)
STOCK_MOVEMENTS    = _build_movements(20000)
RETURNS            = _build_returns(SALES_ORDERS, 1200)
INBOUND_SHIPMENTS  = _build_inbound_shipments(80)
PACKING_STATIONS   = _build_packing_stations()
PICK_JOBS          = _build_pick_jobs(SALES_ORDERS, 60)

# ── SOAP utilities ─────────────────────────────────────────────────────────────

def _soap_wrap(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<soap:Envelope\n'
        '    xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"\n'
        '    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
        '    xmlns:xsd="http://www.w3.org/2001/XMLSchema">\n'
        '  <soap:Body>\n'
        f'{body}\n'
        '  </soap:Body>\n'
        '</soap:Envelope>'
    )


def _soap_fault(code: str, msg: str) -> Response:
    body = (
        '    <soap:Fault>\n'
        f'      <faultcode>{code}</faultcode>\n'
        f'      <faultstring>{_esc(msg)}</faultstring>\n'
        '    </soap:Fault>'
    )
    return Response(_soap_wrap(body), status=400, mimetype="text/xml; charset=utf-8")


def _xml_resp(body: str) -> Response:
    return Response(_soap_wrap(body), mimetype="text/xml; charset=utf-8")


def _esc(v: Any) -> str:
    return (
        str(v)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _get_text(elem: ET.Element, tag: str) -> str:
    child = elem.find(f"{{{PVX_NS}}}{tag}")
    if child is None:
        child = elem.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _int_or(text: str, default: int) -> int:
    try:
        return max(1, int(text)) if text else default
    except ValueError:
        return default


def _paginate(items: list, page_size: int, page_number: int) -> list:
    start = (page_number - 1) * page_size
    return items[start: start + page_size]


def _filter_by_date(items: list, date_key: str, df: str, dt: str) -> list:
    if not df and not dt:
        return items
    fmt = "%Y-%m-%d"
    try:
        d_from = datetime.strptime(df, fmt) if df else datetime.min
        d_to   = datetime.strptime(dt, fmt) if dt else datetime.max
    except ValueError:
        return items
    out = []
    for item in items:
        try:
            d = datetime.strptime(item[date_key][:10], fmt)
            if d_from <= d <= d_to:
                out.append(item)
        except (ValueError, KeyError):
            pass
    return out


# ── Logon ──────────────────────────────────────────────────────────────────────

def _handle_logon(action: ET.Element) -> Response:
    company_id = _get_text(action, "companyId")
    username   = _get_text(action, "username")
    password   = _get_text(action, "password")
    if not all([company_id, username, password]):
        return _soap_fault("Client", "companyId, username, and password are all required")
    token = uuid.uuid4().hex.upper()
    SESSIONS[token] = {
        "company_id": company_id,
        "username":   username,
        "expires_at": datetime.now() + SESSION_TTL,
    }
    body = (
        f'    <LogonResponse xmlns="{PVX_NS}">\n'
        f'      <LogonResult>{token}</LogonResult>\n'
        '    </LogonResponse>'
    )
    return _xml_resp(body)


# ── Template XML builders ──────────────────────────────────────────────────────

def _xml_sales_orders(ps: int, pn: int, df: str, dt: str, search: str) -> str:
    orders = _filter_by_date(SALES_ORDERS, "order_date", df, dt)
    if search:
        s = search.lower()
        orders = [
            o for o in orders
            if s in o["order_number"].lower()
            or s in o["customer_name"].lower()
            or s in o["customer_email"].lower()
            or s in o["status"].lower()
            or s in o["channel"].lower()
        ]
    total = len(orders)
    page  = _paginate(orders, ps, pn)
    rows  = []
    for o in page:
        lines_xml = "\n".join(
            f"""          <SalesOrderLine>
            <LineNumber>{_esc(l['line_number'])}</LineNumber>
            <ItemCode>{_esc(l['sku'])}</ItemCode>
            <ItemName>{_esc(l['item_name'])}</ItemName>
            <QuantityOrdered>{l['quantity_ordered']}</QuantityOrdered>
            <QuantityDespatched>{l['quantity_despatched']}</QuantityDespatched>
            <UnitSellingPrice>{l['unit_price']:.2f}</UnitSellingPrice>
            <TotalLineValue>{l['total_price']:.2f}</TotalLineValue>
          </SalesOrderLine>"""
            for l in o["lines"]
        )
        rows.append(
            f"""  <SalesOrder>
    <OrderNumber>{_esc(o['order_number'])}</OrderNumber>
    <SalesChannel>{_esc(o['channel'])}</SalesChannel>
    <OrderDate>{_esc(o['order_date'])}</OrderDate>
    <DespatchDate>{_esc(o['dispatch_date'])}</DespatchDate>
    <CustomerName>{_esc(o['customer_name'])}</CustomerName>
    <CustomerEmail>{_esc(o['customer_email'])}</CustomerEmail>
    <CustomerPhone>{_esc(o['customer_phone'])}</CustomerPhone>
    <ShippingAddress1>{_esc(o['address1'])}</ShippingAddress1>
    <ShippingCity>{_esc(o['city'])}</ShippingCity>
    <ShippingPostcode>{_esc(o['postcode'])}</ShippingPostcode>
    <ShippingCountry>{_esc(o['country'])}</ShippingCountry>
    <CarrierName>{_esc(o['carrier'])}</CarrierName>
    <TrackingNumber>{_esc(o['tracking'])}</TrackingNumber>
    <OrderStatus>{_esc(o['status'])}</OrderStatus>
    <TotalOrderValue>{o['total_value']:.2f}</TotalOrderValue>
    <NumberOfLines>{len(o['lines'])}</NumberOfLines>
    <SalesOrderLines>
{lines_xml}
    </SalesOrderLines>
  </SalesOrder>"""
        )
    return (
        f'<ArrayOfSalesOrder xmlns="{PVX_NS}"'
        f' TotalCount="{total}" Page="{pn}" PageSize="{ps}">\n'
        + "\n".join(rows)
        + "\n</ArrayOfSalesOrder>"
    )


def _xml_item_stock(ps: int, pn: int, df: str, dt: str, search: str) -> str:
    items = [{**sku_data, **STOCK.get(sku_code, {})} for sku_code, sku_data in SKUS.items()]
    if search:
        s = search.lower()
        items = [
            i for i in items
            if s in i["sku"].lower()
            or s in i["style_name"].lower()
            or s in i["category"].lower()
            or s in i["colour_name"].lower()
            or s in i["size"].lower()
        ]
    total = len(items)
    page  = _paginate(items, ps, pn)
    rows  = []
    for i in page:
        avail = i.get("available", 0)
        alloc = i.get("allocated", 0)
        rows.append(
            f"""  <ItemStock>
    <ItemCode>{_esc(i['sku'])}</ItemCode>
    <ItemName>{_esc(i['style_name'])} — {_esc(i['colour_name'])} / Size {_esc(i['size'])}</ItemName>
    <StyleCode>{_esc(i['style_code'])}</StyleCode>
    <Category>{_esc(i['category'])}</Category>
    <Colour>{_esc(i['colour_name'])}</Colour>
    <Size>{_esc(i['size'])}</Size>
    <SizeType>{_esc(i['size_type'])}</SizeType>
    <Barcode>{_esc(i['barcode'])}</Barcode>
    <WeightKg>{i['weight_kg']}</WeightKg>
    <SellingPrice>{i['price']:.2f}</SellingPrice>
    <AvailableQuantity>{avail}</AvailableQuantity>
    <AllocatedQuantity>{alloc}</AllocatedQuantity>
    <OnOrderQuantity>{i.get('on_order', 0)}</OnOrderQuantity>
    <TotalQuantity>{avail + alloc}</TotalQuantity>
    <PrimaryLocation>{_esc(i.get('location', ''))}</PrimaryLocation>
    <ReorderPoint>{i.get('reorder_pt', 12)}</ReorderPoint>
  </ItemStock>"""
        )
    return (
        f'<ArrayOfItemStock xmlns="{PVX_NS}"'
        f' TotalCount="{total}" Page="{pn}" PageSize="{ps}">\n'
        + "\n".join(rows)
        + "\n</ArrayOfItemStock>"
    )


def _xml_stock_movements(ps: int, pn: int, df: str, dt: str, search: str) -> str:
    mvs = _filter_by_date(STOCK_MOVEMENTS, "date", df, dt)
    if search:
        s = search.lower()
        mvs = [
            m for m in mvs
            if s in m["sku"].lower()
            or s in m["type"].lower()
            or s in m["reference"].lower()
            or s in m["operator"].lower()
        ]
    total = len(mvs)
    page  = _paginate(mvs, ps, pn)
    rows  = []
    for m in page:
        rows.append(
            f"""  <StockMovement>
    <Reference>{_esc(m['reference'])}</Reference>
    <MovementType>{_esc(m['type'])}</MovementType>
    <ItemCode>{_esc(m['sku'])}</ItemCode>
    <ItemName>{_esc(m['item_name'])}</ItemName>
    <Quantity>{m['quantity']}</Quantity>
    <FromLocation>{_esc(m['from_location'])}</FromLocation>
    <ToLocation>{_esc(m['to_location'])}</ToLocation>
    <MovementDate>{_esc(m['date'])}</MovementDate>
    <Operator>{_esc(m['operator'])}</Operator>
    <OperatorName>{_esc(_OP_MAP.get(m['operator'], {}).get('name', ''))}</OperatorName>
    <Notes>{_esc(m['notes'])}</Notes>
  </StockMovement>"""
        )
    return (
        f'<ArrayOfStockMovement xmlns="{PVX_NS}"'
        f' TotalCount="{total}" Page="{pn}" PageSize="{ps}">\n'
        + "\n".join(rows)
        + "\n</ArrayOfStockMovement>"
    )


def _xml_returns(ps: int, pn: int, df: str, dt: str, search: str) -> str:
    rets = _filter_by_date(RETURNS, "return_date", df, dt)
    if search:
        s = search.lower()
        rets = [
            r for r in rets
            if s in r["return_number"].lower()
            or s in r["original_order"].lower()
            or s in r["customer_name"].lower()
            or s in r["sku"].lower()
            or s in r["reason"].lower()
            or s in r["grade"].lower()
            or s in r["disposition"].lower()
        ]
    total = len(rets)
    page  = _paginate(rets, ps, pn)
    rows  = []
    for r in page:
        rows.append(
            f"""  <Return>
    <ReturnNumber>{_esc(r['return_number'])}</ReturnNumber>
    <OriginalOrderNumber>{_esc(r['original_order'])}</OriginalOrderNumber>
    <ReturnDate>{_esc(r['return_date'])}</ReturnDate>
    <ItemCode>{_esc(r['sku'])}</ItemCode>
    <ItemName>{_esc(r['item_name'])}</ItemName>
    <QuantityReturned>{r['quantity']}</QuantityReturned>
    <ReturnReason>{_esc(r['reason'])}</ReturnReason>
    <ItemCondition>{_esc(r['condition'])}</ItemCondition>
    <Grade>{_esc(r['grade'])}</Grade>
    <GradeDescription>{_esc(r['grade_description'])}</GradeDescription>
    <Disposition>{_esc(r['disposition'])}</Disposition>
    <ProcessingBay>{_esc(r['processing_bay'])}</ProcessingBay>
    <ProcessingOperator>{_esc(r['processing_operator'])}</ProcessingOperator>
    <ProcessingMinutes>{r['processing_minutes']}</ProcessingMinutes>
    <Status>{_esc(r['status'])}</Status>
    <CustomerName>{_esc(r['customer_name'])}</CustomerName>
    <CustomerEmail>{_esc(r['customer_email'])}</CustomerEmail>
    <RefundAmount>{r['refund_amount']:.2f}</RefundAmount>
    <TrackingNumber>{_esc(r['tracking_number'])}</TrackingNumber>
  </Return>"""
        )
    return (
        f'<ArrayOfReturn xmlns="{PVX_NS}"'
        f' TotalCount="{total}" Page="{pn}" PageSize="{ps}">\n'
        + "\n".join(rows)
        + "\n</ArrayOfReturn>"
    )


def _xml_locations(ps: int, pn: int, df: str, dt: str, search: str) -> str:
    locs = LOCATIONS
    if search:
        s = search.lower()
        locs = [
            l for l in locs
            if s in l["reference"].lower()
            or s in l["zone"].lower()
            or s in l["aisle"].lower()
            or s in l["type"].lower()
        ]
    total = len(locs)
    page  = _paginate(locs, ps, pn)
    # Build SKU count map once
    loc_sku_count: dict[str, int] = {}
    for d in STOCK.values():
        loc = d.get("location", "")
        loc_sku_count[loc] = loc_sku_count.get(loc, 0) + 1
    rows = []
    for l in page:
        rows.append(
            f"""  <Location>
    <LocationReference>{_esc(l['reference'])}</LocationReference>
    <Zone>{_esc(l['zone'])}</Zone>
    <Aisle>{_esc(l['aisle'])}</Aisle>
    <Bay>{_esc(l['bay'])}</Bay>
    <Level>{_esc(l['level'])}</Level>
    <LocationType>{_esc(l['type'])}</LocationType>
    <PickSequence>{l['pick_sequence']}</PickSequence>
    <MaxWeightKg>{l['max_weight']:.1f}</MaxWeightKg>
    <IsActive>{l['active']}</IsActive>
    <SKUCount>{loc_sku_count.get(l['reference'], 0)}</SKUCount>
  </Location>"""
        )
    return (
        f'<ArrayOfLocation xmlns="{PVX_NS}"'
        f' TotalCount="{total}" Page="{pn}" PageSize="{ps}">\n'
        + "\n".join(rows)
        + "\n</ArrayOfLocation>"
    )


def _xml_inbound_shipments(ps: int, pn: int, df: str, dt: str, search: str) -> str:
    asns = _filter_by_date(INBOUND_SHIPMENTS, "expected_date", df, dt)
    if search:
        s = search.lower()
        asns = [
            a for a in asns
            if s in a["asn_number"].lower()
            or s in a["po_number"].lower()
            or s in a["supplier_name"].lower()
            or s in a["status"].lower()
            or s in a["supplier_country"].lower()
        ]
    total = len(asns)
    page  = _paginate(asns, ps, pn)
    rows  = []
    for a in page:
        lines_xml = "\n".join(
            f"""          <ShipmentLine>
            <LineNumber>{_esc(l['line'])}</LineNumber>
            <ItemCode>{_esc(l['sku'])}</ItemCode>
            <ItemName>{_esc(l['item_name'])}</ItemName>
            <Colour>{_esc(l['colour'])}</Colour>
            <Size>{_esc(l['size'])}</Size>
            <QuantityOrdered>{l['qty_ordered']}</QuantityOrdered>
            <QuantityReceived>{l['qty_received']}</QuantityReceived>
            <Variance>{l['variance']}</Variance>
            <UnitCostGBP>{l['unit_cost_gbp']:.2f}</UnitCostGBP>
            <PutAwayLocation>{_esc(l['put_away_loc'])}</PutAwayLocation>
          </ShipmentLine>"""
            for l in a["lines"]
        )
        rows.append(
            f"""  <InboundShipment>
    <ASNNumber>{_esc(a['asn_number'])}</ASNNumber>
    <PONumber>{_esc(a['po_number'])}</PONumber>
    <SupplierCode>{_esc(a['supplier_code'])}</SupplierCode>
    <SupplierName>{_esc(a['supplier_name'])}</SupplierName>
    <SupplierCountry>{_esc(a['supplier_country'])}</SupplierCountry>
    <ExpectedDate>{_esc(a['expected_date'])}</ExpectedDate>
    <ActualDate>{_esc(a['actual_date'])}</ActualDate>
    <Status>{_esc(a['status'])}</Status>
    <DockDoor>{_esc(a['dock_door'])}</DockDoor>
    <HandlingUnits>{a['handling_units']}</HandlingUnits>
    <TotalCartons>{a['total_cartons']}</TotalCartons>
    <TotalUnitsOrdered>{a['total_units_ordered']}</TotalUnitsOrdered>
    <TotalUnitsReceived>{a['total_units_received']}</TotalUnitsReceived>
    <Operator>{_esc(a['operator'])}</Operator>
    <OperatorName>{_esc(_OP_MAP.get(a['operator'], {}).get('name', ''))}</OperatorName>
    <NumberOfLines>{len(a['lines'])}</NumberOfLines>
    <ShipmentLines>
{lines_xml}
    </ShipmentLines>
  </InboundShipment>"""
        )
    return (
        f'<ArrayOfInboundShipment xmlns="{PVX_NS}"'
        f' TotalCount="{total}" Page="{pn}" PageSize="{ps}">\n'
        + "\n".join(rows)
        + "\n</ArrayOfInboundShipment>"
    )


def _xml_packing_stations(ps: int, pn: int, df: str, dt: str, search: str) -> str:
    stations = PACKING_STATIONS
    if search:
        s = search.lower()
        stations = [
            st for st in stations
            if s in st["station_id"].lower()
            or s in st["operator_name"].lower()
            or s in st["status"].lower()
            or s in st["shift"].lower()
        ]
    total = len(stations)
    page  = _paginate(stations, ps, pn)
    rows  = []
    for st in page:
        carrier_xml = "\n".join(
            f"      <{_esc(c.replace(' ', '_'))}>{n}</{_esc(c.replace(' ', '_'))}>"
            for c, n in st["carrier_split"].items()
        )
        box_xml = "\n".join(
            f"      <Box size={chr(34)}{_esc(b)}{chr(34)}>{n}</Box>"
            for b, n in st["box_usage"].items()
        )
        rows.append(
            f"""  <PackingStation>
    <StationId>{_esc(st['station_id'])}</StationId>
    <OperatorId>{_esc(st['operator_id'])}</OperatorId>
    <OperatorName>{_esc(st['operator_name'])}</OperatorName>
    <Shift>{_esc(st['shift'])}</Shift>
    <ShiftStart>{_esc(st['shift_start'])}</ShiftStart>
    <Status>{_esc(st['status'])}</Status>
    <OrdersPackedToday>{st['orders_packed_today']}</OrdersPackedToday>
    <UnitsPackedToday>{st['units_packed_today']}</UnitsPackedToday>
    <AvgPackTimeSecs>{st['avg_pack_time_secs']}</AvgPackTimeSecs>
    <LastOrderPacked>{_esc(st['last_order_packed'])}</LastOrderPacked>
    <LastActivity>{_esc(st['last_activity'])}</LastActivity>
    <VoidFillBagsUsed>{st['void_fill_bags_used']}</VoidFillBagsUsed>
    <LabelsPrinted>{st['labels_printed']}</LabelsPrinted>
    <ErrorsToday>{st['errors_today']}</ErrorsToday>
    <CarrierSplit>
{carrier_xml}
    </CarrierSplit>
    <BoxUsage>
{box_xml}
    </BoxUsage>
  </PackingStation>"""
        )
    return (
        f'<ArrayOfPackingStation xmlns="{PVX_NS}"'
        f' TotalCount="{total}" Page="{pn}" PageSize="{ps}">\n'
        + "\n".join(rows)
        + "\n</ArrayOfPackingStation>"
    )


def _xml_pick_jobs(ps: int, pn: int, df: str, dt: str, search: str) -> str:
    jobs = PICK_JOBS
    if search:
        s = search.lower()
        jobs = [
            j for j in jobs
            if s in j["job_id"].lower()
            or s in j["order_number"].lower()
            or s in j["picker_name"].lower()
            or s in j["status"].lower()
        ]
    total = len(jobs)
    page  = _paginate(jobs, ps, pn)
    rows  = []
    for j in page:
        lines_xml = "\n".join(
            f"""      <PickLine>
        <Line>{_esc(l['line'])}</Line>
        <ItemCode>{_esc(l['sku'])}</ItemCode>
        <Quantity>{l['qty']}</Quantity>
        <Location>{_esc(l['location'])}</Location>
        <PickSequence>{l['pick_seq']}</PickSequence>
        <Picked>{'true' if l['picked'] else 'false'}</Picked>
      </PickLine>"""
            for l in j["lines"]
        )
        rows.append(
            f"""  <PickJob>
    <JobId>{_esc(j['job_id'])}</JobId>
    <OrderNumber>{_esc(j['order_number'])}</OrderNumber>
    <Channel>{_esc(j['channel'])}</Channel>
    <PickerId>{_esc(j['picker_id'])}</PickerId>
    <PickerName>{_esc(j['picker_name'])}</PickerName>
    <Status>{_esc(j['status'])}</Status>
    <TotalLines>{j['total_lines']}</TotalLines>
    <LinesPicked>{j['lines_picked']}</LinesPicked>
    <AssignedAt>{_esc(j['assigned_at'])}</AssignedAt>
    <StartedAt>{_esc(j['started_at'])}</StartedAt>
    <Carrier>{_esc(j['carrier'])}</Carrier>
    <PickZone>{_esc(j['pick_zone'])}</PickZone>
    <PickLines>
{lines_xml}
    </PickLines>
  </PickJob>"""
        )
    return (
        f'<ArrayOfPickJob xmlns="{PVX_NS}"'
        f' TotalCount="{total}" Page="{pn}" PageSize="{ps}">\n'
        + "\n".join(rows)
        + "\n</ArrayOfPickJob>"
    )


def _xml_operators(ps: int, pn: int, df: str, dt: str, search: str) -> str:
    ops = OPERATORS
    if search:
        s = search.lower()
        ops = [
            o for o in ops
            if s in o["name"].lower()
            or s in o["role"].lower()
            or s in o["shift"].lower()
            or s in o["id"].lower()
        ]
    total = len(ops)
    page  = _paginate(ops, ps, pn)
    rows  = []
    for o in page:
        rows.append(
            f"""  <Operator>
    <OperatorId>{_esc(o['id'])}</OperatorId>
    <OperatorName>{_esc(o['name'])}</OperatorName>
    <Role>{_esc(o['role'])}</Role>
    <Shift>{_esc(o['shift'])}</Shift>
  </Operator>"""
        )
    return (
        f'<ArrayOfOperator xmlns="{PVX_NS}"'
        f' TotalCount="{total}" Page="{pn}" PageSize="{ps}">\n'
        + "\n".join(rows)
        + "\n</ArrayOfOperator>"
    )


_TEMPLATES = {
    "SalesOrders":       _xml_sales_orders,
    "ItemStock":         _xml_item_stock,
    "StockMovements":    _xml_stock_movements,
    "Returns":           _xml_returns,
    "Locations":         _xml_locations,
    "InboundShipments":  _xml_inbound_shipments,
    "PackingStations":   _xml_packing_stations,
    "PickJobs":          _xml_pick_jobs,
    "Operators":         _xml_operators,
}

# ── GetData / SaveData ─────────────────────────────────────────────────────────

def _handle_get_data(action: ET.Element) -> Response:
    token    = _get_text(action, "sessionToken")
    template = _get_text(action, "templateName")
    ps       = _int_or(_get_text(action, "pageSize"),   100)
    pn       = _int_or(_get_text(action, "pageNumber"),   1)
    df       = _get_text(action, "dateFrom")
    dt       = _get_text(action, "dateTo")
    search   = _get_text(action, "searchTerms")
    ok, err  = _validate_session(token)
    if not ok:
        body = (
            f'    <GetDataResponse xmlns="{PVX_NS}">\n'
            f'      <GetDataResult>Error: {_esc(err)}</GetDataResult>\n'
            '    </GetDataResponse>'
        )
        return _xml_resp(body)
    builder = _TEMPLATES.get(template)
    if builder is None:
        available = ", ".join(_TEMPLATES)
        body = (
            f'    <GetDataResponse xmlns="{PVX_NS}">\n'
            f'      <GetDataResult>Error: Unknown template &apos;{_esc(template)}&apos;. '
            f'Available: {available}</GetDataResult>\n'
            '    </GetDataResponse>'
        )
        return _xml_resp(body)
    data_xml = builder(ps, pn, df, dt, search)
    body = (
        f'    <GetDataResponse xmlns="{PVX_NS}">\n'
        f'      <GetDataResult><![CDATA[{data_xml}]]></GetDataResult>\n'
        '    </GetDataResponse>'
    )
    return _xml_resp(body)


def _handle_save_data(action: ET.Element) -> Response:
    token    = _get_text(action, "sessionToken")
    ok, err  = _validate_session(token)
    if not ok:
        body = (
            f'    <SaveDataResponse xmlns="{PVX_NS}">\n'
            f'      <SaveDataResult>Error: {_esc(err)}</SaveDataResult>\n'
            '    </SaveDataResponse>'
        )
        return _xml_resp(body)
    ref  = f"MOCK-{uuid.uuid4().hex[:8].upper()}"
    body = (
        f'    <SaveDataResponse xmlns="{PVX_NS}">\n'
        f'      <SaveDataResult>OK:{ref}</SaveDataResult>\n'
        '    </SaveDataResponse>'
    )
    return _xml_resp(body)


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/WMSServicesAPI", methods=["GET", "POST"])
@app.route("/api", methods=["POST"])
def soap_endpoint():
    if request.method == "GET":
        if "wsdl" in request.args:
            return Response(_WSDL, mimetype="text/xml; charset=utf-8")
        return Response(
            "<info>POST SOAP requests to this endpoint. Append ?wsdl for the service description.</info>",
            mimetype="text/xml",
        )
    try:
        root = ET.fromstring(request.data)
    except ET.ParseError as exc:
        return _soap_fault("Client", f"XML parse error: {exc}")
    body_elem = root.find(f"{{{SOAP_NS}}}Body")
    if body_elem is None:
        return _soap_fault("Client", "SOAP Body element not found")
    action_elem = next(iter(body_elem), None)
    if action_elem is None:
        return _soap_fault("Client", "SOAP Body is empty")
    tag    = action_elem.tag
    method = tag.split("}")[-1] if "}" in tag else tag
    dispatch = {
        "Logon":    _handle_logon,
        "GetData":  _handle_get_data,
        "SaveData": _handle_save_data,
    }
    handler = dispatch.get(method)
    if not handler:
        return _soap_fault(
            "Client",
            f"Unknown SOAP action '{method}'. Supported: {', '.join(dispatch)}",
        )
    return handler(action_elem)


@app.route("/", methods=["GET"])
def health():
    active      = sum(1 for s in SESSIONS.values() if datetime.now() < s["expires_at"])
    dispatched  = sum(1 for o in SALES_ORDERS if o["status"] == "Dispatched")
    pick_zones  = sum(1 for l in LOCATIONS if l["zone"] == "PICK")
    bulk_zones  = sum(1 for l in LOCATIONS if l["zone"] == "BULK")
    special     = len(LOCATIONS) - pick_zones - bulk_zones
    asn_open    = sum(1 for a in INBOUND_SHIPMENTS if a["status"] in ("Expected", "In Progress", "Overdue"))
    return jsonify({
        "service": "Mock Peoplevox WMS API",
        "brand":   "Aria London",
        "status":  "running",
        "stats": {
            "skus":                  len(SKUS),
            "locations": {
                "total":   len(LOCATIONS),
                "pick_face": pick_zones,
                "bulk":      bulk_zones,
                "special":   special,
            },
            "operators":             len(OPERATORS),
            "sales_orders":          len(SALES_ORDERS),
            "dispatched_orders":     dispatched,
            "stock_movements":       len(STOCK_MOVEMENTS),
            "returns":               len(RETURNS),
            "inbound_shipments":     len(INBOUND_SHIPMENTS),
            "open_asns":             asn_open,
            "packing_stations":      len(PACKING_STATIONS),
            "active_pick_jobs":      len(PICK_JOBS),
            "active_sessions":       active,
        },
        "endpoints": {
            "soap":   "POST /WMSServicesAPI",
            "wsdl":   "GET  /WMSServicesAPI?wsdl",
            "health": "GET  /",
        },
        "templates": list(_TEMPLATES),
    })


# ── Minimal WSDL ───────────────────────────────────────────────────────────────

_WSDL = f"""<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://schemas.xmlsoap.org/wsdl/"
             xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
             xmlns:tns="{PVX_NS}"
             xmlns:xsd="http://www.w3.org/2001/XMLSchema"
             name="WMSServicesAPI"
             targetNamespace="{PVX_NS}">
  <types>
    <xsd:schema targetNamespace="{PVX_NS}">
      <xsd:element name="Logon">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="companyId" type="xsd:string"/>
          <xsd:element name="username"  type="xsd:string"/>
          <xsd:element name="password"  type="xsd:string"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>
      <xsd:element name="LogonResponse">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="LogonResult" type="xsd:string"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>
      <xsd:element name="GetData">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="sessionToken" type="xsd:string"/>
          <xsd:element name="templateName" type="xsd:string"/>
          <xsd:element name="searchTerms"  type="xsd:string" minOccurs="0"/>
          <xsd:element name="pageSize"     type="xsd:int"    minOccurs="0"/>
          <xsd:element name="pageNumber"   type="xsd:int"    minOccurs="0"/>
          <xsd:element name="dateFrom"     type="xsd:string" minOccurs="0"/>
          <xsd:element name="dateTo"       type="xsd:string" minOccurs="0"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>
      <xsd:element name="GetDataResponse">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="GetDataResult" type="xsd:string"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>
      <xsd:element name="SaveData">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="sessionToken" type="xsd:string"/>
          <xsd:element name="templateName" type="xsd:string"/>
          <xsd:element name="xmlData"      type="xsd:string" minOccurs="0"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>
      <xsd:element name="SaveDataResponse">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="SaveDataResult" type="xsd:string"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>
    </xsd:schema>
  </types>
  <message name="LogonIn">    <part name="parameters" element="tns:Logon"/></message>
  <message name="LogonOut">   <part name="parameters" element="tns:LogonResponse"/></message>
  <message name="GetDataIn">  <part name="parameters" element="tns:GetData"/></message>
  <message name="GetDataOut"> <part name="parameters" element="tns:GetDataResponse"/></message>
  <message name="SaveDataIn"> <part name="parameters" element="tns:SaveData"/></message>
  <message name="SaveDataOut"><part name="parameters" element="tns:SaveDataResponse"/></message>
  <portType name="WMSServicesAPISoap">
    <operation name="Logon">
      <input  message="tns:LogonIn"/>
      <output message="tns:LogonOut"/>
    </operation>
    <operation name="GetData">
      <input  message="tns:GetDataIn"/>
      <output message="tns:GetDataOut"/>
    </operation>
    <operation name="SaveData">
      <input  message="tns:SaveDataIn"/>
      <output message="tns:SaveDataOut"/>
    </operation>
  </portType>
  <binding name="WMSServicesAPISoap" type="tns:WMSServicesAPISoap">
    <soap:binding style="document" transport="http://schemas.xmlsoap.org/soap/http"/>
    <operation name="Logon">
      <soap:operation soapAction="{PVX_NS}Logon"/>
      <input><soap:body use="literal"/></input>
      <output><soap:body use="literal"/></output>
    </operation>
    <operation name="GetData">
      <soap:operation soapAction="{PVX_NS}GetData"/>
      <input><soap:body use="literal"/></input>
      <output><soap:body use="literal"/></output>
    </operation>
    <operation name="SaveData">
      <soap:operation soapAction="{PVX_NS}SaveData"/>
      <input><soap:body use="literal"/></input>
      <output><soap:body use="literal"/></output>
    </operation>
  </binding>
  <service name="WMSServicesAPI">
    <port name="WMSServicesAPISoap" binding="tns:WMSServicesAPISoap">
      <soap:address location="http://localhost:8080/WMSServicesAPI"/>
    </port>
  </service>
</definitions>"""


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    dispatched = sum(1 for o in SALES_ORDERS if o["status"] == "Dispatched")
    pick_locs  = sum(1 for l in LOCATIONS if l["zone"] == "PICK")
    bulk_locs  = sum(1 for l in LOCATIONS if l["zone"] == "BULK")
    spec_locs  = len(LOCATIONS) - pick_locs - bulk_locs
    asn_open   = sum(1 for a in INBOUND_SHIPMENTS if a["status"] in ("Expected","In Progress","Overdue"))
    print()
    print("  ====================================================")
    print("  Mock Peoplevox WMS API — Aria London")
    print("  ====================================================")
    print()
    print(f"  SKUs                   {len(SKUS):>7,}")
    print(f"  Warehouse locations    {len(LOCATIONS):>7,}")
    print(f"    Pick face (A–L)      {pick_locs:>7,}")
    print(f"    Bulk/overstock (M–R) {bulk_locs:>7,}")
    print(f"    Special areas        {spec_locs:>7,}")
    print(f"  Operators              {len(OPERATORS):>7,}")
    print(f"  Sales orders           {len(SALES_ORDERS):>7,}  ({dispatched:,} dispatched)")
    print(f"  Stock movements        {len(STOCK_MOVEMENTS):>7,}")
    print(f"  Returns                {len(RETURNS):>7,}")
    print(f"  Inbound shipments      {len(INBOUND_SHIPMENTS):>7,}  ({asn_open} open)")
    print(f"  Packing stations       {len(PACKING_STATIONS):>7,}")
    print(f"  Active pick jobs       {len(PICK_JOBS):>7,}")
    print()
    print("  Templates: " + " | ".join(_TEMPLATES))
    print()
    print("  SOAP   POST http://localhost:8080/WMSServicesAPI")
    print("  WSDL   GET  http://localhost:8080/WMSServicesAPI?wsdl")
    print("  Health GET  http://localhost:8080/")
    print()
    app.run(host="0.0.0.0", port=8080, debug=False)
