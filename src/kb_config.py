import logging
import os
from pathlib import Path
from typing import Any
import warnings

from dotenv import load_dotenv
import langchain_google_genai
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
import yaml

# Suppress LangChain's pending deprecation warnings regarding cache allowed_objects
warnings.filterwarnings("ignore", message=".*allowed_objects.*")

load_dotenv()  # Load environment variables from .env

# Enable caching to speed up iterative runs and save costs
# set_llm_cache(SQLiteCache(database_path=".langchain.db"))

CONFIG_PATH = Path("config.yaml")
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


def load_config() -> dict[str, Any]:
    env_config = os.getenv("CONFIG_FILE")
    if env_config:
        config_p = Path(env_config)
        if config_p.exists():
            with open(config_p, 'r') as f:
                return yaml.safe_load(f) or {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, 'r') as f:
            return yaml.safe_load(f) or {}
    elif DEFAULT_CONFIG_PATH.exists():
        with open(DEFAULT_CONFIG_PATH, 'r') as f:
            return yaml.safe_load(f) or {}
    else:
        raise FileNotFoundError(
            "Configuration file not found. Ensure 'config.yaml' exists in the workspace root "
            "or set the 'CONFIG_FILE' environment variable."
        )


def get_wiki_dir() -> Path:
    """Returns the Path to the llm-wiki directory, checking environment variables, config.yaml, or default."""
    env_val = os.getenv("LLM_WIKI_DIR")
    if env_val:
        return Path(env_val)
    config = load_config()
    paths = config.get("PATHS", {})
    if isinstance(paths, dict) and "WIKI_DIR" in paths:
        return Path(paths["WIKI_DIR"])
    if "WIKI_DIR" in config:
        return Path(config["WIKI_DIR"])
    return Path("llm-wiki")


def get_output_dir() -> Path:
    """Returns the export directory for clean drafts and compiled documents from config.yaml or default."""
    config = load_config()
    paths = config.get("PATHS", {})
    if isinstance(paths, dict) and "OUTPUT_DIR" in paths:
        return Path(paths["OUTPUT_DIR"])
    if "OUTPUT_DIR" in config:
        return Path(config["OUTPUT_DIR"])
    return Path("ai-generated-cvs")


def get_strategy_default() -> str:
    """Returns the default regional strategy from config.yaml or default."""
    config = load_config()
    defaults = config.get("DEFAULTS", {})
    if isinstance(defaults, dict) and "STRATEGY" in defaults:
        return str(defaults["STRATEGY"])
    return str(config.get("STRATEGY_DEFAULT", "emea"))


def get_model_for_step(step_name: str, temperature: float = 0, format: str | None = None):
    """
    Returns an LLM instance optimized for a specific pipeline step.
    Looks up the step in the 'STEPS' section of config.yaml.
    Fails fast with explicit errors if the step or model is unconfigured.
    """
    config = load_config()
    steps = config.get("STEPS", {})
    models_map = config.get("MODELS", {})

    step_config = steps.get(step_name)
    if not step_config:
        raise KeyError(
            f"Pipeline step '{step_name}' is not defined in config.yaml under 'STEPS'. "
            f"Please define it in your configuration."
        )

    model_type = step_config.get("TYPE")
    if not model_type:
        raise ValueError(
            f"Pipeline step '{step_name}' in config.yaml is missing required 'TYPE' "
            f"(e.g. 'gemini', 'openai', 'ollama')."
        )

    kwargs: dict[str, Any] = {}
    if model_type == "openai":
        model_name = step_config.get("MODEL_NAME") or models_map.get("openai")
        if not model_name:
            raise ValueError(
                f"No OpenAI model configured for step '{step_name}'. "
                f"Specify 'MODEL_NAME' under STEPS.{step_name} or MODELS.openai in config.yaml."
            )
        if format == "json":
            kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        # OpenAI reasoning models (e.g., o1, o3-mini) do not support setting a temperature parameter
        if model_name.startswith("o1") or model_name.startswith("o3"):
            return ChatOpenAI(model=model_name, **kwargs)
        return ChatOpenAI(model=model_name, temperature=temperature, **kwargs)

    elif model_type == "ollama":
        model_name = step_config.get("MODEL_NAME") or models_map.get("ollama")
        if not model_name:
            raise ValueError(
                f"No Ollama model configured for step '{step_name}'. "
                f"Specify 'MODEL_NAME' under STEPS.{step_name} or MODELS.ollama in config.yaml."
            )
        base_url = config.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)
        kwargs = {}
        if format:
            kwargs["format"] = format
        return ChatOllama(
            model=model_name,
            base_url=base_url,
            temperature=temperature,
            # Optimized to 12k to guarantee 100% GPU offload under 6GB VRAM without truncating large CV context
            num_ctx=12288,
            **kwargs
        )

    elif model_type == "gemini":
        model_name = step_config.get("MODEL_NAME") or models_map.get("gemini")
        if not model_name:
            raise ValueError(
                f"No Gemini model configured for step '{step_name}'. "
                f"Specify 'MODEL_NAME' under STEPS.{step_name} or MODELS.gemini in config.yaml."
            )
        # Transparently map older/deprecated Gemini model names to modern equivalents (e.g. Gemini 2.5)
        # to avoid 404 NOT_FOUND errors.
        if model_name == "gemini-1.5-flash":
            logging.info(f"Mapping deprecated model 'gemini-1.5-flash' to 'gemini-2.5-flash' for step '{step_name}'")
            model_name = "gemini-2.5-flash"
        elif model_name == "gemini-1.5-pro":
            logging.info(f"Mapping deprecated model 'gemini-1.5-pro' to 'gemini-2.5-pro' for step '{step_name}'")
            model_name = "gemini-2.5-pro"
        return langchain_google_genai.ChatGoogleGenerativeAI(model=model_name, temperature=temperature)

    else:
        raise ValueError(f"Invalid TYPE for step '{step_name}': {model_type}")


