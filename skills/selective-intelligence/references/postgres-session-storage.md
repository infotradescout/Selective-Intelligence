# Optional shared session persistence

Use this for shared checkpoints with **one active executor per workspace and
session**. A replacement process may recover only after the previous executor
is confirmed terminated. The existing file backend remains the default and
requires no database, API key, paid service, or Python dependency.

SI retains interpretation, approval, task, receipt, and verification ownership.
PostgreSQL stores the same validated JSON session and monotonic revision. This
does not turn another product, gateway, or model into an SI engine.

## Configure a native SI worker

Install the optional `psycopg[binary]>=3.2,<4` dependency in that worker's Python
environment. Set these server-side variables using the deployment secret store:

| Variable | Value |
| --- | --- |
| `SI_SESSION_BACKEND` | `postgres` |
| `SI_SESSION_EXECUTION_MODE` | `single-active`; explicitly acknowledge the execution prerequisite below |
| `SI_SESSION_DATABASE_URL` | Direct PostgreSQL connection URI for the approved database |
| `SI_SESSION_NAMESPACE` | Explicit project identifier, such as `si-worker-preview` |

Use a direct Neon endpoint, **not** its `-pooler` transaction-pooling endpoint.
The engine holds a session advisory lock while a governed operation runs. Each
checkpoint commits independently so it survives a killed worker. After confirming
that worker has terminated, a replacement acquires the lock and reads the
persisted revision. Remote
connections require `sslmode=verify-full`; system trust roots are the default.

Initialize the table explicitly on the intended isolated database:

```bash
python scripts/lane_session.py initialize-store
```

This creates `public.si_runtime_sessions`. Normal session reads/writes never
provision a database or create a table. Give the runtime role only the database
and table privileges it needs; use a separate migration identity if appropriate.
Namespaces prevent accidental record collisions, **not** access by another
holder of the same database credentials. Separate product trust boundaries need
separate roles/databases or an independently enforced authorization layer.

The existing engine, CLI and MCP callers continue through `lane_session`; no
second checkpoint API or duplicated orchestration engine is introduced. Keep
workspaces and artifact evidence accessible at the paths recorded in the session.
Shared session storage alone does not move local files between machines.

## Recovery contract

- A database advisory lock serializes cooperative checkpoint updates while the
  connection is alive. It is not a worker lease or a scheduler.
- Stale revisions cannot overwrite newer approval, correction, or evidence.
- A missing store, lost connection, invalid configuration, or database error
  fails closed; it never creates a local replacement session.
- Process death releases its database lock. Completed evidence remains durable.
- A network failure can release that lock while the old executor still runs.
  PostgreSQL revision checks do not fence workspace writes, rollback, or external
  tools. **Do not automatically launch a replacement on lock release, connection
  loss, or timeout. Confirm the old executor has terminated first.** The explicit
  `single-active` setting acknowledges this prerequisite; it does not enforce
  process termination or make active-active execution safe.
- Database durability is not exactly-once execution of arbitrary external tools.
  Preserve existing pending/unknown receipts, reconciliation and idempotency
  rules before retrying an interrupted external action.
- Selecting `file` again does not migrate sessions back. Do not change a live
  worker's backend or namespace as a recovery shortcut.

## Verify before adopting

Set `SI_TEST_POSTGRES_URL` to a **disposable local or approved isolated test**
database and run the PostgreSQL session tests. They create the session table and
use temporary unique namespaces. Never supply a customer production database.

```bash
python -B -m unittest discover -s tests -p test_postgres_sessions.py
```

Those tests cover process restart, lock release after process death, concurrent
writers, stale revisions, namespace separation and recovery of real engine
verification evidence. Local Postgres proof does not establish a Neon
deployment, installed client adoption, cross-machine workspace availability or
provider-side spending limits. Record those states separately.
