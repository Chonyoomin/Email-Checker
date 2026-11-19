"""Real LangChain graph construction; model responses remain offline fixtures."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_workflow.runner import ROOT, Workspace, build_invoker


def test_three_real_agent_graphs_construct_with_role_permissions():
    agents = pytest.importorskip("langchain.agents")
    pytest.importorskip("langchain_ollama")
    real_create = agents.create_agent
    constructed = []

    def construct(**kwargs):
        graph = real_create(**kwargs)
        assert callable(graph.invoke)
        constructed.append(kwargs)
        schema = kwargs["response_format"]
        if schema is None:
            output = {"messages": [SimpleNamespace(content="coder fixture")]}
        elif len(constructed) == 2:
            output = {"structured_response": schema.schema(
                verdict="changes_requested", summary="fixture", findings=["pending"], evidence=[])}
        else:
            output = {"structured_response": schema.schema(
                handoff_markdown="# Fixture", next_action="repair")}
        return SimpleNamespace(invoke=lambda *args, **kwargs: output)

    with patch.object(agents, "create_agent", side_effect=construct):
        invoke = build_invoker(ROOT, "offline-fixture", 10)
        for role in ("coder", "reviewer", "documenter"):
            assert invoke(role, Workspace(ROOT), {"task": "1.1"})

    names = [{tool.__name__ for tool in item["tools"]} for item in constructed]
    assert "write_file" in names[0]
    assert "write_file" not in names[1] | names[2]
    assert "run_tests" in names[1]
    assert "run_tests" not in names[2]
