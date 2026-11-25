"""Unit tests for kb_config using pure pytest and monkeypatch."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, mock_open, patch
import pytest

from kb_config import (
    get_fallback_model_for_step,
    get_model,
    get_model_for_step,
    get_strategy_default,
    get_wiki_dir,
    load_config,
    set_wiki_dir,
)


class TestKBConfigAdditional:
    """Test suite for kb_config configuration and LLM factory resolution."""

    @pytest.fixture(autouse=True)
    def _reset_wiki_dir(self) -> Any:
        set_wiki_dir(None)
        yield
        set_wiki_dir(None)

    def test_set_wiki_dir_override(self) -> None:
        set_wiki_dir("custom-wiki-path")
        assert get_wiki_dir() == Path("custom-wiki-path")
        set_wiki_dir(None)

    @patch("kb_config.load_config", return_value={"PATHS": {"WIKI_DIR": "my-config-wiki"}})
    def test_get_wiki_dir_from_config(self, mock_load: MagicMock) -> None:
        _ = mock_load
        assert get_wiki_dir() == Path("my-config-wiki")

    @patch("kb_config.load_config", return_value={})
    def test_get_wiki_dir_fallback(self, mock_load: MagicMock) -> None:
        _ = mock_load
        assert get_wiki_dir() == Path("llm-wiki")

    @patch("kb_config.CONFIG_PATH")
    @patch("kb_config.DEFAULT_CONFIG_PATH")
    def test_load_config_path_exists(self, mock_default_path: MagicMock, mock_config_path: MagicMock) -> None:
        mock_config_path.exists.return_value = True
        mock_default_path.exists.return_value = False

        mock_content = "STRATEGY_DEFAULT: 'us-east'\n"
        with patch("builtins.open", mock_open(read_data=mock_content)):
            config = load_config()
            assert config.get("STRATEGY_DEFAULT") == "us-east"

    @patch("kb_config.CONFIG_PATH")
    @patch("kb_config.DEFAULT_CONFIG_PATH")
    def test_load_config_default_exists(self, mock_default_path: MagicMock, mock_config_path: MagicMock) -> None:
        mock_config_path.exists.return_value = False
        mock_default_path.exists.return_value = True

        mock_content = "STRATEGY_DEFAULT: 'apac'\n"
        with patch("builtins.open", mock_open(read_data=mock_content)):
            config = load_config()
            assert config.get("STRATEGY_DEFAULT") == "apac"

    @patch("kb_config.CONFIG_PATH")
    @patch("kb_config.DEFAULT_CONFIG_PATH")
    def test_load_config_neither_exists(self, mock_default_path: MagicMock, mock_config_path: MagicMock) -> None:
        mock_config_path.exists.return_value = False
        mock_default_path.exists.return_value = False

        with pytest.raises(FileNotFoundError):
            load_config()

    @patch("kb_config.load_config")
    def test_get_strategy_default(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {"STRATEGY_DEFAULT": "latam"}
        assert get_strategy_default() == "latam"

    @patch("kb_config.load_config")
    def test_get_model_for_step_missing_step(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "STEPS": {"REFINEMENT": {"TYPE": "ollama", "MODEL_NAME": "qwen"}},
            "OLLAMA_BASE_URL": "http://ollama-test",
        }
        with pytest.raises(KeyError):
            get_model_for_step("UNKNOWN_STEP")

    @patch("kb_config.load_config")
    def test_get_model_for_step_openai(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "STEPS": {"TEST_STEP": {"TYPE": "openai", "MODEL_NAME": "gpt-4"}},
            "MODELS": {"openai": "gpt-4o"},
        }
        with patch("kb_config.ChatOpenAI") as mock_openai:
            get_model_for_step("TEST_STEP", format="json")
            mock_openai.assert_called_with(
                model="gpt-4", temperature=0, model_kwargs={"response_format": {"type": "json_object"}}
            )

    @patch("kb_config.load_config")
    def test_get_model_for_step_openai_reasoning(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "STEPS": {"TEST_STEP": {"TYPE": "openai", "MODEL_NAME": "o1-mini"}},
        }
        with patch("kb_config.ChatOpenAI") as mock_openai:
            get_model_for_step("TEST_STEP")
            mock_openai.assert_called_with(model="o1-mini")

    @patch("kb_config.load_config")
    def test_get_model_for_step_gemini(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "STEPS": {"TEST_STEP": {"TYPE": "gemini", "MODEL_NAME": "gemini-1.5-flash"}},
        }
        with patch("langchain_google_genai.ChatGoogleGenerativeAI") as mock_gemini:
            get_model_for_step("TEST_STEP")
            mock_gemini.assert_called_with(model="gemini-2.5-flash", temperature=0)

    @patch("kb_config.load_config")
    def test_get_model_for_step_gemini_pro(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "STEPS": {"TEST_STEP": {"TYPE": "gemini", "MODEL_NAME": "gemini-1.5-pro"}},
        }
        with patch("langchain_google_genai.ChatGoogleGenerativeAI") as mock_gemini:
            get_model_for_step("TEST_STEP")
            mock_gemini.assert_called_with(model="gemini-2.5-pro", temperature=0)

    @patch("kb_config.load_config")
    def test_get_model_for_step_invalid(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "STEPS": {"TEST_STEP": {"TYPE": "unsupported-model-type"}},
        }
        with pytest.raises(ValueError):
            get_model_for_step("TEST_STEP")

    @patch("kb_config.load_config")
    def test_get_fallback_model_for_step_none(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {}
        assert get_fallback_model_for_step("SOME_STEP") is None

    @patch("kb_config.load_config")
    def test_get_fallback_model_for_step_openai(
        self, mock_load: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_load.return_value = {
            "STEPS": {"TEST_STEP": {"FALLBACK": {"TYPE": "openai", "MODEL_NAME": "gpt-4.1-mini"}}},
        }
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert get_fallback_model_for_step("TEST_STEP") is None

        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
        with patch("kb_config.ChatOpenAI") as mock_openai:
            get_fallback_model_for_step("TEST_STEP", format="json")
            mock_openai.assert_called_with(
                model="gpt-4.1-mini", temperature=0, response_format={"type": "json_object"}
            )

    @patch("kb_config.load_config")
    def test_get_fallback_model_for_step_gemini(
        self, mock_load: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_load.return_value = {
            "STEPS": {"TEST_STEP": {"FALLBACK": {"TYPE": "gemini", "MODEL_NAME": "gemini-1.5-flash"}}},
        }
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        assert get_fallback_model_for_step("TEST_STEP") is None

        monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
        with patch("langchain_google_genai.ChatGoogleGenerativeAI") as mock_gemini:
            get_fallback_model_for_step("TEST_STEP")
            mock_gemini.assert_called_with(model="gemini-2.5-flash", temperature=0)

    @patch("kb_config.load_config")
    def test_get_fallback_model_for_step_gemini_pro(
        self, mock_load: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_load.return_value = {
            "STEPS": {"TEST_STEP": {"FALLBACK": {"TYPE": "gemini", "MODEL_NAME": "gemini-1.5-pro"}}},
        }
        monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
        with patch("langchain_google_genai.ChatGoogleGenerativeAI") as mock_gemini:
            get_fallback_model_for_step("TEST_STEP")
            mock_gemini.assert_called_with(model="gemini-2.5-pro", temperature=0)

    @patch("kb_config.load_config")
    def test_get_fallback_model_for_step_ollama(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "STEPS": {"TEST_STEP": {"FALLBACK": {"TYPE": "ollama", "MODEL_NAME": "llama3"}}},
            "OLLAMA_BASE_URL": "http://localhost:11434",
        }
        with patch("kb_config.ChatOllama") as mock_ollama:
            get_fallback_model_for_step("TEST_STEP", format="json")
            mock_ollama.assert_called_with(
                model="llama3", base_url="http://localhost:11434", temperature=0, num_ctx=12288, format="json"
            )

    @patch("kb_config.load_config")
    def test_get_fallback_model_for_step_invalid_type(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "STEPS": {"TEST_STEP": {"FALLBACK": {"TYPE": "unknown", "MODEL_NAME": "model"}}},
        }
        assert get_fallback_model_for_step("TEST_STEP") is None

    @patch("kb_config.load_config")
    def test_get_model_legacy_wrapper(self, mock_load: MagicMock) -> None:
        mock_load.return_value = {
            "STEPS": {"REFINEMENT": {"TYPE": "ollama", "MODEL_NAME": "qwen2.5:7b"}},
            "OLLAMA_BASE_URL": "http://localhost:11434",
        }
        with patch("kb_config.ChatOllama") as mock_ollama:
            get_model()
            mock_ollama.assert_called_once()
