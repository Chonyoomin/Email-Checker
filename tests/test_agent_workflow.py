import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_workflow.runner import (Workspace, cycle_lock, execute_cycle,
                                   execute_workflow, read_fix_queue, resolve_file)


@pytest.mark.parametrize("path", ["../escape.py", ".git/config", ".env", "tokens/key.txt",
                                  "checkpoints/model.json", "nested/.env.secret"])
def test_protected_reads(tmp_path, path):
    with pytest.raises(ValueError):
        resolve_file(tmp_path, path)


@pytest.mark.parametrize("path", ["agents/coder.md", "AGENTS.md", "agent_workflow/runner.py",
                                  "docs/memory/HANDOFF.md", "Email_Scam_Checker_Coding_Agent_PRD.md"])
def test_coder_cannot_change_rules_or_memory(tmp_path, path):
    with pytest.raises(ValueError):
        Workspace(tmp_path).write_file(path, "overwrite")


def test_coder_can_write_product(tmp_path):
    Workspace(tmp_path).write_file("src/app.py", "answer = 42\n")
    assert (tmp_path / "src/app.py").read_text() == "answer = 42\n"


def test_lock_prevents_overlapping_cycles(tmp_path):
    with cycle_lock(tmp_path):
        with pytest.raises(RuntimeError):
            with cycle_lock(tmp_path):
                pass
    assert not (tmp_path / ".agent-workflow.lock").exists()


def make_invoker(order, verdict="approved", fail=None):
    def invoke(role, workspace, payload):
        order.append(role)
        if role == fail:
            raise RuntimeError("Simulated model outage")
        if role == "coder":
            workspace.write_file("src/app.py", "answer = 42\n")
            return {"summary": "Implemented"}
        if role == "reviewer":
            assert workspace.read_file("src/app.py") == "answer = 42\n"
            return {"verdict": verdict, "summary": "Reviewed actual code", "findings": [],
                    "evidence": ["src/app.py"]}
        return {"handoff_markdown": "# Handoff\n\nEvidence reviewed.\n", "next_action": "Inspect 1.2"}
    return invoke


def fake_checks(workspace):
    workspace.checks.append({"command": ["pytest", "-q"], "exit_code": 0, "output": "fixture"})


def test_cycle_order_and_persistent_memory(tmp_path):
    order = []
    with patch.object(Workspace, "run_tests", fake_checks):
        report = execute_cycle(tmp_path, "1.1", make_invoker(order))
    assert order == ["coder", "reviewer", "documenter"]
    assert report["status"] == "approved"
    assert report["changed_files"] == ["src/app.py"]
    assert (tmp_path / "docs/memory/HANDOFF.md").exists()
    saved = json.loads(next((tmp_path / "docs/runs").glob("*/report.json")).read_text())
    assert saved["stage"] == "complete"


def test_failed_checks_override_model_approval_and_document(tmp_path):
    def failing(workspace):
        workspace.checks.append({"exit_code": 5, "output": "No tests collected"})
    order = []
    with patch.object(Workspace, "run_tests", failing):
        report = execute_cycle(tmp_path, "1.1", make_invoker(order))
    assert order == ["coder", "reviewer", "documenter"]
    assert report["status"] == "changes_requested"
    assert "Repair task 1.1" in (tmp_path / "docs/memory/LAST_CYCLE.md").read_text()


def test_outage_preserves_handoff_and_records_partial_work(tmp_path):
    handoff = tmp_path / "docs/memory/HANDOFF.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text("previous handoff")
    with patch.object(Workspace, "run_tests", fake_checks):
        with pytest.raises(RuntimeError):
            execute_cycle(tmp_path, "1.1", make_invoker([], fail="reviewer"))
    assert handoff.read_text() == "previous handoff"
    saved = json.loads(next((tmp_path / "docs/runs").glob("*/report.json")).read_text())
    assert saved["status"] == "interrupted"
    assert saved["stage"] == "reviewer"
    assert not (tmp_path / ".agent-workflow.lock").exists()


def test_timeout_is_recorded(tmp_path):
    import subprocess
    workspace = Workspace(tmp_path)
    with patch("agent_workflow.runner.subprocess.run", side_effect=subprocess.TimeoutExpired("pytest", 120)):
        workspace.run_tests()
    assert workspace.checks[0]["exit_code"] == 124


def test_changed_code_during_review_invalidates_approval(tmp_path):
    invoke = make_invoker([])
    def mutate(role, workspace, payload):
        result = invoke(role, workspace, payload)
        if role == "reviewer":
            (tmp_path / "src/app.py").write_text("changed during tests")
        return result
    with patch.object(Workspace, "run_tests", fake_checks):
        with pytest.raises(RuntimeError, match="review is invalid"):
            execute_cycle(tmp_path, "1.1", mutate)


def test_review_findings_return_to_coder_and_require_reapproval(tmp_path):
    order = []
    base = make_invoker(order)
    rounds = 0
    received = []
    def invoke(role, workspace, payload):
        nonlocal rounds
        result = base(role, workspace, payload)
        if role == "coder":
            rounds += 1
            received.append(payload["repair_requests"])
        if role == "reviewer" and rounds == 1:
            result.update(verdict="changes_requested", findings=[
                "1.1: src/app.py fails at startup; verify local launch.",
                "1.1: Missing dependency lockfile; add and verify installation."])
        return result
    with patch.object(Workspace, "run_tests", fake_checks):
        report = execute_workflow(tmp_path, "1.1", invoke)
    assert order == ["coder", "reviewer", "documenter"] * 2
    assert received[0] == []
    assert len(received[1]) == 2
    assert all(item["status"] == "open" for item in received[1])
    assert report["status"] == "approved"
    assert all(item["status"] == "resolved" for item in read_fix_queue(tmp_path)["issues"])
    assert "[x]" in (tmp_path / "docs/memory/REVIEW_FIXES.md").read_text()


def test_open_fixes_block_different_task_and_survive_documenter_failure(tmp_path):
    base = make_invoker([], fail="documenter", verdict="changes_requested")
    with patch.object(Workspace, "run_tests", fake_checks):
        with pytest.raises(RuntimeError, match="outage"):
            execute_cycle(tmp_path, "1.1", base)
        assert read_fix_queue(tmp_path)["issues"][0]["status"] == "open"
        with pytest.raises(RuntimeError, match="Fix task 1.1"):
            execute_cycle(tmp_path, "1.2", make_invoker([]))


def test_repair_loop_stops_at_limit_and_retains_open_fixes(tmp_path):
    order = []
    with patch.object(Workspace, "run_tests", fake_checks):
        report = execute_workflow(tmp_path, "1.1", make_invoker(order, verdict="changes_requested"),
                                  max_cycles=2)
    assert report["status"] == "changes_requested"
    assert order == ["coder", "reviewer", "documenter"] * 2
    assert read_fix_queue(tmp_path)["issues"][0]["status"] == "open"

