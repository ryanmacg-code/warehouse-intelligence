#!/usr/bin/env python3
"""
Smoke-test client for the mock Peoplevox WMS API.
Run the server first:  python mock_pvx_server.py
Then run this script:  python test_pvx_mock.py
"""

import sys
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error

BASE_URL   = "http://localhost:8080/WMSServicesAPI"
PVX_NS     = "http://www.peoplevox.co.uk/"
SOAP_NS    = "http://schemas.xmlsoap.org/soap/envelope/"
COMPANY_ID = "arialondonfashion"
USERNAME   = "dev"
PASSWORD   = "password"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _post_soap(xml_body: str) -> ET.Element:
    envelope = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    {xml_body}
  </soap:Body>
</soap:Envelope>"""
    req = urllib.request.Request(
        BASE_URL,
        data=envelope.encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return ET.fromstring(resp.read())
    except urllib.error.HTTPError as e:
        # SOAP faults come back as HTTP 400/500 -- parse the body anyway
        return ET.fromstring(e.read())


def _result_text(root: ET.Element, result_tag: str) -> str:
    el = root.find(f".//{{{PVX_NS}}}{result_tag}")
    if el is None:
        el = root.find(f".//{result_tag}")
    return el.text.strip() if el is not None and el.text else ""


def _f(elem: ET.Element, tag: str) -> ET.Element | None:
    """Find a child element trying both the Peoplevox namespace and no namespace."""
    el = elem.find(f"{{{PVX_NS}}}{tag}")
    if el is None:
        el = elem.find(tag)
    return el


def _t(elem: ET.Element, tag: str) -> str:
    """Return text of a child element, empty string if absent."""
    el = _f(elem, tag)
    return (el.text or "").strip() if el is not None else ""


def _section(title: str):
    print(f"\n-- {title} " + "-" * max(0, 60 - len(title)))


def ok(label: str):
    print(f"  [PASS] {label}")


def fail(label: str, detail: str = ""):
    print(f"  [FAIL] {label}" + (f": {detail}" if detail else ""))
    sys.exit(1)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_logon() -> str:
    _section("Logon")
    root  = _post_soap(f"""
    <Logon xmlns="{PVX_NS}">
      <companyId>{COMPANY_ID}</companyId>
      <username>{USERNAME}</username>
      <password>{PASSWORD}</password>
    </Logon>""")
    token = _result_text(root, "LogonResult")
    if not token or token.startswith("Error"):
        fail("Logon", token)
    ok(f"Got session token: {token[:16]}...")
    return token


def test_logon_missing_fields():
    root  = _post_soap(f"""
    <Logon xmlns="{PVX_NS}">
      <companyId>{COMPANY_ID}</companyId>
      <username></username>
      <password></password>
    </Logon>""")
    fault = root.find(f".//{{{SOAP_NS}}}Fault")
    if fault is None:
        fault = root.find(".//Fault")
    if fault is None:
        fail("Logon with missing fields should return a SOAP fault")
    ok("Missing credentials returns SOAP fault")


def test_invalid_token():
    root   = _post_soap(f"""
    <GetData xmlns="{PVX_NS}">
      <sessionToken>INVALIDTOKEN000</sessionToken>
      <templateName>SalesOrders</templateName>
      <pageSize>1</pageSize>
      <pageNumber>1</pageNumber>
    </GetData>""")
    result = _result_text(root, "GetDataResult")
    if "Error" not in result:
        fail("Invalid token should return error", result)
    ok(f"Invalid token rejected: {result}")


def test_get_data(token: str, template: str) -> ET.Element:
    _section(f"GetData: {template}")
    root   = _post_soap(f"""
    <GetData xmlns="{PVX_NS}">
      <sessionToken>{token}</sessionToken>
      <templateName>{template}</templateName>
      <pageSize>5</pageSize>
      <pageNumber>1</pageNumber>
    </GetData>""")
    result = _result_text(root, "GetDataResult")
    if result.startswith("Error"):
        fail(f"GetData {template}", result)
    inner = ET.fromstring(result)
    total = inner.get("TotalCount", "?")
    count = len(list(inner))
    ok(f"TotalCount={total}, returned {count} records on page 1")
    return inner


def test_sales_orders_pagination(token: str):
    _section("SalesOrders: pagination")
    root1 = _post_soap(f"""
    <GetData xmlns="{PVX_NS}">
      <sessionToken>{token}</sessionToken>
      <templateName>SalesOrders</templateName>
      <pageSize>10</pageSize>
      <pageNumber>1</pageNumber>
    </GetData>""")
    root2 = _post_soap(f"""
    <GetData xmlns="{PVX_NS}">
      <sessionToken>{token}</sessionToken>
      <templateName>SalesOrders</templateName>
      <pageSize>10</pageSize>
      <pageNumber>2</pageNumber>
    </GetData>""")
    inner1 = ET.fromstring(_result_text(root1, "GetDataResult"))
    inner2 = ET.fromstring(_result_text(root2, "GetDataResult"))
    nums1  = [_t(o, "OrderNumber") for o in inner1]
    nums2  = [_t(o, "OrderNumber") for o in inner2]
    if set(nums1) & set(nums2):
        fail("Pages 1 and 2 overlap")
    ok(f"Page 1: {nums1[0]}..{nums1[-1]}  |  Page 2: {nums2[0]}..{nums2[-1]}")


def test_search(token: str):
    _section("ItemStock: search filter")
    root  = _post_soap(f"""
    <GetData xmlns="{PVX_NS}">
      <sessionToken>{token}</sessionToken>
      <templateName>ItemStock</templateName>
      <searchTerms>Black</searchTerms>
      <pageSize>50</pageSize>
      <pageNumber>1</pageNumber>
    </GetData>""")
    inner   = ET.fromstring(_result_text(root, "GetDataResult"))
    colours = {_t(i, "Colour") for i in inner}
    if colours - {"Black"}:
        fail(f"Search 'Black' returned non-Black items: {colours - {'Black'}}")
    ok(f"Search 'Black' returned {inner.get('TotalCount')} items, all colour=Black")


def test_date_filter(token: str):
    _section("SalesOrders: date filter")
    root  = _post_soap(f"""
    <GetData xmlns="{PVX_NS}">
      <sessionToken>{token}</sessionToken>
      <templateName>SalesOrders</templateName>
      <pageSize>200</pageSize>
      <pageNumber>1</pageNumber>
      <dateFrom>2025-01-01</dateFrom>
      <dateTo>2025-12-31</dateTo>
    </GetData>""")
    inner = ET.fromstring(_result_text(root, "GetDataResult"))
    ok(f"2025 date range returned {inner.get('TotalCount')} orders")


def test_unknown_template(token: str):
    _section("Unknown template")
    root   = _post_soap(f"""
    <GetData xmlns="{PVX_NS}">
      <sessionToken>{token}</sessionToken>
      <templateName>NonExistentTemplate</templateName>
      <pageSize>10</pageSize>
      <pageNumber>1</pageNumber>
    </GetData>""")
    result = _result_text(root, "GetDataResult")
    if "Error" not in result:
        fail("Unknown template should return Error", result)
    ok(f"Unknown template returns error: {result[:70]}")


def test_save_data(token: str):
    _section("SaveData")
    root   = _post_soap(f"""
    <SaveData xmlns="{PVX_NS}">
      <sessionToken>{token}</sessionToken>
      <templateName>SalesOrders</templateName>
      <xmlData><![CDATA[<SalesOrder><OrderNumber>TEST-001</OrderNumber></SalesOrder>]]></xmlData>
    </SaveData>""")
    result = _result_text(root, "SaveDataResult")
    if not result.startswith("OK:"):
        fail("SaveData should return OK:REF", result)
    ok(f"SaveData acknowledged: {result}")


def test_sales_order_lines(token: str):
    _section("SalesOrder line items")
    root  = _post_soap(f"""
    <GetData xmlns="{PVX_NS}">
      <sessionToken>{token}</sessionToken>
      <templateName>SalesOrders</templateName>
      <pageSize>3</pageSize>
      <pageNumber>1</pageNumber>
    </GetData>""")
    inner = ET.fromstring(_result_text(root, "GetDataResult"))
    for order in inner:
        num   = _t(order, "OrderNumber")
        lines = _f(order, "SalesOrderLines")
        count = len(list(lines)) if lines is not None else 0
        if count == 0:
            fail(f"Order {num} has no line items")
        status = _t(order, "OrderStatus")
        value  = _t(order, "TotalOrderValue")
        ok(f"{num} | {status:25s} | {count} lines | GBP {value}")


def test_stock_fields(token: str):
    _section("ItemStock: field completeness")
    root  = _post_soap(f"""
    <GetData xmlns="{PVX_NS}">
      <sessionToken>{token}</sessionToken>
      <templateName>ItemStock</templateName>
      <pageSize>3</pageSize>
      <pageNumber>1</pageNumber>
    </GetData>""")
    inner    = ET.fromstring(_result_text(root, "GetDataResult"))
    required = ["ItemCode", "StyleCode", "Colour", "Size", "AvailableQuantity",
                "AllocatedQuantity", "SellingPrice", "PrimaryLocation"]
    for item in inner:
        missing = [f for f in required if _f(item, f) is None]
        if missing:
            fail(f"ItemStock missing fields: {missing}")
        sku   = _t(item, "ItemCode")
        avail = _t(item, "AvailableQuantity")
        loc   = _t(item, "PrimaryLocation")
        ok(f"{sku:35s} avail={avail:>4}  loc={loc}")


# ── Run all ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 66)
    print("  Mock Peoplevox API - test suite")
    print("=" * 66)

    test_logon_missing_fields()
    test_invalid_token()
    token = test_logon()

    test_get_data(token, "SalesOrders")
    test_get_data(token, "ItemStock")
    test_get_data(token, "StockMovements")
    test_get_data(token, "Returns")
    test_get_data(token, "Locations")

    test_sales_orders_pagination(token)
    test_search(token)
    test_date_filter(token)
    test_unknown_template(token)
    test_save_data(token)
    test_sales_order_lines(token)
    test_stock_fields(token)

    print()
    print("=" * 66)
    print("  All tests passed.")
    print("=" * 66)
