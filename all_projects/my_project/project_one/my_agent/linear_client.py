"""
Linear Client for CI Boss Agent.

This module provides Linear GraphQL API integration for creating and updating
issues related to CI/CD runs. All API calls require LINEAR_API_KEY env var.

Environment Variables:
    LINEAR_API_KEY: Personal API key for Linear.
    LINEAR_TEAM_ID: Default team where issues are created.
    LINEAR_LABEL_ID_BUG: (Optional) Label ID for bug issues.
    LINEAR_LABEL_ID_TEST_FAILURE: (Optional) Label ID for test failure issues.
    LINEAR_LABEL_ID_FEATURE: (Optional) Label ID for feature issues.
"""

import os
import logging
from typing import Optional, List, Dict, Any, TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from .graph import CIState

logger = logging.getLogger(__name__)

# Linear GraphQL API endpoint
LINEAR_API_URL = "https://api.linear.app/graphql"

# Maximum description length for Linear issues
MAX_DESCRIPTION_LENGTH = 10000


def _get_linear_config() -> tuple[Optional[str], Optional[str]]:
    """Get Linear configuration from environment.
    
    Returns:
        Tuple of (api_key, team_id). Either or both may be None.
    """
    api_key = os.environ.get("LINEAR_API_KEY")
    team_id = os.environ.get("LINEAR_TEAM_ID")
    
    if not api_key:
        logger.warning(
            "LINEAR_API_KEY not set. Linear integration will be skipped. "
            "Set LINEAR_API_KEY env var to enable Linear features."
        )
    if not team_id:
        logger.warning(
            "LINEAR_TEAM_ID not set. Linear integration will be skipped. "
            "Set LINEAR_TEAM_ID env var to enable Linear features."
        )
    
    return api_key, team_id


def _get_label_ids() -> List[str]:
    """Get optional label IDs from environment.
    
    Returns:
        List of label IDs to apply to new issues.
    """
    labels = []
    
    bug_label = os.environ.get("LINEAR_LABEL_ID_BUG")
    if bug_label:
        labels.append(bug_label)
    
    test_failure_label = os.environ.get("LINEAR_LABEL_ID_TEST_FAILURE")
    if test_failure_label:
        labels.append(test_failure_label)
    
    return labels


