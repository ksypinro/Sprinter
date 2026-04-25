"""HTTP client for Jira webhook management APIs."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

import requests

from fetcher import AuthConfig
from utils import resolve_url


class JiraWebhookAPIError(RuntimeError):
    """Raised when Jira webhook management fails."""


class JiraWebhookAPIClient:
    """Client for Jira admin and dynamic webhook APIs.

    Jira exposes two webhook management surfaces:
    - Admin webhooks: ``/rest/webhooks/1.0/webhook``. These are the practical
      fit for normal Jira administrator/API-token usage.
    - Dynamic app webhooks: ``/rest/api/3/webhook``. These are intended for
      Connect/OAuth apps and include the refresh operation.
    """

    def __init__(self, base_url: str, auth: AuthConfig, timeout_seconds: int = 30):
        """Initialize the client session."""

        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "sprinter-webhook-api/1.0",
            }
        )

        if auth.auth_type == "basic":
            if not auth.email:
                raise ValueError("Basic authentication requires an email.")
            self.session.auth = (auth.email, auth.token)
        elif auth.auth_type == "bearer":
            self.session.headers["Authorization"] = f"Bearer {auth.token}"
        else:
            raise ValueError(f"Unsupported auth type: {auth.auth_type}")

    def create_admin_webhook(
        self,
        name: str,
        url: str,
        events: Iterable[str],
        description: str = "",
        jql_filter: Optional[str] = None,
        exclude_body: bool = False,
        secret: Optional[str] = None,
        filters: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Create a Jira admin webhook."""

        payload = self.build_admin_webhook_payload(
            name=name,
            url=url,
            events=events,
            description=description,
            jql_filter=jql_filter,
            exclude_body=exclude_body,
            secret=secret,
            filters=filters,
        )
        return self._request_json("POST", "/rest/webhooks/1.0/webhook", json_payload=payload)

    def get_admin_webhooks(self) -> Any:
        """Return all Jira admin webhooks visible to the authenticated user."""

        return self._request_json("GET", "/rest/webhooks/1.0/webhook")

    def get_admin_webhook(self, webhook_id: int | str) -> Dict[str, Any]:
        """Return one Jira admin webhook by id."""

        return self._request_json("GET", f"/rest/webhooks/1.0/webhook/{webhook_id}")

    def update_admin_webhook(self, webhook_id: int | str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Update a Jira admin webhook by id."""

        return self._request_json("PUT", f"/rest/webhooks/1.0/webhook/{webhook_id}", json_payload=payload)

    def delete_admin_webhook(self, webhook_id: int | str) -> Dict[str, Any]:
        """Delete a Jira admin webhook by id."""

        self._request("DELETE", f"/rest/webhooks/1.0/webhook/{webhook_id}")
        return {"deleted": True, "webhook_id": str(webhook_id), "api": "admin"}

    def register_dynamic_webhooks(self, url: str, webhooks: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        """Register Jira dynamic app webhooks.

        This endpoint is only available to Connect and OAuth 2.0 app contexts.
        Basic API-token auth usually cannot use it.
        """

        return self._request_json(
            "POST",
            "/rest/api/3/webhook",
            json_payload={"url": url, "webhooks": list(webhooks)},
        )

    def get_dynamic_webhooks(self, start_at: int = 0, max_results: int = 100) -> Dict[str, Any]:
        """Return dynamic app webhooks registered by the calling app."""

        return self._request_json(
            "GET",
            "/rest/api/3/webhook",
            params={"startAt": start_at, "maxResults": max_results},
        )

    def delete_dynamic_webhooks(self, webhook_ids: Iterable[int | str]) -> Dict[str, Any]:
        """Delete dynamic app webhooks by id."""

        ids = [int(webhook_id) for webhook_id in webhook_ids]
        self._request("DELETE", "/rest/api/3/webhook", json_payload={"webhookIds": ids})
        return {"deleted": True, "webhook_ids": ids, "api": "dynamic"}

    def refresh_dynamic_webhooks(self, webhook_ids: Iterable[int | str]) -> Dict[str, Any]:
        """Extend the life of dynamic app webhooks by id."""

        ids = [int(webhook_id) for webhook_id in webhook_ids]
        return self._request_json("PUT", "/rest/api/3/webhook/refresh", json_payload={"webhookIds": ids})

    def build_admin_webhook_payload(
        self,
        name: str,
        url: str,
        events: Iterable[str],
        description: str = "",
        jql_filter: Optional[str] = None,
        exclude_body: bool = False,
        secret: Optional[str] = None,
        filters: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Build the JSON body accepted by Jira's admin webhook API."""

        event_list = [event.strip() for event in events if event and event.strip()]
        if not event_list:
            raise ValueError("At least one webhook event is required.")
        if filters and jql_filter:
            raise ValueError("Pass either filters or jql_filter, not both.")

        payload: Dict[str, Any] = {
            "name": name,
            "description": description,
            "url": url,
            "events": event_list,
            "excludeBody": exclude_body,
        }
        if filters:
            payload["filters"] = filters
        elif jql_filter:
            payload["filters"] = {"issue-related-events-section": jql_filter}
        if secret is not None:
            payload["secret"] = secret
        return payload

    def build_dynamic_webhook_details(self, events: Iterable[str], jql_filter: str) -> Dict[str, Any]:
        """Build one dynamic webhook registration item."""

        event_list = [event.strip() for event in events if event and event.strip()]
        if not event_list:
            raise ValueError("At least one webhook event is required.")
        if not jql_filter.strip():
            raise ValueError("Dynamic webhooks require a JQL filter.")
        return {"events": event_list, "jqlFilter": jql_filter}

    def _request_json(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_payload: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Send a request and parse a JSON response."""

        response = self._request(method, endpoint, params=params, json_payload=json_payload)
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise JiraWebhookAPIError(f"Jira returned non-JSON response for {response.url}: {response.text}") from exc

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """Send a Jira webhook API request and surface errors clearly."""

        response = self.session.request(
            method,
            resolve_url(self.base_url, endpoint),
            params=params,
            json=json_payload,
            timeout=self.timeout_seconds,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise JiraWebhookAPIError(
                f"Request failed for {response.url}: {response.status_code} {response.text}"
            ) from exc
        return response

