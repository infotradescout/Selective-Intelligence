# Execution Bounding and Target Selection

Use this gate after the whole product is understood and before choosing what to build or where to build it. It corrects two independent adoption failures: expanding a good discovery into an unbounded execution, and choosing a convenient surface that cannot carry the product's operational core.

## Preserve breadth; bound execution

Discovery may recover a product much larger than the person's seed. Preserve that complete product definition, its end-state architecture, and its dependency order. Do not pretend the product is smaller because one run is finite.

Then choose one **active deliverable** that is demonstrably bounded to the current execution window. The first deliverable must:

- complete one meaningful user journey from entry through persisted or otherwise durable outcome and reopen/recovery where the job requires it;
- include the UI, behavior, state, access, data, and proof needed for that loop instead of delivering a disconnected layer;
- establish only the foundation needed by the active loop while remaining compatible with the known whole-product architecture;
- have a named beginning, observable ending, negative cases, and evidence that can be completed in the current run;
- leave every later capability in an ordered deliverable map rather than silently dropping it; and
- close only the active deliverable, never the whole product or release.

Select the boundary without asking the person to invent phases. Use dependency order, user value, integration risk, available tools, context capacity, expected verification work, and the cost of interruption. Prefer the smallest end-to-end loop that establishes a reusable architectural path. A form, screen, schema, API layer, or plan alone is not a vertical slice.

For a broad operational inventory product, a valid sequence might preserve receiving, bundles, slabs, photography, locations, barcodes, holds, sales, transfers, pricing controls, and catalog publishing while making the active first deliverable: camera -> adjustable crop -> photo -> stone information -> dimensions -> cost/price -> bundle/slab record -> save -> inventory list -> reopen/edit.

## Information sufficiency by deliverable

The whole-product definition must be sufficient to prevent the active deliverable from choosing an incompatible foundation. The active deliverable itself must be information-complete before execution begins.

Later-deliverable unknowns do not block the active slice when they are recorded, are not dependencies of the slice, and do not force an irreversible product, data, access, or architecture choice now. Resolve them before their own Definition Lock. Never use future uncertainty to excuse a throwaway foundation, and never require every future credential, integration detail, or edge case before building an independent first loop.

## Execution target gate

Choose the execution target from the product's operating requirements, not from whichever builder is easiest to invoke.

Do not default to **Sites** or an equivalent bounded site builder when the production application's core value depends on any of these:

- persistent operational or transactional data;
- complex roles, permissions, tenant boundaries, or private pricing;
- substantial backend workflows, jobs, or state machines;
- repository integration or an established application architecture;
- image ingestion or processing that participates in business state;
- multi-stage receiving, inventory, warehouse, sales, reservation, transfer, or publishing logic; or
- migrations, audit history, resilient failure handling, or system-of-record behavior.

When the person already has an established application or repository that fits the product, prefer that workflow and extend its canonical architecture. Use a standalone production application when no suitable repository exists.

Sites is appropriate when it is actually the best environment for a bounded standalone experience, prototype, presentation, information or marketing surface, or simpler web product. It may prototype or present one surface of a larger operational product, but label that boundary and never represent it as the production system of record or the application's completed foundation.

## Enforce the decision

Before implementation, create an execution contract and validate it with `scripts/execution_contract.py`. The contract must preserve the whole product, identify one active bounded deliverable and its proof, retain later deliverables, and record the execution-target evidence. A passing structural decision does not prove the product interpretation is correct, but a failing decision blocks implementation.

Reject these failures:

- **discovery-to-execution explosion** — treating every discovered capability as work for the current run;
- **phase-delegation burden** — making the person decide how to split a product the system should decompose;
- **layer slice** — calling a screen, schema, service, or plan an end-to-end deliverable;
- **future-input blockade** — refusing an independent first loop until every later integration input exists;
- **whole-product inflation** — calling one closed deliverable the completed product;
- **convenient-target adoption** — selecting Sites because it is available rather than because it fits the operating model; and
- **prototype-as-foundation** — presenting a bounded Sites prototype as the production application architecture.
