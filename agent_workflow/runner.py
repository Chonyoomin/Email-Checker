"""Sequential LangChain development cycle with repository-backed memory."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
CONTEXT = (
    "AGENTS.md", "Email_Scam_Checker_Coding_Agent_PRD.md",
    "Email_Scam_Checker_Task_Breakdown.md", "docs/IMPLEMENTATION_STATUS.md",
    "docs/memory/HANDOFF.md", "docs/memory/DECISIONS.md",
)
BLOCKED = {".git", ".venv", "__pycache__", ".pytest_cache", "tokens", "checkpoints"}
TEXT_SUFFIXES = {".py", ".md", ".toml", ".txt", ".in", ".json", ".html", ".css",
                 ".js", ".yaml", ".yml", ".lock", ".example"}
CODER_DIRS = {"src", "tests", "static", "templates"}
CODER_FILES = {"pyproject.toml", "requirements.txt", "requirements.in", "uv.lock",
               "README.md", ".env.example", ".gitignore", "Dockerfile", "compose.yaml"}


def read_fix_queue(root: Path) -> dict:
    path = root / "docs/memory/REVIEW_FIXES.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"task": None, "issues": []}


def save_fix_queue(root: Path, task: str, run_id: str, review: dict) -> None:
    previous = read_fix_queue(root)
    issues = previous["issues"] if previous["task"] == task else []
    if review["verdict"] == "approved":
        for issue in issues:
            issue.update(status="resolved", resolved_in=run_id)
    else:
        findings = review["findings"] or [review["summary"] or "Review requires changes; acceptance is unverified."]
        for finding in findings:
            if not any(issue["description"] == finding and issue["status"] == "open" for issue in issues):
                issues.append({"id": f"{run_id}-F{len(issues) + 1}", "description": finding,
                               "status": "open", "reported_in": run_id})
    queue = {"task": task, "issues": issues, "last_review": run_id}
    atomic_write(root / "docs/memory/REVIEW_FIXES.json", json.dumps(queue, indent=2, ensure_ascii=False))
    lines = ["# Review fixes", "", f"Task: {task}", "",
             "Fix every open item before advancing. Only reviewer approval resolves items.", ""]
    for issue in issues:
        lines += [f"- [{'x' if issue['status'] == 'resolved' else ' '}] {issue['id']}: {issue['description']}"]
    if not issues:
        lines.append("No open review findings.")
    atomic_write(root / "docs/memory/REVIEW_FIXES.md", "\n".join(lines) + "\n")


def resolve_file(root: Path, name: str) -> Path:
    candidate = (root / name).resolve()
    relative = candidate.relative_to(root.resolve())  # Reject traversal and symlink escapes.
    if not relative.parts or any(p in BLOCKED for p in relative.parts):
        raise ValueError("Protected path")
    if any(p.startswith(".env") and p != ".env.example" for p in relative.parts):
        raise ValueError("Secret configuration is excluded")
    if candidate.suffix not in TEXT_SUFFIXES and candidate.name not in {
        "Dockerfile", ".gitignore", ".gitattributes"
    }:
        raise ValueError("Only project text files are accessible")
    return candidate


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


class Workspace:
    def __init__(self, root: Path):
        self.root = root
        self.checks: list[dict] = []

    def read_file(self, path: str) -> str:
        """Read a UTF-8 project text file; large files require smaller files instead."""
        target = resolve_file(self.root, path)
        if target.stat().st_size > 250_000:
            raise ValueError("File exceeds 250 KB read limit")
        return target.read_text(encoding="utf-8")

    def list_files(self) -> str:
        """List accessible source, tests, configuration and Markdown files."""
        found = []
        for parent, dirs, files in os.walk(self.root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in BLOCKED and
                             not (Path(parent) / d).is_symlink())
            for name in sorted(files):
                relative = (Path(parent) / name).relative_to(self.root).as_posix()
                try:
                    resolve_file(self.root, relative)
                except ValueError:
                    continue
                found.append(relative)
        return "\n".join(found)

    def write_file(self, path: str, content: str) -> str:
        """Coder only: create or replace a product source/test/configuration file."""
        target = resolve_file(self.root, path)
        relative = target.relative_to(self.root.resolve())
        if relative.parts[0] not in CODER_DIRS and relative.as_posix() not in CODER_FILES:
            raise ValueError("Coder cannot edit agent tooling, requirements or memory")
        if len(content.encode("utf-8")) > 250_000:
            raise ValueError("File exceeds write limit")
        atomic_write(target, content)
        return f"Wrote {relative.as_posix()}"

    def run_tests(self) -> str:
        """Run repository pytest checks with a 120 second timeout; record real results."""
        command = [sys.executable, "-m", "pytest", "-q"]
        try:
            result = subprocess.run(command, cwd=self.root, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=120)
            record = {"command": command, "exit_code": result.returncode,
                      "output": (result.stdout + result.stderr)[-20000:]}
        except subprocess.TimeoutExpired:
            record = {"command": command, "exit_code": 124, "output": "Timed out after 120s"}
        self.checks.append(record)
        return json.dumps(record)

    def snapshot(self) -> dict[str, str]:
        return {name: hashlib.sha256((self.root / name).read_bytes()).hexdigest()
                for name in self.list_files().splitlines()
                if not name.startswith("docs/runs/")}


@contextmanager
def cycle_lock(root: Path):
    path = root / ".agent-workflow.lock"
    try:
        handle = path.open("x", encoding="utf-8")
    except FileExistsError as error:
        raise RuntimeError("Another cycle or stale lock exists; see workflow recovery instructions") from error
    try:
        with handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)


def execute_cycle(root: Path, task: str, invoke) -> dict:
    """Injectable agent boundary lets tests verify orchestration without a model."""
    workspace = Workspace(root)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    report: dict = {"run_id": run_id, "task": task, "stage": "coder", "status": "running"}
    run_path = root / "docs" / "runs" / run_id

    def persist():
        report["checks"] = workspace.checks
        atomic_write(run_path / "report.json", json.dumps(report, indent=2, ensure_ascii=False))
        atomic_write(run_path / "REPORT.md", "# Agent cycle\n\n```json\n" +
                     json.dumps(report, indent=2, ensure_ascii=False) + "\n```\n")

    with cycle_lock(root):
        queue = read_fix_queue(root)
        pending = [issue for issue in queue["issues"] if issue["status"] == "open"]
        if pending and queue["task"] != task:
            raise RuntimeError(f"Fix task {queue['task']} before starting task {task}")
        report["repair_requests"] = pending
        before = workspace.snapshot()
        persist()
        try:
            report["coder"] = invoke("coder", workspace, {"task": task, "repair_requests": pending})
            after = workspace.snapshot()
            report["changed_files"] = sorted(name for name in before.keys() | after.keys()
                                              if before.get(name) != after.get(name))
            report["stage"] = "reviewer"
            workspace.run_tests()  # Harness evidence, not an agent's claim.
            persist()
            report["reviewer"] = invoke("reviewer", workspace, report.copy())
            if workspace.snapshot() != after:
                raise RuntimeError("Files changed during verification; review is invalid; rerun the cycle")
            review = report["reviewer"]
            if not workspace.checks or any(c["exit_code"] != 0 for c in workspace.checks):
                review["verdict"] = "changes_requested"
                review["findings"].append("Harness checks failed or timed out; acceptance is unverified.")
            if review["findings"]:
                review["verdict"] = "changes_requested"
            # Save findings before documentation so a documenter outage cannot lose them.
            save_fix_queue(root, task, run_id, review)
            after = workspace.snapshot()
            report["stage"] = "documenter"
            persist()
            documentation = invoke("documenter", workspace, report.copy())
            if workspace.snapshot() != after:
                raise RuntimeError("Files changed during documentation; rerun the cycle")
            report["documenter"] = documentation
            report["status"] = review["verdict"]
            atomic_write(root / "docs/memory/HANDOFF.md", documentation["handoff_markdown"])
            next_action = documentation["next_action"] if review["verdict"] == "approved" else (
                f"Repair task {task}. Resolve reviewer findings and rerun the same task.\n\n" +
                "\n".join(review["findings"]))
            atomic_write(root / "docs/memory/LAST_CYCLE.md",
                         f"# Last cycle\n\nTask: {task}\n\nVerdict: {report['status']}\n\n"
                         f"Report: [full evidence](../runs/{run_id}/REPORT.md)\n\n"
                         f"Next action: {next_action}\n\n"
                         "Task approval does not establish phase completion. Reconcile phase gates "
                         "in IMPLEMENTATION_STATUS.md before advancing phases.\n")
            report["stage"] = "complete"
        except BaseException as error:
            # Preserve partial work and the last successful handoff on model/tool failure.
            report["status"] = "interrupted"
            report["error_type"] = type(error).__name__
            persist()
            atomic_write(root / "docs/memory/LAST_CYCLE.md",
                         f"# Interrupted cycle\n\nTask: {task}\n\nStage: {report['stage']}\n\n"
                         f"Report: ../runs/{run_id}/REPORT.md\n\nInspect partial code and rerun "
                         "the same task. No approval or phase advancement is established.\n")
            raise
        finally:
            persist()
    return report


def execute_workflow(root: Path, task: str, invoke, max_cycles: int = 3) -> dict:
    """Repeat code → review → document for the same task until approved or bounded stop."""
    if max_cycles < 1:
        raise ValueError("max_cycles must be positive")
    for _ in range(max_cycles):
        report = execute_cycle(root, task, invoke)
        if report["status"] == "approved":
            return report
    return report


def build_invoker(root: Path, model_name: str, limit: int):
    # Lazy imports keep --help and deterministic tests independent of LLM packages.
    from langchain.agents import create_agent
    from langchain.agents.structured_output import ToolStrategy
    from langchain_ollama import ChatOllama
    from pydantic import BaseModel, ConfigDict
    from typing import Literal

    class Review(BaseModel):
        model_config = ConfigDict(extra="forbid")
        verdict: Literal["approved", "changes_requested"]
        summary: str
        findings: list[str]
        evidence: list[str]

    class Documentation(BaseModel):
        model_config = ConfigDict(extra="forbid")
        handoff_markdown: str
        next_action: str

    def invoke(role, workspace, payload):
        context = "\n\n".join(f"## {name}\n{workspace.read_file(name)}" for name in CONTEXT)
        if (root / "docs/memory/LAST_CYCLE.md").exists():
            context += "\n\n" + workspace.read_file("docs/memory/LAST_CYCLE.md")
        if (root / "docs/memory/REVIEW_FIXES.md").exists():
            context += "\n\n" + workspace.read_file("docs/memory/REVIEW_FIXES.md")
        tools = [workspace.read_file, workspace.list_files]
        if role == "coder":
            tools += [workspace.write_file, workspace.run_tests]
        elif role == "reviewer":
            tools += [workspace.run_tests]
        schema = Review if role == "reviewer" else Documentation if role == "documenter" else None
        # Separate agent instances and messages prevent coder conversation bias in review.
        agent = create_agent(
            model=ChatOllama(model=model_name, temperature=0, base_url="http://127.0.0.1:11434",
                             client_kwargs={"timeout": 180}),
            tools=tools,
            system_prompt=workspace.read_file(f"agents/{role}.md") + "\n\n" + context,
            response_format=ToolStrategy(schema) if schema else None,
        )
        result = agent.invoke({"messages": [{"role": "user", "content": json.dumps(payload)}]},
                              config={"recursion_limit": limit})
        if schema:
            return result["structured_response"].model_dump()
        return {"summary": result["messages"][-1].content}

    return invoke


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, help="One task ID, e.g. 1.1")
    parser.add_argument("--model", required=True, help="Installed Ollama model supporting tool calls")
    parser.add_argument("--limit", type=int, default=60, help="Per-agent graph step limit")
    parser.add_argument("--max-cycles", type=int, default=3, help="Maximum code/review/document cycles for this task")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    if args.max_cycles < 1:
        parser.error("--max-cycles must be positive")
    import re
    tasks = (ROOT / "Email_Scam_Checker_Task_Breakdown.md").read_text(encoding="utf-8")
    if not re.search(r"^### " + re.escape(args.task) + r"\s", tasks, re.MULTILINE):
        parser.error("--task must be an existing task ID from the breakdown")
    # Development source must not be sent to hosted tracing services.
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    try:
        report = execute_workflow(ROOT, args.task, build_invoker(ROOT, args.model, args.limit), args.max_cycles)
    except Exception as error:
        print(f"Cycle stopped ({type(error).__name__}); inspect docs/runs and LAST_CYCLE.md.", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"{report['status']}: docs/runs/{report['run_id']}/REPORT.md")
    raise SystemExit(0 if report["status"] == "approved" else 2)
