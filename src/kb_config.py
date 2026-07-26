from typing import Any

import yaml
import os
import logging
import warnings
from pathlib import Path
from typing import Any
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langchain_core.globals import set_llm_cache
from langchain_community.cache import SQLiteCache

# Suppress LangChain's pending deprecation warnings regarding cache allowed_objects
warnings.filterwarnings("ignore", message=".*allowed_objects.*")

from dotenv import load_dotenv

load_dotenv() # Load environment variables from .env

# Enable caching to speed up iterative runs and save costs
# set_llm_cache(SQLiteCache(database_path=".langchain.db"))

CONFIG_PATH = Path("config.yaml")
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
GEMINI_1_5_FLASH = "gemini-1.5-flash"

def get_wiki_dir() -> Path:
    """Returns the Path to the llm-wiki directory, checking environment variables or default."""
    env_val = os.getenv("LLM_WIKI_DIR")
    if env_val:
        return Path(env_val)
    return Path("llm-wiki")

def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, 'r') as f:
            return yaml.safe_load(f)
    elif DEFAULT_CONFIG_PATH.exists():
        with open(DEFAULT_CONFIG_PATH, 'r') as f:
            return yaml.safe_load(f)
    else:
        return {
            "MODELS": {"ollama": "gemma4:26b", "openai": "gpt-4o"},
            "STEPS": {
                "EXTRACTION": {"TYPE": "ollama"},
                "REFINEMENT": {"TYPE": "openai"}
            },
            "OLLAMA_BASE_URL": DEFAULT_OLLAMA_BASE_URL,
            "STRATEGY_DEFAULT": "emea"
        }

def get_strategy_default():
    config = load_config()
    return config.get("STRATEGY_DEFAULT", "emea")

def get_model_for_step(step_name: str, temperature: float = 0, format: str | None = None):
    """
    Returns an LLM instance optimized for a specific pipeline step.
    Looks up the step in the 'STEPS' section of config.yaml.
    """
    config = load_config()
    steps = config.get("STEPS", {})
    models_map = config.get("MODELS", {})
    
    step_config = steps.get(step_name)
    if not step_config:
        # Fallback to REFINEMENT or a sensible default
        step_config = steps.get("REFINEMENT", {"TYPE": "ollama"})
        logging.warning(f"Step '{step_name}' not found in config. Falling back to {step_config['TYPE']}")

    model_type = step_config.get("TYPE", "ollama")
    
    kwargs: dict[str, Any] = {}
    if model_type == "openai":
        # Check step-specific MODEL_NAME first, fallback to global mapping
        model_name = step_config.get("MODEL_NAME", models_map.get("openai", "gpt-4o"))
        if format == "json":
            kwargs["response_format"] = {"type": "json_object"}
        # OpenAI reasoning models (e.g., o1, o3-mini) do not support setting a temperature parameter
        if model_name.startswith("o1") or model_name.startswith("o3"):
            return ChatOpenAI(model=model_name, **kwargs)
        return ChatOpenAI(model=model_name, temperature=temperature, **kwargs)
    
    elif model_type == "ollama":
        # Check step-specific MODEL_NAME first, fallback to global mapping
        model_name = step_config.get("MODEL_NAME", models_map.get("ollama", "qwen2.5:7b"))
        base_url = config.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)
        kwargs = {}
        if format:
            kwargs["format"] = format
        return ChatOllama(
            model=model_name, 
            base_url=base_url, 
            temperature=temperature,
            num_ctx=12288, # Optimized to 12k to guarantee 100% GPU offload under 6GB VRAM without truncating large CV context
            **kwargs
        )
    
    elif model_type == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        model_name = step_config.get("MODEL_NAME", models_map.get("gemini", GEMINI_1_5_FLASH))
        # Transparently map older/deprecated Gemini model names to modern equivalents (e.g. Gemini 2.5) to avoid 404 NOT_FOUND errors.
        if model_name == GEMINI_1_5_FLASH:
            logging.info(f"Mapping deprecated model 'gemini-1.5-flash' to 'gemini-2.5-flash' for step '{step_name}'")
            model_name = "gemini-2.5-flash"
        elif model_name == "gemini-1.5-pro":
            logging.info(f"Mapping deprecated model 'gemini-1.5-pro' to 'gemini-2.5-pro' for step '{step_name}'")
            model_name = "gemini-2.5-pro"
        return ChatGoogleGenerativeAI(model=model_name, temperature=temperature)
    
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
        logging.warning(f"Fallback Gemini model defined for '{step_name}', but no GEMINI_API_KEY or GOOGLE_API_KEY is set.")
        return None
    # Transparently map older/deprecated Gemini model names to modern equivalents (e.g. Gemini 2.5) to avoid 404 NOT_FOUND errors.
    if model_name == GEMINI_1_5_FLASH:
        logging.info(f"Mapping deprecated fallback model 'gemini-1.5-flash' to 'gemini-2.5-flash' for step '{step_name}'")
        model_name = "gemini-2.5-flash"
    elif model_name == "gemini-1.5-pro":
        logging.info(f"Mapping deprecated fallback model 'gemini-1.5-pro' to 'gemini-2.5-pro' for step '{step_name}'")
        model_name = "gemini-2.5-pro"
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(model=model_name, temperature=temperature)

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
