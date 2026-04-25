"""Orchestrate local webhook server, ngrok, and Jira webhook registration."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any, Dict, Iterable, Optional

import requests
import yaml

from webhookAPI.factory import build_webhook_api_client


DEFAULT_SETUP_CONFIG_PATH = Path(__file__).with_name("ngrok_config.yaml")


class WebhookSetupError(RuntimeError):
    """Raised when automated webhook setup cannot complete."""


@dataclass(frozen=True)
class NgrokSettings:
    """Settings for the local ngrok process."""

    command: str
    auth_token: Optional[str]
    auth_token_env: str
    addr: str
    api_url: str
    inspect: bool
    url: Optional[str] = None


@dataclass(frozen=True)
class WebhookServerSettings:
    """Settings for the local webhook server process."""

    host: str
    port: int
    path: str
    config_path: str
    webhook_config_path: str


@dataclass(frozen=True)
class JiraWebhookSettings:
    """Settings used to register the Jira admin webhook."""

    name: str
    description: str
    jql: str
    events: tuple[str, ...]
    replace_existing: bool
    delete_on_exit: bool


@dataclass(frozen=True)
class CheckSettings:
    """Settings for readiness and smoke checks."""

    timeout_seconds: int
    poll_interval_seconds: float
    run_smoke_test: bool
    smoke_issue_key: Optional[str]


@dataclass(frozen=True)
class SetupConfig:
    """Complete setup configuration."""

    ngrok: NgrokSettings
    webhook_server: WebhookServerSettings
    jira_webhook: JiraWebhookSettings
    checks: CheckSettings


def parse_args() -> argparse.Namespace:
    """Parse setup CLI arguments."""

    parser = argparse.ArgumentParser(description="Start Sprinter webhook setup with ngrok and Jira registration.")
    parser.add_argument("--config", default=str(DEFAULT_SETUP_CONFIG_PATH), help="Path to webhooks/ngrok_config.yaml.")
    parser.add_argument("--skip-smoke-test", action="store_true", help="Skip the signed end-to-end smoke test.")
    parser.add_argument("--keep-existing", action="store_true", help="Do not delete existing Jira webhooks with the same name.")
    parser.add_argument("--no-register", action="store_true", help="Start server/ngrok but do not register Jira webhook.")
    return parser.parse_args()


def main() -> None:
    """Start webhook server, ngrok, Jira webhook registration, and checks."""

    args = parse_args()
    setup_config = load_setup_config(args.config)
    if args.skip_smoke_test:
        setup_config = replace_checks(setup_config, run_smoke_test=False)
    if args.keep_existing:
        setup_config = replace_jira_webhook(setup_config, replace_existing=False)

    webhook_secret = read_webhook_secret(setup_config.webhook_server.webhook_config_path)
    processes: list[subprocess.Popen] = []
    created_webhook_id: Optional[str] = None

    try:
        webhook_process = start_webhook_server(setup_config.webhook_server)
        processes.append(webhook_process)
        wait_for_local_ready(setup_config)

        ngrok_process = start_ngrok(setup_config.ngrok)
        processes.append(ngrok_process)
        public_base_url = wait_for_ngrok_public_url(setup_config.ngrok, setup_config.checks)
        public_webhook_url = public_base_url.rstrip("/") + setup_config.webhook_server.path

        print(f"Webhook server ready: http://{setup_config.webhook_server.host}:{setup_config.webhook_server.port}{setup_config.webhook_server.path}")
        print(f"ngrok public URL: {public_base_url}")
        print(f"Jira webhook URL: {public_webhook_url}")

        if not args.no_register:
            created_webhook_id = register_jira_webhook(public_webhook_url, webhook_secret, setup_config)
            print(f"Jira webhook registered: {created_webhook_id}")

        check_public_ready(public_base_url, setup_config.checks)
        if setup_config.checks.run_smoke_test:
            run_signed_smoke_test(public_webhook_url, webhook_secret, setup_config)

        print("Webhook setup is ready. Press Ctrl+C to stop webhook server and ngrok.")
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nStopping webhook setup.")
    finally:
        if created_webhook_id and setup_config.jira_webhook.delete_on_exit:
            try:
                build_webhook_api_client(setup_config.webhook_server.config_path).delete_admin_webhook(created_webhook_id)
                print(f"Deleted Jira webhook on exit: {created_webhook_id}")
            except Exception as exc:
                print(f"Could not delete Jira webhook on exit: {exc}", file=sys.stderr)
        stop_processes(processes)


def load_setup_config(path: str | Path = DEFAULT_SETUP_CONFIG_PATH) -> SetupConfig:
    """Load and validate setup configuration from YAML."""

    config_path = Path(path)
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except OSError as exc:
        raise WebhookSetupError(f"Could not read setup config: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise WebhookSetupError(f"Setup config is not valid YAML: {config_path}") from exc

    if not isinstance(data, dict):
        raise WebhookSetupError("Setup config must contain a YAML object.")

    ngrok_section = _section(data, "ngrok")
    server_section = _section(data, "webhook_server")
    jira_section = _section(data, "jira_webhook")
    checks_section = _section(data, "checks")

    events = tuple(str(event).strip() for event in jira_section.get("events", []) if str(event).strip())
    if not events:
        raise WebhookSetupError("jira_webhook.events must contain at least one event.")

    return SetupConfig(
        ngrok=NgrokSettings(
            command=str(ngrok_section.get("command", "ngrok")),
            auth_token=_optional_string(ngrok_section.get("auth_token")),
            auth_token_env=str(ngrok_section.get("auth_token_env", "NGROK_AUTHTOKEN")),
            addr=str(ngrok_section.get("addr", "http://127.0.0.1:8090")),
            api_url=str(ngrok_section.get("api_url", "http://127.0.0.1:4040/api/tunnels")),
            inspect=bool(ngrok_section.get("inspect", True)),
            url=_optional_string(ngrok_section.get("url")),
        ),
        webhook_server=WebhookServerSettings(
            host=str(server_section.get("host", "127.0.0.1")),
            port=int(server_section.get("port", 8090)),
            path=str(server_section.get("path", "/webhooks/jira")),
            config_path=str(server_section.get("config_path", "config.yaml")),
            webhook_config_path=str(server_section.get("webhook_config_path", "webhooks/config.yaml")),
        ),
        jira_webhook=JiraWebhookSettings(
            name=str(jira_section.get("name", "Sprinter local export webhook")),
            description=str(jira_section.get("description", "Created by Sprinter webhook setup.")),
            jql=str(jira_section.get("jql", "project = SCRUM")),
            events=events,
            replace_existing=bool(jira_section.get("replace_existing", True)),
            delete_on_exit=bool(jira_section.get("delete_on_exit", False)),
        ),
        checks=CheckSettings(
            timeout_seconds=int(checks_section.get("timeout_seconds", 45)),
            poll_interval_seconds=float(checks_section.get("poll_interval_seconds", 1)),
            run_smoke_test=bool(checks_section.get("run_smoke_test", True)),
            smoke_issue_key=_optional_string(checks_section.get("smoke_issue_key")),
        ),
    )


def replace_checks(config: SetupConfig, run_smoke_test: bool) -> SetupConfig:
    """Return config with only smoke-test setting changed."""

    checks = CheckSettings(
        timeout_seconds=config.checks.timeout_seconds,
        poll_interval_seconds=config.checks.poll_interval_seconds,
        run_smoke_test=run_smoke_test,
        smoke_issue_key=config.checks.smoke_issue_key,
    )
    return SetupConfig(config.ngrok, config.webhook_server, config.jira_webhook, checks)


def replace_jira_webhook(config: SetupConfig, replace_existing: bool) -> SetupConfig:
    """Return config with only replace-existing setting changed."""

    jira = JiraWebhookSettings(
        name=config.jira_webhook.name,
        description=config.jira_webhook.description,
        jql=config.jira_webhook.jql,
        events=config.jira_webhook.events,
        replace_existing=replace_existing,
        delete_on_exit=config.jira_webhook.delete_on_exit,
    )
    return SetupConfig(config.ngrok, config.webhook_server, jira, config.checks)


def start_webhook_server(settings: WebhookServerSettings) -> subprocess.Popen:
    """Start the local webhook server process."""

    command = [
        sys.executable,
        "-m",
        "webhooks.server",
        "--host",
        settings.host,
        "--port",
        str(settings.port),
        "--path",
        settings.path,
        "--config",
        settings.config_path,
        "--webhook-config",
        settings.webhook_config_path,
    ]
    return subprocess.Popen(command)


def start_ngrok(settings: NgrokSettings) -> subprocess.Popen:
    """Start ngrok and point it at the webhook server."""

    command = build_ngrok_command(settings)
    env = os.environ.copy()
    token = resolve_ngrok_auth_token(settings)
    if token:
        env[settings.auth_token_env] = token
    return subprocess.Popen(command, env=env)


def build_ngrok_command(settings: NgrokSettings) -> list[str]:
    """Build the ngrok process command."""

    command = [
        settings.command,
        "http",
        settings.addr,
        "--log",
        "stdout",
        "--log-format",
        "json",
    ]
    if not settings.inspect:
        command.append("--inspect=false")
    if settings.url:
        command.extend(["--url", settings.url])
    return command


def resolve_ngrok_auth_token(settings: NgrokSettings) -> Optional[str]:
    """Return ngrok auth token from environment or config."""

    return _optional_string(os.environ.get(settings.auth_token_env)) or settings.auth_token


def wait_for_local_ready(config: SetupConfig) -> None:
    """Wait for the local webhook server readiness endpoint."""

    url = f"http://{config.webhook_server.host}:{config.webhook_server.port}/ready"
    wait_for_json_status(url, "ready", config.checks)


def wait_for_ngrok_public_url(settings: NgrokSettings, checks: CheckSettings) -> str:
    """Wait for ngrok's local API to expose an HTTPS public URL."""

    deadline = time.time() + checks.timeout_seconds
    last_error: Optional[str] = None
    while time.time() < deadline:
        try:
            response = requests.get(settings.api_url, timeout=5)
            response.raise_for_status()
            payload = response.json()
            for tunnel in payload.get("tunnels", []):
                public_url = tunnel.get("public_url")
                if isinstance(public_url, str) and public_url.startswith("https://"):
                    return public_url
        except (requests.RequestException, ValueError) as exc:
            last_error = str(exc)
        time.sleep(checks.poll_interval_seconds)
    raise WebhookSetupError(f"ngrok did not expose a public HTTPS URL in time. Last error: {last_error}")


