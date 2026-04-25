"""Factory helpers for constructing Jira webhook API clients."""

from __future__ import annotations

from main import load_config, resolve_auth_config, validate_service_base_url
from webhookAPI.client import JiraWebhookAPIClient


def build_webhook_api_client(config_path: str = "config.yaml") -> JiraWebhookAPIClient:
    """Build a Jira webhook API client from Sprinter config."""

    config = load_config(config_path)
    jira_base_url = validate_service_base_url("jira", config["jira"])
    timeout_seconds = int(config["requests"]["timeout_seconds"])
    return JiraWebhookAPIClient(
        jira_base_url,
        resolve_auth_config("jira", config["jira"]),
        timeout_seconds=timeout_seconds,
    )

