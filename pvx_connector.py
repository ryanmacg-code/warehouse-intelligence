#!/usr/bin/env python3
"""
Peoplevox WMS connector.

Handles SOAP auth, session management, and data retrieval.
Run directly to pull today's sales orders and print them to the console.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any

import requests

# ── Constants ─────────────────────────────────────────────────────────────────

SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
PVX_NS  = "http://www.peoplevox.co.uk/"

# ── Connector ─────────────────────────────────────────────────────────────────

class PeoplevoxConnector:
    """
    Thin wrapper around the Peoplevox SOAP API.

    Handles session lifecycle automatically -callers just call get_data().
    Session token is refreshed 2 minutes before the server-side 30 min expiry.
    """

    def __init__(self, base_url: str, company_id: str, username: str, password: str):
        self.endpoint   = base_url.rstrip("/") + "/WMSServicesAPI"
        self.company_id = company_id
        self.username   = username
        self.password   = password
        self._token:   str | None      = None
        self._expires: datetime | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    def get_data(
        self,
        template:     str,
        page_size:    int = 100,
        page_number:  int = 1,
        date_from:    str = "",
        date_to:      str = "",
        search_terms: str = "",
    ) -> dict:
        """
        Call GetData and return a dict:
            {total: int, page: int, page_size: int, items: list[dict]}

        Each item is a flat or nested dict built from the response XML.
        """
        self._ensure_session()

        extras = ""
        if date_from:
            extras += f"<dateFrom>{_esc(date_from)}</dateFrom>"
        if date_to:
            extras += f"<dateTo>{_esc(date_to)}</dateTo>"
        if search_terms:
            extras += f"<searchTerms>{_esc(search_terms)}</searchTerms>"

        body = f"""<GetData xmlns="{PVX_NS}">
      <sessionToken>{self._token}</sessionToken>
      <templateName>{_esc(template)}</templateName>
      <pageSize>{page_size}</pageSize>
      <pageNumber>{page_number}</pageNumber>
      {extras}
    </GetData>"""

        root        = self._post(body)
        result_text = self._result(root, "GetDataResult")

        if result_text.startswith("Error"):
            raise RuntimeError(f"GetData({template}) failed: {result_text}")

        inner = ET.fromstring(result_text)
        total = int(inner.get("TotalCount", "0"))
        items = [_elem_to_dict(child) for child in inner]

        return {"total": total, "page": page_number, "page_size": page_size, "items": items}

    def save_data(self, template: str, xml_data: str) -> str:
        """Call SaveData and return the acknowledgement string (e.g. OK:MOCK-XXXXX)."""
        self._ensure_session()
        body = f"""<SaveData xmlns="{PVX_NS}">
      <sessionToken>{self._token}</sessionToken>
      <templateName>{_esc(template)}</templateName>
      <xmlData><![CDATA[{xml_data}]]></xmlData>
    </SaveData>"""
        root = self._post(body)
        return self._result(root, "SaveDataResult")

    # ── Session management ────────────────────────────────────────────────────

    def _ensure_session(self):
        if self._token and self._expires and datetime.now() < self._expires:
            return
        self._logon()

    def _logon(self):
        body = f"""<Logon xmlns="{PVX_NS}">
      <companyId>{_esc(self.company_id)}</companyId>
      <username>{_esc(self.username)}</username>
      <password>{_esc(self.password)}</password>
    </Logon>"""
        root  = self._post(body)
        token = self._result(root, "LogonResult")
        if not token or token.startswith("Error"):
            raise RuntimeError(f"Logon failed: {token or 'empty response'}")
        self._token   = token
        self._expires = datetime.now() + timedelta(minutes=28)  # 2 min buffer before server expiry

    # ── HTTP / XML helpers ────────────────────────────────────────────────────

    def _post(self, body: str) -> ET.Element:
        envelope = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">\n'
            '  <soap:Body>\n'
            f'    {body}\n'
            '  </soap:Body>\n'
            '</soap:Envelope>'
        )
        try:
            resp = requests.post(
                self.endpoint,
                data=envelope.encode("utf-8"),
                headers={"Content-Type": "text/xml; charset=utf-8"},
                timeout=15,
            )
        except requests.exceptions.ConnectionError:
            raise RuntimeError(
                f"Cannot connect to Peoplevox at {self.endpoint}. "
                "Is the server running?  python mock_pvx_server.py"
            )
        return ET.fromstring(resp.content)

    def _result(self, root: ET.Element, tag: str) -> str:
        el = root.find(f".//{{{PVX_NS}}}{tag}")
        if el is None:
            el = root.find(f".//{tag}")
        return (el.text or "").strip() if el is not None else ""


# ── XML → dict ────────────────────────────────────────────────────────────────

def _elem_to_dict(elem: ET.Element) -> dict:
    """
    Recursively convert an XML element into a plain dict.
    Child elements with no children become str values.
    Child elements that have children become a list (for repeated tags) or a
    nested dict (for wrapper elements containing multiple differently-named children).
    """
    result: dict[str, Any] = {}
    for child in elem:
        key = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if len(child) > 0:
            # Container element -recurse into each child and collect as list
            value: Any = [_elem_to_dict(gc) for gc in child]
        else:
            value = child.text or ""
        if key in result:
            if not isinstance(result[key], list):
                result[key] = [result[key]]
            result[key].append(value)
        else:
            result[key] = value
    return result


def _esc(s: Any) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ── Console pretty-printer ────────────────────────────────────────────────────

def _col(text: str, width: int) -> str:
    s = str(text)
    return s[:width].ljust(width)


def print_orders(result: dict, heading: str):
    orders = result["items"]
    total  = result["total"]

    print()
    print(f"  {heading}")
    print(f"  {total} order(s) found -showing {len(orders)}")
    print()

    if not orders:
        print("  (no orders to display)")
        return

    # Header row
    cols = [
        ("OrderNumber",    14),
        ("OrderDate",      20),
        ("CustomerName",   22),
        ("OrderStatus",    22),
        ("SalesChannel",   12),
        ("TotalOrderValue", 8),
    ]
    header = "  " + "  ".join(_col(h, w) for h, w in cols)
    print(header)
    print("  " + "-" * (sum(w for _, w in cols) + 2 * len(cols)))

    for o in orders:
        row = "  " + "  ".join(
            _col(o.get(field, ""), width) for field, width in cols
        )
        print(row)

    print()


def print_order_detail(order: dict):
    print(f"  Order {order.get('OrderNumber')}  |  {order.get('OrderStatus')}  |  "
          f"{order.get('SalesChannel')}  |  GBP {order.get('TotalOrderValue')}")
    print(f"  Customer : {order.get('CustomerName')} <{order.get('CustomerEmail')}>")
    print(f"  Shipping : {order.get('ShippingAddress1')}, "
          f"{order.get('ShippingCity')}, {order.get('ShippingPostcode')}")
    print(f"  Carrier  : {order.get('CarrierName')}  |  "
          f"Tracking: {order.get('TrackingNumber') or '(not yet dispatched)'}")
    print(f"  Placed   : {order.get('OrderDate')}")
    if order.get("DespatchDate"):
        print(f"  Despatched: {order.get('DespatchDate')}")

    lines = order.get("SalesOrderLines", [])
    if lines:
        print(f"  Lines ({len(lines)}):")
        for ln in lines:
            despatched = ln.get("QuantityDespatched", "0")
            ordered    = ln.get("QuantityOrdered", "0")
            print(f"    [{ln.get('LineNumber')}] {ln.get('ItemCode'):40s} "
                  f"x{ordered} (desp:{despatched})  GBP {ln.get('UnitSellingPrice')}")
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pvx = PeoplevoxConnector(
        base_url   = "http://localhost:8080",
        company_id = "arialondonfashion",
        username   = "dev",
        password   = "password",
    )

    today     = datetime.now().strftime("%Y-%m-%d")
    week_ago  = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    print()
    print("  Aria London WMS -Peoplevox Connector")
    print("  " + "=" * 50)
    print(f"  Endpoint : http://localhost:8080")
    print(f"  Date     : {today}")
    print()
    print("  Authenticating...", end=" ", flush=True)
    pvx._ensure_session()
    print(f"OK  (token: {pvx._token[:12]}...)")

    # Try today, fall back to last 7 days, then last 30 days
    for label, df, dt in [
        (f"Today's orders ({today})",                 today,     today),
        (f"Last 7 days ({week_ago} to {today})",      week_ago,  today),
        (f"Last 30 days ({month_ago} to {today})",    month_ago, today),
    ]:
        result = pvx.get_data("SalesOrders", page_size=50, date_from=df, date_to=dt)
        if result["total"] > 0:
            print_orders(result, label)
            break
    else:
        print("  No orders found in any time window.")
        sys.exit(0)

    # Detailed view of first 3 orders
    print("  Detail view (first 3 orders):")
    print("  " + "-" * 50)
    for order in result["items"][:3]:
        print_order_detail(order)