def register_jira_webhook(public_webhook_url: str, webhook_secret: str, config: SetupConfig) -> str:
    """Register the Jira admin webhook and return its id."""

    client = build_webhook_api_client(config.webhook_server.config_path)
    if config.jira_webhook.replace_existing:
        for webhook in _iter_admin_webhooks(client.get_admin_webhooks()):
            if webhook.get("name") == config.jira_webhook.name:
                webhook_id = webhook.get("id") or str(webhook.get("self", "")).rstrip("/").split("/")[-1]
                if webhook_id:
                    client.delete_admin_webhook(webhook_id)

    created = client.create_admin_webhook(
        name=config.jira_webhook.name,
        description=config.jira_webhook.description,
        url=public_webhook_url,
        events=config.jira_webhook.events,
        jql_filter=config.jira_webhook.jql,
        exclude_body=False,
        secret=webhook_secret,
    )
    webhook_id = created.get("id") or str(created.get("self", "")).rstrip("/").split("/")[-1]
    if not webhook_id:
        raise WebhookSetupError(f"Jira did not return a webhook id: {created}")
    return str(webhook_id)


def check_public_ready(public_base_url: str, checks: CheckSettings) -> None:
    """Verify the public ngrok URL reaches the local webhook server."""

    wait_for_json_status(public_base_url.rstrip("/") + "/ready", "ready", checks)


