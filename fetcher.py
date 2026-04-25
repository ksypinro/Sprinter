"""HTTP client layer for Jira and Confluence export operations.

The classes in this module encapsulate authentication, retry behavior,
pagination helpers, and service-specific endpoints used by the exporter.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from utils import resolve_url


class ExporterError(RuntimeError):
    """Raised when a remote API request fails in a way the exporter surfaces."""

    pass


@dataclass
class AuthConfig:
    """Normalized authentication settings for a remote Atlassian service.

    Attributes:
        auth_type: Authentication mode, currently ``bearer`` or ``basic``.
        token: Personal access token or API token.
        email: Email address required for basic auth, otherwise ``None``.
    """

    auth_type: str
    token: str
    email: Optional[str] = None


class BaseFetcher:
    """Shared HTTP functionality used by Jira and Confluence clients.

    This base class owns session configuration, retries, authentication,
    downloads, and both offset-based and cursor-based pagination helpers.
    """

    def __init__(self, base_url: str, auth: AuthConfig, timeout_seconds: int = 30, retries: int = 3):
        """Initialize the HTTP session and authentication strategy.

        Args:
            base_url: Service base URL, such as Jira or Confluence root.
            auth: Normalized authentication configuration.
            timeout_seconds: Per-request timeout.
            retries: Retry count for transient failures.
        """

        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "sprinter-exporter/1.0",
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

        retry_policy = Retry(
            total=retries,
            connect=retries,
            read=retries,
            status=retries,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_policy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _request(self, endpoint: str, params: Optional[Dict] = None, stream: bool = False, headers: Optional[Dict] = None) -> requests.Response:
        """Perform a GET request and convert HTTP failures into exporter errors.

        Args:
            endpoint: Relative or absolute endpoint to call.
            params: Optional query-string parameters.
            stream: Whether the response should be streamed for downloads.
            headers: Optional request-specific headers.

        Returns:
            requests.Response: Successful HTTP response object.

        Raises:
            ExporterError: If the remote service returns an unsuccessful
            response.
        """

        url = resolve_url(self.base_url, endpoint)
        response = self.session.get(url, params=params, timeout=self.timeout_seconds, stream=stream, headers=headers)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise ExporterError(f"Request failed for {url}: {response.status_code} {response.text}") from exc
        return response

    def _get_json(self, endpoint: str, params: Optional[Dict] = None) -> Tuple[Dict, requests.structures.CaseInsensitiveDict]:
        """Fetch a JSON endpoint and return both payload and response headers.

        Args:
            endpoint: Relative or absolute endpoint to call.
            params: Optional query-string parameters.

        Returns:
            Tuple[Dict, CaseInsensitiveDict]: Parsed JSON payload and response
            headers, which are useful for pagination.
        """

        response = self._request(endpoint, params=params)
        return response.json(), response.headers

    def _download(self, url: str, dest_path: str) -> None:
        """Stream a remote binary resource to a local file.

        Args:
            url: Relative or absolute resource URL.
            dest_path: Local filesystem path for the downloaded file.
        """

        # Clear Accept header for binary downloads to avoid issues with some servers
        response = self._request(url, stream=True, headers={"Accept": "*/*"})
        with open(dest_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    handle.write(chunk)

    def _paginate_offset(self, endpoint: str, item_key: str, params: Optional[Dict] = None, page_size: int = 100) -> List[Dict]:
        """Collect all items from an offset-based paginated endpoint.

        Args:
            endpoint: Relative endpoint to call.
            item_key: JSON field containing page items.
            params: Optional base query parameters.
            page_size: Number of items requested per page.

        Returns:
            List[Dict]: Flattened list of all retrieved items.
        """

        results: List[Dict] = []
        start_at = 0
        base_params = dict(params or {})

        while True:
            page_params = {**base_params, "startAt": start_at, "maxResults": page_size}
            payload, _ = self._get_json(endpoint, params=page_params)
            items = payload.get(item_key, [])
            results.extend(items)

            if payload.get("isLast") is True:
                break

            total = payload.get("total")
            if total is not None and start_at + len(items) >= total:
                break

            if not items:
                break

            start_at += len(items)

        return results

    def _paginate_cursor(self, endpoint: str, item_key: str = "results", params: Optional[Dict] = None) -> List[Dict]:
        """Collect all items from a cursor- or next-link-based endpoint.

        Args:
            endpoint: Relative endpoint to call.
            item_key: JSON field containing page items.
            params: Optional base query parameters.

        Returns:
            List[Dict]: Flattened list of all retrieved items.
        """

        results: List[Dict] = []
        next_endpoint = endpoint
        next_params = dict(params or {})

        while True:
            payload, headers = self._get_json(next_endpoint, params=next_params)
            results.extend(payload.get(item_key, []))

            next_link = self._extract_next_link(payload, headers)
            if next_link:
                next_endpoint = next_link
                next_params = {}
                continue

            cursor = payload.get("meta", {}).get("cursor")
            if payload.get("meta", {}).get("hasMore") and cursor:
                next_params = dict(params or {})
                next_params["cursor"] = cursor
                next_endpoint = endpoint
                continue

            break

        return results

    def _extract_next_link(self, payload: Dict, headers: requests.structures.CaseInsensitiveDict) -> Optional[str]:
        """Extract the next-page URL from payload metadata or Link headers.

        Args:
            payload: Parsed JSON response body.
            headers: Response headers returned by the API.

        Returns:
            Optional[str]: Absolute or resolved next-page URL, or ``None`` if
            the response does not advertise another page.
        """

        payload_next = payload.get("_links", {}).get("next")
        if payload_next:
            return resolve_url(self.base_url, payload_next)

        link_header = headers.get("Link")
        if not link_header:
            return None

        for part in link_header.split(","):
            section = part.strip()
            if 'rel="next"' in section:
                start = section.find("<")
                end = section.find(">")
                if start != -1 and end != -1:
                    return urljoin(self.base_url, section[start + 1 : end])
        return None


class JiraFetcher(BaseFetcher):
    """Jira-specific API client used by the export workflow."""

    def create_issue(self, payload: Dict) -> Dict:
        """Create a Jira issue using the supplied request payload.

        Args:
            payload: JSON payload accepted by Jira's create issue endpoint.

        Returns:
            Dict: Jira response containing the created issue identifiers.
        """

        response = self.session.post(
            resolve_url(self.base_url, "/rest/api/3/issue"),
            json=payload,
            timeout=self.timeout_seconds,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise ExporterError(
                f"Request failed for {response.url}: {response.status_code} {response.text}"
            ) from exc
        return response.json()

    def fetch_issue(self, issue_key: str) -> Dict:
        """Fetch the full Jira issue payload for one issue key."""

        payload, _ = self._get_json(
            f"/rest/api/3/issue/{issue_key}",
            params={"fields": "*all"},
        )
        return payload

    def fetch_comments(self, issue_key: str, page_size: int = 100) -> List[Dict]:
        """Fetch all comments for a Jira issue using offset pagination."""

        return self._paginate_offset(f"/rest/api/3/issue/{issue_key}/comment", item_key="comments", page_size=page_size)

    def fetch_worklogs(self, issue_key: str, page_size: int = 100) -> List[Dict]:
        """Fetch all worklogs for a Jira issue using offset pagination."""

        return self._paginate_offset(f"/rest/api/3/issue/{issue_key}/worklog", item_key="worklogs", page_size=page_size)

    def fetch_changelog(self, issue_key: str, page_size: int = 100) -> List[Dict]:
        """Fetch the complete changelog history for a Jira issue."""

        return self._paginate_offset(f"/rest/api/3/issue/{issue_key}/changelog", item_key="values", page_size=page_size)

    def fetch_remote_links(self, issue_key: str) -> List[Dict]:
        """Fetch remote links attached to a Jira issue."""

        payload, _ = self._get_json(f"/rest/api/2/issue/{issue_key}/remotelink")
        return payload

    def download_attachment(self, url: str, dest_path: str) -> None:
        """Download a Jira attachment binary to the local filesystem."""

        self._download(url, dest_path)


class ConfluenceFetcher(BaseFetcher):
    """Confluence-specific API client used by the export workflow."""

    def fetch_page(self, page_id: str) -> Dict:
        """Fetch a Confluence page with storage body and metadata expansions."""

        payload, _ = self._get_json(
            f"/api/v2/pages/{page_id}",
            params={
                "body-format": "storage",
                "include-labels": "true",
                "include-properties": "true",
                "include-version": "true",
            },
        )
        return payload

    def fetch_page_attachments(self, page_id: str) -> List[Dict]:
        """Fetch all attachments belonging to a Confluence page."""

        return self._paginate_cursor(f"/api/v2/pages/{page_id}/attachments")

    def fetch_page_footer_comments(self, page_id: str) -> List[Dict]:
        """Fetch all footer comments for a Confluence page."""

        return self._paginate_cursor(
            f"/api/v2/pages/{page_id}/footer-comments",
            params={"body-format": "storage"},
        )

    def fetch_page_inline_comments(self, page_id: str) -> List[Dict]:
        """Fetch all inline comments for a Confluence page."""

        return self._paginate_cursor(
            f"/api/v2/pages/{page_id}/inline-comments",
            params={"body-format": "storage"},
        )

    def fetch_page_ancestors(self, page_id: str) -> List[Dict]:
        """Fetch the ancestor chain for a Confluence page."""

        return self._paginate_cursor(f"/api/v2/pages/{page_id}/ancestors")

    def fetch_page_descendants(self, page_id: str, depth: int = 5) -> List[Dict]:
        """Fetch descendant pages up to a configured traversal depth."""

        return self._paginate_cursor(
            f"/api/v2/pages/{page_id}/descendants",
            params={"depth": depth},
        )

    def search_page_by_space_and_title(self, space_key: str, title: str) -> Optional[str]:
        """Resolve a page id from a Confluence space key and page title.

        This is used as a fallback for legacy Confluence display URLs that do
        not contain a page id directly.
        """

        cql = f'type=page and space="{space_key}" and title="{title.replace(chr(34), r"\\\"")}"'
        payload, _ = self._get_json(
            "/rest/api/content/search",
            params={"cql": cql, "limit": 2},
        )
        results = payload.get("results", [])
        if not results:
            return None
        return results[0].get("id")

    def download_attachment(self, url: str, dest_path: str) -> None:
        """Download a Confluence attachment binary to the local filesystem."""

        self._download(resolve_url(self.base_url, url), dest_path)
