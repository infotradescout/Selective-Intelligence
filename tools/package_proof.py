"""Proposed Render static build; publish only sanitized deterministic proof metadata."""
from __future__ import annotations

import hashlib
import html
import base64
import io
import json
import lzma
import os
import platform
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from pathlib import PurePosixPath

PINS = {
    "si": {
        "repo": "https://github.com/infotradescout/Selective-Intelligence.git",
        "commit": "a810deebca2a36decf1bb6238aa5cbc7f2d9f269",
        "tree": "96c54766d4fe5b304dc57010fda52a25693b01b0",
    },
    "infinity": {
        "repo": "https://github.com/infotradescout/tradescout-infinity.git",
        "commit": "85ab6facde325cf5b65a79c8cf28baeb2be7367c",
        "tree": "4a1702b6934c0fb0b01abad6cf387a6ead57b1ab",
    },
    "platynum": {
        "repo": "https://github.com/infotradescout/platynum-47.git",
        "commit": "f554c5c6ddded94e4a7e04cc288f3af9ec008988",
        "tree": "2b55c2888a888649890dd7d8221594cf257ef1fc",
    },
}
SI_CANONICAL_PIN = "d15220aea58553b08d9f577cf527ff3118f42edf"
CONTRACT_ARCHIVE_SHA256 = "cf5b6bd51bb112329ed6229a2d46c47a3304fe1d648b4b706dcb2ae35df38fa3"
NODE_VERSION = "v22.23.2"
NODE_ARCHIVE = "node-v22.23.2-linux-x64.tar.xz"
NODE_ARCHIVE_SHA256 = "d60acfe00a2932254bb0ad20e01b0d74397a0875595de719654b214f4b03f307"
NODE_DOWNLOAD = f"https://nodejs.org/dist/{NODE_VERSION}/{NODE_ARCHIVE}"


