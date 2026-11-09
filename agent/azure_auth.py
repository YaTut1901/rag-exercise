"""Azure OpenAI auth for the Streamlit agent (App Service MI or local CLI)."""

from __future__ import annotations

import os

from azure.identity import (
    AzureCliCredential,
    DefaultAzureCredential,
    ManagedIdentityCredential,
    get_bearer_token_provider,
)
from openai import AzureOpenAI

from config import api_version, openai_endpoint


def azure_credential():
    """Prefer App Service / MI; fall back to Azure CLI for rare local debugging."""
    if os.environ.get("IDENTITY_ENDPOINT") or os.environ.get("WEBSITE_INSTANCE_ID"):
        return ManagedIdentityCredential()
    try:
        cred = AzureCliCredential()
        cred.get_token("https://cognitiveservices.azure.com/.default")
        return cred
    except Exception:
        return DefaultAzureCredential(exclude_interactive_browser_credential=True)


def token_provider():
    return get_bearer_token_provider(
        azure_credential(),
        "https://cognitiveservices.azure.com/.default",
    )


def make_openai_client() -> AzureOpenAI:
    api_key = (os.environ.get("AZURE_OPENAI_API_KEY") or "").strip()
    if api_key:
        return AzureOpenAI(
            azure_endpoint=openai_endpoint(),
            api_version=api_version(),
            api_key=api_key,
        )
    return AzureOpenAI(
        azure_endpoint=openai_endpoint(),
        api_version=api_version(),
        azure_ad_token_provider=token_provider(),
    )
