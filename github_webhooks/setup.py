"""Orchestrate local GitHub webhook server, ngrok, and GitHub hook registration."""

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
from typing import Any, Iterable, Optional

import requests
import yaml

from github_service.settings import GitHubSettings


DEFAULT_SETUP_CONFIG_PATH = Path(__file__).with_name("ngrok_config.yaml")


class GitHubWebhookSetupError(RuntimeError):
    """Raised when automated GitHub webhook setup cannot complete."""


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
    """Settings for the local GitHub webhook server process."""

    host: str
    port: int
    path: str
    store_path: str


@dataclass(frozen=True)
class GitHubWebhookRegistrationSettings:
    """Settings used to register the GitHub repository webhook."""

    events: tuple[str, ...]
    active: bool
    content_type: str
    insecure_ssl: str
    replace_existing: bool
    delete_on_exit: bool


@dataclass(frozen=True)
class CheckSettings:
    """Settings for readiness and smoke checks."""

    timeout_seconds: int
    poll_interval_seconds: float
    run_smoke_test: bool
    smoke_workflow_id: Optional[str]
    smoke_pr_number: int


@dataclass(frozen=True)
class SetupConfig:
    """Complete GitHub webhook setup configuration."""

    ngrok: NgrokSettings
    webhook_server: WebhookServerSettings
    github_webhook: GitHubWebhookRegistrationSettings
    checks: CheckSettings


class GitHubHookClient:
    """Small GitHub REST client for repository webhook setup."""

    def __init__(self, settings: GitHubSettings, session: Optional[requests.Session] = None):
        settings.require_api()
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {settings.token}",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    @property
    def repo_path(self) -> str:
        return f"/repos/{self.settings.owner}/{self.settings.repo}"

    def list_hooks(self) -> list[dict[str, Any]]:
        return self._request("GET", f"{self.repo_path}/hooks")

    def create_hook(self, public_webhook_url: str, webhook_secret: str, config: GitHubWebhookRegistrationSettings) -> dict[str, Any]:
        return self._request(
            "POST",
            f"{self.repo_path}/hooks",
            json={
                "name": "web",
                "active": config.active,
                "events": list(config.events),
                "config": {
                    "url": public_webhook_url,
                    "content_type": config.content_type,
                    "secret": webhook_secret,
                    "insecure_ssl": config.insecure_ssl,
                },
            },
        )

    def delete_hook(self, hook_id: str | int) -> None:
        self._request("DELETE", f"{self.repo_path}/hooks/{hook_id}", expect_json=False)

    def _request(self, method: str, path: str, json: Optional[dict[str, Any]] = None, expect_json: bool = True):
        response = self.session.request(method, f"{self.settings.api_base_url}{path}", json=json)
        if response.status_code >= 400:
            raise GitHubWebhookSetupError(f"GitHub API {method} {path} failed: {response.status_code} {response.text}")
        if not expect_json or response.status_code == 204:
            return None
        return response.json()


def parse_args() -> argparse.Namespace:
    """Parse setup CLI arguments."""

    parser = argparse.ArgumentParser(description="Start Sprinter GitHub webhook setup with ngrok and repository hook registration.")
    parser.add_argument("--config", default=str(DEFAULT_SETUP_CONFIG_PATH), help="Path to github_webhooks/ngrok_config.yaml.")
    parser.add_argument("--skip-smoke-test", action="store_true", help="Skip the signed end-to-end smoke test.")
    parser.add_argument("--keep-existing", action="store_true", help="Do not delete existing GitHub webhooks with the same URL.")
    parser.add_argument("--no-register", action="store_true", help="Start server/ngrok but do not register a GitHub repository webhook.")
    return parser.parse_args()


