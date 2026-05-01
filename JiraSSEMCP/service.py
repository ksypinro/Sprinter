"""Independent service facade for the SSE MCP server."""

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


class JiraSSEMCPError(RuntimeError):
    """Raised when the SSE MCP service cannot complete a request."""


class JiraSSEService:
    """SSE-oriented Sprinter service facade.

    This package has its own adapter and does not import the existing stdio or
    Streamable HTTP MCP service classes. It only reuses the shared Sprinter
    core modules that already perform Jira and Confluence work.
    """

    def __init__(self, config_path: str = "config.yaml"):
        """Initialize the service with a concrete Sprinter config path."""

        self.config_path = config_path

    def server_info(self) -> Dict[str, Any]:
        """Return non-secret runtime metadata for client diagnostics."""

        return {
            "name": "JiraSSEMCP",
            "transport": "sse",
            "config_path": os.path.abspath(self.config_path),
            "resources": {
                "export_manifest": "jirasse://exports/{issue_key}/manifest",
                "created_response": "jirasse://created/{issue_key}/response",
            },
        }

    def export_issue(self, ticket_url: str) -> Dict[str, Any]:
        """Export a Jira issue and linked Confluence pages through SSE MCP."""

        config = self._load_config()
        self._configure_logging(config)
        jira_fetcher = self._build_jira_fetcher(config)
        confluence_fetcher = self._build_confluence_fetcher(config)

        jira_host = urlparse(config["jira"]["base_url"]).netloc
        issue_key = parse_jira_url(ticket_url, expected_host=jira_host)
        if not issue_key:
            raise JiraSSEMCPError("Could not extract a Jira issue key from the provided URL.")

        issue_dir = os.path.join(self._export_root(config), issue_key)
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
            raise JiraSSEMCPError(str(exc)) from exc
        finally:
            self._detach_handler(file_handler)

        return {
            "issue_key": issue_key,
            "transport": "sse",
            "issue_dir": os.path.abspath(issue_dir),
            "manifest_path": os.path.abspath(os.path.join(issue_dir, "export_manifest.json")),
            "log_path": os.path.abspath(os.path.join(issue_dir, "export.log")),
            "manifest_resource": self.export_manifest_uri(issue_key),
            "remote_link_count": manifest["jira"]["remote_link_count"],
            "linked_page_count": len(manifest["confluence"].get("linked_page_ids", [])),
            "exported_page_count": len(manifest["confluence"].get("exported_pages", [])),
        }

    def create_issue(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a Jira issue from a structured payload through SSE MCP."""

        config = self._load_config()
        self._configure_logging(config)
        jira_fetcher = self._build_jira_fetcher(config)
        validated_payload = self._validate_ticket_payload(payload)

        pending_dir = os.path.join(self._export_root(config), "created", "pending")
        ensure_dir(pending_dir)
        file_handler = attach_file_logging(os.path.join(pending_dir, "export.log"))
        manifest = build_run_manifest("mcp+sse://jira_create_issue", "pending")
        issue_dir = pending_dir

        try:
            response = jira_fetcher.create_issue(validated_payload)
            issue_key = str(response.get("key") or response.get("id") or "created_issue")
            issue_dir = self._created_issue_dir(config, issue_key)
            ensure_dir(issue_dir)

            self._detach_handler(file_handler)
            file_handler = attach_file_logging(os.path.join(issue_dir, "export.log"))

            write_json(os.path.join(issue_dir, "ticket_request.json"), validated_payload)
            write_json(os.path.join(issue_dir, "ticket_response.json"), response)
            write_json(
                os.path.join(issue_dir, "ticket_source.json"),
                {
                    "source": "mcp",
                    "transport": "sse",
                    "config_path": os.path.abspath(self.config_path),
                },
            )

            manifest["issue_key"] = issue_key
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
            write_manifest(issue_dir, manifest)
            raise JiraSSEMCPError(str(exc)) from exc
        finally:
            self._detach_handler(file_handler)

        return {
            "issue_key": issue_key,
            "transport": "sse",
            "issue_dir": os.path.abspath(issue_dir),
            "response_path": os.path.abspath(os.path.join(issue_dir, "ticket_response.json")),
            "manifest_path": os.path.abspath(os.path.join(issue_dir, "export_manifest.json")),
            "response_resource": self.created_response_uri(issue_key),
        }

    def read_export_manifest(self, issue_key: str) -> Dict[str, Any]:
        """Read an exported issue manifest from disk."""

        config = self._load_config()
        return self._read_json(os.path.join(self._export_root(config), issue_key, "export_manifest.json"))

    def read_created_issue_response(self, issue_key: str) -> Dict[str, Any]:
        """Read a created-issue response artifact from disk."""

        config = self._load_config()
        return self._read_json(os.path.join(self._export_root(config), "created", issue_key, "ticket_response.json"))

    def export_manifest_uri(self, issue_key: str) -> str:
        """Return the resource URI for an exported issue manifest."""

        return f"jirasse://exports/{issue_key}/manifest"

    def created_response_uri(self, issue_key: str) -> str:
        """Return the resource URI for a created issue response."""

        return f"jirasse://created/{issue_key}/response"

    def _load_config(self) -> Dict[str, Any]:
        """Load Sprinter config for service calls."""

        return load_config(self.config_path)

    def _configure_logging(self, config: Dict[str, Any]) -> None:
        """Configure logging from the shared Sprinter config."""

        configure_logging(config["requests"]["log_level"])

    def _build_jira_fetcher(self, config: Dict[str, Any]):
        """Build the Jira fetcher used by export and create calls."""

        return build_jira_fetcher(config)

    def _build_confluence_fetcher(self, config: Dict[str, Any]):
        """Build the Confluence fetcher used by export calls."""

        return build_confluence_fetcher(config)

    def _export_root(self, config: Dict[str, Any]) -> str:
        """Return the configured artifact root."""

        return config["storage"]["export_path"]

    def _created_issue_dir(self, config: Dict[str, Any], issue_key: str) -> str:
        """Build the created-issue artifact directory."""

        return os.path.join(self._export_root(config), "created", sanitize_filename(issue_key))

    def _detach_handler(self, handler: Optional[logging.Handler]) -> None:
        """Detach and close a per-run file logger."""

        detach_file_logging(handler)

    def _validate_ticket_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Validate the minimum Jira create-issue payload shape."""

        if not isinstance(payload, dict):
            raise JiraSSEMCPError("Ticket payload must be a JSON object.")

        if "fields" not in payload and "update" not in payload:
            raise JiraSSEMCPError("Ticket payload must include at least 'fields' or 'update'.")

        fields = payload.get("fields", {})
        if fields and not isinstance(fields, dict):
            raise JiraSSEMCPError("'fields' must be a JSON object.")

        if "fields" in payload:
            for field_name in ("project", "issuetype", "summary"):
                if field_name not in fields:
                    raise JiraSSEMCPError(f"Ticket payload is missing required field: fields.{field_name}")

        return payload

    def _read_json(self, path: str) -> Dict[str, Any]:
        """Read JSON from disk and convert common failures to service errors."""

        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError as exc:
            raise JiraSSEMCPError(f"Artifact not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise JiraSSEMCPError(f"Artifact is not valid JSON: {path}") from exc
