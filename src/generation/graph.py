"""LangGraph orchestration and compilation for the CV generation pipeline."""

from typing import Any
from langgraph.graph import StateGraph
from langgraph.types import RetryPolicy

from generation.state import CVPipelineState
from generation.nodes import (
    node_analyzer,
    node_retriever,
    node_drafter,
    node_refiner,
    node_compressor,
    node_auditor
)


def build_graph() -> Any:
    """Build, configure, and compile the CV generation LangGraph pipeline."""
    workflow = StateGraph(CVPipelineState)

    # Retry policy for transient LLM errors
    llm_retry = RetryPolicy(max_attempts=3)

    # Register nodes
    workflow.add_node("analyzer", node_analyzer, retry_policy=llm_retry)
    workflow.add_node("retriever", node_retriever, retry_policy=llm_retry)
    workflow.add_node("drafter", node_drafter, retry_policy=llm_retry)
    workflow.add_node("refiner", node_refiner) # refiner handles its own Command routing
    workflow.add_node("compressor", node_compressor, retry_policy=llm_retry)
    workflow.add_node("auditor", node_auditor, retry_policy=llm_retry) # auditor handles its own Command routing

    # Establish linear transitions
    workflow.set_entry_point("analyzer")
    workflow.add_edge("analyzer", "retriever")
    workflow.add_edge("retriever", "drafter")
    workflow.add_edge("drafter", "refiner")

    # Command routing from refiner handles branching to compressor or auditor
    # When compressor finishes, it loops back to refiner
    workflow.add_edge("compressor", "refiner")

    # Command routing from auditor handles looping back to drafter or exiting at END

    return workflow.compile()
