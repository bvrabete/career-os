import yaml
import os
import logging
from pathlib import Path
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langchain_core.globals import set_llm_cache
from langchain_community.cache import SQLiteCache

from dotenv import load_dotenv

load_dotenv() # Load environment variables from .env

# Enable caching to speed up iterative runs and save costs
set_llm_cache(SQLiteCache(database_path=".langchain.db"))

CONFIG_PATH = Path("config.yaml")
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

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
            "OLLAMA_BASE_URL": "http://localhost:11434",
            "STRATEGY_DEFAULT": "emea"
        }

def get_strategy_default():
    config = load_config()
    return config.get("STRATEGY_DEFAULT", "emea")

def get_model_for_step(step_name: str, temperature: float = 0):
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
    
    if model_type == "openai":
        # Check step-specific MODEL_NAME first, fallback to global mapping
        model_name = step_config.get("MODEL_NAME", models_map.get("openai", "gpt-4o"))
        return ChatOpenAI(model=model_name, temperature=temperature)
    
    elif model_type == "ollama":
        # Check step-specific MODEL_NAME first, fallback to global mapping
        model_name = step_config.get("MODEL_NAME", models_map.get("ollama", "qwen2.5:7b"))
        base_url = config.get("OLLAMA_BASE_URL", "http://localhost:11434")
        return ChatOllama(
            model=model_name, 
            base_url=base_url, 
            temperature=temperature,
            num_ctx=8192 # Increased for large CV context
        )
    
    elif model_type == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        model_name = step_config.get("MODEL_NAME", models_map.get("gemini", "gemini-1.5-flash"))
        return ChatGoogleGenerativeAI(model=model_name, temperature=temperature)
    
    else:
        raise ValueError(f"Invalid TYPE for step '{step_name}': {model_type}")

def get_model(temperature=0):
    """Legacy wrapper for global model instantiation."""
    return get_model_for_step("REFINEMENT", temperature=temperature)

if __name__ == "__main__":
    # Test loading
    try:
        model = get_model_for_step("REFINEMENT")
        print(f"Successfully loaded REFINEMENT model: {model.model_name if hasattr(model, 'model_name') else model.model}")
        
        ex_model = get_model_for_step("EXTRACTION")
        print(f"Successfully loaded EXTRACTION model: {ex_model.model_name if hasattr(ex_model, 'model_name') else ex_model.model}")
    except Exception as e:
        print(f"Error loading models: {e}")
