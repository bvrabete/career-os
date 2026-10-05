"""LangGraph orchestration and compilation for the CV generation pipeline."""

import logging
from typing import Any
from langgraph.graph import StateGraph, END

from generation.state import CVPipelineState
from generation.nodes import (
    node_analyzer,
    node_retriever,
    node_drafter,
    node_refiner,
    node_compressor,
    node_auditor
)


def refiner_guard_routing(state: CVPipelineState) -> str:
    """Route from refiner guard to fast compressor or auditor based on budget check."""
    refiner_feedback = state.get("refiner_feedback", "")
    compression_count = state.get("compression_count", 0)

    if refiner_feedback and compression_count < 2:
        logging.warning(
            f"Refiner guard triggered fast compressor (pass {compression_count + 1}/2) due to page budget overflow."
        )
        return "compressor"
    return "auditor"


def auditor_routing(state: CVPipelineState) -> str:
    """Determine whether to end the pipeline or loop back to drafter for rewrite."""
    feedback = state.get("audit_feedback", "")
    iterations = state.get("iteration_count", 0)

    if "PASS" in feedback or iterations >= 3:
        return str(END)
    return "drafter"


# Alias for backward compatibility
routing_logic = auditor_routing


def build_graph() -> Any:
    """Build, configure, and compile the CV generation LangGraph pipeline."""
    workflow = StateGraph(CVPipelineState)

    # Register nodes
    workflow.add_node("analyzer", node_analyzer)
    workflow.add_node("retriever", node_retriever)
    workflow.add_node("drafter", node_drafter)
    workflow.add_node("refiner", node_refiner)
    workflow.add_node("compressor", node_compressor)
    workflow.add_node("auditor", node_auditor)

    # Establish linear transitions
    workflow.set_entry_point("analyzer")
    workflow.add_edge("analyzer", "retriever")
    workflow.add_edge("retriever", "drafter")
    workflow.add_edge("drafter", "refiner")

    # Conditional routing from refiner guard
    workflow.add_conditional_edges(
        "refiner",
        refiner_guard_routing,
        {"compressor": "compressor", "auditor": "auditor"}
    )
    workflow.add_edge("compressor", "refiner")

    # Conditional routing from auditor feedback loop
    workflow.add_conditional_edges(
        "auditor",
        auditor_routing,
        {str(END): END, "drafter": "drafter"}
    )

    return workflow.compile()
