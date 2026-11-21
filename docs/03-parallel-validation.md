# 3. Parallel validation

## Why

Two validations have to happen before payment:

- is the item in stock
- can it ship within 30 days

Neither depends on the other. Running them in sequence means paying the latency of both when you only need the latency of the slower one.

## The change

`context.parallel()` takes a list of functions, each receiving a context, and runs them concurrently:

```python
def check_inventory(ctx: DurableContext):
    return ctx.invoke(
        os.environ["VALIDATE_ORDER_FUNCTION"],
        order,
        name="check-inventory",
    )


def check_shipping(ctx: DurableContext):
    return ctx.invoke(
        os.environ["CHECK_SHIPPING_FUNCTION"],
        order,
        name="check-shipping",
    )


validation_results = context.parallel(
    [check_inventory, check_shipping],
    name="validate-order",
)

inventory_result, shipping_result = validation_results.get_results()
```

`get_results()` returns results **in the order the branches were declared**, not in completion order. That ordering is what makes the unpack safe.

## What it looks like in the console

Each branch is independently checkpointed, so a failure in one doesn't discard the other's work:

```
validate-order        Succeeded   Parallel        1 sec 902 ms
  parallel-branch-0   Succeeded   ParallelBranch  1 sec 596 ms
  parallel-branch-1   Succeeded   ParallelBranch  1 sec 745 ms
```

The parent operation takes roughly as long as the slower branch rather than the sum, which is the point.

## Branching on the result

```python
if not inventory_result["valid"]:
    return {"status": "rejected", "reason": "Item not in stock"}
```

Out of stock is a hard stop. Slow shipping is not, and that's what the callback step handles.

Next: [04-human-in-the-loop.md](04-human-in-the-loop.md).
