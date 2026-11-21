from aws_durable_execution_sdk_python.context import DurableContext
from aws_durable_execution_sdk_python.execution import durable_execution
from aws_durable_execution_sdk_python.config import WaitForCallbackConfig, Duration
import json
import os


@durable_execution
def handler(event, context: DurableContext):
    print("MILESTONE_INPUT " + json.dumps(event))
    order = event
    context.logger.info("Order received", extra={"order_id": order.get("order_id")})

    # TODO: Step 1 - context.invoke(os.environ['VALIDATE_ORDER_FUNCTION'], order, name="validate-order")
    # Step 1: Validate order in parallel (inventory + shipping)
    def check_inventory(ctx: DurableContext):
        return ctx.invoke(
            os.environ['VALIDATE_ORDER_FUNCTION'],
            order,
            name="check-inventory"
        )

    def check_shipping(ctx: DurableContext):
        return ctx.invoke(
            os.environ['CHECK_SHIPPING_FUNCTION'],
            order,
            name="check-shipping"
        )

    validation_results: BatchResult = context.parallel(
        [check_inventory, check_shipping],
        name="validate-order"
    )

    results = validation_results.get_results()
    inventory_result = results[0]
    shipping_result = results[1]

    if not inventory_result["valid"]:
        return {"status": "rejected", "reason": "Item not in stock"}

        # Step 1b: If not shippable within 30 days, ask the customer
    if not shipping_result["shippable_within_30_days"]:
        def submit_to_customer(callback_id, ctx):
            # In production, this would send an email/SMS with the callback_id
            print(f"Asking customer to approve delayed shipping. Callback ID: {callback_id}")

        try:
            customer_response = context.wait_for_callback(
                submitter=submit_to_customer,
                name="customer-shipping-approval",
                config=WaitForCallbackConfig(timeout=Duration.from_hours(48)),
            )
        except Exception:
            return {"status": "cancelled", "reason": "Customer did not respond within 48 hours"}

        if isinstance(customer_response, str):
            customer_response = json.loads(customer_response)

        if not customer_response.get("approved"):
            return {"status": "cancelled", "reason": "Customer declined delayed shipping"}

    # ... rest of the handler (payment + create order) stays the same

    # TODO: Step 2 - context.invoke(os.environ['PROCESS_PAYMENT_FUNCTION'], payload, name="process-payment")

        # Step 2: Process payment (checkpointed)
    payment = context.invoke(
        os.environ['PROCESS_PAYMENT_FUNCTION'],
        {
            "order_id": order["order_id"],
            "amount": order["total_amount"],
            "customer_id": order["customer_id"]
        },
        name="process-payment"
    )
    context.logger.info("Payment processed", extra={"payment_id": payment["payment_id"]})

    # TODO: Step 3 - context.invoke(os.environ['CREATE_ORDER_FUNCTION'], {"order": order, "payment": payment}, name="create-order")

        # Step 3: Save order to DynamoDB (checkpointed)
    context.invoke(
        os.environ['CREATE_ORDER_FUNCTION'],
        {"order": order, "payment": payment},
        name="create-order"
    )
    context.logger.info("Order saved", extra={"order_id": order["order_id"]})

    return {
        "status": "completed",
        "order_id": order["order_id"],
        "payment_id": payment["payment_id"]
    }

    # TODO: Return {"status": "completed", ...}
    pass
