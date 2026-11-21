# Idempotent Order Workflow

A serverless order-processing workflow built on **AWS Lambda durable functions**, demonstrating how to make multi-step workflows idempotent, concurrent, and capable of pausing for human approval without burning compute. This was from the https://aws-experience.com/amer/smb/e/7e0bb/building-resilient-long-running-applications-in-aws-lambda event.

Built by working through the AWS Lambda durable functions workshop. The handler and SAM template are as deployed, unmodified. The documentation and failure analysis are my own.

---

## The problem

An e-commerce order arrives with items, a customer ID, and a total. The system validates it, charges the customer, and writes the confirmed order to DynamoDB.

Three steps, in sequence. Simple enough until the same order arrives twice.

That happens constantly in production:

- a client times out and retries
- a message queue re-delivers
- a user double-clicks submit

A standard Lambda function has no memory of what it already ran. Every step executes again, payment included. The customer gets charged twice.

This isn't a Lambda problem. Any multi-step workflow on any runtime hits it without a mechanism for tracking completed work. The usual fixes are a state machine, a workflow engine, or hand-rolled idempotency tables with distributed locks. Each adds infrastructure and its own failure modes.

Durable functions solve it inside the Lambda programming model: your handler stays ordinary Python, and the SDK checkpoints each operation so a replay skips work that already finished.

---
<img width="975" height="369" alt="image" src="https://github.com/user-attachments/assets/f2a07330-4bc6-4281-9aec-8f81f5cb6f00" />
<img width="975" height="448" alt="image" src="https://github.com/user-attachments/assets/8c7508dd-3dd0-4761-82b2-67fd7f7356db" />
<img width="975" height="425" alt="image" src="https://github.com/user-attachments/assets/ffdc819b-1a13-47e1-b532-e3e81e75446f" />



## What this repo demonstrates

| Pattern | Primitive | Problem it solves |
|---|---|---|
| Idempotency | execution names | The same order submitted twice charges once |
| Durable orchestration | `@durable_execution`, `context.invoke()` | A crash mid-workflow resumes from the last checkpoint instead of restarting |
| Concurrency | `context.parallel()` | Independent validations run at the same time, each independently checkpointed |
| Human in the loop | `context.wait_for_callback()` | The workflow pauses for a customer decision, for up to 48 hours, with no compute running |

---

## Architecture

### Starting point: a traditional orchestrator

```
order-processor-traditional (Lambda)
  ├─> order-validate         (Lambda)
  ├─> order-process-payment  (Lambda)
  └─> OrdersTable            (DynamoDB)
```

Sequential calls, no checkpointing. Re-invoking with identical input runs every step again.

### Final: a durable function with branching

```
                  ┌─────────────────────────────┐
                  │  Durable Order Processor     │
                  │  @durable_execution          │
                  └──────────────┬───────────────┘
                                 │
                   ┌─────────────┴─────────────┐
                   │   context.parallel()      │
                   ├───────────────────────────┤
                   │  order-validate           │
                   │  order-check-shipping     │
                   └─────────────┬─────────────┘
                                 │
                    shippable within 30 days?
                                 │
                 ┌───── no ──────┴────── yes ─────┐
                 │                                 │
      wait_for_callback()                          │
      "will you wait?"                             │
                 │                                 │
        ┌── declined ──┐                           │
        │              │                           │
   status:         approved ────────────────┬──────┘
   cancelled                                │
   (never charged)                          │
                                   order-process-payment
                                            │
                                      OrdersTable
```

The branch is the interesting part. A customer who declines a delayed shipment exits the workflow **before** the payment step ever runs. No refund logic, no compensating transaction, because the charge never happened.

---

## How idempotency works

Durable executions are keyed by an execution name you supply at invoke time:

```bash
aws lambda invoke \
  --function-name durable-order-processor-trad:\$LATEST \
  --durable-execution-name order-ORD-100 \
  --payload '{"order_id":"ORD-100", ...}' \
  response.json
```

Invoke a second time with the same name and the same payload, and you get back the **original execution's ARN and result**. No steps re-run. No second charge.

Invoke with the same name but a *different* payload and Lambda rejects it outright:

```
DurableExecutionAlreadyStartedException: Execution already started:
arn:aws:lambda:us-east-1:...:durable-execution/order-ORD-300/6f33b5e7-...
```

The execution name is the idempotency key. Choose it from something stable in your domain, an order ID, a payment reference, an upstream message ID.

---

## The callback pattern

When the shipping check reports an item can't ship within 30 days, rejecting the order loses the sale. Asking the customer whether they'll wait keeps it alive, but now the workflow has to pause for an answer that may take days.

`wait_for_callback()` does three things in one call:

