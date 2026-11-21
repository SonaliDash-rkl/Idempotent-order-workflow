"""
Shipping window check.

Reports whether every item can reach the customer within 30 days. A false
result is what sends the orchestrator down the customer-approval branch
rather than rejecting the order outright.

Stub standing in for a real carrier or warehouse lookup.
"""

BACKORDERED = {"ITEM-BACKORDER"}

DEFAULT_DAYS = 3
BACKORDER_DAYS = 45


def handler(event, context):
    items = event.get("items", [])

    worst_case = DEFAULT_DAYS
    for item in items:
        if item.get("item_id") in BACKORDERED:
            worst_case = max(worst_case, BACKORDER_DAYS)

    return {
        "shippable_within_30_days": worst_case <= 30,
        "estimated_days": worst_case,
    }
