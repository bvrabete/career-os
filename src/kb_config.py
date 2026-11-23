"""Strongly-typed Pydantic v2 configuration loader and LLM factory for CareerOS."""

import logging
import os
from pathlib import Path
from typing import Any
import warnings

from dotenv import load_dotenv
import langchain_google_genai
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from pydantic import ValidationError
import yaml

from schemas.config_models import AppConfig

# Suppress LangChain's pending deprecation warnings regarding cache allowed_objects
warnings.filterwarnings("ignore", message=".*allowed_objects.*")

load_dotenv()

CONFIG_PATH = Path("config.yaml")
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

_wiki_dir_override: Path | None = None


def _resolve_config_file() -> Path:
    """Resolve the active config.yaml file path or raise FileNotFoundError."""
    env_config = os.getenv("CONFIG_FILE")
    if env_config:
        config_p = Path(env_config)
        if config_p.exists():
            return config_p
    if CONFIG_PATH.exists():
        return CONFIG_PATH
    if DEFAULT_CONFIG_PATH.exists():
        return DEFAULT_CONFIG_PATH
    raise FileNotFoundError(
        "Configuration file not found. Ensure 'config.yaml' exists in the workspace root "
        "or set the 'CONFIG_FILE' environment variable."
    )


def load_config() -> dict[str, Any]:
    """Load raw dictionary from config.yaml and validate it via the AppConfig Pydantic model."""
    config_path = _resolve_config_file()
    with open(config_path, "r", encoding="utf-8") as f:
        raw_data = yaml.safe_load(f) or {}
    if not isinstance(raw_data, dict):
        raise ValueError(f"Configuration file {config_path} must contain a YAML mapping.")
    AppConfig.model_validate(raw_data)
    return raw_data


def load_typed_config() -> AppConfig:
    """Load and return the strongly-typed AppConfig Pydantic v2 instance."""
    raw = load_config()
    if isinstance(raw, AppConfig):
        return raw
    return AppConfig.model_validate(raw)


def set_wiki_dir(path: Path | str | None) -> None:
    """Set a runtime override for the wiki directory (e.g. from CLI flags)."""
    global _wiki_dir_override
    if path:
        _wiki_dir_override = Path(str(path).strip())
    else:
        _wiki_dir_override = None


def get_wiki_dir() -> Path:
    """Return the Path to the llm-wiki directory from runtime override or Pydantic AppConfig."""
    if _wiki_dir_override is not None:
        return _wiki_dir_override
    return load_typed_config().PATHS.WIKI_DIR


def get_output_dir() -> Path:
    """Return the export directory for clean drafts and compiled documents from Pydantic AppConfig."""
    return load_typed_config().PATHS.OUTPUT_DIR


def get_strategy_default() -> str:
    """Return the default regional strategy from Pydantic AppConfig."""
    return load_typed_config().DEFAULTS.STRATEGY


def get_ollama_num_ctx() -> int:
    """Return OLLAMA_NUM_CTX from Pydantic AppConfig (uses schema default only if omitted in config.yaml)."""
    return load_typed_config().OLLAMA_NUM_CTX


def get_ollama_base_url() -> str:
    """Return OLLAMA_BASE_URL from Pydantic AppConfig (uses schema default only if omitted in config.yaml)."""
    return load_typed_config().OLLAMA_BASE_URL


def _build_openai_model(model_name: str, temperature: float, format: str | None) -> Any:
    kwargs: dict[str, Any] = {}
    if format == "json":
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    if model_name.startswith("o1") or model_name.startswith("o3"):
        return ChatOpenAI(model=model_name, **kwargs)
    return ChatOpenAI(model=model_name, temperature=temperature, **kwargs)


def _build_ollama_model(
    model_name: str, base_url: str, temperature: float, format: str | None, num_ctx: int
) -> Any:
    kwargs: dict[str, Any] = {}
    if format:
        kwargs["format"] = format
    return ChatOllama(
        model=model_name,
        base_url=base_url,
        temperature=temperature,
        num_ctx=num_ctx,
        **kwargs,
    )


def _build_gemini_model(model_name: str, step_name: str, temperature: float, is_fallback: bool = False) -> Any:
    label = "fallback model" if is_fallback else "model"
    if model_name == "gemini-1.5-flash":
        logging.info("Mapping deprecated %s 'gemini-1.5-flash' to 'gemini-2.5-flash' for step '%s'", label, step_name)
        model_name = "gemini-2.5-flash"
    elif model_name == "gemini-1.5-pro":
        logging.info("Mapping deprecated %s 'gemini-1.5-pro' to 'gemini-2.5-pro' for step '%s'", label, step_name)
        model_name = "gemini-2.5-pro"
    return langchain_google_genai.ChatGoogleGenerativeAI(model=model_name, temperature=temperature)


