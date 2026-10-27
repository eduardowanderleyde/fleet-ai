"""O Fleet AI não pode depender de LLM pago (ADR-0004)."""

import os
import tomllib
from pathlib import Path

LOCKFILE = Path(__file__).resolve().parents[1] / "uv.lock"

# SDKs de provedores de LLM pagos e integrações que os puxam.
PAID_LLM_PACKAGES = {
    "ai21",
    "anthropic",
    "cohere",
    "fireworks-ai",
    "google-cloud-aiplatform",
    "google-genai",
    "google-generativeai",
    "groq",
    "langchain-anthropic",
    "langchain-cohere",
    "langchain-google-genai",
    "langchain-groq",
    "langchain-mistralai",
    "langchain-openai",
    "litellm",
    "mistralai",
    "openai",
    "replicate",
    "together",
    "voyageai",
}


def locked_package_names() -> set[str]:
    lock = tomllib.loads(LOCKFILE.read_text())
    return {package["name"] for package in lock["package"]}


def test_no_paid_llm_sdk_is_locked() -> None:
    assert locked_package_names() & PAID_LLM_PACKAGES == set()


def test_suite_runs_without_any_api_key() -> None:
    assert [name for name in os.environ if name.endswith("_API_KEY")] == []
