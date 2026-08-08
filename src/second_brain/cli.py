"""Typer command-line interface for Global Second Brain V1."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from second_brain.bootstrap import initialize_vault
from second_brain.config import load_config
from second_brain.doctor import doctor
from second_brain.ingest.service import IngestionService, IngestResult
from second_brain.ingest.watcher import InboxWatcher
from second_brain.knowledge.compiler import KnowledgeCompiler
from second_brain.maintenance.daemon import BrainDaemon
from second_brain.maintenance.health import verify_source_integrity
from second_brain.maintenance.monthly import MonthlyMaintenance
from second_brain.maintenance.nightly import NightlyMaintenance
from second_brain.maintenance.weekly import WeeklyMaintenance
from second_brain.mcp.server import serve_stdio
from second_brain.models import ProcessingState
from second_brain.observability.status import brain_status
from second_brain.paths import BrainPaths
from second_brain.rebuild import RebuildService
from second_brain.review.service import ReviewService
from second_brain.storage.sqlite import SQLiteStore
from second_brain.transactions.manager import TransactionManager
from second_brain.validation import validate_vault
from second_brain.verification.service import VerificationService

app = typer.Typer(
    help="Local-first Global Second Brain: preserve, retrieve, verify and maintain your knowledge.",
    no_args_is_help=True,
)
review_app = typer.Typer(help="Inspect and decide staged high-risk/ambiguous changes.", no_args_is_help=True)
maintain_app = typer.Typer(help="Run idempotent maintenance routines.", no_args_is_help=True)
mcp_app = typer.Typer(help="Expose policy-scoped brain tools over local MCP.", no_args_is_help=True)
app.add_typer(review_app, name="review")
app.add_typer(maintain_app, name="maintain")
app.add_typer(mcp_app, name="mcp")


def _runtime() -> tuple[BrainPaths, SQLiteStore]:
    paths = BrainPaths.discover()
    store = SQLiteStore(paths.db)
    return paths, store


def _json(value: object) -> None:
    typer.echo(json.dumps(value, indent=2, ensure_ascii=False, default=str))


@app.command("init")
def init_command() -> None:
    """Create the local runtime vault safely; never overwrite an existing vault."""
    paths = BrainPaths.discover()
    result = initialize_vault(paths)
    if not result.ready:
        _json({"created": result.created, "missing_files": result.missing_files, "missing_dirs": result.missing_dirs})
        raise typer.Exit(code=1)
    rebuild = RebuildService(paths).rebuild()
    typer.echo("Runtime vault created." if result.created else "Runtime vault already existed; no canonical files were overwritten.")
    typer.echo(f"Obsidian vault to open: {result.vault}")
    _json({"rebuild": rebuild})


@app.command("doctor")
def doctor_command() -> None:
    """Run actionable vault/database/provider/index/daemon/MCP health checks."""
    checks = doctor(BrainPaths.discover())
    for check in checks:
        marker = "PASS" if check.ok else "FAIL"
        typer.echo(f"[{marker}] {check.name}: {check.detail}")
        if check.action:
            typer.echo(f"       action: {check.action}")
    if any(not check.ok for check in checks):
        raise typer.Exit(code=1)


@app.command("status")
def status_command() -> None:
    """Show structured current brain status and operational counts."""
    _json(brain_status(BrainPaths.discover()))


@app.command("ingest")
def ingest_command(
    path: Annotated[Path | None, typer.Argument(help="File/folder to ingest. Omit to process the Inbox.")] = None,
) -> None:
    """Preserve/extract/index a path or process the current Inbox."""
    paths, store = _runtime()
    config = load_config(paths)
    service = IngestionService(paths, config, store)
    compiler = KnowledgeCompiler(paths, config, store)
    if path is None:
        count = NightlyMaintenance(paths, config, store).process_inbox()
        _json({"processed": count})
        return
    results = service.ingest(path)
    payload = [_ingest_payload(result, compiler) for result in results]
    _json(payload)
    if any(result.state in {ProcessingState.FAILED, ProcessingState.QUARANTINED} for result in results):
        raise typer.Exit(code=1)


def _ingest_payload(result: IngestResult, compiler: KnowledgeCompiler) -> dict[str, object]:
    payload: dict[str, object] = {
        "input_path": str(result.input_path),
        "source_id": result.source_id,
        "state": result.state.value,
        "message": result.message,
        "raw_path": str(result.raw_path) if result.raw_path else None,
        "extracted_path": str(result.extracted_path) if result.extracted_path else None,
    }
    if result.source_id and result.state == ProcessingState.CLASSIFIED:
        compiled = compiler.compile_source(result.source_id)
        payload["compile"] = {
            "state": compiled.state.value,
            "created_concepts": compiled.created_concepts,
            "review_items": compiled.review_items,
            "cache_hit": compiled.cache_hit,
        }
    return payload


@app.command("watch")
def watch_command() -> None:
    """Watch the Inbox continuously and feed events into deterministic ingestion."""
    InboxWatcher().run_forever()


@app.command("daemon")
def daemon_command() -> None:
    """Run the single-instance autonomous Inbox/maintenance daemon."""
    BrainDaemon().run_forever()


@app.command("search")
def search_command(
    query: Annotated[str, typer.Argument(help="Exact, semantic, project, decision or source query.")],
    limit: Annotated[int, typer.Option("--limit", "-n", min=1, max=100)] = 12,
    project_id: Annotated[str | None, typer.Option("--project")] = None,
) -> None:
    """Run hybrid lexical + semantic + metadata + graph retrieval."""
    from second_brain.retrieval.service import RetrievalService

    service = RetrievalService()
    _json([hit.model_dump(mode="json") for hit in service.search(query, limit=limit, project_id=project_id)])


@app.command("ask")
def ask_command(
    question: Annotated[str, typer.Argument(help="Question to answer only from verified brain evidence.")],
    project_id: Annotated[str | None, typer.Option("--project")] = None,
) -> None:
    """Return an evidence-backed answer or a grounded refusal."""
    answer = VerificationService().ask(question, project_id=project_id)
    _json(answer.model_dump(mode="json"))


@review_app.command("list")
def review_list() -> None:
    """List pending review items."""
    _json([item.model_dump(mode="json") for item in ReviewService().list(status="pending")])


@review_app.command("show")
def review_show(review_id: Annotated[str, typer.Argument()]) -> None:
    """Show one review item."""
    _json(ReviewService().get(review_id).model_dump(mode="json"))


@review_app.command("approve")
def review_approve(review_id: Annotated[str, typer.Argument()]) -> None:
    """Approve and atomically apply a pending staged operation."""
    operation_id = ReviewService().approve(review_id)
    _json({"review_id": review_id, "operation_id": operation_id, "status": "applied"})


@review_app.command("reject")
def review_reject(
    review_id: Annotated[str, typer.Argument()],
    reason: Annotated[str, typer.Option("--reason")] = "rejected",
) -> None:
    """Reject a pending review without applying the proposed operation."""
    ReviewService().reject(review_id, reason)
    _json({"review_id": review_id, "status": "rejected", "reason": reason})


@maintain_app.command("nightly")
def maintain_nightly() -> None:
    paths, store = _runtime()
    store.initialize()
    config = load_config(paths)
    _json(NightlyMaintenance(paths, config, store).run())


@maintain_app.command("weekly")
def maintain_weekly() -> None:
    paths, store = _runtime()
    store.initialize()
    config = load_config(paths)
    _json(WeeklyMaintenance(paths, config, store).run())


@maintain_app.command("monthly")
def maintain_monthly() -> None:
    paths, store = _runtime()
    store.initialize()
    config = load_config(paths)
    _json(MonthlyMaintenance(paths, config, store).run())


@app.command("verify")
def verify_command() -> None:
    """Verify vault/template structure and raw-source immutability hashes."""
    paths, store = _runtime()
    report = validate_vault(paths.vault)
    findings = verify_source_integrity(store) if paths.db.exists() else []
    corrupt = [item for item in findings if not item.ok]
    _json(
        {
            "vault_validation": {"ok": report.ok, "checked": report.checked, "errors": report.errors},
            "source_integrity": {
                "checked": len(findings),
                "ok": len(corrupt) == 0,
                "findings": [asdict(item) for item in corrupt],
            },
        }
    )
    if not report.ok or corrupt:
        raise typer.Exit(code=1)


@app.command("rebuild")
def rebuild_command() -> None:
    """Destroy/rebuild generated database/search/vector state from canonical local evidence/ledgers."""
    _json(RebuildService().rebuild())


@app.command("recover")
def recover_command() -> None:
    """Rollback interrupted canonical operations from transaction history."""
    _json({"recovered": TransactionManager().recover_interrupted()})


@mcp_app.command("serve")
def mcp_serve() -> None:
    """Serve Global Brain MCP tools over local stdio transport."""
    serve_stdio()


if __name__ == "__main__":
    app()