def run_signed_smoke_test(public_webhook_url: str, webhook_secret: str, config: SetupConfig) -> None:
    """Send a Jira-style signed smoke event and wait for export completion."""

    issue_key = config.checks.smoke_issue_key
    if not issue_key:
        raise WebhookSetupError("checks.smoke_issue_key is required when run_smoke_test is true.")

    project_key = issue_key.split("-", 1)[0]
    event_id = f"setup-smoke-{int(time.time())}"
    body = json.dumps(
        {
            "webhookEvent": "jira:issue_created",
            "webhookEventId": event_id,
            "issue": {
                "key": issue_key,
                "fields": {"project": {"key": project_key}},
            },
            "user": {"emailAddress": "setup@example.com"},
        },
        separators=(",", ":"),
    )
    signature = build_signature(webhook_secret, body.encode("utf-8"))
    response = requests.post(
        public_webhook_url,
        data=body,
        timeout=10,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature": signature,
        },
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") == "duplicate":
        print(f"Smoke event was already recorded: {payload.get('event_id')}")
        return

    job_id = payload.get("job_id")
    if not job_id:
        raise WebhookSetupError(f"Smoke test did not enqueue a job: {payload}")

    wait_for_job_success(job_id, config)
    print(f"Smoke test completed successfully for {issue_key}: {job_id}")


