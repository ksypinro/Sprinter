"""Small helpers for URL parsing, filesystem naming, and JSON/text output."""

import json
import os
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, unquote_plus, urljoin, urlparse


ISSUE_KEY_PATTERN = re.compile(r"([A-Z][A-Z0-9]+-[0-9]+)")
PAGE_ID_PATTERNS = (
    re.compile(r"/pages/(\d+)(?:/|$)"),
    re.compile(r"/spaces/[^/]+/pages/(\d+)(?:/|$)"),
)
DISPLAY_PATH_PATTERN = re.compile(r"/display/([^/]+)/([^/?#]+)")


def parse_jira_url(url: str, expected_host: Optional[str] = None) -> Optional[str]:
    """Extract the Jira issue key from a Jira URL.

    Args:
        url: Jira URL to inspect.
        expected_host: Optional host restriction. When provided, URLs from
        other hosts are ignored.

    Returns:
        Optional[str]: Parsed issue key, or ``None`` if the URL does not match
        the expected Jira patterns.
    """
    parsed_url = urlparse(url)
    if expected_host and parsed_url.netloc and parsed_url.netloc != expected_host:
        return None

    match = ISSUE_KEY_PATTERN.search(parsed_url.path)
    if match:
        return match.group(1)
    return None


def extract_confluence_page_id(url: str, expected_host: Optional[str] = None) -> Optional[str]:
    """Extract a Confluence page id from common Cloud URL formats.

    Args:
        url: Confluence URL to inspect.
        expected_host: Optional host restriction. When provided, URLs from
        other hosts are ignored.

    Returns:
        Optional[str]: Parsed page id, or ``None`` when no supported page-id
        pattern is present.
    """
    parsed_url = urlparse(url)
    if expected_host and parsed_url.netloc and parsed_url.netloc != expected_host:
        return None

    query_page_id = parse_qs(parsed_url.query).get("pageId")
    if query_page_id:
        return query_page_id[0]

    for pattern in PAGE_ID_PATTERNS:
        match = pattern.search(parsed_url.path)
        if match:
            return match.group(1)
    return None


def extract_confluence_space_title(url: str, expected_host: Optional[str] = None) -> Optional[tuple[str, str]]:
    """Extract a Confluence space key and title from legacy display URLs.

    Args:
        url: Confluence URL to inspect.
        expected_host: Optional host restriction. When provided, URLs from
        other hosts are ignored.

    Returns:
        Optional[tuple[str, str]]: ``(space_key, title)`` for legacy display
        URLs, or ``None`` when the URL does not match that format.
    """
    parsed_url = urlparse(url)
    if expected_host and parsed_url.netloc and parsed_url.netloc != expected_host:
        return None

    match = DISPLAY_PATH_PATTERN.search(parsed_url.path)
    if not match:
        return None

    return match.group(1), unquote_plus(match.group(2))


def is_same_host(url: str, base_url: str) -> bool:
    """Check whether a candidate URL belongs to the same host as a base URL.

    Args:
        url: Candidate absolute URL.
        base_url: Reference base URL from configuration.

    Returns:
        bool: ``True`` when both URLs have the same network location.
    """

    parsed_url = urlparse(url)
    parsed_base = urlparse(base_url)
    return bool(parsed_url.netloc and parsed_base.netloc and parsed_url.netloc == parsed_base.netloc)


def ensure_dir(path: str) -> None:
    """Create a directory if it does not already exist.

    Args:
        path: Directory path to create.
    """
    os.makedirs(path, exist_ok=True)


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename for local storage.

    Args:
        filename: Original filename that may contain characters unsupported by
        the local filesystem.

    Returns:
        str: Filesystem-safe filename, defaulting to ``unnamed`` when the
        result would otherwise be empty.
    """
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", filename).strip()
    return cleaned or "unnamed"


def attachment_filename(attachment_id: Any, original_name: str) -> str:
    """Build a collision-resistant attachment filename.

    Args:
        attachment_id: Stable remote attachment identifier.
        original_name: Original attachment filename from Jira or Confluence.

    Returns:
        str: Sanitized filename prefixed with the attachment id.
    """
    safe_name = sanitize_filename(original_name)
    safe_id = sanitize_filename(str(attachment_id))
    return f"{safe_id}_{safe_name}"


def unique_path(path: str) -> str:
    """Return a non-conflicting path by appending a numeric suffix when needed.

    Args:
        path: Desired output path.

    Returns:
        str: Original path when unused, otherwise a suffixed variant such as
        ``file_1.txt``.
    """
    candidate = Path(path)
    if not candidate.exists():
        return str(candidate)

    stem = candidate.stem
    suffix = candidate.suffix
    parent = candidate.parent
    counter = 1
    while True:
        next_candidate = parent / f"{stem}_{counter}{suffix}"
        if not next_candidate.exists():
            return str(next_candidate)
        counter += 1


def write_json(path: str, data: Any) -> None:
    """Serialize JSON data using UTF-8 and stable indentation.

    Args:
        path: Destination file path.
        data: JSON-serializable object to persist.
    """

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)


def write_text(path: str, text: str) -> None:
    """Write plain text content to disk using UTF-8 encoding.

    Args:
        path: Destination file path.
        text: Text content to write.
    """

    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def resolve_url(base_url: str, url: str) -> str:
    """Resolve a potentially relative URL against a base URL.

    This helper preserves Atlassian context paths such as ``/wiki`` when a
    leading slash is used in API or download links.

    Args:
        base_url: Configured service base URL.
        url: Relative or absolute URL to normalize.

    Returns:
        str: Absolute URL ready for requests.
    """
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("/"):
        return f"{base_url.rstrip('/')}{url}"
    return urljoin(base_url.rstrip("/") + "/", url)
