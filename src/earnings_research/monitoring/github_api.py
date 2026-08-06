"""Minimal GitHub REST client for artifact reads and Issue notification."""

import io
import json
import re
import shutil
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

from earnings_research.monitoring.persistence import BundleError, VerifiedMonitorBundle, verify_bundle


class GitHubAPIError(RuntimeError):
    """Raised when the bounded GitHub API operation fails."""


class GitHubAPIClient:
    """Repository-scoped client with an injectable transport for unit tests."""

    def __init__(
        self,
        *,
        repository: str,
        token: str,
        api_url: str = "https://api.github.com",
        opener: Optional[Callable] = None,
    ) -> None:
        if repository.count("/") != 1:
            raise ValueError("repository must use owner/name format")
        self.repository = repository
        self.token = token
        self.api_url = api_url.rstrip("/")
        self._opener = opener or urllib.request.urlopen

    def fetch_previous_bundle(
        self, *, monitor_target_id: str, output_dir: Path
    ) -> Optional[VerifiedMonitorBundle]:
        """Download the unique highest-version artifact and verify its identity."""
        artifacts = self._list_all_artifacts()
        pattern = re.compile(
            r"^ers-monitor-state-%s-v([1-9][0-9]*)-([A-Za-z0-9._-]+)$"
            % re.escape(monitor_target_id)
        )
        candidates = []
        for artifact in artifacts:
            match = pattern.fullmatch(str(artifact.get("name", "")))
            workflow_run = artifact.get("workflow_run") or {}
            if (
                match
                and not artifact.get("expired", False)
                and workflow_run.get("head_branch") == "main"
            ):
                candidates.append((int(match.group(1)), match.group(2), artifact))
        if not candidates:
            return None
        highest = max(version for version, _, _ in candidates)
        tails = [item for item in candidates if item[0] == highest]
        if len(tails) != 1:
            raise BundleError("multiple GitHub artifacts claim the same current checkpoint version")
        version, run_id, artifact = tails[0]
        archive = self._request_bytes("GET", "/repos/%s/actions/artifacts/%s/zip" % (self.repository, artifact["id"]))
        output_dir = Path(output_dir)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)
        _extract_zip_safely(archive, output_dir)
        bundle_dir = _bundle_root(output_dir)
        bundle = verify_bundle(
            bundle_dir,
            expected_target_id=monitor_target_id,
            expected_checkpoint_version=version,
        )
        if bundle.manifest.monitor_run_id != run_id:
            raise BundleError("artifact name run ID does not match verified manifest")
        return bundle

    def find_open_issue(self, dedup_key: str) -> Optional[Dict]:
        marker = "<!-- ers-monitor-dedup:%s -->" % dedup_key
        issues = self._request_json("GET", "/repos/%s/issues?state=open&per_page=100" % self.repository)
        matches = [item for item in issues if marker in str(item.get("body") or "") and "pull_request" not in item]
        if len(matches) > 1:
            raise GitHubAPIError("multiple open Issues share one monitor dedup key")
        return matches[0] if matches else None

    def create_issue(self, title: str, body: str) -> Dict:
        return self._request_json("POST", "/repos/%s/issues" % self.repository, {"title": title, "body": body})

    def comment_issue(self, issue_number: int, body: str) -> Dict:
        return self._request_json(
            "POST",
            "/repos/%s/issues/%s/comments" % (self.repository, issue_number),
            {"body": body},
        )

    def _list_all_artifacts(self) -> List[Dict]:
        artifacts = []
        for page in range(1, 101):
            payload = self._request_json(
                "GET",
                "/repos/%s/actions/artifacts?per_page=100&page=%s" % (self.repository, page),
            )
            page_items = payload.get("artifacts", [])
            if not isinstance(page_items, list):
                raise GitHubAPIError("artifact listing response is malformed")
            artifacts.extend(page_items)
            if len(page_items) < 100:
                return artifacts
        raise GitHubAPIError("artifact listing exceeded bounded pagination")

    def _request_json(self, method: str, path: str, payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        response = self._open(method, path, data)
        try:
            return json.loads(response.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise GitHubAPIError("GitHub API returned malformed JSON") from exc

    def _request_bytes(self, method: str, path: str) -> bytes:
        return self._open(method, path, None)

    def _open(self, method: str, path: str, data: Optional[bytes]) -> bytes:
        request = urllib.request.Request(
            self.api_url + path,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer %s" % self.token,
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "ers-monitor-v1",
            },
        )
        try:
            with self._opener(request) as response:
                return response.read()
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            raise GitHubAPIError("GitHub API request failed") from exc


def _extract_zip_safely(archive: bytes, output_dir: Path) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            root = output_dir.resolve()
            for member in zipped.infolist():
                destination = (output_dir / member.filename).resolve()
                if root != destination and root not in destination.parents:
                    raise BundleError("artifact archive contains an unsafe path")
            zipped.extractall(output_dir)
    except zipfile.BadZipFile as exc:
        raise BundleError("artifact archive is not a valid zip file") from exc


def _bundle_root(output_dir: Path) -> Path:
    if (output_dir / "manifest.json").is_file():
        return output_dir
    directories = [path for path in output_dir.iterdir() if path.is_dir()]
    if len(directories) == 1 and (directories[0] / "manifest.json").is_file():
        return directories[0]
    raise BundleError("downloaded artifact does not contain one bundle root")