def _execute_graphql(
    query: str,
    variables: Dict[str, Any],
    api_key: str
) -> Optional[Dict[str, Any]]:
    """Execute a GraphQL query against Linear API.
    
    Args:
        query: GraphQL query or mutation.
        variables: Variables for the query.
        api_key: Linear API key.
        
    Returns:
        Response data or None if request fails.
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": api_key,  # Linear uses the key directly
    }
    
    try:
        response = requests.post(
            LINEAR_API_URL,
            headers=headers,
            json={"query": query, "variables": variables},
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            if "errors" in data:
                logger.error(f"Linear GraphQL errors: {data['errors']}")
                return None
            return data.get("data")
        else:
            logger.error(
                f"Linear API request failed: HTTP {response.status_code} - "
                f"{response.text[:200]}"
            )
            return None
            
    except requests.RequestException as e:
        logger.error(f"Request error calling Linear API: {e}")
        return None


def _build_issue_description(state: "CIState") -> str:
    """Build a description for a Linear issue.
    
    Args:
        state: Current CI state.
        
    Returns:
        Formatted markdown description.
    """
    lines = [
        "## CI/CD Test Failure Details",
        "",
        f"**Repository:** {state.get('repo', 'N/A')}",
        f"**Commit:** `{state.get('commit_sha', 'N/A')}`",
    ]
    
    pr_number = state.get("pr_number")
    if pr_number:
        lines.append(f"**Pull Request:** #{pr_number}")
    
    # Add summary
    summary = state.get("summary")
    if summary:
        lines.extend([
            "",
            "### Summary",
            summary,
        ])
    
    # Add changed files
    changed_files = state.get("changed_files", [])
    if changed_files:
        lines.extend([
            "",
            f"### Changed Files ({len(changed_files)} total)",
        ])
        # Show up to 20 files
        for f in changed_files[:20]:
            lines.append(f"- `{f}`")
        if len(changed_files) > 20:
            lines.append(f"- ... and {len(changed_files) - 20} more files")
    
    # Add test logs (truncated)
    test_logs = state.get("test_logs")
    if test_logs:
        lines.extend([
            "",
            "### Test Logs",
            "```",
        ])
        # Reserve space for the rest of the description
        max_logs = MAX_DESCRIPTION_LENGTH - len("\n".join(lines)) - 500
        truncated_logs = test_logs[:max(max_logs, 1000)]
        if len(test_logs) > max_logs:
            truncated_logs += "\n... (truncated)"
        lines.append(truncated_logs)
        lines.append("```")
    
    description = "\n".join(lines)
    
    # Ensure we don't exceed max length
    if len(description) > MAX_DESCRIPTION_LENGTH:
        description = description[:MAX_DESCRIPTION_LENGTH - 20] + "\n\n... (truncated)"
    
    return description


def _build_issue_title(state: "CIState") -> str:
    """Build a title for a Linear issue.
    
    Args:
        state: Current CI state.
        
    Returns:
        Issue title.
    """
    repo = state.get("repo", "unknown")
    commit_sha = state.get("commit_sha", "unknown")
    short_sha = commit_sha[:7] if len(commit_sha) >= 7 else commit_sha
    
    return f"[CI] Playwright failure on {repo}@{short_sha}"


def create_linear_issue(state: "CIState") -> Optional[Dict[str, Any]]:
    """Create a new Linear issue for a CI failure.
    
    Args:
        state: Current CI state.
        
    Returns:
        Dict with issue details (id, identifier, url) or None if failed.
    """
    api_key, team_id = _get_linear_config()
    if not api_key or not team_id:
        return None
    
    title = _build_issue_title(state)
    description = _build_issue_description(state)
    label_ids = _get_label_ids()
    
    # GraphQL mutation to create an issue
    mutation = """
    mutation CreateIssue($input: IssueCreateInput!) {
        issueCreate(input: $input) {
            success
            issue {
                id
                identifier
                url
            }
        }
    }
    """
    
    input_data: Dict[str, Any] = {
        "teamId": team_id,
        "title": title,
        "description": description,
        "priority": 2,  # Medium priority
    }
    
    if label_ids:
        input_data["labelIds"] = label_ids
    
    variables = {"input": input_data}
    
    result = _execute_graphql(mutation, variables, api_key)
    
    if result and result.get("issueCreate", {}).get("success"):
        issue = result["issueCreate"]["issue"]
        logger.info(
            f"Created Linear issue {issue['identifier']}: {issue['url']}"
        )
        return issue
    else:
        logger.error("Failed to create Linear issue")
        return None


def add_comment_to_issue(issue_id: str, body: str) -> bool:
    """Add a comment to an existing Linear issue.
    
    Args:
        issue_id: Linear issue ID.
        body: Comment body (markdown supported).
        
    Returns:
        True if comment was added, False otherwise.
    """
    api_key, _ = _get_linear_config()
    if not api_key:
        return False
    
    mutation = """
    mutation CreateComment($input: CommentCreateInput!) {
        commentCreate(input: $input) {
            success
        }
    }
    """
    
    variables = {
        "input": {
            "issueId": issue_id,
            "body": body,
        }
    }
    
    result = _execute_graphql(mutation, variables, api_key)
    
    if result and result.get("commentCreate", {}).get("success"):
        logger.info(f"Added comment to Linear issue {issue_id}")
        return True
    else:
        logger.error(f"Failed to add comment to Linear issue {issue_id}")
        return False


def update_issue_state(issue_id: str, state_name: str = "Done") -> bool:
    """Update the workflow state of a Linear issue.
    
    Note: This finds the first workflow state matching the name.
    If no match is found, the issue state is not changed.
    
    Args:
        issue_id: Linear issue ID.
        state_name: Target state name (e.g., "Done", "In Progress").
        
    Returns:
        True if state was updated, False otherwise.
    """
    api_key, team_id = _get_linear_config()
    if not api_key or not team_id:
        return False
    
    # First, find the workflow state ID
    state_query = """
    query GetWorkflowStates($teamId: String!) {
        team(id: $teamId) {
            states {
                nodes {
                    id
                    name
                }
            }
        }
    }
    """
    
    result = _execute_graphql(state_query, {"teamId": team_id}, api_key)
    
    if not result or not result.get("team"):
        logger.error("Failed to fetch workflow states")
        return False
    
    states = result["team"]["states"]["nodes"]
    target_state = next((s for s in states if s["name"].lower() == state_name.lower()), None)
    
    if not target_state:
        logger.warning(f"Workflow state '{state_name}' not found")
        return False
    
    # Update the issue
    mutation = """
    mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
        issueUpdate(id: $id, input: $input) {
            success
        }
    }
    """
    
    variables = {
        "id": issue_id,
        "input": {"stateId": target_state["id"]}
    }
    
    result = _execute_graphql(mutation, variables, api_key)
    
    if result and result.get("issueUpdate", {}).get("success"):
        logger.info(f"Updated Linear issue {issue_id} to state '{state_name}'")
        return True
    else:
        logger.error(f"Failed to update Linear issue {issue_id}")
        return False


def create_or_update_linear_issue(state: "CIState") -> "CIState":
    """Create or update a Linear issue for the current CI state.
    
    Behavior:
      - If LINEAR_API_KEY or LINEAR_TEAM_ID are missing, log and return state unchanged.
      - If state["linear_issue_id"] is already set:
          - Append a comment to that issue describing the latest test run.
          - Optionally update workflow state if tests passed.
      - Else:
          - Create a new issue with:
              title: e.g. "[CI] Playwright failure on {repo}@{short_sha}"
              description: includes PR number, commit, changed files, summary, and truncated logs.
              labels: (optional) bug / test-failure label IDs from env.
          - Store issue id + URL / identifier back onto state.
    
    Args:
        state: Current CI state.
        
    Returns:
        Modified state with linear_issue_id and linear_issue_url if applicable.
    """
    api_key, team_id = _get_linear_config()
    if not api_key or not team_id:
        return state
    
    test_status = state.get("test_status", "pending")
    existing_issue_id = state.get("linear_issue_id")
    
    if existing_issue_id:
        # Update existing issue
        if test_status == "passed":
            # Add a comment and optionally close the issue
            comment = (
                "## ✅ Tests Now Passing\n\n"
                f"**Commit:** `{state.get('commit_sha', 'N/A')}`\n\n"
                "The tests that previously failed are now passing."
            )
            add_comment_to_issue(existing_issue_id, comment)
            # Optionally move to Done state
            update_issue_state(existing_issue_id, "Done")
        elif test_status == "failed":
            # Add a comment with the latest failure
            summary = state.get("summary", "No summary available")
            test_logs = state.get("test_logs", "")
            truncated_logs = test_logs[:2000] if test_logs else ""
            if len(test_logs) > 2000:
                truncated_logs += "\n... (truncated)"
            
            comment = (
                "## ❌ Test Failure Update\n\n"
                f"**Commit:** `{state.get('commit_sha', 'N/A')}`\n\n"
                f"### Summary\n{summary}\n\n"
                "### Test Logs\n```\n" + truncated_logs + "\n```"
            )
            add_comment_to_issue(existing_issue_id, comment)
    else:
        # Create new issue only if tests failed
        if test_status == "failed":
            issue = create_linear_issue(state)
            if issue:
                state["linear_issue_id"] = issue["id"]
                state["linear_issue_url"] = issue["url"]
                state["linear_issue_identifier"] = issue.get("identifier")
    
    return state
