"""
Inventory validation.

Stub standing in for a real inventory service. Reconstructed so the stack
deploys and runs standalone; the workshop provided this as a pre-deployed
function.
"""

OUT_OF_STOCK = {"ITEM-OOS", "ITEM-DISCONTINUED"}


def handler(event, context):
    items = event.get("items", [])

    for item in items:
        if item.get("item_id") in OUT_OF_STOCK:
            return {"valid": False, "reason": f"{item['item_id']} is not in stock"}

    return {"valid": True, "reason": None}
