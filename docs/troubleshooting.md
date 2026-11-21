# Troubleshooting

Real failures from building this, and how I worked out what was wrong. The diagnosis matters more than the fix in each case, because the console surfaces durable-execution failures differently from ordinary Lambda errors.

---

## 1. A CLI read timeout that was not a failure

**Symptom**

```
aws: [ERROR]: Read timeout on endpoint URL:
"https://lambda.us-east-1.amazonaws.com/2015-03-31/functions/durable-order-processor-trad%3A%24LATEST/invocations"
```

**What I assumed:** the invoke failed.

**What actually happened:** the invoke succeeded. The function reached `wait_for_callback()` and suspended, as designed, for up to 48 hours. A synchronous invoke waits for a return value that isn't coming, so the CLI hit its 60-second read timeout and gave up. The execution was alive the whole time, parked at the callback.

**Fix**

```bash
aws lambda invoke --invocation-type Event ...
```

Returns `"StatusCode": 202` immediately and hands back the `DurableExecutionArn`.

**Takeaway:** once a workflow can suspend, synchronous invocation stops being the right default. The client and the workflow no longer share a lifetime.

---

## 2. Reusing an execution name

**Symptom**

```
An error occurred (DurableExecutionAlreadyStartedException) when calling the Invoke operation:
Execution already started:
arn:aws:lambda:us-east-1:...:durable-execution/order-ORD-300/6f33b5e7-db57-3757-9634-367e72c5878c
```

**Cause:** I reused `--durable-execution-name order-ORD-300` with a *different* payload.

This is the idempotency guarantee working. An execution name identifies one logical execution:

- same name, same payload → returns the original result, nothing re-runs
- same name, different payload → rejected

**Takeaway:** the execution name is a real key, not a label. Derive it from something stable in the domain, and don't recycle it across tests.

---

## 3. NameError after an edit: `durable_execution` is not defined

This was the one that cost the most time.

**Symptom**

Execution status **Failed**, duration **11 minutes 10 seconds**. Durable operations: **0**. Event history: **10 events**.

Expanding the event history gave:

```json
{
  "EventType": "InvocationCompleted",
  "Error": {
    "Payload": {
      "ErrorMessage": "name 'durable_execution' is not defined",
      "ErrorType": "NameError",
      "StackTrace": [
        "File \"/var/task/durable_order_processor_trad.py\", line 6, in <module>\n    @durable_execution\n"
      ]
    }
  }
}
```

**Diagnosis, in order:**

1. **Zero operations with a non-empty event history** is the tell. If the handler had run at all, the first `context.parallel()` would have checkpointed and shown up as an operation. Zero means the failure happened before any durable work, which narrows it to module import or decorator evaluation.
2. **Eleven minutes for something that fails instantly** is the second tell. Async invokes are retried by Lambda with backoff. The 11 minutes is retry wall-clock, not execution time. A sync invoke would have failed in a second and been far more obvious.
3. The stack trace confirms it: the traceback is entirely inside `importlib`, ending at `line 6, in <module>`. Module-level, not handler-level.

**Root cause:** while adding the callback step, the new config import *replaced* the existing SDK import instead of being added alongside it. The file ended up as:

```python
from aws_durable_execution_sdk_python.config import WaitForCallbackConfig, Duration
import json
import os


@durable_execution        # <- no longer imported
def handler(event, context: DurableContext):   # <- also no longer imported
```

**Fix:** restore both imports and keep the new one.

```python
from aws_durable_execution_sdk_python.context import DurableContext
from aws_durable_execution_sdk_python.execution import durable_execution
from aws_durable_execution_sdk_python.config import WaitForCallbackConfig, Duration
```

**Takeaway:** `sam build` and `sam deploy` both succeed on a file with a missing import. Nothing validates that the module imports cleanly until the first invoke. A local `python -c "import durable_order_processor"` before deploying would have caught it in a second.

---

## 4. The callback row appears to be missing

**Symptom:** the execution is Running, but no Callback operation is visible in the Durable operations table.

**Cause:** `wait_for_callback()` doesn't create one flat operation. It creates a child context containing a create-callback operation plus a step that runs the submitter. In the console the callback is a **child row**, collapsed by default under the `customer-shipping-approval` row whose SubType is `RunInChild`.

Expanded, the tree looks like this:

```
validate-order              Succeeded   Parallel
  parallel-branch-0         Succeeded   ParallelBranch
  parallel-branch-1         Succeeded   ParallelBranch
customer-shipping-approval  Started     RunInChild
  customer-shipping-...     Started     Callback      <- the one you need
  customer-shipping-...     Succeeded   Step
```

Select the Callback child row, then **Actions → Send success**.

The table also doesn't auto-refresh, so a genuinely missing row is worth a manual refresh and a check of the pagination arrows before concluding anything.

---

## 5. A declined order reports "Succeeded"

**Symptom:** the customer declined, and the execution status still says Succeeded.

**Not a bug.** Two different things are being reported:

| | Meaning |
|---|---|
| **Execution status** | Did the function run to completion without raising? |
| **Return payload** | What was the business outcome? |

A decline is a normal, successful run that returns:

```json
{"status": "cancelled", "reason": "Customer declined delayed shipping"}
```

Check the **Input/Output** tab for the outcome. Confirmation is also visible in the operations list: a declined execution has no `process-payment` operation at all.

---

## 6. `BatchResult` used but never imported

Spotted while cleaning the code up for this repo:

```python
validation_results: BatchResult = context.parallel(...)
```

`BatchResult` was never imported, and this does not raise. Python does not evaluate annotations on local variable assignments at runtime (PEP 526), so the name is never looked up. It works by accident.

It would break the moment anything tried to resolve the annotation, under `from __future__ import annotations` or any runtime that evaluates them, and a type checker would flag it immediately.

Left in place here, because `src/` is the code as actually deployed and I'd rather the repo be accurate than tidy. The correct fix is either to import `BatchResult` or to drop the annotation.
