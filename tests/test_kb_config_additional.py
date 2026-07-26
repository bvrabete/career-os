import os
import unittest
import yaml
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

import kb_config
from kb_config import (
    get_wiki_dir,
    load_config,
    get_strategy_default,
    get_model_for_step,
    get_fallback_model_for_step,
    get_model
)


class TestKBConfigAdditional(unittest.TestCase):

    def setUp(self) -> None:
        self.original_env = dict(os.environ)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_get_wiki_dir_env_set(self) -> None:
        os.environ["LLM_WIKI_DIR"] = "custom-wiki-path"
        self.assertEqual(get_wiki_dir(), Path("custom-wiki-path"))

    def test_get_wiki_dir_env_unset(self) -> None:
        if "LLM_WIKI_DIR" in os.environ:
            del os.environ["LLM_WIKI_DIR"]
        self.assertEqual(get_wiki_dir(), Path("llm-wiki"))

    @patch("kb_config.CONFIG_PATH")
    @patch("kb_config.DEFAULT_CONFIG_PATH")
    def test_load_config_path_exists(self, mock_default_path: MagicMock, mock_config_path: MagicMock) -> None:
        mock_config_path.exists.return_value = True
        mock_default_path.exists.return_value = False
        
        mock_content = "STRATEGY_DEFAULT: 'us-east'\n"
        with patch("builtins.open", mock_open(read_data=mock_content)):
            config = load_config()
            self.assertEqual(config.get("STRATEGY_DEFAULT"), "us-east")

    @patch("kb_config.CONFIG_PATH")
    @patch("kb_config.DEFAULT_CONFIG_PATH")
    def test_load_config_default_exists(self, mock_default_path: MagicMock, mock_config_path: MagicMock) -> None:
        mock_config_path.exists.return_value = False
        mock_default_path.exists.return_value = True
        
        mock_content = "STRATEGY_DEFAULT: 'apac'\n"
        with patch("builtins.open", mock_open(read_data=mock_content)):
            config = load_config()
            self.assertEqual(config.get("STRATEGY_DEFAULT"), "apac")

    @patch("kb_config.CONFIG_PATH")
    @patch("kb_config.DEFAULT_CONFIG_PATH")
    def test_load_config_neither_exists(self, mock_default_path: MagicMock, mock_config_path: MagicMock) -> None:
        mock_config_path.exists.return_value = False
        mock_default_path.exists.return_value = False
        
        config = load_config()
        self.assertIn("MODELS", config)
        self.assertEqual(config.get("STRATEGY_DEFAULT"), "emea")

    @patch("kb_config.load_config")
    def test_get_strategy_default(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {"STRATEGY_DEFAULT": "latam"}
        self.assertEqual(get_strategy_default(), "latam")

    @patch("kb_config.load_config")
    def test_get_model_for_step_fallback(self, mock_load: MagicMock) -> None:
        # Step name not found, falls back to REFINEMENT (ollama default in default config)
        mock_load.return_value = {
            "STEPS": {"REFINEMENT": {"TYPE": "ollama", "MODEL_NAME": "qwen"}},
            "OLLAMA_BASE_URL": "http://ollama-test"
        }
        with patch("kb_config.ChatOllama") as mock_ollama:
            get_model_for_step("UNKNOWN_STEP")
            mock_ollama.assert_called_once()

    @patch("kb_config.load_config")
    def test_get_model_for_step_openai(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "STEPS": {"TEST_STEP": {"TYPE": "openai", "MODEL_NAME": "gpt-4"}},
            "MODELS": {"openai": "gpt-4o"}
        }
        with patch("kb_config.ChatOpenAI") as mock_openai:
            get_model_for_step("TEST_STEP", format="json")
            mock_openai.assert_called_with(model="gpt-4", temperature=0, model_kwargs={"response_format": {"type": "json_object"}})

    @patch("kb_config.load_config")
    def test_get_model_for_step_openai_reasoning(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "STEPS": {"TEST_STEP": {"TYPE": "openai", "MODEL_NAME": "o1-mini"}}
        }
        with patch("kb_config.ChatOpenAI") as mock_openai:
            get_model_for_step("TEST_STEP")
            # Reasoning models must not set temperature parameter
            mock_openai.assert_called_with(model="o1-mini")

    @patch("kb_config.load_config")
    def test_get_model_for_step_gemini(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "STEPS": {"TEST_STEP": {"TYPE": "gemini", "MODEL_NAME": "gemini-1.5-flash"}}
        }
        with patch("langchain_google_genai.ChatGoogleGenerativeAI") as mock_gemini:
            get_model_for_step("TEST_STEP")
            # Should map to gemini-2.5-flash transparently
            mock_gemini.assert_called_with(model="gemini-2.5-flash", temperature=0)

    @patch("kb_config.load_config")
    def test_get_model_for_step_gemini_pro(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "STEPS": {"TEST_STEP": {"TYPE": "gemini", "MODEL_NAME": "gemini-1.5-pro"}}
        }
        with patch("langchain_google_genai.ChatGoogleGenerativeAI") as mock_gemini:
            get_model_for_step("TEST_STEP")
            # Should map to gemini-2.5-pro transparently
            mock_gemini.assert_called_with(model="gemini-2.5-pro", temperature=0)

    @patch("kb_config.load_config")
    def test_get_model_for_step_invalid(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "STEPS": {"TEST_STEP": {"TYPE": "unsupported-model-type"}}
        }
        with self.assertRaises(ValueError):
            get_model_for_step("TEST_STEP")

    @patch("kb_config.load_config")
    def test_get_fallback_model_for_step_none(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {}
        self.assertIsNone(get_fallback_model_for_step("SOME_STEP"))

    @patch("kb_config.load_config")
    def test_get_fallback_model_for_step_openai(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "STEPS": {"TEST_STEP": {"FALLBACK": {"TYPE": "openai", "MODEL_NAME": "gpt-4o-mini"}}}
        }
        # With env var missing
        if "OPENAI_API_KEY" in os.environ:
            del os.environ["OPENAI_API_KEY"]
        self.assertIsNone(get_fallback_model_for_step("TEST_STEP"))

        # With env var present
        os.environ["OPENAI_API_KEY"] = "fake-key"
        with patch("kb_config.ChatOpenAI") as mock_openai:
            get_fallback_model_for_step("TEST_STEP", format="json")
            mock_openai.assert_called_with(model="gpt-4o-mini", temperature=0, response_format={"type": "json_object"})

    @patch("kb_config.load_config")
    def test_get_fallback_model_for_step_gemini(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "STEPS": {"TEST_STEP": {"FALLBACK": {"TYPE": "gemini", "MODEL_NAME": "gemini-1.5-flash"}}}
        }
        # With credentials missing
        if "GEMINI_API_KEY" in os.environ:
            del os.environ["GEMINI_API_KEY"]
        if "GOOGLE_API_KEY" in os.environ:
            del os.environ["GOOGLE_API_KEY"]
        self.assertIsNone(get_fallback_model_for_step("TEST_STEP"))

        # With credentials present
        os.environ["GEMINI_API_KEY"] = "fake-gemini-key"
        with patch("langchain_google_genai.ChatGoogleGenerativeAI") as mock_gemini:
            get_fallback_model_for_step("TEST_STEP")
            mock_gemini.assert_called_with(model="gemini-2.5-flash", temperature=0)

    @patch("kb_config.load_config")
    def test_get_fallback_model_for_step_gemini_pro(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "STEPS": {"TEST_STEP": {"FALLBACK": {"TYPE": "gemini", "MODEL_NAME": "gemini-1.5-pro"}}}
        }
        os.environ["GEMINI_API_KEY"] = "fake-gemini-key"
        with patch("langchain_google_genai.ChatGoogleGenerativeAI") as mock_gemini:
            get_fallback_model_for_step("TEST_STEP")
            mock_gemini.assert_called_with(model="gemini-2.5-pro", temperature=0)

    @patch("kb_config.load_config")
    def test_get_fallback_model_for_step_ollama(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "STEPS": {"TEST_STEP": {"FALLBACK": {"TYPE": "ollama", "MODEL_NAME": "llama3"}}},
            "OLLAMA_BASE_URL": "http://localhost:11434"
        }
        with patch("kb_config.ChatOllama") as mock_ollama:
            get_fallback_model_for_step("TEST_STEP", format="json")
            mock_ollama.assert_called_with(model="llama3", base_url="http://localhost:11434", temperature=0, num_ctx=8192, format="json")

    @patch("kb_config.load_config")
    def test_get_fallback_model_for_step_invalid_type(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "STEPS": {"TEST_STEP": {"FALLBACK": {"TYPE": "unknown", "MODEL_NAME": "model"}}}
        }
        self.assertIsNone(get_fallback_model_for_step("TEST_STEP"))

    @patch("kb_config.load_config")
    def test_get_model_legacy_wrapper(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "STEPS": {"REFINEMENT": {"TYPE": "ollama", "MODEL_NAME": "qwen2.5:7b"}},
            "OLLAMA_BASE_URL": "http://localhost:11434"
        }
        with patch("kb_config.ChatOllama") as mock_ollama:
            get_model()
            mock_ollama.assert_called_once()


if __name__ == "__main__":
    unittest.main()