def wait_for_job_success(job_id: str, config: SetupConfig) -> None:
    """Poll local job status until success or failure."""

    url = f"http://{config.webhook_server.host}:{config.webhook_server.port}/jobs/{job_id}"
    deadline = time.time() + config.checks.timeout_seconds
    while time.time() < deadline:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        job = response.json().get("job", {})
        status = job.get("status")
        if status == "success":
            return
        if status == "failed":
            raise WebhookSetupError(f"Smoke test export job failed: {job.get('error')}")
        time.sleep(config.checks.poll_interval_seconds)
    raise WebhookSetupError(f"Smoke test export job did not finish in time: {job_id}")


def wait_for_json_status(url: str, expected_status: str, checks: CheckSettings) -> None:
    """Poll a JSON endpoint until it returns the expected status field."""

    deadline = time.time() + checks.timeout_seconds
    last_error: Optional[str] = None
    while time.time() < deadline:
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") == expected_status:
                return
            last_error = f"unexpected status payload: {payload}"
        except (requests.RequestException, ValueError) as exc:
            last_error = str(exc)
        time.sleep(checks.poll_interval_seconds)
    raise WebhookSetupError(f"Endpoint did not become ready: {url}. Last error: {last_error}")


def build_signature(secret: str, body: bytes) -> str:
    """Build Jira-style X-Hub-Signature for a request body."""

    return "sha256=" + hmac.new(secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256).hexdigest()


def read_webhook_secret(webhook_config_path: str) -> str:
    """Read the webhook HMAC secret from webhooks/config.yaml."""

    with open(webhook_config_path, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    secret = config.get("auth", {}).get("secret")
    if not secret:
        raise WebhookSetupError(f"auth.secret is missing from {webhook_config_path}")
    return str(secret)


def stop_processes(processes: Iterable[subprocess.Popen]) -> None:
    """Terminate child processes in reverse start order."""

    for process in reversed(list(processes)):
        if process.poll() is not None:
            continue
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _iter_admin_webhooks(payload: Any) -> Iterable[Dict[str, Any]]:
    """Normalize Jira admin webhook list response shape."""

    if isinstance(payload, list):
        yield from (item for item in payload if isinstance(item, dict))
    elif isinstance(payload, dict):
        values = payload.get("values") or payload.get("webhooks") or []
        yield from (item for item in values if isinstance(item, dict))


def _section(config: Dict[str, Any], name: str) -> Dict[str, Any]:
    """Return a config section as a dictionary."""

    section = config.get(name, {})
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise WebhookSetupError(f"Config section must be a mapping: {name}")
    return section


def _optional_string(value: Any) -> Optional[str]:
    """Return a non-empty stripped string, or None."""

    if value is None:
        return None
    value = str(value).strip()
    return value or None


if __name__ == "__main__":
    main()