def get_model_for_step(step_name: str, temperature: float = 0, format: str | None = None) -> Any:
    """Return an LLM instance for a pipeline step resolved strictly from Pydantic AppConfig."""
    cfg = load_typed_config()
    if step_name not in cfg.STEPS:
        raise KeyError(
            f"Pipeline step '{step_name}' is not defined in config.yaml under 'STEPS'. "
            f"Please define it in your configuration."
        )

    step_config = cfg.STEPS[step_name]
    model_type = step_config.TYPE
    if not model_type:
        raise ValueError(
            f"Pipeline step '{step_name}' in config.yaml is missing required 'TYPE' "
            f"(e.g. 'gemini', 'openai', 'ollama')."
        )

    model_name = step_config.MODEL_NAME or cfg.MODELS.get(model_type)
    if not model_name:
        raise ValueError(
            f"No {model_type} model configured for step '{step_name}'. "
            f"Specify 'MODEL_NAME' under STEPS.{step_name} or MODELS.{model_type} in config.yaml."
        )

    if model_type == "openai":
        return _build_openai_model(model_name, temperature, format)
    if model_type == "ollama":
        return _build_ollama_model(model_name, cfg.OLLAMA_BASE_URL, temperature, format, num_ctx=cfg.OLLAMA_NUM_CTX)
    if model_type == "gemini":
        return _build_gemini_model(model_name, step_name, temperature, is_fallback=False)

    raise ValueError(f"Invalid TYPE for step '{step_name}': {model_type}")


def _create_openai_fallback(model_name: str, step_name: str, temperature: float, format: str | None) -> Any:
    if not os.getenv("OPENAI_API_KEY"):
        logging.warning("Fallback OpenAI model defined for '%s', but OPENAI_API_KEY is not set.", step_name)
        return None
    kwargs: dict[str, Any] = {}
    if format == "json":
        kwargs["response_format"] = {"type": "json_object"}
    return ChatOpenAI(model=model_name, temperature=temperature, **kwargs)


def _create_gemini_fallback(model_name: str, step_name: str, temperature: float) -> Any:
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        logging.warning(
            "Fallback Gemini model defined for '%s', but no GEMINI_API_KEY or GOOGLE_API_KEY is set.",
            step_name,
        )
        return None
    return _build_gemini_model(model_name, step_name, temperature, is_fallback=True)


def get_fallback_model_for_step(step_name: str, temperature: float = 0, format: str | None = None) -> Any:
    """Return the fallback LLM instance configured under a pipeline step via Pydantic AppConfig."""
    try:
        cfg = load_typed_config()
    except ValidationError:
        return None

    step_config = cfg.STEPS.get(step_name)
    if not step_config or step_config.FALLBACK is None:
        return None

    fb = step_config.FALLBACK
    if fb.TYPE == "openai":
        return _create_openai_fallback(fb.MODEL_NAME, step_name, temperature, format)
    if fb.TYPE == "gemini":
        return _create_gemini_fallback(fb.MODEL_NAME, step_name, temperature)
    if fb.TYPE == "ollama":
        return _build_ollama_model(fb.MODEL_NAME, cfg.OLLAMA_BASE_URL, temperature, format, num_ctx=cfg.OLLAMA_NUM_CTX)
    return None


def get_model(temperature: float = 0) -> Any:
    """Legacy wrapper for global model instantiation."""
    return get_model_for_step("REFINEMENT", temperature=temperature)


def get_scoring_config() -> dict[str, Any]:
    """Return the validated scoring configuration dictionary from Pydantic AppConfig."""
    return load_typed_config().SCORING.model_dump()


def get_coverage_selection_enabled() -> bool:
    """Return whether coverage-aware evidence selection is enabled in Pydantic AppConfig."""
    return load_typed_config().GENERATION.ENABLE_COVERAGE_SELECTION


def get_coverage_selection_config() -> dict[str, Any]:
    """Return the validated coverage-aware evidence selection configuration from Pydantic AppConfig."""
    return load_typed_config().GENERATION.COVERAGE_SELECTION.model_dump()
