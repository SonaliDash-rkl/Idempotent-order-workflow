# 1. The problem with multi-step workflows

## Setup

A standard Lambda orchestrator handling an order:

```
order-processor-traditional
  ├─> order-validate
  ├─> order-process-payment
  └─> OrdersTable (DynamoDB)
```

Three calls in sequence. Nothing unusual about it.

## The experiment

Invoke twice with an identical payload:

```bash
aws lambda invoke \
  --function-name order-processor-traditional \
  --cli-binary-format raw-in-base64-out \
  --payload '{"order_id":"ORD-002","customer_id":"CUST-456","items":[{"item_id":"ITEM-B","quantity":1,"price":50}],"total_amount":50}' \
  response1.json && cat response1.json
```

```bash
# identical command, second time
aws lambda invoke ... response2.json && cat response2.json
```

Both return `"StatusCode": 200` and both complete. Two payment IDs, one order. The customer has been charged twice.

## Why this isn't a Lambda problem

The function has no record of what it already did. Each invocation starts from nothing, so every step runs again, including the irreversible one.

Any multi-step workflow faces this, on any runtime. Containers, EC2, a cron job on a box under someone's desk. The vulnerability comes from the absence of a completed-work ledger, not from where the code runs.

Duplicate delivery is not an edge case:

- a client times out and retries, but the original request succeeded
- SQS delivers at-least-once, by design
- a user double-clicks submit
- a deployment replays a dead-letter queue

## The conventional fixes

| Approach | Cost |
|---|---|
| Idempotency table with request keys | A table, a lock strategy, TTL management, and a race between check and write |
| Step Functions or another state machine | A second service, a DSL, a separate deployment and versioning story |
| Make every step idempotent individually | Possible for writes, hard for third-party payment APIs |

Each works. Each adds a moving part.

## What durable functions change

The handler stays ordinary Python. The SDK maintains the checkpoint log for you, and the execution name supplied at invoke time is the idempotency key.

That's the subject of [02-durable-execution.md](02-durable-execution.md).
