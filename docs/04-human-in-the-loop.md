# 4. Human in the loop with callbacks

## The scenario

The shipping check reports an item can't arrive within 30 days. Two bad options:

- reject the order, and lose a sale the customer might have accepted
- charge now and hope they're fine with it, which invites a chargeback

The right move is to ask. That turns a workflow that finishes in two seconds into one that might take three days, because it's now waiting on a person.

## Why this is hard without durable execution

A workflow waiting on a human usually becomes:

- a record in a table marking the order as pending
- a scheduled job polling for responses
- reconciliation logic for responses that arrive after a timeout
- a separate path that resumes the workflow from the middle

That's a second system, and it exists only to hold a position in the first one.

## The change

```python
if not shipping_result["shippable_within_30_days"]:

    def submit_to_customer(callback_id, ctx):
        # Production: send an email or SMS containing a link that carries
        # this callback_id.
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
```

`wait_for_callback()` does three things:

1. mints a unique callback ID
2. calls the submitter with that ID, so it can be delivered to the customer
3. suspends the execution

No compute runs while suspended. No polling. The 48-hour timeout raises, which is why the call sits in a `try`.

## Resuming

Any caller with the ID can resume the execution:

```bash
aws lambda send-durable-execution-callback-success \
  --callback-id <callback-id> \
  --result '{"approved": true, "message": "I can wait for the delivery"}'
```

Or from the Lambda console, under **Durable executions → Actions → Send success**.

The function is indifferent to the source. A web form, a mobile app, an internal ops tool, a Slack action, all identical from its point of view. The contract is the callback ID plus a payload.

## Finding the callback in the console

It's nested. `wait_for_callback()` builds a child context containing the create-callback operation and a step that runs the submitter, so the Callback row is collapsed under the `RunInChild` parent:

```
customer-shipping-approval  Started     RunInChild
  customer-shipping-...     Started     Callback      <- select this one
  customer-shipping-...     Succeeded   Step
```

## Results

**Approved** (`order-ORD-204`): execution resumes, payment runs, order is written. Status Succeeded.

**Declined** (`order-ORD-202`): execution returns before the payment step.

```json
{"status": "cancelled", "reason": "Customer declined delayed shipping"}
```

Execution status also reads Succeeded, because the function ran to completion without error. The business outcome is in the payload, not the status. The operations list is the clearer evidence: the declined execution has no `process-payment` operation at all.

That ordering is the design point. Asking before charging means a decline needs no refund, no reversal, and no compensating transaction, because nothing happened that has to be undone.

## Cost

A suspended execution isn't a running one. An order parked for two days on a customer decision consumes no Lambda duration while it waits. The polling-based alternative pays for every check that finds nothing.

Back to the [README](../README.md).
