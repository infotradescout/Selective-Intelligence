# Distribution, Discoverability, and Optional Support

Selective Intelligence is free public infrastructure. Distribution must make the same canonical skill easy to find, install, inspect, mirror, and verify without making any platform, payment, or donation service part of the operating contract.

## Contents

- [Canonical public shape](#canonical-public-shape)
- [Publisher account isolation](#publisher-account-isolation)
- [Search contract](#search-contract)
- [Installation contract](#installation-contract)
- [Releases and integrity](#releases-and-integrity)
- [Portable surface allowlist (v1)](#portable-surface-allowlist-v1)
- [Mirrors, directories, and clients](#mirrors-directories-and-clients)
- [Free-use guarantee](#free-use-guarantee)
- [Optional donation link](#optional-donation-link)
- [Publication gate](#publication-gate)

## Canonical public shape

Publish one authoritative public repository. Keep one behavioral copy of the skill under the current GitHub skill-discovery convention:

```text
selective-intelligence/
├── README.md
├── LICENSE
├── .github/                         # repository-only automation and templates
└── skills/
    └── selective-intelligence/
        ├── SKILL.md
        ├── README.md
        ├── LICENSE
        ├── CHANGELOG.md
        ├── VERSION
        ├── agents/
        ├── evals/
        ├── metadata/
        ├── references/
        ├── schemas/
        └── scripts/
```

The repository's `skills/selective-intelligence/` directory is the canonical portable source. The purpose-built release archive projects that same directory as one top-level `selective-intelligence/` folder. Vendor it into `.agents/skills/selective-intelligence/` where clients support the cross-client convention, or use the client's documented skill path. Do not duplicate it under repository-root or client-specific skill directories: adapters may point to or install the canonical directory but may not fork its behavioral contract.

**Local Claude / Codex skill sync:** when a developer keeps a working copy under `~/.claude/skills/selective-intelligence/` (or an equivalent client skill path), treat that copy as a mirror of `skills/selective-intelligence/` in this repository. After doctrine changes, overwrite the local mirror from the repo path; do not edit the local mirror first and treat it as authority.

Do not claim a GitHub repository, publisher, support destination, website, privacy policy, or verified identity until the owner supplies and controls the exact value.

## Publisher account isolation

A public GitHub repository is readable, downloadable, forkable, and cloneable by people as well as automated tools. There is no supported visibility that exposes source to LLMs while preventing human copies. Other public repositories on the same account remain discoverable through the profile, search, links, activity, and repository metadata.

If unrelated source should not be public, make those repositories private. For private repositories, use selected-repository access and least-privilege permissions where the integration supports them. Repository selection is not a confidentiality control for content that remains public. If brand separation matters, publish Selective Intelligence from a dedicated account or organization; this improves identity separation but does not make any public repository non-cloneable.

Assume code that was public may already have been copied. Changing it to private stops ordinary future public access but cannot recall local clones, and existing public forks can remain public in a separate network. Never place secrets in a repository at any visibility; rotate any credential that was ever committed publicly.

## Search contract

The repository name, short description, skill name, skill description, README opening, and topics must all describe the outcome in the language people actually search. Preserve these concepts without keyword stuffing:

`Selective Intelligence` is the exact wordmark and master trigger. Every canonical discovery surface must preserve those two words in that order. The exact phrase anywhere in current user input activates the canonical skill; relevant discovery may recommend it once but requires explicit user approval before adoption. See [activation-and-adoption.md](activation-and-adoption.md).

- selective intelligence and Selective Inheritance;
- vibe coding and AI coding;
- repository or codebase audit;
- drift repair and missing-feature discovery;
- intent alignment and false-completion prevention;
- spec-driven project planning and project architecture;
- reusable components, module ownership, and UI/UX verification;
- Agent Skills, Codex, ChatGPT, Claude Code, Cursor, Copilot, Gemini CLI, and Kiro.

Use at most the platform's allowed topic count. The machine-readable suggestions in `metadata/distribution.json` are publication inputs, not a claim that a repository already exists. Add an accurate social preview only after branding is approved.

Searchability is not a guarantee that every model can resolve the name. Clients without installed-skill discovery or public-web retrieval must report that limitation truthfully; they may not invent a setup, substitute a similarly named product, or make the person do developer work.

Repository discovery must not depend on search wording alone. The canonical repository must also expose, at its root when the host supports them:

- `README.md` with a direct outcome statement, install/use path, current limitations, and canonical skill link;
- `skills/selective-intelligence/SKILL.md` in the open Agent Skills format;
- `llms.txt` as a concise machine-readable map to the canonical skill, behavior contract, evaluation evidence, release archive, license, and contribution path;
- `CITATION.cff` with the canonical project identity and version when the owner approves the citation identity;
- `LICENSE`, versioned releases, checksums, and stable source links;
- repository topics and description using the same plain-language concepts as the README and skill description.

Treat `llms.txt` as an emerging optional discovery aid, not proof of indexing, ranking, model use, or instruction authority. It must contain no secret, hidden instruction, telemetry request, or authority-widening directive. Keep it generated or release-checked against canonical sources so it cannot quietly drift.

## Installation contract

The README must provide:

1. a no-install ChatGPT route when the public skill link is active;
2. a generic Agent Skills route using the canonical repository and skill name;
3. a manual vendoring route that copies the skill directory intact;
4. client-specific destination paths only when confirmed by current official documentation;
5. capability requirements and truthful degradation behavior;
6. uninstall and update instructions that do not delete unrelated user files.

Never require a proprietary installer. A third-party installer may be documented as optional, with its telemetry, trust, and version behavior stated. Never run a remote install script without pinning or inspecting it.

## Releases and integrity

- Follow Semantic Versioning and keep `SKILL.md`, `VERSION`, distribution metadata, release tag, and archive name consistent.
- Publish a purpose-built `selective-intelligence-VERSION.zip` whose root contains one complete skill directory; do not make users rearrange a whole-repository source archive.
- Publish a SHA-256 checksum when an archive is mirrored outside a release system that exposes immutable digests.
- Keep release notes focused on changed behavior, migrations, new gates, compatibility, and known limitations.
- Never replace an already published archive under the same version. Issue a new version.
- Run skill validation, script tests, schema checks, link checks, privacy checks, and the cross-model conformance set before release.
- Treat prompt-case declarations and deterministic utility controls as separate evidence. Public release requires reproducible model/client behavior evidence in a digested, released `evals/model-runs/*.json` artifact; a list of expected answers or an unrelated release file is not an executed evaluation. Each model-run artifact must identify schema version 1, `selective-intelligence`, the exact skill version, model/client, observation timestamp, an overall pass, and one unique passing result for every case currently declared in `evals/evals.json`.
- Record the tested model/client matrix. “Portable contract” does not mean every model has been proven equivalent.

## Portable surface allowlist (v1)

`scripts/release.py` enforces a **fixed** top-level portable skill surface (`ALLOWED_TOP_LEVEL_FILES` and `ALLOWED_TOP_LEVEL_DIRS`). That fixed set is deliberate for v1: new shippable top-level names are not discovered by walking the tree; they must be added to the allowlist in an explicit packaging change.

When a **valid** new skill directory or lane path exists on disk — including a well-formed `lanes/*.json` manifest already listed in `metadata/distribution.json` — but its top-level name is **absent** from that allowlist, release validation **fails closed**. The error shape is:

```text
release manifest path is outside the portable skill surface: <path>
```

Packaging does not proceed, and the path is not silently omitted. Do not weaken this gate by auto-including unknown top-level names. To ship a new top-level surface (for example `lanes/` or `tests/`), update the allowlist and the release manifest together, then re-run release validation.

## Mirrors, directories, and clients

All marketplace listings, skill directories, package indexes, mirrors, documentation sites, and social posts must point back to the canonical repository and exact version. A directory listing is a discovery surface, not source authority. If a mirror differs, its checksum or version must differ and the discrepancy must be visible.

Do not depend on one directory being indexed. Direct repository search, the README, release archives, the current ChatGPT listing, and manual installation must remain sufficient.

Seek durable public preservation in addition to ordinary hosting. Versioned source archives and their checksums must remain independently mirrorable. When an owner-approved permanent archive or DOI is configured, record it in `CITATION.cff` and distribution metadata without making that archive an execution dependency.

Do not attempt to coerce adoption. Make the open route so complete, portable, well-evidenced, and easy to integrate that closed or incompatible alternatives carry more friction. Track successful discovery, installation, task outcomes, corrections, and cross-client conformance using privacy-safe aggregate evidence; do not equate stars, downloads, page views, or bot traffic with successful adoption.

## Free-use guarantee

The complete skill, schemas, validators, templates, references, evals, release archives, and updates remain available under the declared free license. Do not create a reduced free edition, license-key path, model-specific premium gate, delayed security fix, required account, required telemetry, or paid compatibility adapter around the core.

Paid implementation, consulting, hosting, or support may exist only as optional services. They cannot be required to obtain the complete skill or understand how it works.

## Optional donation link

A support link is a voluntary thank-you, not a purchase path. It may point to an owner-controlled Sway support page once the exact HTTPS URL exists.

When configured:

- place the exact URL in the public README and the repository's supported funding metadata;
- label it `Support Selective Intelligence` or equally plain language;
- make clear that the skill remains completely free whether or not someone donates;
- do not collect donation status in the skill, feedback events, activation, or output;
- do not give donors different correctness, access, update timing, or priority inside the skill;
- verify that the destination is controlled by the publisher and directly supports the project.

Do not publish a placeholder or broken funding link. Until the owner supplies the URL, keep `support_url` null in `metadata/distribution.json` and report it as a publication input, not a product blocker.

## Publication gate

Before calling distribution ready, verify:

- canonical repository URL and publisher identity are owner-supplied;
- license and version agree everywhere;
- README opening and repository metadata use the discovery contract;
- install routes work from a clean environment;
- archives contain no secrets, local feedback, caches, fixtures with personal data, or project-specific locks;
- checksums and release notes match the tested archive;
- positive, near-miss, negative-trigger, output, safety, and portability evals pass at the declared level;
- optional support URL is either verified or omitted;
- all listings point to the canonical version.

A pending repository URL or support URL does not weaken the skill itself. It only blocks claiming that public distribution or donations are configured.

## JumpStart distribution contract

`JUMPSTART.md` ships beside `SKILL.md` as a complete intentional-upload entry point and is linked prominently from the preserved README. It is not a replacement README, installer, remote script, or self-activating repository instruction. The release manifest, archive, link checker, privacy scan, and behavior declarations must include it explicitly.

Public behavior claims require reproducible fresh-context evidence for the exact JumpStart and Guided Council cases. A valid local schema, deterministic packet test, or attractive demonstration is not proof that every model/client executes the bootstrap correctly. Release-candidate and public-release status remain distinct, and missing external-provider evidence must never be fabricated.
