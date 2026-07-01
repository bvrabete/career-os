"""Forwarding proxy for the modularized Ingestion Pipeline.

This file maintains full backward compatibility for any script importing from
`kb_ingest_graph` while delegating implementation directly to the modular
`src/ingestion` package.
"""
from ingestion import (
    IngestionState,
    build_ingest_graph,
    bootstrap_wiki_structure as _bootstrap_wiki_structure,
    get_wiki_root,
    get_schema_path,
    get_mappings_path
)

__all__ = [
    "IngestionState",
    "build_ingest_graph",
    "_bootstrap_wiki_structure",
    "get_wiki_root",
    "get_schema_path",
    "get_mappings_path",
]
