#!/usr/bin/env python3
"""Sprinter System Setup Script.

Bootstraps the entire Sprinter development environment:
  1. Checks Python version (>= 3.10)
  2. Creates a virtual environment (.venv)
  3. Installs dependencies from requirements.txt
  4. Creates a .env template with all required environment variables
  5. Creates config.yaml from the example if needed
  6. Validates that critical env vars are set
  7. Checks for external CLI tools (ngrok, codex, git)
  8. Initializes the orchestrator storage directory
  9. Ensures orchestrator-owned Jira/GitHub webhook servers auto-start
 10. Prints a summary of what's ready and what still needs action

Usage:
    python3 systemSetup.py
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent
VENV_DIR = REPO_ROOT / ".venv"
REQUIREMENTS_FILE = REPO_ROOT / "requirements.txt"
ENV_FILE = REPO_ROOT / ".env"
CONFIG_FILE = REPO_ROOT / "config.yaml"
ORCHESTRATOR_CONFIG_FILE = REPO_ROOT / "orchestrator" / "config.yaml"
ORCHESTRATOR_STORAGE = REPO_ROOT / "exports" / ".orchestrator"

MIN_PYTHON = (3, 10)

REQUIRED_ENV_VARS = [
    ("ATLASSIAN_EMAIL", "Jira/Confluence login email"),
    ("ATLASSIAN_API_TOKEN", "Atlassian API token"),
    ("SPRINTER_GITHUB_TOKEN", "GitHub personal access token (repo scope)"),
    ("SPRINTER_GITHUB_OWNER", "GitHub repository owner or organization"),
    ("SPRINTER_GITHUB_REPO", "GitHub repository name"),
    ("SPRINTER_WEBHOOK_SECRET", "Jira webhook authentication secret"),
    ("SPRINTER_GITHUB_WEBHOOK_SECRET", "GitHub webhook HMAC secret"),
    ("NGROK_AUTHTOKEN", "ngrok authentication token"),
]

OPTIONAL_ENV_VARS = [
    ("SPRINTER_GITHUB_BASE_BRANCH", "main", "Base branch for pull requests"),
    ("SPRINTER_GITHUB_BRANCH_PREFIX", "sprinter/", "Branch prefix for PRs"),
    ("SPRINTER_GITHUB_DRAFT_PR", "true", "Create PRs as draft"),
    ("SPRINTER_GITHUB_REMOTE", "origin", "Git remote name"),
    ("SPRINTER_GITHUB_API_BASE_URL", "https://api.github.com", "GitHub API base URL"),
]

EXTERNAL_TOOLS = [
    ("git", "Git version control", True),
    ("ngrok", "ngrok tunnel for public webhooks", False),
    ("codex", "OpenAI Codex CLI for analysis and implementation", False),
]

ENV_TEMPLATE = '''# =============================================================================
# Sprinter Environment Variables
# =============================================================================
# Source this file before running the orchestrator:
#   source .env
#
# WARNING: Do NOT commit this file to version control.
# =============================================================================

# --- Atlassian (Jira / Confluence) -------------------------------------------
export ATLASSIAN_EMAIL=""
export ATLASSIAN_API_TOKEN=""

# --- GitHub ------------------------------------------------------------------
export SPRINTER_GITHUB_TOKEN=""
export SPRINTER_GITHUB_OWNER=""
export SPRINTER_GITHUB_REPO=""

# --- Webhook Security --------------------------------------------------------
export SPRINTER_WEBHOOK_SECRET=""
export SPRINTER_GITHUB_WEBHOOK_SECRET=""

# --- ngrok -------------------------------------------------------------------
export NGROK_AUTHTOKEN=""

# --- Optional GitHub Settings ------------------------------------------------
# export SPRINTER_GITHUB_BASE_BRANCH="main"
# export SPRINTER_GITHUB_BRANCH_PREFIX="sprinter/"
# export SPRINTER_GITHUB_DRAFT_PR="true"
# export SPRINTER_GITHUB_REMOTE="origin"

# --- Optional Codex Settings ------------------------------------------------
# export SPRINTER_CODEX_ANALYSIS_COMMAND="codex"
# export SPRINTER_CODEX_ANALYSIS_TIMEOUT_SECONDS="600"
# export SPRINTER_CODEX_IMPLEMENTER_COMMAND="codex"
# export SPRINTER_CODEX_IMPLEMENTER_TIMEOUT_SECONDS="1800"
'''

CONFIG_TEMPLATE = '''# Atlassian exporter configuration.
# Prefer environment variables for tokens so they do not live in this file.

jira:
  base_url: "https://your-site.atlassian.net/"
  auth:
    type: "basic"
    email_env: "ATLASSIAN_EMAIL"
    token_env: "ATLASSIAN_API_TOKEN"

confluence:
  base_url: "https://your-site.atlassian.net/wiki"
  auth:
    type: "basic"
    email_env: "ATLASSIAN_EMAIL"
    token_env: "ATLASSIAN_API_TOKEN"

requests:
  timeout_seconds: 30
  retries: 3
  page_size: 100
  log_level: "INFO"

storage:
  export_path: "exports"
  download_attachments: true
  include_confluence_descendants: true
confluence_descendant_depth: 5
'''

DEFAULT_WEBHOOK_SERVER_CONFIG = {
    "auto_start": True,
    "jira": {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8090,
        "path": "/webhooks/jira",
        "config_path": "config.yaml",
        "store_path": None,
    },
    "github": {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8091,
        "path": "/webhooks/github",
        "store_path": "exports/.github_webhooks",
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class Colors:
    """ANSI color codes for terminal output."""
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def banner(text: str) -> None:
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'=' * 60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}  {text}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'=' * 60}{Colors.RESET}")


def step(number: int, text: str) -> None:
    print(f"\n{Colors.BOLD}[{number}] {text}{Colors.RESET}")


def success(text: str) -> None:
    print(f"  {Colors.GREEN}✓ {text}{Colors.RESET}")


def warning(text: str) -> None:
    print(f"  {Colors.YELLOW}⚠ {text}{Colors.RESET}")


def error(text: str) -> None:
    print(f"  {Colors.RED}✗ {text}{Colors.RESET}")


def info(text: str) -> None:
    print(f"  {Colors.CYAN}→ {text}{Colors.RESET}")


def run_command(args: list[str], cwd: Path = REPO_ROOT, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=check)


def which(command: str) -> bool:
    """Check if a command is available on PATH."""
    return shutil.which(command) is not None


# ---------------------------------------------------------------------------
# Setup Steps
# ---------------------------------------------------------------------------

def check_python_version() -> bool:
    """Step 1: Check Python version."""
    step(1, "Checking Python version")

    major, minor = sys.version_info[:2]
    version_str = f"{major}.{minor}.{sys.version_info[2]}"

    if (major, minor) >= MIN_PYTHON:
        success(f"Python {version_str} (>= {MIN_PYTHON[0]}.{MIN_PYTHON[1]} required)")
        return True
    else:
        error(f"Python {version_str} is too old. Sprinter requires Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+")
        return False


def create_venv() -> bool:
    """Step 2: Create virtual environment."""
    step(2, "Setting up virtual environment")

    if VENV_DIR.exists():
        success(f".venv already exists at {VENV_DIR}")
        return True

    try:
        info("Creating virtual environment...")
        run_command([sys.executable, "-m", "venv", str(VENV_DIR)])
        success(f"Created .venv at {VENV_DIR}")
        return True
    except subprocess.CalledProcessError as e:
        error(f"Failed to create .venv: {e.stderr}")
        return False


def install_dependencies() -> bool:
    """Step 3: Install dependencies."""
    step(3, "Installing dependencies")

    pip_path = VENV_DIR / "bin" / "pip"
    if not pip_path.exists():
        error(f"pip not found at {pip_path}")
        return False

    if not REQUIREMENTS_FILE.exists():
        error(f"requirements.txt not found at {REQUIREMENTS_FILE}")
        return False

    try:
        info("Installing packages from requirements.txt...")
        result = run_command([str(pip_path), "install", "-r", str(REQUIREMENTS_FILE)])
        # Count installed packages
        lines = [l for l in result.stdout.splitlines() if "Successfully installed" in l or "already satisfied" in l]
        if lines:
            for line in lines:
                success(line.strip())
        else:
            success("All dependencies installed")
        return True
    except subprocess.CalledProcessError as e:
        error(f"Failed to install dependencies: {e.stderr}")
        return False


def create_env_file() -> bool:
    """Step 4: Create .env template."""
    step(4, "Creating .env template")

    if ENV_FILE.exists():
        success(f".env already exists at {ENV_FILE}")
        warning("Review the file and fill in any missing values")
        return True

    try:
        ENV_FILE.write_text(ENV_TEMPLATE, encoding="utf-8")
        success(f"Created .env template at {ENV_FILE}")
        warning("IMPORTANT: Edit .env and fill in your credentials before running the orchestrator")
        return True
    except OSError as e:
        error(f"Failed to create .env: {e}")
        return False


def create_config_file() -> bool:
    """Step 5: Create config.yaml."""
    step(5, "Creating config.yaml")

    if CONFIG_FILE.exists():
        success(f"config.yaml already exists at {CONFIG_FILE}")
        return True

    try:
        CONFIG_FILE.write_text(CONFIG_TEMPLATE, encoding="utf-8")
        success(f"Created config.yaml at {CONFIG_FILE}")
        warning("Edit config.yaml and set your Atlassian base_url")
        return True
    except OSError as e:
        error(f"Failed to create config.yaml: {e}")
        return False


def validate_env_vars() -> tuple[int, int]:
    """Step 6: Validate environment variables."""
    step(6, "Validating environment variables")

    set_count = 0
    missing_count = 0

    for var_name, description in REQUIRED_ENV_VARS:
        value = os.environ.get(var_name, "").strip()
        if value:
            success(f"{var_name} is set")
            set_count += 1
        else:
            warning(f"{var_name} is NOT set — {description}")
            missing_count += 1

    if missing_count > 0:
        info(f"Fill in the missing variables in .env, then run: source .env")

    return set_count, missing_count


def check_external_tools() -> tuple[int, int]:
    """Step 7: Check for external CLI tools."""
    step(7, "Checking external tools")

    found = 0
    missing = 0

    for tool_name, description, required in EXTERNAL_TOOLS:
        if which(tool_name):
            success(f"{tool_name} — {description}")
            found += 1
        elif required:
            error(f"{tool_name} — {description} (REQUIRED, not found)")
            missing += 1
        else:
            warning(f"{tool_name} — {description} (optional, not found)")
            missing += 1

    return found, missing


def initialize_orchestrator_storage() -> bool:
    """Step 8: Initialize orchestrator storage directories."""
    step(8, "Initializing orchestrator storage")

    dirs_to_create = [
        ORCHESTRATOR_STORAGE / "events" / "pending",
        ORCHESTRATOR_STORAGE / "events" / "processing",
        ORCHESTRATOR_STORAGE / "events" / "completed",
        ORCHESTRATOR_STORAGE / "events" / "failed",
        ORCHESTRATOR_STORAGE / "commands",
        ORCHESTRATOR_STORAGE / "workflows",
        ORCHESTRATOR_STORAGE / "logs",
        REPO_ROOT / "exports",
    ]

    created = 0
    for dir_path in dirs_to_create:
        if not dir_path.exists():
            dir_path.mkdir(parents=True, exist_ok=True)
            created += 1

    if created > 0:
        success(f"Created {created} storage directories under {ORCHESTRATOR_STORAGE}")
    else:
        success(f"Storage directories already exist at {ORCHESTRATOR_STORAGE}")

    return True


def ensure_orchestrator_webhook_autostart() -> bool:
    """Step 9: Ensure the orchestrator starts both webhook servers."""

    step(9, "Checking orchestrator webhook auto-start")

    try:
        import yaml
    except ImportError:
        error("PyYAML is required to update orchestrator/config.yaml")
        return False

    try:
        if ORCHESTRATOR_CONFIG_FILE.exists():
            data = yaml.safe_load(ORCHESTRATOR_CONFIG_FILE.read_text(encoding="utf-8")) or {}
        else:
            data = {}
    except (OSError, yaml.YAMLError) as exc:
        error(f"Could not read {ORCHESTRATOR_CONFIG_FILE}: {exc}")
        return False

    if not isinstance(data, dict):
        error(f"{ORCHESTRATOR_CONFIG_FILE} must contain a YAML object")
        return False

    changed = _ensure_webhook_server_config(data)

    if not changed:
        success("Orchestrator already auto-starts Jira and GitHub webhook servers")
        return True

    try:
        ORCHESTRATOR_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        ORCHESTRATOR_CONFIG_FILE.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    except OSError as exc:
        error(f"Could not write {ORCHESTRATOR_CONFIG_FILE}: {exc}")
        return False

    success("Updated orchestrator/config.yaml to auto-start Jira and GitHub webhook servers")
    return True


def ensure_gitignore() -> None:
    """Make sure .env is in .gitignore."""
    gitignore_path = REPO_ROOT / ".gitignore"
    if gitignore_path.exists():
        content = gitignore_path.read_text(encoding="utf-8")
        if ".env" not in content:
            with gitignore_path.open("a", encoding="utf-8") as f:
                f.write("\n.env\n")
            success("Added .env to .gitignore")
    else:
        gitignore_path.write_text(".env\n", encoding="utf-8")
        success("Created .gitignore with .env entry")


def _ensure_webhook_server_config(data: dict) -> bool:
    """Populate missing webhook server settings needed by the orchestrator."""

    changed = False
    servers = data.get("webhook_servers")
    if not isinstance(servers, dict):
        servers = {}
        data["webhook_servers"] = servers
        changed = True

    if servers.get("auto_start") is not True:
        servers["auto_start"] = True
        changed = True

    changed = _ensure_webhook_section(servers, "jira", DEFAULT_WEBHOOK_SERVER_CONFIG["jira"]) or changed
    changed = _ensure_webhook_section(servers, "github", DEFAULT_WEBHOOK_SERVER_CONFIG["github"]) or changed
    return changed


def _ensure_webhook_section(servers: dict, name: str, defaults: dict) -> bool:
    """Ensure one webhook server section is present and enabled."""

    section = servers.get(name)
    if not isinstance(section, dict):
        servers[name] = dict(defaults)
        return True

    changed = False
    if section.get("enabled") is not True:
        section["enabled"] = True
        changed = True

    for key, value in defaults.items():
        if key == "enabled":
            continue
        if key not in section:
            section[key] = value
            changed = True
    return changed


def print_summary(
    python_ok: bool,
    venv_ok: bool,
    deps_ok: bool,
    env_ok: bool,
    config_ok: bool,
    env_set: int,
    env_missing: int,
    tools_found: int,
    tools_missing: int,
    storage_ok: bool,
    webhook_autostart_ok: bool,
) -> None:
    """Step 10: Print final summary."""
    banner("Setup Summary")

    items = [
        ("Python version", python_ok),
        ("Virtual environment", venv_ok),
        ("Dependencies", deps_ok),
        (".env template", env_ok),
        ("config.yaml", config_ok),
        ("Orchestrator storage", storage_ok),
        ("Webhook auto-start config", webhook_autostart_ok),
    ]

    all_ok = True
    for label, ok in items:
        if ok:
            success(label)
        else:
            error(label)
            all_ok = False

    print()
    if env_missing > 0:
        warning(f"Environment variables: {env_set} set, {env_missing} missing")
    else:
        success(f"Environment variables: all {env_set} required vars are set")

    if tools_missing > 0:
        warning(f"External tools: {tools_found} found, {tools_missing} not found")
    else:
        success(f"External tools: all {tools_found} tools found")

    print()
    if all_ok and env_missing == 0:
        print(f"{Colors.BOLD}{Colors.GREEN}  🚀 Sprinter is ready!{Colors.RESET}")
        print()
        info("Start the orchestrator:")
        print(f"    source .env")
        print(f"    .venv/bin/python -m orchestrator start")
        print()
        info("The orchestrator auto-starts local Jira and GitHub webhook servers when it starts.")
        print()
        info("Register webhooks (in a separate terminal):")
        print(f"    source .env")
        print(f"    .venv/bin/python -m webhooks.setup")
        print(f"    .venv/bin/python -m github_webhooks.setup")
    else:
        print(f"{Colors.BOLD}{Colors.YELLOW}  ⚠ Setup is incomplete.{Colors.RESET}")
        print()
        if env_missing > 0:
            info("Next step: Edit .env with your credentials, then run:")
            print(f"    source .env")
            print(f"    python3 systemSetup.py  # re-run to verify")
        if not all_ok:
            info("Fix the errors above and re-run this script.")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    banner("Sprinter System Setup")

    python_ok = check_python_version()
    if not python_ok:
        error("Cannot continue without a compatible Python version.")
        return 1

    venv_ok = create_venv()
    deps_ok = install_dependencies() if venv_ok else False
    env_ok = create_env_file()
    config_ok = create_config_file()
    ensure_gitignore()
    env_set, env_missing = validate_env_vars()
    tools_found, tools_missing = check_external_tools()
    storage_ok = initialize_orchestrator_storage()
    webhook_autostart_ok = ensure_orchestrator_webhook_autostart()

    print_summary(
        python_ok, venv_ok, deps_ok, env_ok, config_ok,
        env_set, env_missing, tools_found, tools_missing, storage_ok, webhook_autostart_ok,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
