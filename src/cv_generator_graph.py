"""Legacy compat entrypoint for the CV generation pipeline.

Delegates entirely to the new, modular 'generation' package.
"""

from generation.state import CVPipelineState
from generation.graph import build_graph, routing_logic
from generation.nodes import (
    node_analyzer,
    node_retriever,
    node_drafter,
    node_refiner,
    node_auditor,
)
from generation.helpers import (
    llm_text as _llm_text,
    robust_json_loads,
    score_by_keywords as _score_by_keywords,
    generate_skill_bridging_map as _generate_skill_bridging_map,
    compress_experience_llm as _compress_experience_llm,
    prune_recent_experience as _prune_recent_experience,
)

__all__ = [
    "CVPipelineState",
    "build_graph",
    "routing_logic",
    "node_analyzer",
    "node_retriever",
    "node_drafter",
    "node_refiner",
    "node_auditor",
    "_llm_text",
    "robust_json_loads",
    "_score_by_keywords",
    "_generate_skill_bridging_map",
    "_compress_experience_llm",
    "_prune_recent_experience",
]
