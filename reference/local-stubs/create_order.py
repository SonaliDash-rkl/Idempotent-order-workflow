"""
Order persistence.

Writes the confirmed order to DynamoDB once payment has been captured.

Stub standing in for whatever the real order service would be.
"""

import os
from decimal import Decimal

import boto3

TABLE = boto3.resource("dynamodb").Table(os.environ["ORDERS_TABLE"])


def handler(event, context):
    order = event["order"]
    payment = event["payment"]

    item = {
        "order_id": order["order_id"],
        "customer_id": order["customer_id"],
        "total_amount": Decimal(str(order["total_amount"])),
        "payment_id": payment["payment_id"],
        "status": "confirmed",
    }

    TABLE.put_item(Item=item)

    return {"order_id": order["order_id"], "status": "confirmed"}