def main() -> None:
    """Start webhook server, ngrok, GitHub hook registration, and checks."""

    args = parse_args()
    setup_config = load_setup_config(args.config)
    if args.skip_smoke_test:
        setup_config = replace_checks(setup_config, run_smoke_test=False)
    if args.keep_existing:
        setup_config = replace_github_webhook(setup_config, replace_existing=False)

    github_settings = GitHubSettings.from_env()
    github_settings.require_webhook()
    webhook_secret = github_settings.webhook_secret or ""
    processes: list[subprocess.Popen] = []
    created_hook_id: Optional[str] = None

    try:
        webhook_process = start_github_webhook_server(setup_config.webhook_server)
        processes.append(webhook_process)
        wait_for_local_ready(setup_config)

        ngrok_process = start_ngrok(setup_config.ngrok)
        processes.append(ngrok_process)
        public_base_url = wait_for_ngrok_public_url(setup_config.ngrok, setup_config.checks)
        public_webhook_url = public_base_url.rstrip("/") + setup_config.webhook_server.path

        print(f"GitHub webhook server ready: http://{setup_config.webhook_server.host}:{setup_config.webhook_server.port}{setup_config.webhook_server.path}")
        print(f"ngrok public URL: {public_base_url}")
        print(f"GitHub webhook URL: {public_webhook_url}")

        if not args.no_register:
            client = GitHubHookClient(github_settings)
            created_hook_id = register_github_webhook(public_webhook_url, webhook_secret, setup_config, client)
            print(f"GitHub repository webhook registered: {created_hook_id}")

        check_public_ready(public_base_url, setup_config.checks)
        if setup_config.checks.run_smoke_test:
            run_signed_smoke_test(public_webhook_url, webhook_secret, setup_config)

        print("GitHub webhook setup is ready. Press Ctrl+C to stop webhook server and ngrok.")
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nStopping GitHub webhook setup.")
    finally:
        if created_hook_id and setup_config.github_webhook.delete_on_exit:
            try:
                GitHubHookClient(github_settings).delete_hook(created_hook_id)
                print(f"Deleted GitHub repository webhook on exit: {created_hook_id}")
            except Exception as exc:
                print(f"Could not delete GitHub repository webhook on exit: {exc}", file=sys.stderr)
        stop_processes(processes)


