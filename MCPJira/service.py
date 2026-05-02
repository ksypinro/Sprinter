"""Service facade used by the MCP server.

This module wraps the existing Sprinter export and create workflows so they can
be reused from an MCP server without changing the current CLI behavior.
"""

import json
import logging
import os
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from main import (
    attach_file_logging,
    build_confluence_fetcher,
    build_jira_fetcher,
    build_run_manifest,
    configure_logging,
    detach_file_logging,
    export_confluence_content_with_manifest,
    export_jira_issue,
    finalize_run_manifest,
    load_config,
    write_manifest,
)
from utils import ensure_dir, parse_jira_url, sanitize_filename, write_json


class MCPJiraServiceError(RuntimeError):
    """Raised when the MCP service layer cannot complete a requested action."""


class SprinterService:
    """Thin service layer that exposes the existing workflows as methods.

    The class intentionally keeps business logic close to the current Sprinter
    implementation. The MCP server calls this facade so the CLI and MCP paths
    share the same behavior as much as possible.
    """

    def __init__(self, config_path: Optional[str] = None):
        """Initialize the service with an optional config override.

        Args:
            config_path: Explicit config path. When omitted, the service looks
                for ``SPRINTER_CONFIG`` and finally falls back to ``config.yaml``.
        """

        self.config_path = config_path or os.getenv("SPRINTER_CONFIG", "config.yaml")

    def _load_config(self) -> Dict[str, Any]:
        """Load the Sprinter configuration for this service instance."""

        return load_config(self.config_path)

    def _build_jira_fetcher(self, config: Dict[str, Any]):
        """Create the Jira client used by service operations."""

        return build_jira_fetcher(config)

    def _build_confluence_fetcher(self, config: Dict[str, Any]):
        """Create the Confluence client used by export operations."""

        return build_confluence_fetcher(config)

    def _configure_logging(self, config: Dict[str, Any]) -> None:
        """Configure logging using the same settings as the CLI workflow."""

        configure_logging(config["requests"]["log_level"])

    def _detach_handler(self, handler: Optional[logging.Handler]) -> None:
        """Remove a previously attached file handler if one exists."""

        detach_file_logging(handler)

    def _validate_ticket_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Validate that a Jira create-issue payload has the minimum shape.

        Args:
            payload: Candidate request payload supplied by an MCP client.

        Returns:
            Dict[str, Any]: The validated payload.

        Raises:
            MCPJiraServiceError: If the payload does not contain the required
                Jira create-issue structure.
        """

        if not isinstance(payload, dict):
            raise MCPJiraServiceError("Ticket payload must be a JSON object.")

        if "fields" not in payload and "update" not in payload:
            raise MCPJiraServiceError("Ticket payload must include at least 'fields' or 'update'.")

        fields = payload.get("fields", {})
        if fields and not isinstance(fields, dict):
            raise MCPJiraServiceError("'fields' must be a JSON object.")

        for field_name in ("project", "issuetype", "summary"):
            if "fields" in payload and field_name not in fields:
                raise MCPJiraServiceError(f"Ticket payload is missing required field: fields.{field_name}")

        return payload

    def _export_root(self, config: Dict[str, Any]) -> str:
        """Return the configured export root path."""

        return config["storage"]["export_path"]

    def _export_issue_dir(self, config: Dict[str, Any], issue_key: str) -> str:
        """Build the export directory for a Jira issue key."""

        return os.path.join(self._export_root(config), issue_key)

    def _created_issue_dir(self, config: Dict[str, Any], issue_key: str) -> str:
        """Build the artifact directory for a created issue."""

        return os.path.join(self._export_root(config), "created", sanitize_filename(str(issue_key)))

    def export_issue(self, ticket_url: str) -> Dict[str, Any]:
        """Export a Jira issue and linked Confluence content.

        Args:
            ticket_url: Jira issue URL to export.

        Returns:
            Dict[str, Any]: Small structured result suitable for an MCP tool
            response, including paths and resource URIs.

        Raises:
            MCPJiraServiceError: If config loading, URL parsing, or export
                execution fails.
        """

        config = self._load_config()
        self._configure_logging(config)
        jira_fetcher = self._build_jira_fetcher(config)
        confluence_fetcher = self._build_confluence_fetcher(config)

        jira_host = urlparse(config["jira"]["base_url"]).netloc
        issue_key = parse_jira_url(ticket_url, expected_host=jira_host)
        if not issue_key:
            raise MCPJiraServiceError("Could not extract a Jira issue key from the provided URL.")

        issue_dir = self._export_issue_dir(config, issue_key)
        ensure_dir(issue_dir)
        file_handler = attach_file_logging(os.path.join(issue_dir, "export.log"))
        manifest = build_run_manifest(ticket_url, issue_key)

        try:
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
            manifest["confluence"] = export_confluence_content_with_manifest(
                confluence_fetcher,
                remote_links,
                issue_dir,
                confluence_base_url=config["confluence"]["base_url"],
                descendant_depth=int(config["storage"]["confluence_descendant_depth"]),
                include_descendants=bool(config["storage"]["include_confluence_descendants"]),
                download_attachments=bool(config["storage"]["download_attachments"]),
            )
            finalize_run_manifest(manifest, "success")
            write_manifest(issue_dir, manifest)
        except Exception as exc:
            manifest["errors"].append(str(exc))
            finalize_run_manifest(manifest, "failed")
            write_manifest(issue_dir, manifest)
            raise MCPJiraServiceError(str(exc)) from exc
        finally:
            self._detach_handler(file_handler)

        return {
            "issue_key": issue_key,
            "issue_dir": os.path.abspath(issue_dir),
            "manifest_path": os.path.abspath(os.path.join(issue_dir, "export_manifest.json")),
            "log_path": os.path.abspath(os.path.join(issue_dir, "export.log")),
            "manifest_resource": self.export_manifest_uri(issue_key),
            "remote_link_count": manifest["jira"]["remote_link_count"],
            "linked_page_count": len(manifest["confluence"].get("linked_page_ids", [])),
            "exported_page_count": len(manifest["confluence"].get("exported_pages", [])),
        }

    def create_issue(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a Jira issue from a structured JSON payload.

        Args:
            payload: Jira create-issue payload.

        Returns:
            Dict[str, Any]: Small structured result suitable for an MCP tool
            response, including the created issue key and artifact paths.

        Raises:
            MCPJiraServiceError: If validation or Jira create-issue execution
                fails.
        """

        config = self._load_config()
        self._configure_logging(config)
        jira_fetcher = self._build_jira_fetcher(config)
        validated_payload = self._validate_ticket_payload(payload)

        pending_dir = os.path.join(self._export_root(config), "created", "pending")
        ensure_dir(pending_dir)
        pending_log = os.path.join(pending_dir, "export.log")
        file_handler = attach_file_logging(pending_log)
        manifest = build_run_manifest("mcp://jira_create_issue", "pending")

        try:
            response = jira_fetcher.create_issue(validated_payload)
            issue_key = response.get("key") or response.get("id") or "created_issue"
            issue_dir = self._created_issue_dir(config, str(issue_key))
            ensure_dir(issue_dir)

            # Switch logging to the final issue directory once the key exists.
            self._detach_handler(file_handler)
            file_handler = attach_file_logging(os.path.join(issue_dir, "export.log"))

            write_json(os.path.join(issue_dir, "ticket_request.json"), validated_payload)
            write_json(os.path.join(issue_dir, "ticket_response.json"), response)
            write_json(
                os.path.join(issue_dir, "ticket_source.json"),
                {"source": "mcp", "config_path": os.path.abspath(self.config_path)},
            )

            manifest["issue_key"] = str(issue_key)
            manifest["jira"] = {
                "issue_dir": issue_dir,
                "created_issue": response,
                "request_fields": sorted(validated_payload.get("fields", {}).keys()),
            }
            manifest["confluence"] = {"linked_page_ids": [], "exported_pages": []}
            finalize_run_manifest(manifest, "success")
            write_manifest(issue_dir, manifest)
        except Exception as exc:
            manifest["errors"].append(str(exc))
            finalize_run_manifest(manifest, "failed")
            write_manifest(pending_dir, manifest)
            raise MCPJiraServiceError(str(exc)) from exc
        finally:
            self._detach_handler(file_handler)

        return {
            "issue_key": str(issue_key),
            "issue_dir": os.path.abspath(issue_dir),
            "response_path": os.path.abspath(os.path.join(issue_dir, "ticket_response.json")),
            "manifest_path": os.path.abspath(os.path.join(issue_dir, "export_manifest.json")),
            "response_resource": self.created_response_uri(str(issue_key)),
        }

    def read_export_manifest(self, issue_key: str) -> Dict[str, Any]:
        """Read an exported issue manifest from disk."""

        return self._read_json(os.path.join(self._export_root(self._load_config()), issue_key, "export_manifest.json"))

    def read_created_issue_response(self, issue_key: str) -> Dict[str, Any]:
        """Read a created-issue response artifact from disk."""

        return self._read_json(
            os.path.join(self._export_root(self._load_config()), "created", issue_key, "ticket_response.json")
        )

    def export_manifest_uri(self, issue_key: str) -> str:
        """Build the MCP resource URI for an exported issue manifest."""

        return f"sprinter://exports/{issue_key}/manifest"

    def created_response_uri(self, issue_key: str) -> str:
        """Build the MCP resource URI for a created issue response."""

        return f"sprinter://created/{issue_key}/response"

    def _read_json(self, path: str) -> Dict[str, Any]:
        """Read a JSON file from disk and surface friendly service errors."""

        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError as exc:
            raise MCPJiraServiceError(f"Artifact not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise MCPJiraServiceError(f"Artifact is not valid JSON: {path}") from exc
