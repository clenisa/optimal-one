"""
GitHub Client for CI Boss Agent.

This module provides GitHub REST API integration for fetching commit/PR
metadata and posting comments. All API calls require GITHUB_TOKEN env var.

Environment Variables:
    GITHUB_TOKEN: Personal Access Token with 'repo' scope.
"""

import os
import logging
from typing import Optional, List, Dict, Any, TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from .graph import CIState

logger = logging.getLogger(__name__)

# GitHub API base URL
GITHUB_API_BASE = "https://api.github.com"

# Maximum length for log snippets in comments
MAX_LOG_SNIPPET_LENGTH = 2000


def _get_github_token() -> Optional[str]:
    """Get GitHub token from environment.
    
    Returns:
        The GitHub token if set, None otherwise.
    """
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        logger.warning(
            "GITHUB_TOKEN not set. GitHub integration will be skipped. "
            "Set GITHUB_TOKEN env var to enable GitHub features."
        )
    return token


def _get_headers(token: str) -> Dict[str, str]:
    """Build headers for GitHub API requests.
    
    Args:
        token: GitHub Personal Access Token.
        
    Returns:
        Headers dict for requests.
    """
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _parse_repo(repo: str) -> tuple[str, str]:
    """Parse owner/repo string into components.
    
    Args:
        repo: Repository in "owner/repo" format.
        
    Returns:
        Tuple of (owner, repo_name).
        
    Raises:
        ValueError: If repo format is invalid.
    """
    if "/" not in repo:
        raise ValueError(f"Invalid repo format: {repo}. Expected 'owner/repo'.")
    parts = repo.split("/", 1)
    return parts[0], parts[1]


def fetch_pr_details(repo: str, pr_number: int, token: str) -> Optional[Dict[str, Any]]:
    """Fetch pull request details from GitHub.
    
    Args:
        repo: Repository in "owner/repo" format.
        pr_number: Pull request number.
        token: GitHub token.
        
    Returns:
        PR details dict or None if request fails.
    """
    try:
        owner, repo_name = _parse_repo(repo)
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo_name}/pulls/{pr_number}"
        
        response = requests.get(url, headers=_get_headers(token), timeout=30)
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(
                f"Failed to fetch PR #{pr_number} from {repo}: "
                f"HTTP {response.status_code} - {response.text[:200]}"
            )
            return None
            
    except requests.RequestException as e:
        logger.error(f"Request error fetching PR: {e}")
        return None
    except ValueError as e:
        logger.error(f"Error parsing repo: {e}")
        return None


def fetch_pr_files(repo: str, pr_number: int, token: str) -> Optional[List[str]]:
    """Fetch list of changed files in a pull request.
    
    Args:
        repo: Repository in "owner/repo" format.
        pr_number: Pull request number.
        token: GitHub token.
        
    Returns:
        List of changed file paths or None if request fails.
    """
    try:
        owner, repo_name = _parse_repo(repo)
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo_name}/pulls/{pr_number}/files"
        
        # Paginate through all files (up to a reasonable limit)
        all_files: List[str] = []
        page = 1
        per_page = 100
        
        while page <= 10:  # Max 1000 files
            params = {"page": page, "per_page": per_page}
            response = requests.get(
                url, headers=_get_headers(token), params=params, timeout=30
            )
            
            if response.status_code == 200:
                files_data = response.json()
                if not files_data:
                    break
                all_files.extend([f["filename"] for f in files_data])
                if len(files_data) < per_page:
                    break
                page += 1
            else:
                logger.error(
                    f"Failed to fetch files for PR #{pr_number}: "
                    f"HTTP {response.status_code} - {response.text[:200]}"
                )
                return None
                
        return all_files
        
    except requests.RequestException as e:
        logger.error(f"Request error fetching PR files: {e}")
        return None
    except ValueError as e:
        logger.error(f"Error parsing repo: {e}")
        return None


def fetch_commit_files(repo: str, commit_sha: str, token: str) -> Optional[List[str]]:
    """Fetch list of changed files in a commit.
    
    Args:
        repo: Repository in "owner/repo" format.
        commit_sha: Commit SHA.
        token: GitHub token.
        
    Returns:
        List of changed file paths or None if request fails.
    """
    try:
        owner, repo_name = _parse_repo(repo)
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo_name}/commits/{commit_sha}"
        
        response = requests.get(url, headers=_get_headers(token), timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            files = data.get("files", [])
            return [f["filename"] for f in files]
        else:
            logger.error(
                f"Failed to fetch commit {commit_sha}: "
                f"HTTP {response.status_code} - {response.text[:200]}"
            )
            return None
            
    except requests.RequestException as e:
        logger.error(f"Request error fetching commit: {e}")
        return None
    except ValueError as e:
        logger.error(f"Error parsing repo: {e}")
        return None


def fetch_commit_details(repo: str, commit_sha: str, token: str) -> Optional[Dict[str, Any]]:
    """Fetch commit details from GitHub.
    
    Args:
        repo: Repository in "owner/repo" format.
        commit_sha: Commit SHA.
        token: GitHub token.
        
    Returns:
        Commit details dict or None if request fails.
    """
    try:
        owner, repo_name = _parse_repo(repo)
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo_name}/commits/{commit_sha}"
        
        response = requests.get(url, headers=_get_headers(token), timeout=30)
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(
                f"Failed to fetch commit {commit_sha}: "
                f"HTTP {response.status_code} - {response.text[:200]}"
            )
            return None
            
    except requests.RequestException as e:
        logger.error(f"Request error fetching commit: {e}")
        return None
    except ValueError as e:
        logger.error(f"Error parsing repo: {e}")
        return None


