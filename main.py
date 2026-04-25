"""Command-line entrypoint and workflow orchestration for Sprinter.

This module coordinates configuration loading, authentication resolution,
Jira export, Jira issue creation, Confluence export, logging, and manifest
generation.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import yaml

from fetcher import AuthConfig, ConfluenceFetcher, ExporterError, JiraFetcher
from utils import (
    attachment_filename,
    ensure_dir,
    extract_confluence_page_id,
    extract_confluence_space_title,
    is_same_host,
    parse_jira_url,
    sanitize_filename,
    unique_path,
    write_json,
    write_text,
)


class ConfigError(ValueError):
    """Raised when local configuration is missing, malformed, or unsafe to use."""

    pass


PLACEHOLDER_VALUES = {
    "",
    "YOUR_JIRA_PAT",
    "YOUR_CONFLUENCE_PAT",
    "YOUR_TOKEN",
    "YOUR_EMAIL@example.com",
    "https://your-domain.atlassian.net",
    "https://your-domain.atlassian.net/wiki",
}


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for export and create workflows.

    Returns:
        argparse.Namespace: Parsed subcommand arguments describing either an
        export or create operation.
    """

    parser = argparse.ArgumentParser(description="Export Jira issues, linked Confluence content, or create Jira issues.")
    parser.add_argument("--config", default="config.yaml", help="Path to the YAML configuration file.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="Export a Jira issue and linked Confluence content.")
    export_parser.add_argument("ticket_url", help="The Jira issue URL to export.")

    create_parser = subparsers.add_parser("create", help="Create a Jira issue from a JSON payload file.")
    create_parser.add_argument("ticket_file", help="Path to the ticket JSON file.")

    return parser.parse_args()


def load_config(config_path: str = "config.yaml") -> Dict:
    """Load YAML configuration and fill in exporter defaults.

    Args:
        config_path: Path to the YAML config file.

    Returns:
        Dict: Parsed configuration enriched with default request and storage
        settings.

    Raises:
        ConfigError: If the config file does not exist or omits required
        top-level sections.
        yaml.YAMLError: If the YAML file cannot be parsed.
    """

    if not os.path.exists(config_path):
        raise ConfigError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    for section_name in ("jira", "confluence", "storage"):
        if section_name not in config:
            raise ConfigError(f"Missing required config section: {section_name}")

    config.setdefault("requests", {})
    config["requests"].setdefault("timeout_seconds", 30)
    config["requests"].setdefault("retries", 3)
    config["requests"].setdefault("page_size", 100)
    config["requests"].setdefault("log_level", "INFO")

    storage = config["storage"]
    storage.setdefault("export_path", "./exports")
    storage.setdefault("download_attachments", True)
    storage.setdefault("include_confluence_descendants", True)
    storage.setdefault("confluence_descendant_depth", 5)

    return config


def configure_logging(level_name: str) -> None:
    """Configure the root logger used by the exporter.

    Args:
        level_name: Logging level name such as ``INFO`` or ``DEBUG``.
    """

    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")


def attach_file_logging(log_path: str) -> logging.Handler:
    """Attach a file handler so each export run persists its log output.

    Args:
        log_path: Destination path for the run log file.

    Returns:
        logging.Handler: The handler that was attached so callers can remove
        it after the run completes.
    """

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(handler)
    return handler


def build_run_manifest(ticket_url: str, issue_key: str) -> Dict:
    """Create the initial manifest object for a single export run.

    Args:
        ticket_url: Full Jira issue URL provided by the caller.
        issue_key: Parsed Jira issue key.

    Returns:
        Dict: Manifest skeleton with timestamps, status, and empty result
        sections that are filled during execution.
    """

    return {
        "ticket_url": ticket_url,
        "issue_key": issue_key,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "status": "running",
        "jira": {},
        "confluence": {},
        "errors": [],
    }


def finalize_run_manifest(manifest: Dict, status: str) -> Dict:
    """Mark a manifest as finished and stamp the completion time.

    Args:
        manifest: Mutable manifest dictionary for the current run.
        status: Final status string such as ``success`` or ``failed``.

    Returns:
        Dict: The same manifest instance after mutation for convenient
        chaining by callers.
    """

    manifest["status"] = status
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    return manifest


def write_manifest(issue_dir: str, manifest: Dict) -> None:
    """Persist the run manifest into the issue export directory.

    Args:
        issue_dir: Export directory for the Jira issue.
        manifest: Manifest payload to serialize as JSON.
    """

    write_json(os.path.join(issue_dir, "export_manifest.json"), manifest)


def _value_from_env(env_name: Optional[str]) -> Optional[str]:
    """Read and normalize a configuration value from the environment.

    Args:
        env_name: Environment variable name to read. ``None`` is treated as
        unset.

    Returns:
        Optional[str]: Trimmed environment value, or ``None`` when the
        variable name is missing or the variable is unset.
    """

    if not env_name:
        return None
    value = os.getenv(env_name)
    return value.strip() if value else None


def _require_non_placeholder(value: Optional[str], field_name: str) -> str:
    """Reject empty or placeholder config values before making API calls.

    Args:
        value: Candidate config value.
        field_name: Human-readable field path used in error messages.

    Returns:
        str: The validated value.

    Raises:
        ConfigError: If the value is empty or still contains a template
        placeholder.
    """

    if not value or value in PLACEHOLDER_VALUES:
        raise ConfigError(f"Invalid or placeholder value for {field_name}.")
    return value


def resolve_auth_config(section_name: str, section: Dict) -> AuthConfig:
    """Resolve one service's authentication settings into a normalized object.

    The function supports the preferred ``auth`` block as well as the older
    ``pat`` fallback so existing config files keep working.

    Args:
        section_name: Logical service name used in error messages.
        section: Parsed config section for Jira or Confluence.

    Returns:
        AuthConfig: Normalized authentication settings for the fetcher layer.

    Raises:
        ConfigError: If required auth values are absent or placeholders.
    """

    auth_section = dict(section.get("auth", {}))

    token = auth_section.get("token") or _value_from_env(auth_section.get("token_env"))
    email = auth_section.get("email") or _value_from_env(auth_section.get("email_env"))
    auth_type = auth_section.get("type")

    if not token and section.get("pat"):
        token = section["pat"]
        auth_type = auth_type or "bearer"

    if not auth_type:
        auth_type = "basic" if email else "bearer"

    token = _require_non_placeholder(token, f"{section_name}.auth.token")
    if auth_type == "basic":
        email = _require_non_placeholder(email, f"{section_name}.auth.email")

    return AuthConfig(auth_type=auth_type, token=token, email=email)


def validate_service_base_url(section_name: str, section: Dict) -> str:
    """Validate and normalize a Jira or Confluence base URL.

    Args:
        section_name: Logical service name used in validation errors.
        section: Parsed config section containing ``base_url``.

    Returns:
        str: Normalized base URL with trailing slash removed.

    Raises:
        ConfigError: If the configured URL is missing or not a valid absolute
        URL.
    """

    base_url = _require_non_placeholder(section.get("base_url"), f"{section_name}.base_url")
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        raise ConfigError(f"Invalid URL for {section_name}.base_url: {base_url}")
    return base_url.rstrip("/")


def build_jira_fetcher(config: Dict) -> JiraFetcher:
    """Create a configured Jira API client.

    Args:
        config: Fully loaded exporter configuration.

    Returns:
        JiraFetcher: Ready-to-use Jira API client with auth, retry, and
        timeout behavior applied.
    """

    timeout_seconds = int(config["requests"]["timeout_seconds"])
    retries = int(config["requests"]["retries"])
    jira_base_url = validate_service_base_url("jira", config["jira"])
    return JiraFetcher(
        jira_base_url,
        resolve_auth_config("jira", config["jira"]),
        timeout_seconds=timeout_seconds,
        retries=retries,
    )


def build_confluence_fetcher(config: Dict) -> ConfluenceFetcher:
    """Create a configured Confluence API client.

    Args:
        config: Fully loaded exporter configuration.

    Returns:
        ConfluenceFetcher: Ready-to-use Confluence API client with auth,
        retry, and timeout behavior applied.
    """

    timeout_seconds = int(config["requests"]["timeout_seconds"])
    retries = int(config["requests"]["retries"])
    confluence_base_url = validate_service_base_url("confluence", config["confluence"])
    return ConfluenceFetcher(
        confluence_base_url,
        resolve_auth_config("confluence", config["confluence"]),
        timeout_seconds=timeout_seconds,
        retries=retries,
    )


def load_ticket_payload(ticket_file: str) -> Dict:
    """Load and validate the Jira issue creation payload from JSON.

    Args:
        ticket_file: Path to the JSON file describing the issue to create.

    Returns:
        Dict: Parsed JSON payload ready for the Jira create issue endpoint.

    Raises:
        ConfigError: If the file is missing, invalid JSON, or does not contain
        the required Jira create-issue structure.
    """

    if not os.path.exists(ticket_file):
        raise ConfigError(f"Ticket file not found: {ticket_file}")

    try:
        with open(ticket_file, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Ticket file is not valid JSON: {ticket_file}") from exc

    if not isinstance(payload, dict):
        raise ConfigError("Ticket file must contain a JSON object.")

    if "fields" not in payload and "update" not in payload:
        raise ConfigError("Ticket file must contain at least a 'fields' or 'update' object.")

    fields = payload.get("fields", {})
    if fields and not isinstance(fields, dict):
        raise ConfigError("'fields' must be a JSON object.")

    if "fields" in payload:
        required_field_paths = [
            ("project", "project"),
            ("issuetype", "issuetype"),
            ("summary", "summary"),
        ]
        for field_name, label in required_field_paths:
            if field_name not in fields:
                raise ConfigError(f"Ticket file is missing required field: fields.{label}")

    return payload


def write_created_issue_artifacts(issue_dir: str, ticket_file: str, payload: Dict, response: Dict) -> None:
    """Persist the request and response for a Jira issue creation run.

    Args:
        issue_dir: Destination directory for created-issue artifacts.
        ticket_file: Source payload file path.
        payload: JSON payload sent to Jira.
        response: Jira API response for the created issue.
    """

    ensure_dir(issue_dir)
    write_json(os.path.join(issue_dir, "ticket_request.json"), payload)
    write_json(os.path.join(issue_dir, "ticket_response.json"), response)
    write_json(
        os.path.join(issue_dir, "ticket_source.json"),
        {"ticket_file": os.path.abspath(ticket_file)},
    )


def create_jira_issue_from_file(jira_fetcher: JiraFetcher, ticket_file: str, export_root: str) -> Tuple[str, Dict, Dict]:
    """Create a Jira issue from a JSON file and persist creation artifacts.

    Args:
        jira_fetcher: Configured Jira API client.
        ticket_file: Path to the JSON payload file.
        export_root: Root storage path from config.

    Returns:
        Tuple[str, Dict, Dict]: Output directory, original payload, and Jira
        response payload.
    """

    payload = load_ticket_payload(ticket_file)
    logging.info("Creating Jira issue from %s", ticket_file)
    response = jira_fetcher.create_issue(payload)

    issue_key = response.get("key") or response.get("id") or "created_issue"
    issue_dir = os.path.join(export_root, "created", sanitize_filename(str(issue_key)))
    write_created_issue_artifacts(issue_dir, ticket_file, payload, response)
    logging.info("Created Jira issue %s", response.get("key", response.get("id", "unknown")))
    return issue_dir, payload, response


def export_jira_issue(
    jira_fetcher: JiraFetcher,
    issue_key: str,
    issue_dir: str,
    page_size: int,
    download_attachments: bool,
) -> List[Dict]:
    """Export one Jira issue and all issue-scoped artifacts to disk.

    This writes the issue payload, comments, worklogs, changelog, remote
    links, and attachment metadata. Attachment binaries are optionally
    downloaded into a subdirectory.

    Args:
        jira_fetcher: Configured Jira API client.
        issue_key: Jira issue key to export.
        issue_dir: Destination directory for the issue export.
        page_size: Page size used for paginated Jira endpoints.
        download_attachments: Whether to download attachment binaries.

    Returns:
        List[Dict]: Remote link objects discovered on the Jira issue so the
        Confluence export step can inspect them.
    """

    logging.info("Fetching Jira issue: %s", issue_key)
    ensure_dir(issue_dir)

    issue_data = jira_fetcher.fetch_issue(issue_key)
    comments = jira_fetcher.fetch_comments(issue_key, page_size=page_size)
    worklogs = jira_fetcher.fetch_worklogs(issue_key, page_size=page_size)
    changelog = jira_fetcher.fetch_changelog(issue_key, page_size=page_size)
    remote_links = jira_fetcher.fetch_remote_links(issue_key)

    write_json(os.path.join(issue_dir, "issue.json"), issue_data)
    write_json(os.path.join(issue_dir, "comments.json"), comments)
    write_json(os.path.join(issue_dir, "worklogs.json"), worklogs)
    write_json(os.path.join(issue_dir, "changelog.json"), changelog)
    write_json(os.path.join(issue_dir, "remote_links.json"), remote_links)

    attachments = issue_data.get("fields", {}).get("attachment", [])
    write_json(os.path.join(issue_dir, "attachments.json"), attachments)

    if download_attachments and attachments:
        attachment_dir = os.path.join(issue_dir, "attachments")
        ensure_dir(attachment_dir)
        for attachment in attachments:
            file_name = attachment_filename(attachment.get("id", "attachment"), attachment["filename"])
            destination = unique_path(os.path.join(attachment_dir, file_name))
            logging.info("Downloading Jira attachment: %s", os.path.basename(destination))
            jira_fetcher.download_attachment(attachment["content"], destination)

    logging.info("Exported Jira issue to %s", issue_dir)
    return remote_links


def collect_confluence_page_ids(
    remote_links: List[Dict],
    confluence_base_url: str,
    confluence_fetcher: Optional[ConfluenceFetcher] = None,
) -> Tuple[List[str], List[Dict]]:
    """Resolve Confluence page ids from Jira remote links.

    The function first tries direct page-id extraction from modern Confluence
    URLs. When a fetcher is provided, it also attempts to resolve legacy
    ``/display/SPACE/Title`` links through Confluence search.

    Args:
        remote_links: Jira remote link payloads.
        confluence_base_url: Configured Confluence base URL used for host
        validation.
        confluence_fetcher: Optional Confluence client for legacy-link
        resolution.

    Returns:
        Tuple[List[str], List[Dict]]: A deduplicated list of page ids and a
        list of same-host links that still could not be resolved.
    """

    page_ids: List[str] = []
    unresolved_links: List[Dict] = []
    seen: Set[str] = set()
    expected_host = urlparse(confluence_base_url).netloc

    for link in remote_links:
        link_url = link.get("object", {}).get("url", "")
        if not link_url or not is_same_host(link_url, confluence_base_url):
            continue

        page_id = extract_confluence_page_id(link_url, expected_host=expected_host)
        if not page_id and confluence_fetcher:
            space_title = extract_confluence_space_title(link_url, expected_host=expected_host)
            if space_title:
                page_id = confluence_fetcher.search_page_by_space_and_title(*space_title)

        if page_id:
            if page_id not in seen:
                page_ids.append(page_id)
                seen.add(page_id)
        else:
            unresolved_links.append(link)

    return page_ids, unresolved_links


def export_confluence_page(
    confluence_fetcher: ConfluenceFetcher,
    page_id: str,
    wiki_dir: str,
    visited: Set[str],
    descendant_depth: int,
    download_attachments: bool,
) -> List[Dict]:
    """Export a single Confluence page and return its descendants.

    Args:
        confluence_fetcher: Configured Confluence API client.
        page_id: Confluence page identifier to export.
        wiki_dir: Destination directory that stores all Confluence exports for
        the Jira issue.
        visited: Mutable set used to avoid exporting the same page twice.
        descendant_depth: Maximum descendant depth to request from the API.
        download_attachments: Whether to download Confluence attachment
        binaries.

    Returns:
        List[Dict]: Descendant page records returned by Confluence. The caller
        can use them to decide whether to recurse further.
    """

    if page_id in visited:
        return []
    visited.add(page_id)

    logging.info("Exporting Confluence page: %s", page_id)
    page = confluence_fetcher.fetch_page(page_id)
    ancestors = confluence_fetcher.fetch_page_ancestors(page_id)
    descendants = confluence_fetcher.fetch_page_descendants(page_id, depth=descendant_depth)
    footer_comments = confluence_fetcher.fetch_page_footer_comments(page_id)
    inline_comments = confluence_fetcher.fetch_page_inline_comments(page_id)
    attachments = confluence_fetcher.fetch_page_attachments(page_id)

    page_dir = os.path.join(wiki_dir, f"page_{page_id}")
    ensure_dir(page_dir)

    write_json(os.path.join(page_dir, "page.json"), page)
    write_json(os.path.join(page_dir, "ancestors.json"), ancestors)
    write_json(os.path.join(page_dir, "descendants.json"), descendants)
    write_json(os.path.join(page_dir, "footer_comments.json"), footer_comments)
    write_json(os.path.join(page_dir, "inline_comments.json"), inline_comments)
    write_json(os.path.join(page_dir, "attachments.json"), attachments)

    page_title = sanitize_filename(page.get("title", f"page_{page_id}"))
    write_text(os.path.join(page_dir, f"{page_title}.storage.html"), page.get("body", {}).get("storage", {}).get("value", ""))

    if download_attachments and attachments:
        attachment_dir = os.path.join(page_dir, "attachments")
        ensure_dir(attachment_dir)
        for attachment in attachments:
            title = attachment.get("title") or attachment.get("fileName") or "attachment"
            file_name = attachment_filename(attachment.get("id", "attachment"), title)
            destination = unique_path(os.path.join(attachment_dir, file_name))
            logging.info("Downloading Confluence attachment: %s", os.path.basename(destination))
            confluence_fetcher.download_attachment(attachment["downloadLink"], destination)

    return descendants


def export_confluence_content_with_manifest(
    confluence_fetcher: ConfluenceFetcher,
    remote_links: List[Dict],
    issue_dir: str,
    confluence_base_url: str,
    descendant_depth: int,
    include_descendants: bool,
    download_attachments: bool,
) -> Dict:
    """Export all Confluence content linked from the Jira issue.

    Args:
        confluence_fetcher: Configured Confluence API client.
        remote_links: Remote links discovered on the Jira issue.
        issue_dir: Destination directory for the Jira issue export.
        confluence_base_url: Configured Confluence base URL.
        descendant_depth: Maximum descendant depth for Confluence traversal.
        include_descendants: Whether child pages should also be exported.
        download_attachments: Whether Confluence attachment binaries should be
        downloaded.

    Returns:
        Dict: Confluence-specific summary data that is embedded in the overall
        run manifest.
    """

    page_ids, unresolved_links = collect_confluence_page_ids(
        remote_links,
        confluence_base_url,
        confluence_fetcher=confluence_fetcher,
    )

    manifest = {
        "remote_link_count": len(remote_links),
        "linked_page_ids": page_ids,
        "unresolved_links": len(unresolved_links),
        "exported_pages": [],
    }

    if not page_ids and not unresolved_links:
        logging.info("No Confluence links found in remote links.")
        return manifest

    wiki_dir = os.path.join(issue_dir, "wiki")
    ensure_dir(wiki_dir)
    write_json(os.path.join(wiki_dir, "linked_pages.json"), page_ids)
    write_json(os.path.join(wiki_dir, "unresolved_links.json"), unresolved_links)

    visited: Set[str] = set()
    for page_id in page_ids:
        descendants = export_confluence_page(
            confluence_fetcher,
            page_id,
            wiki_dir,
            visited,
            descendant_depth=descendant_depth,
            download_attachments=download_attachments,
        )
        manifest["exported_pages"].append(page_id)
        if include_descendants:
            for descendant in descendants:
                descendant_id = descendant.get("id")
                if descendant.get("type") == "page" and descendant_id and descendant_id not in visited:
                    export_confluence_page(
                        confluence_fetcher,
                        descendant_id,
                        wiki_dir,
                        visited,
                        descendant_depth=descendant_depth,
                        download_attachments=download_attachments,
                    )
                    manifest["exported_pages"].append(descendant_id)

    return manifest


def main() -> None:
    """Run the CLI workflow from argument parsing through manifest persistence.

    The function intentionally owns the top-level error handling so the CLI
    exits with a clear non-zero status on configuration, filesystem, or API
    failures.
    """

    args = parse_args()
    issue_dir: Optional[str] = None
    manifest: Optional[Dict] = None
    file_handler: Optional[logging.Handler] = None

    try:
        config = load_config(args.config)
        configure_logging(config["requests"]["log_level"])
        jira_fetcher = build_jira_fetcher(config)
        confluence_fetcher: Optional[ConfluenceFetcher] = None

        if args.command == "export":
            confluence_fetcher = build_confluence_fetcher(config)
            jira_host = urlparse(config["jira"]["base_url"]).netloc
            issue_key = parse_jira_url(args.ticket_url, expected_host=jira_host)
            if not issue_key:
                raise ConfigError("Could not extract a Jira issue key from the provided URL.")

            manifest = build_run_manifest(args.ticket_url, issue_key)
            issue_dir = os.path.join(config["storage"]["export_path"], issue_key)
            ensure_dir(issue_dir)
            file_handler = attach_file_logging(os.path.join(issue_dir, "export.log"))
            logging.info("Starting export for %s", issue_key)

            remote_links = export_jira_issue(
                jira_fetcher,
                issue_key,
                issue_dir,
                page_size=int(config["requests"]["page_size"]),
                download_attachments=bool(config["storage"]["download_attachments"]),
            )
            manifest["jira"] = {
                "issue_dir": issue_dir,
                "remote_link_count": len(remote_links),
            }

            confluence_manifest = export_confluence_content_with_manifest(
                confluence_fetcher,
                remote_links,
                issue_dir,
                confluence_base_url=config["confluence"]["base_url"],
                descendant_depth=int(config["storage"]["confluence_descendant_depth"]),
                include_descendants=bool(config["storage"]["include_confluence_descendants"]),
                download_attachments=bool(config["storage"]["download_attachments"]),
            )
            manifest["confluence"] = confluence_manifest
            logging.info("Writing export manifest.")
            finalize_run_manifest(manifest, "success")
            write_manifest(issue_dir, manifest)
        elif args.command == "create":
            manifest = build_run_manifest(args.ticket_file, "pending")
            issue_dir = os.path.join(config["storage"]["export_path"], "created", "pending")
            ensure_dir(issue_dir)
            file_handler = attach_file_logging(os.path.join(issue_dir, "export.log"))
            logging.info("Starting Jira issue creation from %s", args.ticket_file)

            created_dir, payload, response = create_jira_issue_from_file(
                jira_fetcher,
                args.ticket_file,
                config["storage"]["export_path"],
            )

            if created_dir != issue_dir:
                logging.getLogger().removeHandler(file_handler)
                file_handler.close()
                issue_dir = created_dir
                file_handler = attach_file_logging(os.path.join(issue_dir, "export.log"))

            manifest["issue_key"] = response.get("key", response.get("id", "created_issue"))
            manifest["jira"] = {
                "issue_dir": issue_dir,
                "ticket_file": os.path.abspath(args.ticket_file),
                "created_issue": response,
                "request_fields": sorted(payload.get("fields", {}).keys()),
            }
            manifest["confluence"] = {"linked_page_ids": [], "exported_pages": []}
            finalize_run_manifest(manifest, "success")
            write_manifest(issue_dir, manifest)
    except (ConfigError, ExporterError, OSError, yaml.YAMLError) as exc:
        logging.error("Export failed: %s", exc)
        if manifest is not None and issue_dir is not None:
            manifest["errors"].append(str(exc))
            finalize_run_manifest(manifest, "failed")
            write_manifest(issue_dir, manifest)
        sys.exit(1)
    finally:
        if file_handler is not None:
            logging.getLogger().removeHandler(file_handler)
            file_handler.close()


if __name__ == "__main__":
    main()
