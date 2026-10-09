"""Offline adapter tests; these are not hosted-agent/model acceptance tests."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import agent
import bootstrap


def directory_alias(alias: Path, target: Path) -> None:
    """Exercise a real redirected directory without granting Windows privileges."""
    try:
        alias.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        if os.name != "nt" or getattr(exc, "winerror", None) != 1314:
            raise
        # A junction exercises the same resolve-versus-absolute boundary.
        subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(alias), str(target)],
            check=True, capture_output=True, text=True,
        )


class AgentTests(unittest.TestCase):
    def test_definition_preserves_source_and_roles(self):
        value = agent.definition()
        self.assertEqual(value["name"], "Selective Intelligence")
        self.assertEqual(bootstrap.SOURCE_COMMIT, "e194759bb6507f5f651d0d69edd19fdafdbb8b2c")
        self.assertEqual(bootstrap.SOURCE_TREE, "6da6833f5c0703c909ebb4d4df4060857ea48b73")
        self.assertEqual(value, json.loads((agent.ROOT / "prepared-definition.json").read_bytes()))
        self.assertEqual(value["multi_agent"], {"enabled": False})
        self.assertEqual(set(value), {"name", "model", "instructions", "multi_agent"})
        self.assertIn("essential logo, photos", value["instructions"])
        self.assertIn("Objector", value["instructions"])
        self.assertNotIn("api_key", json.dumps(value))

    def test_prepared_definition_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = (agent.ROOT / "prepared-definition.json").read_bytes()
            (root / "prepared-definition.json").write_bytes(raw.replace(b"gpt-6-astra", b"gpt-6-sol"))
            with patch.object(agent, "ROOT", root), self.assertRaisesRegex(ValueError, "reviewed packet"):
                agent.definition()

    def test_crlf_checkout_preserves_reviewed_definition(self):
        expected = agent.definition()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = (agent.ROOT / "prepared-definition.json").read_bytes()
            (root / "prepared-definition.json").write_bytes(raw.replace(b"\n", b"\r\n"))
            with patch.object(agent, "ROOT", root):
                self.assertEqual(agent.definition(), expected)

    def test_unreviewed_model_rejected(self):
        with self.assertRaisesRegex(ValueError, "reviewed only"):
            agent.definition("gpt-6-sol")

    def test_registration_local_source_block_prevents_receipt_and_request(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"OPENAI_API_KEY": "synthetic-key", "OPENAI_PROJECT_ID": "proj_fixture"}
        ), patch.object(agent, "api_request") as request:
            state = Path(directory) / "receipt.json"
            with self.assertRaisesRegex(RuntimeError, "local-only"):
                agent.register(state, request=request)
            request.assert_not_called()
            self.assertFalse(state.exists())

    def test_hosted_bootstrap_is_blocked_before_git_or_source_write(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "source"
            with patch.object(bootstrap, "DESTINATION", destination), patch.object(bootstrap, "git") as git:
                with self.assertRaisesRegex(RuntimeError, "local-only"):
                    bootstrap.prepare(destination)
                git.assert_not_called()
                self.assertFalse(destination.exists())

    def test_invalid_model_rejected(self):
        for model in ("", "gpt\nheader", "model; rm -rf /", "x" * 129):
            with self.subTest(model=model), self.assertRaises(ValueError):
                agent.definition(model)

    def test_environment_contains_exact_bootstrap(self):
        value = agent.environment()
        self.assertEqual(base64.b64decode(value["files"][0]["data"]), (agent.ROOT / "bootstrap.py").read_bytes())
        self.assertEqual(value["network"], {"access": "restricted", "allowed_domains": ["github.com"]})
        self.assertNotIn("env", value)
        self.assertNotIn("plugins", value)
        self.assertNotIn("packages", value)
        self.assertEqual(value["capability_directories"], ["/workspace/si-source/skills"])

    def test_session_requires_identity_task_and_lane(self):
        for identity, prompt, lane in (("../bad", "work", "test"), ("agent_1", " ", "test"), ("agent_1", "work", "../x")):
            with self.subTest(identity=identity, lane=lane), self.assertRaises(ValueError):
                agent.session_request(identity, prompt, lane)
        with self.assertRaisesRegex(RuntimeError, "local-only"):
            agent.session_request("agent_test", "Inspect this fixture", "fixture")
        with patch.object(bootstrap, "require_hosted_source"):
            value = agent.session_request("agent_test", "Inspect this fixture", "fixture")
        self.assertEqual(value["agent_id"], "agent_test")
        self.assertEqual(value["metadata"]["si_lane"], "fixture")
        self.assertNotIn("agent", value)

    def test_export_is_offline_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(agent, "api_request", side_effect=AssertionError("network call")):
            output = Path(directory) / "new"
            receipt = agent.export(output)
            self.assertEqual(receipt["api_calls"], 0)
            self.assertFalse(receipt["plugin_modified"])
            self.assertFalse(receipt["registration_allowed"])
            self.assertFalse(receipt["session_preparation_allowed"])
            self.assertFalse(receipt["multi_agent_enabled"])
            self.assertEqual(receipt["source_delivery"], "local_only_not_publicly_fetchable")
            self.assertEqual(json.loads((output / "agent.json").read_text(encoding="utf-8")), agent.definition())
            self.assertEqual((output / "instructions.md").read_bytes(), agent.definition()["instructions"].encode("utf-8"))
            with self.assertRaises(ValueError):
                agent.export(output)

    def test_redirected_output_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "real").mkdir()
            directory_alias(root / "alias", root / "real")
            with self.assertRaises(ValueError):
                agent.export(root / "alias" / "export")

    def test_missing_credentials_prevent_write(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            state = Path(directory) / "receipt.json"
            with self.assertRaises(ValueError):
                agent.register(state, request=lambda *args: self.fail("unexpected request"))
            self.assertFalse(state.exists())

    def test_registration_readback_and_duplicate_prevention(self):
        calls = []
        def fake(method, path, payload=None):
            calls.append((method, path))
            return {"id": "agent_fixture", **agent.definition()}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-key", "OPENAI_PROJECT_ID": "proj_fixture"}), patch.object(bootstrap, "require_hosted_source"):
            state = Path(directory) / "registration.json"
            result = agent.register(state, request=fake)
            self.assertEqual(result["sessions_started"], 0)
            self.assertEqual(calls, [("POST", "/agents"), ("GET", "/agents/agent_fixture")])
            with self.assertRaises(FileExistsError):
                agent.register(state, request=fake)
            self.assertEqual(len(calls), 2)
            self.assertNotIn("synthetic-key", state.read_text(encoding="utf-8"))

    def test_uncertain_registration_is_not_retried(self):
        calls = []
        def fail(*args):
            calls.append(args)
            raise TimeoutError("simulated lost response")
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-key", "OPENAI_PROJECT_ID": "proj_fixture"}), patch.object(bootstrap, "require_hosted_source"):
            state = Path(directory) / "registration.json"
            with self.assertRaises(TimeoutError):
                agent.register(state, request=fail)
            with self.assertRaises(FileExistsError):
                agent.register(state, request=fail)
            self.assertEqual(len(calls), 1)
            self.assertEqual(json.loads(state.read_text(encoding="utf-8"))["status"], "registration_attempted_reconcile_before_retry")

    def test_readback_mismatch_preserves_created_identity(self):
        def fake(method, path, payload=None):
            return {"id": "agent_fixture", **agent.definition(), "model": "different"} if method == "GET" else {"id": "agent_fixture"}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-key", "OPENAI_PROJECT_ID": "proj_fixture"}), patch.object(bootstrap, "require_hosted_source"):
            state = Path(directory) / "registration.json"
            with self.assertRaises(RuntimeError):
                agent.register(state, request=fake)
            self.assertTrue(state.with_name(state.name + ".created.json").exists())
            self.assertFalse(state.with_name(state.name + ".verified.json").exists())

    def test_tool_readback_mismatch_rejected(self):
        def fake(method, path, payload=None):
            return {"id": "agent_fixture", **agent.definition(), "tools": [{"type": "web_search"}]}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-key", "OPENAI_PROJECT_ID": "proj_fixture"}), patch.object(bootstrap, "require_hosted_source"):
            with self.assertRaises(RuntimeError):
                agent.register(Path(directory) / "registration.json", request=fake)

    def test_registration_endpoint_guard(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-key", "OPENAI_PROJECT_ID": "proj_fixture"}):
            for endpoint in ("/agents/../../files", "/agents/sessions", "https://example.org/agents"):
                with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                    agent.api_request("POST", endpoint, {})

    def test_direct_requests_cannot_bypass_local_source_block(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-key", "OPENAI_PROJECT_ID": "proj_fixture"}), patch.object(
            agent.urllib.request, "Request", side_effect=AssertionError("request constructed")
        ) as construct, patch.object(agent.urllib.request, "build_opener", side_effect=AssertionError("network opener")) as opener:
            for method, endpoint in (("POST", "/agents"), ("GET", "/agents/agent_fixture")):
                with self.subTest(method=method), self.assertRaisesRegex(RuntimeError, "local-only"):
                    agent.api_request(method, endpoint, {})
            construct.assert_not_called()
            opener.assert_not_called()

    def test_credentials_not_in_git_environment(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-key", "GITHUB_TOKEN": "synthetic-token", "GIT_CONFIG_COUNT": "5"}):
            environment = bootstrap.git_environment()
            self.assertNotIn("OPENAI_API_KEY", environment)
            self.assertNotIn("GITHUB_TOKEN", environment)
            self.assertEqual(environment["GIT_CONFIG_COUNT"], "0")
            self.assertEqual(environment["GIT_TERMINAL_PROMPT"], "0")

    def test_bootstrap_refuses_other_destination(self):
        with self.assertRaises(ValueError):
            bootstrap.prepare(Path("/tmp/not-the-agent-source"))


class RegistrationIdentityTests(unittest.TestCase):
    """Bind readback to the created ID and preserve every uncertain operation."""

    def check_rejected(self, created, observed, *, expect_readback=True):
        calls = []
        def fake(method, path, payload=None):
            calls.append((method, path))
            return created if method == "POST" else observed
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "OPENAI_API_KEY": "synthetic-key", "OPENAI_PROJECT_ID": "proj_fixture"
        }, clear=True), patch.object(bootstrap, "require_hosted_source"), patch.object(agent.urllib.request, "build_opener", side_effect=AssertionError("network forbidden")):
            state = Path(directory) / "registration.json"
            with self.assertRaises(RuntimeError):
                agent.register(state, request=fake)
            intent = state.read_bytes()
            self.assertFalse(state.with_name(state.name + ".verified.json").exists())
            created_path = state.with_name(state.name + ".created.json")
            self.assertEqual(created_path.exists(), expect_readback)
            if expect_readback:
                self.assertEqual(json.loads(created_path.read_text())["agent_id"], "agent_fixture")
            expected = [("POST", "/agents")]
            if expect_readback:
                expected.append(("GET", "/agents/agent_fixture"))
            self.assertEqual(calls, expected)
            with self.assertRaises(FileExistsError):
                agent.register(state, request=fake)
            self.assertEqual(calls, expected)
            self.assertEqual(state.read_bytes(), intent)

    def test_missing_readback_identity_is_rejected(self):
        self.check_rejected({"id": "agent_fixture"}, agent.definition())

    def test_different_readback_identity_is_rejected(self):
        self.check_rejected({"id": "agent_fixture"}, {**agent.definition(), "id": "agent_other"})

    def test_malformed_readback_identity_is_rejected(self):
        for identity in (None, "", 1, True, [], {}, "agent_fixture\n"):
            with self.subTest(identity=identity):
                self.check_rejected({"id": "agent_fixture"}, {**agent.definition(), "id": identity})

    def test_nonobject_creation_is_rejected(self):
        for created in (None, [], "agent_fixture", 42):
            with self.subTest(created=created):
                self.check_rejected(created, {}, expect_readback=False)

    def test_nonobject_readback_is_rejected(self):
        for observed in (None, [], "agent_fixture", 42):
            with self.subTest(observed=observed):
                self.check_rejected({"id": "agent_fixture"}, observed)

    def test_malformed_tool_item_is_rejected(self):
        for tool in (None, "web_search", [], 42):
            with self.subTest(tool=tool):
                self.check_rejected({"id": "agent_fixture"}, {
                    **agent.definition(), "id": "agent_fixture", "tools": [tool]
                })

    def test_matching_identity_allows_provider_metadata(self):
        calls = []
        def fake(method, path, payload=None):
            calls.append((method, path))
            return {**agent.definition(), "id": "agent_fixture", "object": "agent", "created_at": 1}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "OPENAI_API_KEY": "synthetic-key", "OPENAI_PROJECT_ID": "proj_fixture"
        }, clear=True), patch.object(bootstrap, "require_hosted_source"), patch.object(agent.urllib.request, "build_opener", side_effect=AssertionError("network forbidden")):
            state = Path(directory) / "registration.json"
            result = agent.register(state, request=fake)
            self.assertEqual(result["agent_id"], "agent_fixture")
            self.assertEqual(result["sessions_started"], 0)
            self.assertEqual(json.loads(state.with_name(state.name + ".verified.json").read_text()), result)
            self.assertEqual(calls, [("POST", "/agents"), ("GET", "/agents/agent_fixture")])

    def test_readback_failure_retains_id_and_never_recreates(self):
        calls = []
        def fake(method, path, payload=None):
            calls.append((method, path))
            if method == "POST":
                return {"id": "agent_fixture"}
            raise TimeoutError("synthetic readback timeout")
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "OPENAI_API_KEY": "synthetic-key", "OPENAI_PROJECT_ID": "proj_fixture"
        }, clear=True), patch.object(bootstrap, "require_hosted_source"), patch.object(agent.urllib.request, "build_opener", side_effect=AssertionError("network forbidden")):
            state = Path(directory) / "registration.json"
            with self.assertRaises(TimeoutError):
                agent.register(state, request=fake)
            self.assertEqual(json.loads(state.with_name(state.name + ".created.json").read_text())["agent_id"], "agent_fixture")
            self.assertFalse(state.with_name(state.name + ".verified.json").exists())
            with self.assertRaises(FileExistsError):
                agent.register(state, request=fake)
            self.assertEqual(calls, [("POST", "/agents"), ("GET", "/agents/agent_fixture")])



class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        bootstrap.git(self.root, "init", "--template=")
        self.skill = self.root / "skills" / "selective-intelligence" / "SKILL.md"
        self.skill.parent.mkdir(parents=True)
        self.skill.write_text("# Synthetic SI source fixture\n", encoding="utf-8", newline="\n")
        bootstrap.git(self.root, "add", ".")
        bootstrap.git(self.root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture")
        self.commit = bootstrap.git(self.root, "rev-parse", "HEAD")
        self.tree = bootstrap.git(self.root, "rev-parse", "HEAD^{tree}")

    def tearDown(self):
        self.temporary.cleanup()

    def test_real_git_fixture_verifies(self):
        self.assertEqual(bootstrap.verify_checkout(self.root, self.commit, self.tree)["status"], "source_identity_verified")

    def test_wrong_commit_or_tree_rejected(self):
        for commit, tree in (("0" * 40, self.tree), (self.commit, "0" * 40)):
            with self.subTest(commit=commit, tree=tree), self.assertRaises(ValueError):
                bootstrap.verify_checkout(self.root, commit, tree)

    def test_dirty_or_extra_file_rejected(self):
        (self.root / "extra.txt").write_text("unapproved")
        with self.assertRaises(ValueError):
            bootstrap.verify_checkout(self.root, self.commit, self.tree)

    def test_assume_unchanged_cannot_hide_modified_skill(self):
        bootstrap.git(self.root, "update-index", "--assume-unchanged", "skills/selective-intelligence/SKILL.md")
        self.skill.write_text("tampered\n")
        with self.assertRaisesRegex(ValueError, "bytes differ"):
            bootstrap.verify_checkout(self.root, self.commit, self.tree)

    def test_redirected_source_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            alias = Path(directory) / "source"
            directory_alias(alias, self.root)
            with self.assertRaises(ValueError):
                bootstrap.verify_checkout(alias, self.commit, self.tree)


if __name__ == "__main__":
    unittest.main()