def post_pr_comment(
    repo: str,
    pr_number: int,
    body: str,
    token: str
) -> bool:
    """Post a comment on a pull request.
    
    Args:
        repo: Repository in "owner/repo" format.
        pr_number: Pull request number.
        body: Comment body (markdown supported).
        token: GitHub token.
        
    Returns:
        True if comment was posted successfully, False otherwise.
    """
    try:
        owner, repo_name = _parse_repo(repo)
        # Use issues endpoint for PR comments
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo_name}/issues/{pr_number}/comments"
        
        response = requests.post(
            url,
            headers=_get_headers(token),
            json={"body": body},
            timeout=30
        )
        
        if response.status_code in (200, 201):
            logger.info(f"Successfully posted comment to PR #{pr_number}")
            return True
        else:
            logger.error(
                f"Failed to post comment to PR #{pr_number}: "
                f"HTTP {response.status_code} - {response.text[:200]}"
            )
            return False
            
    except requests.RequestException as e:
        logger.error(f"Request error posting comment: {e}")
        return False
    except ValueError as e:
        logger.error(f"Error parsing repo: {e}")
        return False


def build_ci_comment(state: "CIState") -> str:
    """Build a formatted CI comment for a PR.
    
    Args:
        state: Current CI state.
        
    Returns:
        Formatted markdown comment body.
    """
    # Status emoji
    test_status = state.get("test_status", "pending")
    if test_status == "passed":
        status_emoji = "✅"
        status_text = "Tests Passed"
    elif test_status == "failed":
        status_emoji = "❌"
        status_text = "Tests Failed"
    else:
        status_emoji = "⏳"
        status_text = "Tests Pending"
    
    # Build comment
    lines = [
        f"## {status_emoji} CI Boss Report: {status_text}",
        "",
        f"**Commit:** `{state.get('commit_sha', 'N/A')[:8]}`",
    ]
    
    # Add summary if available
    summary = state.get("summary")
    if summary:
        lines.extend([
            "",
            "### Summary",
            summary,
        ])
    
    # Add Linear issue link if available
    linear_url = state.get("linear_issue_url")
    linear_id = state.get("linear_issue_identifier")
    if linear_url:
        linear_text = linear_id if linear_id else "Linear Issue"
        lines.extend([
            "",
            f"📋 **Linked Linear Issue:** [{linear_text}]({linear_url})",
        ])
    
    # Add truncated test logs if available and tests failed
    test_logs = state.get("test_logs")
    if test_logs and test_status == "failed":
        truncated_logs = test_logs[:MAX_LOG_SNIPPET_LENGTH]
        if len(test_logs) > MAX_LOG_SNIPPET_LENGTH:
            truncated_logs += "\n... (truncated)"
        lines.extend([
            "",
            "<details>",
            "<summary>Test Logs (click to expand)</summary>",
            "",
            "```",
            truncated_logs,
            "```",
            "",
            "</details>",
        ])
    
    # Add changed files summary
    changed_files = state.get("changed_files", [])
    if changed_files:
        files_preview = changed_files[:10]
        lines.extend([
            "",
            f"**Changed Files:** {len(changed_files)} file(s)",
        ])
        if len(changed_files) > 10:
            lines.append(f"  (showing first 10 of {len(changed_files)})")
        for f in files_preview:
            lines.append(f"  - `{f}`")
    
    lines.extend([
        "",
        "---",
        "_Generated by CI Boss Agent_",
    ])
    
    return "\n".join(lines)


def post_ci_results_comment(state: "CIState") -> bool:
    """Post CI results as a comment on the PR.
    
    This is a convenience function that builds and posts the comment.
    Silently skips if PR number is not set or token is missing.
    
    Args:
        state: Current CI state.
        
    Returns:
        True if comment was posted, False otherwise (including when skipped).
    """
    # Check prerequisites
    pr_number = state.get("pr_number")
    repo = state.get("repo")
    
    if not pr_number:
        logger.info("No PR number set, skipping comment posting.")
        return False
    
    if not repo:
        logger.warning("No repo set, cannot post comment.")
        return False
    
    token = _get_github_token()
    if not token:
        return False
    
    # Build and post comment
    body = build_ci_comment(state)
    return post_pr_comment(repo, pr_number, body, token)
