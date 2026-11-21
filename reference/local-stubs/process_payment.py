"""
Payment capture.

The irreversible step, and the reason the rest of this repo exists. Running
it twice charges the customer twice, which is exactly what durable execution
prevents by checkpointing the result under a stable operation name.

Stub standing in for a real payment provider.
"""

import uuid


def handler(event, context):
    payment_id = f"PAY-{uuid.uuid4().hex[:8]}"

    print(
        f"Charging {event['customer_id']} "
        f"{event['amount']} for order {event['order_id']} as {payment_id}"
    )

    return {
        "payment_id": payment_id,
        "order_id": event["order_id"],
        "amount": event["amount"],
        "status": "captured",
    }