def load_setup_config(path: str | Path = DEFAULT_SETUP_CONFIG_PATH) -> SetupConfig:
    """Load and validate setup configuration from YAML."""

    config_path = Path(path)
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except OSError as exc:
        raise GitHubWebhookSetupError(f"Could not read setup config: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise GitHubWebhookSetupError(f"Setup config is not valid YAML: {config_path}") from exc

    if not isinstance(data, dict):
        raise GitHubWebhookSetupError("Setup config must contain a YAML object.")

    ngrok_section = _section(data, "ngrok")
    server_section = _section(data, "webhook_server")
    github_section = _section(data, "github_webhook")
    checks_section = _section(data, "checks")

    events = tuple(str(event).strip() for event in github_section.get("events", []) if str(event).strip())
    if not events:
        raise GitHubWebhookSetupError("github_webhook.events must contain at least one event.")

    return SetupConfig(
        ngrok=NgrokSettings(
            command=str(ngrok_section.get("command", "ngrok")),
            auth_token=_optional_string(ngrok_section.get("auth_token")),
            auth_token_env=str(ngrok_section.get("auth_token_env", "NGROK_AUTHTOKEN")),
            addr=str(ngrok_section.get("addr", "http://127.0.0.1:8091")),
            api_url=str(ngrok_section.get("api_url", "http://127.0.0.1:4040/api/tunnels")),
            inspect=bool(ngrok_section.get("inspect", True)),
            url=_optional_string(ngrok_section.get("url")),
        ),
        webhook_server=WebhookServerSettings(
            host=str(server_section.get("host", "127.0.0.1")),
            port=int(server_section.get("port", 8091)),
            path=str(server_section.get("path", "/webhooks/github")),
            store_path=str(server_section.get("store_path", "exports/.github_webhooks")),
        ),
        github_webhook=GitHubWebhookRegistrationSettings(
            events=events,
            active=bool(github_section.get("active", True)),
            content_type=str(github_section.get("content_type", "json")),
            insecure_ssl=str(github_section.get("insecure_ssl", "0")),
            replace_existing=bool(github_section.get("replace_existing", True)),
            delete_on_exit=bool(github_section.get("delete_on_exit", False)),
        ),
        checks=CheckSettings(
            timeout_seconds=int(checks_section.get("timeout_seconds", 45)),
            poll_interval_seconds=float(checks_section.get("poll_interval_seconds", 1)),
            run_smoke_test=bool(checks_section.get("run_smoke_test", True)),
            smoke_workflow_id=_optional_string(checks_section.get("smoke_workflow_id")),
            smoke_pr_number=int(checks_section.get("smoke_pr_number", 1)),
        ),
    )


def replace_checks(config: SetupConfig, run_smoke_test: bool) -> SetupConfig:
    """Return config with only smoke-test setting changed."""

    checks = CheckSettings(
        timeout_seconds=config.checks.timeout_seconds,
        poll_interval_seconds=config.checks.poll_interval_seconds,
        run_smoke_test=run_smoke_test,
        smoke_workflow_id=config.checks.smoke_workflow_id,
        smoke_pr_number=config.checks.smoke_pr_number,
    )
    return SetupConfig(config.ngrok, config.webhook_server, config.github_webhook, checks)


def replace_github_webhook(config: SetupConfig, replace_existing: bool) -> SetupConfig:
    """Return config with only replace-existing setting changed."""

    github = GitHubWebhookRegistrationSettings(
        events=config.github_webhook.events,
        active=config.github_webhook.active,
        content_type=config.github_webhook.content_type,
        insecure_ssl=config.github_webhook.insecure_ssl,
        replace_existing=replace_existing,
        delete_on_exit=config.github_webhook.delete_on_exit,
    )
    return SetupConfig(config.ngrok, config.webhook_server, github, config.checks)


def start_github_webhook_server(settings: WebhookServerSettings) -> subprocess.Popen:
    """Start the local GitHub webhook server process."""

    command = [
        sys.executable,
        "-m",
        "github_webhooks.server",
        "--host",
        settings.host,
        "--port",
        str(settings.port),
        "--path",
        settings.path,
        "--store-path",
        settings.store_path,
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
    """Wait for the local GitHub webhook server readiness endpoint."""

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
    raise GitHubWebhookSetupError(f"ngrok did not expose a public HTTPS URL in time. Last error: {last_error}")


def register_github_webhook(
    public_webhook_url: str,
    webhook_secret: str,
    config: SetupConfig,
    client: GitHubHookClient,
) -> str:
    """Register the GitHub repository webhook and return its id."""

    if config.github_webhook.replace_existing:
        for hook in _iter_github_webhooks(client.list_hooks()):
            hook_config = hook.get("config") if isinstance(hook.get("config"), dict) else {}
            if hook.get("name") == "web" and hook_config.get("url") == public_webhook_url:
                hook_id = hook.get("id")
                if hook_id:
                    client.delete_hook(hook_id)

    created = client.create_hook(public_webhook_url, webhook_secret, config.github_webhook)
    hook_id = created.get("id")
    if not hook_id:
        raise GitHubWebhookSetupError(f"GitHub did not return a webhook id: {created}")
    return str(hook_id)


def check_public_ready(public_base_url: str, checks: CheckSettings) -> None:
    """Verify the public ngrok URL reaches the local webhook server."""

    wait_for_json_status(public_base_url.rstrip("/") + "/ready", "ready", checks)


def run_signed_smoke_test(public_webhook_url: str, webhook_secret: str, config: SetupConfig) -> None:
    """Send a GitHub-style signed smoke event."""

    workflow_id = config.checks.smoke_workflow_id
    if not workflow_id:
        raise GitHubWebhookSetupError("checks.smoke_workflow_id is required when run_smoke_test is true.")

    delivery_id = f"setup-smoke-{int(time.time())}"
    body = json.dumps(
        {
            "action": "opened",
            "pull_request": {
                "number": config.checks.smoke_pr_number,
                "title": f"Implement {workflow_id}",
                "body": "Smoke test pull request generated by Sprinter GitHub webhook setup.",
                "html_url": "https://github.example/sprinter/smoke/pull/1",
                "diff_url": "https://github.example/sprinter/smoke/pull/1.diff",
                "head": {"ref": f"sprinter/{workflow_id}", "sha": "setupsmoke"},
                "base": {"ref": "main"},
            },
        },
        separators=(",", ":"),
    )
    response = requests.post(
        public_webhook_url,
        data=body,
        timeout=10,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Delivery": delivery_id,
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": build_signature(webhook_secret, body.encode("utf-8")),
        },
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") not in {"accepted", "duplicate"}:
        raise GitHubWebhookSetupError(f"Smoke test was not accepted: {payload}")
    print(f"Smoke test completed successfully for {workflow_id}: {payload.get('status')}")


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
    raise GitHubWebhookSetupError(f"Endpoint did not become ready: {url}. Last error: {last_error}")


def build_signature(secret: str, body: bytes) -> str:
    """Build GitHub X-Hub-Signature-256 for a request body."""

    return "sha256=" + hmac.new(secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256).hexdigest()


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


def _iter_github_webhooks(payload: Any) -> Iterable[dict[str, Any]]:
    """Normalize GitHub hook list response shape."""

    if isinstance(payload, list):
        yield from (item for item in payload if isinstance(item, dict))


def _section(config: dict[str, Any], name: str) -> dict[str, Any]:
    """Return a config section as a dictionary."""

    section = config.get(name, {})
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise GitHubWebhookSetupError(f"Config section must be a mapping: {name}")
    return section


def _optional_string(value: Any) -> Optional[str]:
    """Return a non-empty stripped string, or None."""

    if value is None:
        return None
    value = str(value).strip()
    return value or None


if __name__ == "__main__":
    main()
