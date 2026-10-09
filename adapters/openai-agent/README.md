# Selective Intelligence — local agent reconciliation

The offline export now matches the exact reviewed agent preparation: name
Selective Intelligence, model `gpt-6-astra`, its full corrected instructions,
and `multi_agent.enabled: false`. The default definition adds no tools,
metadata, alternate model, or subagent configuration to that prepared packet.
Omitted tools default to an empty list in the current OpenAI create contract.

This is an isolated local reconciliation of the existing PR61 adapter owners,
originally imported byte-for-byte from `46be3f6fa78fdb7e76b99c9f7040a836615e7cc2`.
It also preserves the registration identity repair from the current separately
owned PR61 head `72264189b82353f9ac58ade4442e64fc62b05028`: creation must return
an object with a valid ID, and readback must return an object with that exact ID
before any verified receipt. Uncertain intent and created-ID receipts are retained;
there is no second creation attempt. The existing empty-tools comparison remains
bound to the reviewed local packet rather than importing PR61's web-search default.
It is based on the accepted SI source `e194759bb6507f5f651d0d69edd19fdafdbb8b2c`,
tree `6da6833f5c0703c909ebb4d4df4060857ea48b73`. It changes no existing
worktree, installation, plugin listing, remote PR, or public release.

The public-fetch origin is now `https://github.com/flavorgood/Selective-Intelligence.git`,
the verified destination after the repository migration. Git redirects remain
disabled. The accepted offline archive's manifest retains its recorded
`infotradescout` origin through `RESOURCE_MANIFEST_REPOSITORY`; its source pin,
bytes, and fingerprint remain unchanged. That recorded origin is never fetched.

## Exact preparation and source boundary

`prepared-definition.json` is the unchanged reviewed preparation artifact,
SHA256 `cfb5e0dff556d6fc99a2aa4ff5c7e800e80d22a1e2859478e274476ea9aba0a1`.
The helper checks that packet before exporting it. Only Git's possible CRLF
checkout conversion is normalized for this check; JSON instruction escapes and
the resulting instruction string remain unchanged. A different model or modified
packet fails closed. The existing web-search default and ON/max3 configuration
were removed because they are absent from the reviewed preparation.

Corrected e194 is local-only. Exact canonical resources can now be delivered
without source publication, using the pinned offline archive described below.
Actual hosted installation has not been proved. `SOURCE_READY_FOR_HOSTED_USE` remains false:
the public-fetch bootstrap, registration, direct API requests and valid
session-request preparation remain blocked before external activity. The default
export retains the blocked fetch template. The optional resource export instead
contains the locally verified offline installation setup; it does not pass through
the public-fetch gate. Neither export proves hosted or model acceptance.

Do not flip this guard just to register. The owning PR must prove the required
hosted resources using the exact input archive, under applicable execution authority.
Referenced SI roles, tools, and checkpoints are not provisioned by instruction
text. With subagents OFF, same-context review is degraded; an independent
reviewer must use a distinct supported, authorized context.

## Offline operation

The optional `--source-resources <exact-e194-archive>` export embeds two inline
inputs: this bootstrap and the complete 119-file canonical skill ZIP. Setup uses
only Python's standard library, installs the verified files without fetching or
executing source installers, and disables outbound network access. The archive is
1,959,856 bytes, SHA256 `af55e8d64536987897409263a43a5483405294f3f825da13b6c6c4207138ccd6`.
It fits the current 5 MiB per-file / 10 MiB request inline limits. This is canonical
skill resource delivery, not a full Git checkout or hosted/model acceptance.

`bootstrap.py --build-resources <local-repository> --output <new-archive>` builds
from pinned e194 Git objects, verifies every archive byte against its Git blob,
and includes the complete source file manifest. It does not read mutable working
files, fetch missing objects, or include Git history, configuration or credentials.
`bootstrap.py --install-resources <archive> --destination <new-isolated-directory>`
checks the pinned fingerprint, provenance, paths, modes, file set and blobs before
creating an exclusive destination. Existing and redirected destinations are
preserved. If installation fails after directory reservation, partial output is
retained for reconciliation and no success receipt is written; do not overwrite it.

Run in a new local export directory:

```powershell
python -B adapters/openai-agent/agent.py export --output <new-absolute-local-directory> --source-resources <exact-e194-archive>
python -B -m unittest discover -s adapters/openai-agent -p test_resources.py -v
```

Export requires no credentials, account call, model run, package installation,
or network. It preserves existing destinations and reports source identity,
definition/bootstrap/environment hashes, zero API calls, and explicit
registration/session blocks. The definition's instruction body is also exported
as `instructions.md`.

The existing registration-only controls remain: explicit project binding,
fixed official TLS origin, no redirects or automatic retries, exclusive
pre-request intent receipt, retained provider ID, and readback verification.
The added identity checks run against synthetic replies under a test-only source
gate override with the network opener blocked. Their negative control reproduces
the missing identity/type checks in the prior local implementation; a passing
repair cannot prove that a provider, hosted environment or client accepted it.
They are exercised with synthetic replies under a test-only source-gate override.
The CLI requires `--approve-registration` as before, and source delivery
still blocks it. The helper cannot start sessions, run inference, publish,
delete agents, or create credentials.

## Evidence and remaining work

The affected adapter checks exercise exact OFF configuration, packet integrity,
checkout line endings, export preservation, source-delivery blocks,
registration/readback/retry controls, and real disposable local Git fixtures.
They are offline checks, not hosted-agent, model, API account, public listing,
or customer acceptance. Accepted SI core/profile/directory proof at e194 is
reused and its unchanged suites are not rerun here.

Fresh native independent review is separate from the standing Meta Muse route.
Muse review remains pending until its owner-selected authenticated side chat
can be inspected and its packet/response recorded. No Muse pass is inferred.

Keep PR61 under its existing owner. Its remote head is unchanged by this
local work. Later agent saving requires applicable authorization and an
existing supported project/account; any session additionally requires
authorized model/tool/sandbox execution. No keys, grants, spending,
registration, session, push, merge, installation, or publication occurred.

Official contracts checked in this continuation:

- [Create an agent](https://developers.openai.com/api/reference/python/resources/beta/subresources/agents/methods/create)
- [Plugin listing metadata](https://developers.openai.com/plugins/deploy/submission#listing-metadata)
- [Hosted environment input files and limits](https://developers.openai.com/api/docs/guides/agents-api/environments/files)
