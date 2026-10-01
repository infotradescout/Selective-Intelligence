# Selective Intelligence — dedicated agent candidate

## Owner's direction

Build an SI agent instead of pursuing plugin repair/resubmission. Leave the
existing plugin, public repository, portable core, and installed copies alone.
This adapter changes delivery, not SI's canonical behavior. It creates neither a
new SaaS nor a mandatory paid edition. It does not unpublish an existing plugin.

The first target is OpenAI's current Managed Agents API, corresponding to the
Agents area of the supplied Platform screenshot. It is not legacy Agent Builder,
a custom GPT, a public directory listing, or a claim that an API definition alone
creates a public-facing application.

## What ships here

`agent.py` builds the reusable agent definition and its hosted session environment.
It also offers an explicit registration-only operation with readback verification;
it cannot start a session, delete an agent, share it publicly, or run inference.
`session_request()` prepares, but does not send, a task request for a provider-returned
agent ID and an explicit project lane.

`bootstrap.py` prepares the complete existing canonical skill in a fresh isolated
sandbox from exact commit `3015ede746c84dfb5deac94a622b650701a21e15`, tree
`51d2ccb7133785685beb08f1ce74616fe4a1ccb7`. This is the verified PR #60 source
candidate, not a claim that #60 was merged or released. No existing plugin ZIP,
manifest, activation reference, or installed directory is rewritten.

The bootstrap fetches only the fixed public GitHub source, verifies commit/tree
identity and actual canonical skill bytes before execution, rejects modified or
redirected copies, disables Git credential helpers, and does not install packages
or run downloaded installation scripts. It requires Python 3 and Git in the
hosted environment. Failure of setup prevents the agent from starting. Git identity
checks establish source integrity, not independent security certification.

The dedicated agent reads the original SI skill and relevant roles. Managed
multi-agent support is enabled with up to three concurrent subagents; the SI
workflow still determines when separate contexts are warranted. Web search is
configured. Sandbox network access is restricted to github.com for source setup.
No GitHub write credential, deployment connector, database, Drive connection,
or Infinity service is fabricated or automatically inherited from ChatGPT.
Additional integrations and network domains need their own authorized configuration.

## Verification and current limits

Nineteen offline tests pass, including real local Git fixture checks, modified
source detection despite assume-unchanged, export integrity, output preservation,
credential isolation, registration readback, and no blind retry after an uncertain
creation response. Registration tests use synthetic provider responses. These
are adapter/source-integrity tests, not model, live tool, or hosted sandbox acceptance.

The full pinned repository could not be cloned in this execution container because
DNS/network access was unavailable. Its identity and relevant governing sources
were read through the connected GitHub app. Full pinned-source bootstrap, complete
repository/project-index refresh, independent review, account registration,
provider billing/model entitlement, fresh task behavior, checkpoint recovery,
external integrations, and public access remain unverified. Do not convert this
candidate into a production claim using the offline test count.

No OpenAI project credential or authenticated browser connection was available.
The Desktop Commander device was reported offline by its connector; that says
nothing about whether the user's PC is physically running. No API request,
billable agent session, new hosting service, or public publication was performed.

## Maintainer operations

These commands are for the executing maintainer/agent; they are not setup homework
for the product owner. Exports require no key, account, package installation, or network.

```bash
python -B adapters/openai-agent/agent.py export --output /new/export/path
python -B -m unittest discover -s adapters/openai-agent -p test_agent.py -v
```

Account registration requires an authorized application API key and explicit project
binding configured outside chat as `OPENAI_API_KEY` and `OPENAI_PROJECT_ID`:

```bash
python -B adapters/openai-agent/agent.py register \
  --output /secure/new/registration.json --approve-registration
```

Keep credentials outside the sandbox and repository. The fixed-origin client uses
TLS, refuses redirects, and sends no automatic retries. An exclusive intent receipt
is saved before creation; returned IDs and readback evidence are separate receipts.
If a response is lost, reconcile that exact project/definition before another
registration attempt. Do not delete the intent receipt just to retry.

OpenAI model/tool/sandbox execution is separately billed; the free SI core remains
unchanged. Do not start billable sessions without an explicit applicable budget.
The exported environment and returned agent ID are inputs to a subsequent authorized
session, not a running agent. The helper does not implement a chat UI or session driver.

## Next acceptance checkpoint

1. In an authorized project, register this definition and retain/read back its ID.
2. Verify the exact-source bootstrap in the real hosted sandbox. Run a bounded
   synthetic file task, inspect real subagent/tool items, and verify its artifact.
3. Continue that same session from saved project state, prove no repeated side effect,
   then attach individually approved operational connectors. Public access and
   cross-session/cross-machine recovery require their own acceptance.

Reuse original SI checkpoint/controller owners. Keep work outside `/workspace/si-source`
to preserve the installed source. One agent definition is not project-data storage;
a new environment template starts a fresh workspace. Do not claim durable external
recovery just because a session ID or template exists.

## API sources checked on 2026-10-01

- https://developers.openai.com/api/docs/guides/agents-api/quickstart
- https://developers.openai.com/api/docs/guides/agents-api/configuration
- https://developers.openai.com/api/docs/guides/agents-api/environments/openai-hosted
- https://developers.openai.com/api/docs/guides/agents-api/multi-agent
- https://developers.openai.com/api/reference/python/resources/beta/subresources/agents/methods/create
- https://developers.openai.com/api/reference/python/resources/beta/subresources/agents/subresources/sessions/methods/create

Review status: same-context/degraded review only, not independent review.
