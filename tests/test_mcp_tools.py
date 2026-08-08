from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from second_brain.config import load_config
from second_brain.ingest.service import IngestionService
from second_brain.mcp.server import create_server
from second_brain.mcp.tools_read import BrainReadTools
from second_brain.mcp.tools_write import BrainWriteTools
from second_brain.paths import BrainPaths
from second_brain.storage.sqlite import SQLiteStore

EXPECTED_TOOLS = {
    "brain_search",
    "brain_get_source",
    "brain_get_note",
    "brain_get_project",
    "brain_get_project_state",
    "brain_get_decisions",
    "brain_get_conflicts",
    "brain_get_current_context",
    "brain_get_unanswered_questions",
    "brain_status",
    "brain_ingest",
    "brain_process_inbox",
    "brain_propose_update",
    "brain_update_project_state",
    "brain_create_handoff",
    "brain_review_list",
}


def test_mcp_server_registers_required_policy_scoped_tools(isolated_brain: BrainPaths) -> None:
    server = create_server(isolated_brain)
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}
    assert names >= EXPECTED_TOOLS


def test_mcp_read_tools_return_brain_evidence(
    isolated_brain: BrainPaths, store: SQLiteStore, input_dir: Path
) -> None:
    source = input_dir / "mcp-source.txt"
    source.write_text("MCP read evidence marker MCP-READ-4488.", encoding="utf-8")
    result = IngestionService(isolated_brain, load_config(isolated_brain), store).ingest_file(source)
    assert result.source_id is not None
    reads = BrainReadTools(isolated_brain, store)
    search = reads.search("MCP-READ-4488")
    assert any(item["source_id"] == result.source_id for item in search)
    source_payload = reads.get_source(result.source_id)
    assert source_payload["source"]["id"] == result.source_id
    assert source_payload["segments"]


def test_mcp_generic_update_is_staged_and_protected_paths_are_blocked(
    isolated_brain: BrainPaths, store: SQLiteStore
) -> None:
    writes = BrainWriteTools(isolated_brain, load_config(isolated_brain), store)
    result = writes.propose_update(
        "03 Knowledge/Concepts/mcp-proposal.md",
        "# Proposed MCP Content\n",
        "Synthetic safe proposal",
        evidence=[],
    )
    assert result["review_id"].startswith("RVW-")
    assert result["status"] == "pending"
    assert not (isolated_brain.vault / "03 Knowledge" / "Concepts" / "mcp-proposal.md").exists()
    assert writes.review_list()

    for path in ("AGENTS.md", "10 System/SYSTEM.md", "02 Sources/Raw/Other/blocked.txt", ".brain/config.yaml"):
        with pytest.raises(ValueError, match="protected|blocked"):
            writes.propose_update(path, "bad", "must remain blocked")