1. mints a unique callback ID
2. runs your submitter function with that ID, so you can email or SMS it to the customer
3. suspends the execution entirely

While suspended there is **no running compute and no polling**. The execution resumes when something calls the Lambda API with the callback ID:

```bash
aws lambda send-durable-execution-callback-success \
  --callback-id <callback-id> \
  --result '{"approved": true}'
```

The function doesn't care where that call came from, a web form, a mobile app, an ops console. It needs the ID and a payload.

### Observed behaviour

| Execution | Decision | Execution status | Returned payload |
|---|---|---|---|
| `order-ORD-204` | approved | Succeeded | order confirmed, payment processed |
| `order-ORD-202` | declined | Succeeded | `{"status": "cancelled", "reason": "Customer declined delayed shipping"}` |

Worth noting: a declined order still reports **Succeeded**. That's the execution status, meaning the function ran to completion without error. The business outcome lives in the return payload. Conflating the two is an easy mistake when you're reading the console for the first time.

---

## Repository layout

```
.
├── README.md
├── docs/
│   ├── 01-the-problem.md          duplicate submissions and double charges
│   ├── 02-durable-execution.md    converting the handler, execution names
│   ├── 03-parallel-validation.md  context.parallel()
│   ├── 04-human-in-the-loop.md    wait_for_callback()
│   └── troubleshooting.md         failures I hit and how I diagnosed them
├── src/
│   ├── durable_order_processor_trad.py   the orchestrator, as built
│   └── template.yaml                     SAM stack
└── reference/
    └── local-stubs/                      downstream services, reconstructed
        ├── validate_order.py
        ├── check_shipping.py
        ├── process_payment.py
        └── create_order.py
```

A note on scope. `src/` is the workshop build exactly as deployed, unmodified. The template expects four downstream Lambdas (`order-validate`, `order-check-shipping`, `order-process-payment`, `order-create-order`) and a DynamoDB table, which the workshop environment provides pre-deployed.

`reference/local-stubs/` holds my own reconstruction of those four, written from their observed inputs and outputs. They are not workshop code and are not wired into the template. They're there so the behaviour of each downstream call is legible without access to a workshop account.

---

## Running it

Requires the AWS CLI, AWS SAM CLI, and Python 3.12+.

```bash
cd src
sam build
sam deploy
```

This deploys the orchestrator only. The four downstream functions and the DynamoDB table must already exist under the names in `template.yaml`.

Invoke with a backordered item to exercise the callback branch:

```bash
aws lambda invoke \
  --function-name durable-order-processor-trad:\$LATEST \
  --cli-binary-format raw-in-base64-out \
  --invocation-type Event \
  --durable-execution-name order-ORD-301 \
  --payload '{"order_id":"ORD-301","customer_id":"CUST-200","items":[{"item_id":"ITEM-BACKORDER","quantity":1,"price":50}],"total_amount":50}' \
  response.json && cat response.json
```

`ITEM-BACKORDER` is what trips the 30-day shipping check and sends the workflow into the approval branch. Any other item ID runs straight through.

`--invocation-type Event` matters here. A synchronous invoke blocks until the CLI read timeout, because the function suspends at the callback and won't return for up to 48 hours. The execution still starts correctly, but the CLI reports a read timeout that looks like a failure and isn't.

Then complete the callback from the Lambda console, under **Durable executions**, or via `send-durable-execution-callback-success`.

---

## What I took away

**Orchestration without a separate orchestrator.** The workflow is ordinary sequential Python. No state machine definition, no DSL, no second service to deploy and version. For teams already fluent in Lambda the onboarding cost is close to zero.

**Checkpoints change how you reason about failure.** The question stops being "how do I make this whole thing atomic" and becomes "what is the smallest unit worth replaying". That's a better question, and it maps cleanly onto how ETL and data pipelines are already decomposed.

**Determinism is a real constraint.** Replay works by re-running the handler and skipping completed operations. Anything non-deterministic outside a step, a random value, a timestamp, a dictionary iteration order that shifts, breaks the match against the checkpoint log.

**Suspension is genuinely free.** A workflow parked for two days on a human decision costs nothing while it waits. Polling loops and scheduled re-checks both cost something, and both are more code.

---

## Credits

Built against the AWS Lambda durable functions workshop. The scenario comes from that workshop; the documentation, diagrams, and failure analysis here are my own.

- [AWS Lambda durable functions](https://docs.aws.amazon.com/lambda/latest/dg/durable-execution-sdk.html)
- [Durable execution SDK reference](https://docs.aws.amazon.com/durable-execution/sdk-reference/languages/python/)
- [aws-durable-execution-sdk-python](https://pypi.org/project/aws-durable-execution-sdk-python/)
