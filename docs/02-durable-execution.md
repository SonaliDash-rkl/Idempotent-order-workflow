# 2. Converting to durable execution

## The change

Two things turn a standard handler into a durable one.

**Decorate the handler** and take a `DurableContext`:

```python
from aws_durable_execution_sdk_python.context import DurableContext
from aws_durable_execution_sdk_python.execution import durable_execution


@durable_execution
def handler(event, context: DurableContext):
    ...
```

**Route downstream calls through the context** instead of calling them directly:

```python
payment = context.invoke(
    os.environ["PROCESS_PAYMENT_FUNCTION"],
    {"order_id": order["order_id"], "amount": order["total_amount"]},
    name="process-payment",
)
```

The `name` is not cosmetic. It's the identity of that operation in the checkpoint log, and it's how the SDK knows on replay that this step already ran.

## How checkpointing works

When the handler calls a durable operation, the SDK:

1. looks for a checkpoint matching that operation name and type
2. if one exists, returns the recorded result without executing anything
3. if not, executes the operation and writes the result to the log
4. returns the result and carries on

Recovery is therefore a **replay**. The handler re-runs from the top, but every completed operation is skipped and answered from the log. By the time execution reaches the crash point, it has reconstructed all prior state without redoing any work.

## Determinism is the constraint

Replay only works if the handler issues the same sequence of operations given the same inputs and log. The SDK validates operation names and types against the log as it goes.

Things that break it, when they sit outside a step:

- `random`, `uuid4`, `datetime.now()`
- reading mutable external state to decide which branch to take
- iteration whose order isn't stable

The fix is to push non-determinism into a `context.step()`, so the value is generated once and checkpointed.

## Execution names as idempotency keys

This is where the double charge from module 1 is solved. The key lives in the invoke, not the code:

```bash
aws lambda invoke \
  --function-name durable-order-processor-trad:\$LATEST \
  --cli-binary-format raw-in-base64-out \
  --durable-execution-name order-ORD-100 \
  --payload '{"order_id":"ORD-100","customer_id":"CUST-789","items":[{"item_id":"ITEM-C","quantity":1,"price":50}],"total_amount":50}' \
  response1.json && cat response1.json
```

```json
{
  "StatusCode": 200,
  "DurableExecutionArn": "arn:aws:lambda:us-east-1:...:durable-execution/order-ORD-100/482c61ca-c53d-3f69-8ac4-10ace7754072"
}
{"status": "completed", "order_id": "ORD-100", "payment_id": "PAY-0a987dfb"}
```

Run the identical command again and the same execution ARN comes back. No steps re-run. One payment ID, because there was only ever one payment.

Supply the same name with a different payload and Lambda refuses:

```
DurableExecutionAlreadyStartedException: Execution already started: ...
```

## Picking an execution name

It has to be stable and derivable from the request. Good candidates:

- the order ID, as used here
- an upstream message ID from SQS or EventBridge
- a payment reference from the client

Bad candidates: anything containing a timestamp, a random value, or a retry counter. Those produce a fresh execution per attempt, which is exactly the behaviour being eliminated.

Next: [03-parallel-validation.md](03-parallel-validation.md).
