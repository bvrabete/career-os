"""Layers 5 & 6: Opt-in integration tests for local Ollama (@pytest.mark.ollama) and live cloud LLMs (@pytest.mark.live_llm)."""

import json
import os
import urllib.request
from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama
import pytest

from generation.formatting import invoke_structured_llm
from generation.state import AnalyzerOutput
import kb_config


def _get_available_ollama_models(base_url: str = "http://localhost:11434") -> list[str]:
    """Return list of locally pulled Ollama model names, or empty list if Ollama is unreachable."""
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=1.5) as resp:
            if int(resp.status) != 200:
                return []
            payload = json.loads(resp.read().decode("utf-8"))
            models = payload.get("models", [])
            return [str(m.get("name")) for m in models if isinstance(m, dict) and m.get("name")]
    except Exception:
        return []


@pytest.mark.ollama
def test_ollama_num_ctx_and_structured_analyzer() -> None:
    """Verify ChatOllama num_ctx is resolved from config.yaml (>=12288) and parses an agency JD into AnalyzerOutput."""
    num_ctx = kb_config.get_ollama_num_ctx()
    base_url = kb_config.get_ollama_base_url()
    assert num_ctx >= 12288
    available_models = _get_available_ollama_models(base_url=base_url)
    if not available_models:
        pytest.fail(
            f"Ollama integration test failed: local Ollama daemon is not reachable or has no models pulled at {base_url}. "
            "Start Ollama (`ollama serve`) and pull a model (e.g. `ollama pull qwen2.5:7b`) before running `-m ollama`."
        )

    preferred = next((m for m in available_models if "qwen" in m or "llama" in m), available_models[0])
    llm = ChatOllama(
        model=preferred,
        base_url=base_url,
        temperature=0,
        num_ctx=num_ctx,
        format="json",
    )
    prompt = (
        "Extract JSON matching AnalyzerOutput for this JD: "
        "'Hays Recruitment is hiring a Principal Cloud Architect on behalf of our client Adyen in Amsterdam. "
        "Skills: Kubernetes, Go, Kafka.'"
    )
    res = invoke_structured_llm(llm, AnalyzerOutput, [HumanMessage(content=prompt)])
    assert isinstance(res, AnalyzerOutput)
    assert res.target_role != ""


@pytest.mark.live_llm
def test_live_cloud_llm_structured_output() -> None:
    """Opt-in smoke test for cloud LLM structured output; fails if API credentials are missing."""
    if not (os.environ.get("OPENAI_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        pytest.fail(
            "Live LLM integration test failed: neither OPENAI_API_KEY nor GEMINI_API_KEY is set in the environment."
        )

    llm = kb_config.get_model_for_step("DRAFTING")
    resp = llm.invoke([HumanMessage(content="Reply with the single word READY.")])
    assert "READY" in str(resp.content).upper()