def _create_openai_fallback(model_name: str, step_name: str, temperature: float, format: str | None):
    if not os.getenv("OPENAI_API_KEY"):
        logging.warning(f"Fallback OpenAI model defined for '{step_name}', but OPENAI_API_KEY is not set.")
        return None
    kwargs: dict[str, Any] = {}
    if format == "json":
        kwargs["response_format"] = {"type": "json_object"}
    return ChatOpenAI(model=model_name, temperature=temperature, **kwargs)


def _create_gemini_fallback(model_name: str, step_name: str, temperature: float):
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        logging.warning(
            f"Fallback Gemini model defined for '{step_name}', but no GEMINI_API_KEY or GOOGLE_API_KEY is set."
        )
        return None
    # Transparently map older/deprecated Gemini model names to modern equivalents (e.g. Gemini 2.5)
    # to avoid 404 NOT_FOUND errors.
    if model_name == "gemini-1.5-flash":
        logging.info(
            f"Mapping deprecated fallback model 'gemini-1.5-flash' to 'gemini-2.5-flash' for step '{step_name}'"
        )
        model_name = "gemini-2.5-flash"
    elif model_name == "gemini-1.5-pro":
        logging.info(
            f"Mapping deprecated fallback model 'gemini-1.5-pro' to 'gemini-2.5-pro' for step '{step_name}'"
        )
        model_name = "gemini-2.5-pro"
    return langchain_google_genai.ChatGoogleGenerativeAI(model=model_name, temperature=temperature)


def _create_ollama_fallback(model_name: str, base_url: str, temperature: float, format: str | None):
    kwargs: dict[str, Any] = {}
    if format:
        kwargs["format"] = format
    return ChatOllama(
        model=model_name,
        base_url=base_url,
        temperature=temperature,
        num_ctx=8192,
        **kwargs
    )


def get_fallback_model_for_step(step_name: str, temperature: float = 0, format: str | None = None):
    """
    Returns the fallback LLM instance configured under a specific pipeline step in config.yaml.
    Checks for credential availability before instantiating.
    """
    config = load_config()
    steps = config.get("STEPS", {})
    step_config = steps.get(step_name)
    if not step_config or "FALLBACK" not in step_config:
        return None

    fallback_config = step_config["FALLBACK"]
    model_type = fallback_config.get("TYPE")
    model_name = fallback_config.get("MODEL_NAME")

    if not model_type or not model_name:
        return None

    if model_type == "openai":
        return _create_openai_fallback(model_name, step_name, temperature, format)

    if model_type == "gemini":
        return _create_gemini_fallback(model_name, step_name, temperature)

    if model_type == "ollama":
        base_url = config.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)
        return _create_ollama_fallback(model_name, base_url, temperature, format)

    return None


def get_model(temperature=0):
    """Legacy wrapper for global model instantiation."""
    return get_model_for_step("REFINEMENT", temperature=temperature)


if __name__ == "__main__":
    # Test loading
    try:
        model = get_model_for_step("REFINEMENT")
        m_name = getattr(model, "model_name", getattr(model, "model", "unknown"))
        print(f"Successfully loaded REFINEMENT model: {m_name}")

        ex_model = get_model_for_step("EXTRACTION")
        ex_name = getattr(ex_model, "model_name", getattr(ex_model, "model", "unknown"))
        print(f"Successfully loaded EXTRACTION model: {ex_name}")
    except Exception as e:
        print(f"Error loading models: {e}")
