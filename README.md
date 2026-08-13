# Selective Intelligence

Selective Intelligence—formerly Selective Inheritance—is a free, portable Agent Skill that bridges plain-language product ownership and developer-grade execution. It reconstructs and challenges human intent before locking it, chooses and proves job-specific UI/UX interaction models, audits and realigns repositories, builds complete human value loops, and treats every release as an evidence-backed checkpoint with a visible improvement frontier—not a fictional state of perfection.

Published by [Platynum Standard](https://github.com/Platynum-Standard). The canonical source is [infotradescout/Selective-Intelligence](https://github.com/infotradescout/Selective-Intelligence).

> **📱 Mobile IDE on the way** — a self-hosted, mobile-first code editor is in build: clone it, deploy it, open the link on your phone, and edit from anywhere.

## Start without installing anything

The hardest part of vibe coding is often the blank chat at the beginning. Use [JUMPSTART.md](skills/selective-intelligence/JUMPSTART.md) to remove that cold start:

`JUMPSTART.md` is the full Tier 1 path for real work in this package; it runs the same intent lock, queue safety, council lanes, and proof checks you need to ship.

1. Download or copy `JUMPSTART.md`.
2. Upload or paste it into ChatGPT with whatever you have—an idea, URL, file, note, screenshot, or existing repository. If you have nothing else yet, JumpStart asks one plain-language outcome question.
3. For continuing product or brand work, follow its prompt to create or open one dedicated ChatGPT Project. Choose project-only memory at creation when isolation is appropriate and the option is available.
4. Let it recover intent, choose the smallest sufficient setup, separate the Worker, Objector, and Aligner roles, execute authorized work, challenge the result, correct valid objections, and leave a resume state.

When the active ChatGPT environment can spawn distinct agents, JumpStart uses that capability automatically; another AI subscription is not required. When it cannot, the same roles run in separate sequential contexts. A second model remains an optional manual Objector, not a prerequisite.

Along the way, save an approved durable decision, reusable output, or hard-won correction as a Project source so later chats inherit the understanding. Before saving, check ownership and permission to retain it, whether the Project is shared, what data is permitted, and the applicable data-use setting. Do not save secrets, brainstorming, stale prices, false completion claims, or cross-project material.

Project sources are continuity aids, not proof: current locks, repository state, tests, and authoritative evidence still win.

Use it when you want an agent to:

- understand terse, corrective, or evolving intent without turning criticism into a new task or invented halt;
- bridge a non-developer's product direction into exact journeys, design, architecture, implementation, operations, and proof without technical homework;
- match effort to the stakes: build a throwaway, local prototype immediately with no ceremony, then graduate to full locking, review, and proof once the work gains persistence, real users, money, or a deployment;
- define a new product, smallest complete MVP, architecture, data, APIs, UI/UX, build order, and proof before coding;
- resume a project across models, agents, branches, or interrupted sessions without losing the governing truth;
- crawl a repository and reconcile intended behavior with routes, components, services, schemas, permissions, tests, deployment, and live surfaces;
- consolidate duplicate modules and place new work under clear canonical ownership;
- turn a URL or sparse brief into a complete profile, campaign, artifact, or system without inventing facts;
- generate precision flyers and text-bearing collateral as render-verified PDFs;
- replace generic landing pages, long scrolls, card walls, and dashboard defaults with a tested interaction model that fits the real job;
- learn from corrections and outcome signals without uploading prompts or personal data;
- preserve what remains weak or untested after a useful release instead of calling the job perfect or permanently finished.

## Open forever

The complete core remains public-domain-equivalent under CC0: skill instructions, behavior cases, validators, schemas, references, release archives, and updates. It requires no vendor, paid account, telemetry, license key, or private compatibility layer. Adapters may expose the canonical source in different clients but may not create a gated behavioral edition.

Human and machine entry points are kept at the repository root: this README, [`llms.txt`](llms.txt), [`CITATION.cff`](CITATION.cff), [`CONTRIBUTING.md`](CONTRIBUTING.md), and the canonical [`SKILL.md`](skills/selective-intelligence/SKILL.md). These make the project easier to navigate and mirror; they are not a promise of indexing, ranking, or forced adoption.

## Use in ChatGPT

[Open Selective Intelligence in ChatGPT](https://chatgpt.com/skills?skill_id=6a60f7ecb940819186be4dffa3094f85) when the skill is enabled for your account. Until a public listing is active, this route may return to the ChatGPT home page for other users.

Example requests:

- “Start this product. Lock the full first release, architecture, database, APIs, UI/UX, and proof before you build it.”
- “Crawl this repo, find drift, missing features, unrouted pages, duplicate systems, and finish the real user flow.”
- “Pick this project back up from its current lock without repeating work or trusting stale evidence.”
- “Use Selective Intelligence to audit and improve Selective Intelligence.”

### Non-developer delegation (for AI teams)

If your team is not developers, run this in order:

1. `si-intake`
2. `si-planner`
3. `si-worker`
4. `si-queue-manager`
5. `si-objector`
6. `si-aligner`
7. `si-verifier`

Each pass gets a short packet and passes it to the next pass. Every output is plain language
by design.

If you have multi-context agent capability, these passes can run in separate AI contexts/agents. If not, run
them in sequence in the same context and keep passing packets.

## Keep queued prompts from getting lost

If prompts arrive faster than one PR/branch slice, use the local queue:

- write each request into the queue first;
- execute one bounded item at a time;
- remove the item only when that slice is fully implemented and reconciled.

This keeps context from drifting when users are spamming requests.

## Portable installation

The canonical portable source is the complete [`skills/selective-intelligence/`](https://github.com/infotradescout/Selective-Intelligence/tree/main/skills/selective-intelligence) directory. Keep that directory intact: `SKILL.md`, `agents/`, `references/`, `schemas/`, `scripts/`, `metadata/`, `evals/`, `lanes/`, `subskills/`, and `tests/` form one skill.

With GitHub CLI 2.90.0 or newer, preview and install it with:

```bash
gh skill preview infotradescout/Selective-Intelligence selective-intelligence
gh skill install infotradescout/Selective-Intelligence selective-intelligence
```

For a manual project-level installation, copy the canonical directory intact to `.agents/skills/selective-intelligence/`. A versioned release archive, once published, will extract as one complete `selective-intelligence/` directory.

Common project-level destinations are:

| Client family | Skill destination |
|---|---|
| Agent Skills-compatible clients, Codex, Cursor, Copilot, Gemini | `.agents/skills/selective-intelligence/` |
| Claude Code | `.claude/skills/selective-intelligence/` |
| Cursor alternative | `.cursor/skills/selective-intelligence/` |
| Gemini CLI alternative | `.gemini/skills/selective-intelligence/` |
| Kiro | `.kiro/skills/selective-intelligence/` |

Use the canonical repository or versioned release archive as the source for every destination. Client paths are adapters, not separate editions.

Filesystem access is required for repository and Start modes. Python 3.10 or newer runs the dependency-free validators. Live web evidence needs browser or network access. When a capability is unavailable, the skill narrows the blocker and preserves the same truth standard.

The current deterministic release-candidate evidence is recorded in [evals/results-0.3.0.json](skills/selective-intelligence/evals/results-0.3.0.json). The eight hidden-oracle behavior cases require captured outputs, repeated fresh contexts, and independent per-invariant grading; six bounded smoke observations across three cases are recorded but do not constitute a full pass. The broader prompt cases in `evals/evals.json` also remain declarations until a reproducible model/client runner records evidence. Cross-client equivalence is not claimed without execution proof.

### Update and uninstall

To update after publication, run `gh skill update selective-intelligence`, or obtain a newer versioned archive or canonical repository revision, verify its release checksum, and replace only the existing `selective-intelligence` skill directory at the destination you chose. Preserve any project-created `.selective-intelligence/` Start Packs and feedback stores; they are project data, not installed skill files.

Version 0.3.0 adds Intent Intelligence, Product Design Intelligence, the vibe-coder–developer bridge, provisional-by-default Council intake, pre-lock intent challenge, evidence-bearing behavior evaluation, and continuous-improvement release checkpoints. It preserves the Start Pack schema and validator at component version 0.1.1 and advances the Council packet protocol to 0.3.0. Existing packs do not gain semantic proof merely by changing a version field; reconstruct and challenge material intent before the next build lock.

To uninstall, remove only the installed `selective-intelligence` skill directory from that documented destination. Do not delete a parent skills directory or any project `.selective-intelligence/` directory.

## GitHub visibility and repository isolation

Selective Intelligence may be published as a public repository on an existing GitHub account. This does not expose private repositories on that account.

Every repository that remains public is independently viewable, downloadable, forkable, and cloneable. GitHub has no public-but-non-cloneable, AI-only, or unlisted-public repository mode. If unrelated source must not be copied by unauthorized people, make that repository private before publishing this skill. For private repositories, use selected-repository access and least-privilege permissions where the integration supports them. A dedicated account or organization can improve brand and profile separation, but it cannot prevent copying of any repository that is public.

Assume anything previously public may already have been copied. Changing visibility does not recall local clones, and existing public forks can remain public in a separate network. Never commit secrets; rotate any credential exposed publicly. See GitHub's documentation for [repository visibility](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility), [cloning](https://docs.github.com/en/repositories/creating-and-managing-repositories/cloning-a-repository), and [source archives](https://docs.github.com/en/repositories/working-with-files/using-files/downloading-source-code-archives).

## Free forever

The complete skill, validators, schemas, references, templates, evals, and updates are released under [CC0 1.0 Universal](skills/selective-intelligence/LICENSE). Use, copy, modify, redistribute, or commercialize them without asking permission.

An optional Sway support link will be added only after the owner supplies the exact destination. Donations will never unlock features, change output quality, or become required for installation or updates.

See [distribution and discoverability](skills/selective-intelligence/references/distribution-and-discoverability.md) for the public repository, release, integrity, and support-link contract.
