"""SQLite schema and migrations for generated/structured brain state."""

from __future__ import annotations

SCHEMA_VERSION = 1

MIGRATION_1 = r"""
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL,
    title TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    original_path TEXT NOT NULL,
    raw_path TEXT,
    extracted_path TEXT,
    mime_type TEXT,
    size_bytes INTEGER NOT NULL,
    created_at TEXT,
    ingested_at TEXT NOT NULL,
    status TEXT NOT NULL,
    authority TEXT NOT NULL DEFAULT 'unknown',
    sensitivity TEXT NOT NULL DEFAULT 'local_only',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(status);
CREATE INDEX IF NOT EXISTS idx_sources_type ON sources(source_type);
CREATE INDEX IF NOT EXISTS idx_sources_ingested ON sources(ingested_at);

CREATE TABLE IF NOT EXISTS source_segments (
    segment_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    locator TEXT NOT NULL,
    text TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_segments_source_position ON source_segments(source_id, position);

CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    note_type TEXT NOT NULL,
    title TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'provisional',
    created_at TEXT,
    updated_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_notes_type ON notes(note_type);
CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated_at);

CREATE TABLE IF NOT EXISTS concepts (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL,
    verification_state TEXT NOT NULL,
    note_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_concepts_title ON concepts(title);
CREATE INDEX IF NOT EXISTS idx_concepts_state ON concepts(verification_state);

CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    statement TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence_state TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(id),
    source_locator TEXT,
    valid_from TEXT,
    valid_to TEXT,
    supersedes TEXT REFERENCES claims(id),
    superseded_by TEXT REFERENCES claims(id),
    materialized_path TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_claims_source ON claims(source_id);
CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status);

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    note_path TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    project_path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);

CREATE TABLE IF NOT EXISTS project_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    current_state TEXT NOT NULL,
    next_action TEXT,
    blockers_json TEXT NOT NULL DEFAULT '[]',
    open_questions_json TEXT NOT NULL DEFAULT '[]',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    verified_at TEXT,
    created_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_project_states_project_active ON project_states(project_id, active);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    decision TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT '',
    reasoning TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    decided_at TEXT,
    supersedes TEXT REFERENCES decisions(id),
    superseded_by TEXT REFERENCES decisions(id),
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_decisions_project ON decisions(project_id);
CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status);

CREATE TABLE IF NOT EXISTS relationships (
    id TEXT PRIMARY KEY,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    source_id TEXT REFERENCES sources(id),
    provisional INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_relationships_from ON relationships(from_id);
CREATE INDEX IF NOT EXISTS idx_relationships_to ON relationships(to_id);
CREATE INDEX IF NOT EXISTS idx_relationships_relation ON relationships(relation);

CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    permission_level INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS processing_jobs (
    id TEXT PRIMARY KEY,
    source_id TEXT REFERENCES sources(id),
    input_path TEXT NOT NULL,
    state TEXT NOT NULL,
    stage TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    error_type TEXT,
    error_message TEXT,
    next_action TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON processing_jobs(state);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON processing_jobs(source_id);

CREATE TABLE IF NOT EXISTS review_items (
    review_id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    risk TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    affected_paths_json TEXT NOT NULL DEFAULT '[]',
    decision TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_review_status ON review_items(status);

CREATE TABLE IF NOT EXISTS operations (
    operation_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    description TEXT NOT NULL,
    permission_level INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    error_type TEXT,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_operations_status ON operations(status);

CREATE TABLE IF NOT EXISTS conflicts (
    id TEXT PRIMARY KEY,
    left_id TEXT NOT NULL,
    right_id TEXT NOT NULL,
    conflict_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    explanation TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_conflicts_status ON conflicts(status);

CREATE TABLE IF NOT EXISTS open_loops (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    project_id TEXT REFERENCES projects(id),
    source_id TEXT REFERENCES sources(id),
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_open_loops_status ON open_loops(status);
CREATE INDEX IF NOT EXISTS idx_open_loops_project ON open_loops(project_id);

CREATE TABLE IF NOT EXISTS project_candidates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    rationale TEXT NOT NULL,
    confidence_state TEXT NOT NULL,
    source_id TEXT REFERENCES sources(id),
    status TEXT NOT NULL DEFAULT 'candidate',
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_project_candidates_status ON project_candidates(status);
CREATE INDEX IF NOT EXISTS idx_project_candidates_name ON project_candidates(name);

CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    searched_json TEXT NOT NULL DEFAULT '[]',
    found_json TEXT NOT NULL DEFAULT '[]',
    missing_evidence TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_questions_status ON questions(status);

CREATE TABLE IF NOT EXISTS retrieval_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    query_type TEXT NOT NULL,
    results_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    answered INTEGER NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    retrieval_event_id INTEGER REFERENCES retrieval_events(id),
    rating INTEGER,
    comment TEXT,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS ai_cache (
    cache_key TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    task_version TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_cache_source_task ON ai_cache(source_hash, task_type);

CREATE TABLE IF NOT EXISTS vector_items (
    object_id TEXT PRIMARY KEY,
    object_type TEXT NOT NULL,
    source_id TEXT,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    vector_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_vector_type ON vector_items(object_type);

CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
    object_id UNINDEXED,
    object_type UNINDEXED,
    title,
    text,
    source_id UNINDEXED,
    locator UNINDEXED,
    tokenize='unicode61'
);
"""

MIGRATION_2 = r"""
CREATE TABLE IF NOT EXISTS embedding_profiles (
    profile_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    revision TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    schema_version TEXT NOT NULL,
    learned INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_embedding_profiles_active ON embedding_profiles(active);
"""

MIGRATIONS: dict[int, str] = {1: MIGRATION_1, 2: MIGRATION_2}
