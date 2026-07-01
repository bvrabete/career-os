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
    node_auditor
)


def routing_logic(state: CVPipelineState) -> str:
    """Determine the next step in the pipeline based on auditor/refiner feedback."""
    feedback = state.get("audit_feedback", "")
    refiner_feedback = state.get("refiner_feedback", "")
    iterations = state.get("iteration_count", 0)

    if refiner_feedback and iterations < 3:
        logging.warning("Refiner triggered a re-draft due to length/density.")
        return "drafter"

    if "PASS" in feedback or iterations >= 3:
        return str(END)
    else:
        return "drafter"


def build_graph() -> Any:
    """Build, configure, and compile the CV generation LangGraph pipeline."""
    workflow = StateGraph(CVPipelineState)
    
    # Register nodes
    workflow.add_node("analyzer", node_analyzer)
    workflow.add_node("retriever", node_retriever)
    workflow.add_node("drafter", node_drafter)
    workflow.add_node("refiner", node_refiner)
    workflow.add_node("auditor", node_auditor)

    # Establish linear transitions
    workflow.set_entry_point("analyzer")
    workflow.add_edge("analyzer", "retriever")
    workflow.add_edge("retriever", "drafter")
    workflow.add_edge("drafter", "refiner")
    workflow.add_edge("refiner", "auditor")

    # Add conditional feedback loop routing from auditor
    workflow.add_conditional_edges(
        "auditor",
        routing_logic,
        {str(END): END, "drafter": "drafter"}
    )

    return workflow.compile()
