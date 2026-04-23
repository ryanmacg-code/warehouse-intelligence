#!/usr/bin/env python3
"""
run_demo_queries.py — end-to-end test of the 4 demo queries.
Calls the tool functions from pvx_mcp_server directly and prints output.
"""

import sys
import os

# Make sure we can import from the project directory
sys.path.insert(0, os.path.dirname(__file__))

from pvx_mcp_server import analyse_returns, get_inventory, get_stock_adjustments, get_warehouse_health

SEP = "\n" + "=" * 80 + "\n"

print(SEP)
print("QUERY A — analyse_returns (90-day window, surfaces problem SKUs)")
print(SEP)
result = analyse_returns(date_from="2026-01-24", date_to="2026-04-23")
print(result)

print(SEP)
print("QUERY B — get_inventory (pickface, low_stock=True)")
print(SEP)
result = get_inventory(site="pickface", low_stock=True, page_size=20)
print(result)

print(SEP)
print("QUERY C — get_stock_adjustments (90-day window, full operator ranking)")
print(SEP)
result = get_stock_adjustments(date_from="2026-01-24", date_to="2026-04-23", min_counts=10, page_size=5)
print(result)

print(SEP)
print("QUERY D — get_warehouse_health (unprompted insight)")
print(SEP)
result = get_warehouse_health()
print(result)
