"""LangGraph graph construction and compilation for the Ingestion Pipeline."""
from typing import Any
from langgraph.graph import StateGraph, END
from ingestion.state import IngestionState
from ingestion.extraction import node_extractor
from ingestion.generation import node_generator
from ingestion.nodes import (
    node_parser, node_classifier, node_entity_resolver,
    node_merger, node_validator, node_writer
)


def build_ingest_graph(dry_run: bool = False) -> Any:
    """Build and compile the ingestion pipeline StateGraph."""
    workflow = StateGraph(IngestionState)

    workflow.add_node("parser", node_parser)
    workflow.add_node("classifier", node_classifier)
    workflow.add_node("extractor", node_extractor)
    workflow.add_node("entity_resolver", node_entity_resolver)
    workflow.add_node("generator", node_generator)
    workflow.add_node("merger", node_merger)
    workflow.add_node("validator", node_validator)

    def writer_node(state: IngestionState) -> dict[str, Any]:
        return node_writer(state, dry_run=dry_run)

    workflow.add_node("writer", writer_node)

    workflow.set_entry_point("parser")
    workflow.add_edge("parser", "classifier")

    workflow.add_conditional_edges(
        "classifier",
        lambda s: "extract" if s.get("doc_type") not in ("skip",) else "end",
        {"extract": "extractor", "end": END},
    )

    workflow.add_edge("extractor", "entity_resolver")
    workflow.add_edge("entity_resolver", "generator")
    workflow.add_edge("generator", "merger")
    workflow.add_edge("merger", "validator")
    workflow.add_edge("validator", "writer")
    workflow.add_edge("writer", END)

    return workflow.compile()