def main() -> None:
    platform_source = Path.cwd().resolve()
    # Temporary clones, logs and engine state never enter the public directory.
    work = Path(tempfile.mkdtemp(prefix="package-proof-"))
    logs = work / "logs"
    logs.mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "NODE_VERSION": NODE_VERSION.removeprefix("v"),
        "PYTHON_VERSION": "3.12.14",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "TMPDIR": str(work),
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0",
        "COREPACK_HOME": str(work / "corepack"),
        "NPM_CONFIG_CACHE": str(work / "npm-cache"),
        "NPM_CONFIG_USERCONFIG": os.devnull,
        "NPM_CONFIG_REGISTRY": "https://registry.npmjs.org",
    }
    steps: list[dict] = []

    def run(name: str, argv: list[str], cwd: Path, extra: dict | None = None,
            timeout: int = 900) -> str:
        print(f"RUN {name}", flush=True)
        result = subprocess.run(argv, cwd=cwd, env={**env, **(extra or {})},
                                capture_output=True, text=True, timeout=timeout)
        output = result.stdout + result.stderr
        payload = output.encode()
        (logs / f"{name}.log").write_bytes(payload)
        steps.append({"name": name, "exitCode": result.returncode,
                      "outputSha256": hashlib.sha256(payload).hexdigest()})
        if result.returncode:
            # Raw private-repository logs are not copied into public output.
            print(output[-16000:], file=sys.stderr, flush=True)
            raise RuntimeError(f"{name} failed, exit {result.returncode}; inspect private build logs")
        return output

    def git(cwd: Path, *args: str) -> str:
        result = subprocess.run(["git", *args], cwd=cwd, env=env,
                                capture_output=True, text=True, timeout=180, check=True)
        return result.stdout.strip()

    def verify(name: str, path: Path) -> None:
        pin = PINS[name]
        if git(path, "rev-parse", "HEAD") != pin["commit"]:
            raise RuntimeError(f"{name}: unexpected source commit")
        if git(path, "rev-parse", "HEAD^{tree}") != pin["tree"]:
            raise RuntimeError(f"{name}: unexpected source tree")
        if git(path, "status", "--porcelain=v1", "--untracked-files=all"):
            raise RuntimeError(f"{name}: source checkout is not clean")

    def clone(name: str) -> Path:
        target = work / name
        target.mkdir()
        run(f"{name}-git-init", ["git", "init", "--quiet", str(target)], work)
        run(f"{name}-git-fetch", ["git", "-c", "credential.helper=", "fetch", "--quiet",
            "--no-tags", "--depth=1", PINS[name]["repo"], PINS[name]["commit"]], target)
        run(f"{name}-git-checkout", ["git", "checkout", "--quiet", "--detach", "FETCH_HEAD"], target)
        verify(name, target)
        return target

    # The launcher is a separately reviewed source branch. Candidate clones below
    # retain their immutable pins. Never reset setup-modified platform files.
    launcher_commit = git(platform_source, "rev-parse", "HEAD")
    launcher_tree = git(platform_source, "rev-parse", "HEAD^{tree}")
    committed_runner = subprocess.run(["git", "show", "HEAD:tools/package_proof.py"],
        cwd=platform_source, env=env, capture_output=True, check=True, timeout=30).stdout
    if committed_runner != Path(__file__).read_bytes():
        raise RuntimeError("Executing launcher differs from its committed source")
    # These values are generated from the exact reviewed source, not client/env
    # files. Chunks remain private configuration and never enter child envs.
    encoded = "".join(os.environ.pop(f"P47_SOURCE_XZ_{i:02d}") for i in range(8))
    archive = base64.b64decode(encoded, validate=True)
    expected_archive_hash = os.environ.pop("P47_SOURCE_XZ_SHA256")
    if hashlib.sha256(archive).hexdigest() != expected_archive_hash:
        raise RuntimeError("Private source archive hash mismatch")
    commit_object = base64.b64decode(os.environ.pop("P47_COMMIT_OBJECT"), validate=True)
    identity = hashlib.sha1(b"commit " + str(len(commit_object)).encode() + b"\0" + commit_object).hexdigest()
    if identity != PINS["platynum"]["commit"]:
        raise RuntimeError("Original Platynum commit object mismatch")
    source = work / "platynum"
    source.mkdir()
    with tarfile.open(fileobj=io.BytesIO(lzma.decompress(archive)), mode="r:") as bundle:
        members = bundle.getmembers()
        if len(members) != 80:
            raise RuntimeError("Unexpected reviewed source file count")
        paths = []
        for member in members:
            relative = PurePosixPath(member.name)
            if (not member.isfile() or relative.is_absolute() or ".." in relative.parts
                    or ".git" in relative.parts or member.name in paths):
                raise RuntimeError("Unsafe or duplicate source archive member")
            paths.append(member.name)
            target = source / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = bundle.extractfile(member)
            if stream is None:
                raise RuntimeError("Missing source bytes")
            target.write_bytes(stream.read())
            target.chmod(member.mode & 0o777)
    run("platynum-git-init", ["git", "init", "--quiet", str(source)], work)
    run("platynum-git-index", ["git", "add", "--force", "--", *paths], source)
    if git(source, "write-tree") != PINS["platynum"]["tree"]:
        raise RuntimeError("Reconstructed Platynum source tree mismatch")
    original = subprocess.run(["git", "hash-object", "-t", "commit", "-w", "--stdin"],
        cwd=source, env=env, input=commit_object, capture_output=True, check=True, timeout=30)
    if original.stdout.decode().strip() != PINS["platynum"]["commit"]:
        raise RuntimeError("Reconstructed Platynum commit mismatch")
    # One authentic commit; no unrelated history or parent contents are bundled.
    (source / ".git/shallow").write_text(PINS["platynum"]["commit"] + "\n")
    run("platynum-detach", ["git", "checkout", "--quiet", "--detach",
        PINS["platynum"]["commit"]], source)
    verify("platynum", source)
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("This proof requires Python 3.12")
    # Python-started native builds do not initialize Render's shell-managed Node.
    # Install one official, checksum-pinned binary into an owned temporary prefix.
    if sys.platform != "linux" or platform.machine() not in ("x86_64", "amd64"):
        raise RuntimeError("The pinned proof toolchain requires Linux x64")
    print("RUN node-toolchain-bootstrap", flush=True)
    node_archive = work / NODE_ARCHIVE
    digest = hashlib.sha256()
    total_bytes = 0
    with urllib.request.urlopen(NODE_DOWNLOAD, timeout=90) as response, node_archive.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            total_bytes += len(chunk)
            if total_bytes > 64 * 1024 * 1024:
                raise RuntimeError("Node toolchain download exceeds the bounded archive size")
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != NODE_ARCHIVE_SHA256:
        raise RuntimeError("Official Node toolchain checksum mismatch")
    toolchain = work / "node-toolchain"
    toolchain.mkdir()
    with tarfile.open(node_archive) as bundle:
        bundle.extractall(toolchain, filter="data")
    node_bin = toolchain / NODE_ARCHIVE.removesuffix(".tar.xz") / "bin"
    env["PATH"] = str(node_bin) + os.pathsep + env["PATH"]
    steps.append({"name": "node-toolchain-bootstrap", "exitCode": 0,
                  "artifactSha256": digest.hexdigest(), "downloadBytes": total_bytes})
    node_output = run("node-version", ["node", "--version"], work)
    # Native builders may print toolchain setup notices around the actual version.
    # Accept one explicit version line; never confuse setup text with execution.
    versions = [line.strip() for line in node_output.splitlines()
                if re.fullmatch(r"v\d+\.\d+\.\d+", line.strip())]
    if versions != [NODE_VERSION]:
        raise RuntimeError(f"This proof requires exactly {NODE_VERSION}; observed {versions}")
    node_version = versions[0]
    run("corepack-version", ["corepack", "--version"], work)
    si = clone("si")
    infinity = clone("infinity")

    canonical = work / "si-canonical"
    canonical.mkdir()
    run("si-canonical-init", ["git", "init", "--quiet", str(canonical)], work)
    run("si-canonical-fetch", ["git", "-c", "credential.helper=", "fetch", "--quiet",
        "--no-tags", "--depth=1", PINS["si"]["repo"], SI_CANONICAL_PIN], canonical)
    run("si-canonical-checkout", ["git", "checkout", "--quiet", "--detach", "FETCH_HEAD"], canonical)
    if git(canonical, "rev-parse", "HEAD") != SI_CANONICAL_PIN:
        raise RuntimeError("Infinity's declared SI pin was not checked out")

    py = sys.executable
    quality_path = work / "si-quality.json"
    run("si-quality", [py, "-B", "skills/selective-intelligence/scripts/quality_gate.py",
                       "--output", str(quality_path)], si)
    quality = json.loads(quality_path.read_text())
    required = {"deterministic_controls", "council_safeguards", "behavior_evidence_safeguards",
                "unit_tests", "release_integrity"}
    if (quality.get("passed") is not True
            or {x["name"] for x in quality.get("checks", [])} != required
            or not all(x.get("passed") is True for x in quality["checks"])
            or quality["sourceIdentity"]["gitHead"] != PINS["si"]["commit"]
            or quality["sourceIdentity"]["workingTreeDirty"] is not False):
        raise RuntimeError("SI quality receipt is incomplete or bound to a different source")
    for name, argv in [
        ("si-discovery", [py, "-B", "tools/test_discovery_bridge.py"]),
        ("si-native-pointers", [py, "-B", "tools/test_native_pointers.py"]),
        ("si-chatgpt-adapter", [py, "-B", "tools/test_chatgpt_adapter.py"]),
        ("si-public-plugin", [py, "-B", "-m", "unittest", "tools.test_public_plugin"]),
    ]:
        run(name, argv, si)

    run("infinity-install", ["corepack", "pnpm", "install", "--frozen-lockfile"], infinity)
    infinity_output = run("infinity-check", ["corepack", "pnpm", "check"], infinity,
                          {"SI_SOURCE_ROOT": str(canonical)})
    # Canonical pnpm check is unchanged; assert its actual Node report is nonempty and complete.
    for key, count in {"tests": 56, "pass": 56, "fail": 0, "skipped": 0}.items():
        if not re.search(rf"(?:#|ℹ)\s+{key}\s+{count}(?:\s|$)", infinity_output):
            raise RuntimeError(f"Infinity has no expected complete {key} result")
    index_output = run("infinity-index", [py, "-B", str(canonical /
        "skills/selective-intelligence/scripts/project_index.py"), "doctor", "--root",
        str(infinity), "--strict", "--json"], infinity)
    index = json.loads(index_output)
    if index.get("ready") is not True or index.get("stale") is not False:
        raise RuntimeError("Infinity source index is not ready")
    pack = work / "pack"
    pack.mkdir()
    run("infinity-pack", ["npm", "pack", "--pack-destination", str(pack)],
        infinity / "packages/contracts")
    archives = list(pack.glob("*.tgz"))
    if len(archives) != 1 or hashlib.sha256(archives[0].read_bytes()).hexdigest() != CONTRACT_ARCHIVE_SHA256:
        raise RuntimeError("Infinity archive does not match the pinned TradeScout consumer package")

    run("platynum-install", ["npm", "ci", "--include=dev", "--no-audit", "--no-fund"], source)
    run("platynum-build", ["npm", "run", "build"], source)
    for zone in ("UTC", "Asia/Tokyo"):
        label = zone.replace("/", "-")
        report = work / f"platynum-{label}.json"
        run(f"platynum-tests-{label}", ["npm", "test", "--", "--reporter=json",
            f"--outputFile={report}"], source,
            {"TZ": zone, "SI_TEST_ENGINE": str(si / "skills/selective-intelligence/scripts/build_engine.py")})
        results = json.loads(report.read_text())
        if (results.get("success") is not True or results.get("numTotalTests") != 107
                or results.get("numPassedTests") != 107
                or results.get("numPendingTests") != 0 or results.get("numFailedTests") != 0):
            raise RuntimeError(f"Platynum {zone} report is incomplete")

    for name, path in (("si", si), ("infinity", infinity), ("platynum", source)):
        verify(name, path)
    summary = {
        "schemaVersion": 1, "passed": True, "observedAt": datetime.now(UTC).isoformat(),
        "sources": PINS, "python": sys.version.split()[0], "node": node_version,
        "nodeToolchain": {"url": NODE_DOWNLOAD, "sha256": NODE_ARCHIVE_SHA256},
        "launcherCommit": launcher_commit, "launcherTree": launcher_tree,
        "launcherSourceSha256": hashlib.sha256(committed_runner).hexdigest(),
        "platynumTransport": "private configuration archive; original commit and full tree verified",
        "siQualityChecks": quality["checks"], "infinityTests": 56,
        "platynumTestsPerTimezone": 107, "timezones": ["UTC", "Asia/Tokyo"],
        "infinityCanonicalSiPin": SI_CANONICAL_PIN,
        "consumerArchiveSha256": CONTRACT_ARCHIVE_SHA256, "steps": steps,
        "canonicalGitHubCi": "unresolved; independent hosted proof does not clear required checks",
        "limits": ["No physical Windows installation", "No live model/provider transaction",
                   "No private catalog snapshot replay", "No PostgreSQL registry proof",
                   "No main merge or production release"],
    }
    public = platform_source / "package-proof-public"
    if public.exists():
        raise RuntimeError("Public proof directory already exists; refusing stale output reuse")
    public.mkdir()
    (public / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (public / "index.html").write_text(
        "<!doctype html><html lang='en'><meta charset='utf-8'><title>Package proof</title>"
        "<main><h1>Deterministic package proof passed</h1><p>SI, Infinity and Platynum. "
        "Canonical GitHub CI remains unresolved. This is not a production release.</p>"
        "<p><a href='summary.json'>Exact revisions and evidence</a></p><pre>" +
        html.escape(json.dumps({name: pin["commit"] for name, pin in PINS.items()}, indent=2)) +
        "</pre></main></html>")
    if sorted(x.name for x in public.iterdir()) != ["index.html", "summary.json"]:
        raise RuntimeError("Unexpected public artifact")
    print("PASS: sanitized static proof summary created", flush=True)


if __name__ == "__main__":
    main()
