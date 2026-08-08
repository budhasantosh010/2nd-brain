from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from second_brain.config import load_config
from second_brain.ingest.service import IngestionService
from second_brain.knowledge.projects import ProjectService, ProjectSpec
from second_brain.paths import BrainPaths
from second_brain.storage.sqlite import SQLiteStore


def _payload(result: Any) -> Any:
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        if isinstance(structured, dict) and "result" in structured:
            return structured["result"]
        return structured
    content = getattr(result, "content", [])
    texts = [getattr(item, "text", "") for item in content if getattr(item, "text", "")]
    if not texts:
        return None
    text = "\n".join(texts)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


async def _exercise_mcp(paths: BrainPaths, source_id: str, project_id: str) -> None:
    env = os.environ.copy()
    env["SECOND_BRAIN_VAULT"] = str(paths.vault)
    env["SECOND_BRAIN_AI_PROVIDER"] = "none"
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "second_brain.cli", "mcp", "serve"],
        env=env,
        cwd=str(paths.repo),
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        names = {tool.name for tool in tools.tools}
        required = {
            "brain_status",
            "brain_search",
            "brain_get_source",
            "brain_get_project",
            "brain_get_project_state",
            "brain_get_decisions",
            "brain_propose_update",
            "brain_review_list",
        }
        assert required <= names

        status = await session.call_tool("brain_status", {})
        assert not status.is_error
        assert _payload(status) is not None

        search = await session.call_tool("brain_search", {"query": "stdio evidence"})
        assert not search.is_error
        assert source_id in json.dumps(_payload(search), default=str)

        source = await session.call_tool("brain_get_source", {"source_id": source_id})
        assert not source.is_error
        assert source_id in json.dumps(_payload(source), default=str)

        project = await session.call_tool("brain_get_project", {"project_id": project_id})
        assert not project.is_error
        assert project_id in json.dumps(_payload(project), default=str)

        state = await session.call_tool("brain_get_project_state", {"project_id": project_id})
        assert not state.is_error
        assert project_id in json.dumps(_payload(state), default=str)

        decisions = await session.call_tool("brain_get_decisions", {"project_id": project_id})
        assert not decisions.is_error

        proposal = await session.call_tool(
            "brain_propose_update",
            {
                "relative_path": "03 Knowledge/Concepts/mcp-proposal.md",
                "proposed_content": "# MCP Proposal\n\nStaged only.\n",
                "reason": "stdio integration acceptance",
                "evidence": [source_id],
            },
        )
        assert not proposal.is_error
        assert "review" in json.dumps(_payload(proposal), default=str).lower()

        reviews = await session.call_tool("brain_review_list", {})
        assert not reviews.is_error
        assert "stdio integration acceptance" in json.dumps(_payload(reviews), default=str)

        invalid = await session.call_tool("brain_get_source", {"source_id": "SRC-does-not-exist"})
        assert invalid.is_error

        protected = await session.call_tool(
            "brain_propose_update",
            {
                "relative_path": "10 System/SYSTEM.md",
                "proposed_content": "blocked",
                "reason": "must be rejected",
            },
        )
        assert protected.is_error

        before = (paths.vault / "AGENTS.md").read_text(encoding="utf-8")
        await session.call_tool("brain_status", {})
        after = (paths.vault / "AGENTS.md").read_text(encoding="utf-8")
        assert after == before


def test_real_stdio_client_server_round_trip(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
    input_dir: Path,
) -> None:
    source = input_dir / "stdio-evidence.txt"
    source.write_text("MCP stdio evidence is preserved and searchable.", encoding="utf-8")
    result = IngestionService(isolated_brain, load_config(isolated_brain), store).ingest_file(source)
    assert result.source_id is not None
    project_id = ProjectService(isolated_brain, store).create(
        ProjectSpec(title="MCP Integration", goal="Verify real stdio client/server serialization.")
    )
    asyncio.run(_exercise_mcp(isolated_brain, result.source_id, project_id))
