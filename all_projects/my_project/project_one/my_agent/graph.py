# my_agent/graph.py
"""
CI Boss Agent - A CI/CD orchestration agent that integrates with GitHub,
Playwright tests, and Linear for issue tracking.

This agent coordinates CI/CD workflows by:
1. Fetching commit/PR metadata from GitHub
2. Running Playwright tests
3. Creating/updating Linear issues for failures
4. Posting results back to GitHub PRs

Environment Variables:
    GITHUB_TOKEN: Personal Access Token with 'repo' scope
    PLAYWRIGHT_COMMAND: Command to run tests (default: "npx playwright test")
    PLAYWRIGHT_WORKING_DIR: Directory to run tests from
    LINEAR_API_KEY: Personal API key for Linear
    LINEAR_TEAM_ID: Default team where issues are created
    LINEAR_LABEL_ID_BUG: (Optional) Label ID for bug issues
    LINEAR_LABEL_ID_TEST_FAILURE: (Optional) Label ID for test failure issues
    OPENAI_API_KEY: Required for the planner LLM
"""

from typing import TypedDict, Literal, List, Optional
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
import json
import re
import os
import subprocess
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# State Definition
# =============================================================================

class CIState(TypedDict, total=False):
    """
    State for the CI Boss agent.
    
    Attributes:
        repo: Repository in "owner/repo" format (e.g., "optimaltech/my-repo").
        commit_sha: Git commit SHA being tested.
        commit_message: Commit message (optional, fetched from GitHub).
        pr_number: Pull request number (optional, for PR-based workflows).
        changed_files: List of files changed in the commit/PR.
        test_status: Current test status - "pending", "passed", or "failed".
        test_logs: Output from test execution (stdout + stderr).
        summary: LLM-generated summary of the CI run.
        next_action: Next action to take - "run_tests", "analyze_failures", "summarize".
        linear_issue_id: Linear issue ID if one was created.
        linear_issue_url: URL to the Linear issue.
        linear_issue_identifier: Human-readable Linear issue ID (e.g., "ENG-123").
    """
    # Core CI/CD fields
    repo: str
    commit_sha: str
    commit_message: Optional[str]
    pr_number: Optional[int]
    changed_files: List[str]
    
    # Test execution fields
    test_status: Literal["pending", "passed", "failed"]
    test_logs: Optional[str]
    
    # Planner/LLM fields
    summary: Optional[str]
    next_action: Optional[str]
    
    # Linear integration fields
    linear_issue_id: Optional[str]
    linear_issue_url: Optional[str]
    linear_issue_identifier: Optional[str]


# =============================================================================
# LLM Planner
# =============================================================================

# Initialize the planner LLM (lazy to avoid requiring API key at import)
_llm_planner = None


def _get_planner_llm():
    """Get or create the planner LLM instance."""
    global _llm_planner
    if _llm_planner is None:
        _llm_planner = ChatOpenAI(model="gpt-4o")
    return _llm_planner


# =============================================================================
# Node: Planner (Master Agent)
# =============================================================================

def planner_node(state: CIState) -> CIState:
    """
    Planner node - decides what to do next based on current state.
    
    The planner analyzes the current CI state and determines the next action:
    - "run_tests": Run Playwright tests (if not yet run or need retry)
    - "analyze_failures": Analyze test failures and create/update Linear issues
    - "summarize": Generate final summary and post results to GitHub
    
    Args:
        state: Current CI state.
        
    Returns:
        Updated state with next_action and summary fields.
    """
    # Import here to avoid circular imports
    from .github_client import post_ci_results_comment
    from .linear_client import create_or_update_linear_issue
    
    test_status = state.get("test_status", "pending")
    test_logs = state.get("test_logs", "")
    test_logs_preview = test_logs[:4000] if test_logs else "N/A"
    next_action = state.get("next_action")
    
    # If tests have been run and we're past the first planning cycle,
    # decide based on results
    if test_status != "pending" and next_action == "run_tests":
        if test_status == "failed":
            # Tests failed - create/update Linear issue and analyze
            state = create_or_update_linear_issue(state)
            state["next_action"] = "analyze_failures"
            state["summary"] = "Tests failed. Creating Linear issue and analyzing failures."
            return state
        elif test_status == "passed":
            # Tests passed - summarize and post results
            state["next_action"] = "summarize"
            state["summary"] = "All tests passed successfully."
            # Post results to GitHub
            post_ci_results_comment(state)
            return state
    
    # For analyze_failures, generate detailed summary and post
    if next_action == "analyze_failures":
        # Generate LLM summary of failures
        llm = _get_planner_llm()
        prompt = f"""You are a CI/CD expert. Analyze these test failures and provide a brief summary.

Repository: {state.get('repo', 'N/A')}
Commit: {state.get('commit_sha', 'N/A')}
Changed files: {state.get('changed_files', [])}

Test logs (truncated):
{test_logs_preview}

Provide:
1. A brief summary of what failed
2. Likely cause based on changed files
3. Suggested fix

Format as concise markdown."""

        try:
            resp = llm.invoke(prompt)
            content = resp.content if hasattr(resp, 'content') else str(resp)
            state["summary"] = content
        except Exception as e:
            logger.error(f"LLM error in planner: {e}")
            state["summary"] = f"Test failures detected. See logs for details."
        
        # Update Linear issue with analysis
        state = create_or_update_linear_issue(state)
        
        # Post results to GitHub
        post_ci_results_comment(state)
        
        state["next_action"] = "summarize"
        return state
    
    # Default behavior: use LLM to decide next action
    prompt = f"""You are a CI boss agent managing CI/CD workflows.

IMPORTANT: You must analyze the situation and decide the next action.

Repository: {state.get('repo', 'N/A')}
Commit: {state.get('commit_sha', 'N/A')}
PR: {state.get('pr_number', 'N/A')}
Changed files: {state.get('changed_files', [])}

Test status: {test_status}
Test logs (preview): {test_logs_preview[:1000] if test_logs_preview != 'N/A' else 'N/A'}

Previous action: {next_action or 'None (first run)'}

Decide what to do next:
- "run_tests": Run Playwright tests (if tests haven't run yet)
- "analyze_failures": Analyze test failures (if tests failed)
- "summarize": Generate final summary (if tests passed or analysis complete)

You MUST respond with valid JSON: {{"action": "run_tests|analyze_failures|summarize", "summary": "brief explanation"}}
"""

    try:
        llm = _get_planner_llm()
        resp = llm.invoke(prompt)
        content = resp.content if hasattr(resp, 'content') else str(resp)
        
        # Parse response - try to extract JSON
        json_match = re.search(r'\{[^{}]*"action"[^{}]*\}', content, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                action = parsed.get("action", "run_tests")
                summary = parsed.get("summary", "Proceeding with CI workflow")
                
                # Validate action
                if action not in ("run_tests", "analyze_failures", "summarize"):
                    action = "run_tests" if test_status == "pending" else "summarize"
            except json.JSONDecodeError:
                action = "run_tests" if test_status == "pending" else "summarize"
                summary = "Proceeding with CI workflow"
        else:
            # Fallback parsing
            if test_status == "pending":
                action = "run_tests"
            elif test_status == "failed":
                action = "analyze_failures"
            else:
                action = "summarize"
            summary = content[:200] if len(content) > 200 else content
            
    except Exception as e:
        logger.error(f"LLM error in planner: {e}")
        # Fallback logic
        if test_status == "pending":
            action = "run_tests"
            summary = "Starting test execution"
        elif test_status == "failed":
            action = "analyze_failures"
            summary = "Analyzing test failures"
        else:
            action = "summarize"
            summary = "Completing CI workflow"
    
    state["summary"] = summary
    state["next_action"] = action
    return state


# =============================================================================
# Node: GitHub Helper
# =============================================================================

def github_node(state: CIState) -> CIState:
    """
    GitHub helper node - fetch commit/PR metadata and changed files.
    
    This node:
    - Fetches PR details if pr_number is provided but commit_sha is missing
    - Fetches changed files from either PR or commit endpoint
    - Stores commit message if available
    
    If GITHUB_TOKEN is not set, logs a warning and returns state unchanged.
    
    Args:
        state: Current CI state with repo and optionally pr_number/commit_sha.
        
    Returns:
        Updated state with changed_files, commit_sha, and optionally commit_message.
    """
    from .github_client import (
        _get_github_token,
        fetch_pr_details,
        fetch_pr_files,
        fetch_commit_files,
        fetch_commit_details,
    )
    
    repo = state.get("repo")
    if not repo:
        logger.warning("No repository specified in state")
        return state
    
    token = _get_github_token()
    if not token:
        # Token missing - return with placeholder data for testing
        logger.warning("GITHUB_TOKEN not set - using placeholder data")
        if not state.get("changed_files"):
            state["changed_files"] = []
        if not state.get("commit_sha"):
            state["commit_sha"] = "HEAD"
        return state
    
    pr_number = state.get("pr_number")
    commit_sha = state.get("commit_sha")
    
    # If we have a PR number but no commit SHA, fetch PR to get head commit
    if pr_number and not commit_sha:
        pr_details = fetch_pr_details(repo, pr_number, token)
        if pr_details:
            commit_sha = pr_details.get("head", {}).get("sha")
            if commit_sha:
                state["commit_sha"] = commit_sha
                logger.info(f"Fetched head commit SHA from PR: {commit_sha[:8]}")
    
    # Fetch changed files
    changed_files = None
    
    if pr_number:
        # Prefer PR endpoint for changed files
        changed_files = fetch_pr_files(repo, pr_number, token)
        if changed_files:
            logger.info(f"Fetched {len(changed_files)} changed files from PR #{pr_number}")
    
    if not changed_files and commit_sha:
        # Fall back to commit endpoint
        changed_files = fetch_commit_files(repo, commit_sha, token)
        if changed_files:
            logger.info(f"Fetched {len(changed_files)} changed files from commit {commit_sha[:8]}")
    
    if changed_files:
        state["changed_files"] = changed_files
    elif not state.get("changed_files"):
        state["changed_files"] = []
    
    # Optionally fetch commit message
    if commit_sha and not state.get("commit_message"):
        commit_details = fetch_commit_details(repo, commit_sha, token)
        if commit_details:
            commit_message = commit_details.get("commit", {}).get("message", "")
            if commit_message:
                state["commit_message"] = commit_message[:500]  # Truncate if too long
    
    # Ensure we have a commit SHA
    if not state.get("commit_sha"):
        state["commit_sha"] = "HEAD"
    
    return state


# =============================================================================
# Node: Test Runner (Playwright)
# =============================================================================

# Default Playwright command and timeout
DEFAULT_PLAYWRIGHT_COMMAND = "npx playwright test"
DEFAULT_PLAYWRIGHT_TIMEOUT = 1800  # 30 minutes in seconds
MAX_LOG_LENGTH = 20000  # Maximum characters for test logs


def test_runner_node(state: CIState) -> CIState:
    """
    Test runner node - execute Playwright tests and capture results.
    
    This node:
    - Only runs if next_action == "run_tests"
    - Executes the Playwright command (configurable via env vars)
    - Captures stdout/stderr and stores in test_logs
    - Sets test_status to "passed" or "failed"
    
    Environment Variables:
        PLAYWRIGHT_COMMAND: Command to run (default: "npx playwright test")
        PLAYWRIGHT_WORKING_DIR: Working directory for test execution
    
    Args:
        state: Current CI state.
        
    Returns:
        Updated state with test_status and test_logs.
    """
    next_action = state.get("next_action")
    
    # Only run tests if planner requested it
    if next_action != "run_tests":
        logger.info(f"Skipping test execution (next_action={next_action})")
        return state
    
    # Get configuration from environment
    command = os.environ.get("PLAYWRIGHT_COMMAND", DEFAULT_PLAYWRIGHT_COMMAND)
    working_dir = os.environ.get("PLAYWRIGHT_WORKING_DIR")
    
    logger.info(f"Running Playwright tests: {command}")
    if working_dir:
        logger.info(f"Working directory: {working_dir}")
    
    try:
        # Run the test command
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=DEFAULT_PLAYWRIGHT_TIMEOUT,
            cwd=working_dir if working_dir else None,
        )
        
        # Combine stdout and stderr
        logs = ""
        if result.stdout:
            logs += result.stdout
        if result.stderr:
            logs += "\n--- STDERR ---\n" + result.stderr
        
        # Truncate logs if too long
        if len(logs) > MAX_LOG_LENGTH:
            logs = logs[:MAX_LOG_LENGTH] + "\n\n... (truncated)"
        
        state["test_logs"] = logs
        
        # Determine status based on return code
        if result.returncode == 0:
            state["test_status"] = "passed"
            logger.info("Playwright tests passed")
        else:
            state["test_status"] = "failed"
            logger.warning(f"Playwright tests failed (exit code: {result.returncode})")
            
    except subprocess.TimeoutExpired:
        state["test_status"] = "failed"
        state["test_logs"] = (
            f"ERROR: Test execution timed out after {DEFAULT_PLAYWRIGHT_TIMEOUT} seconds.\n"
            f"Command: {command}\n"
            "Consider increasing the timeout or optimizing tests."
        )
        logger.error("Test execution timed out")
        
    except FileNotFoundError as e:
        state["test_status"] = "failed"
        state["test_logs"] = (
            f"ERROR: Command not found - {e}\n"
            f"Command: {command}\n"
            "Ensure Playwright is installed (npm install @playwright/test)."
        )
        logger.error(f"Command not found: {e}")
        
    except Exception as e:
        state["test_status"] = "failed"
        state["test_logs"] = (
            f"ERROR: Failed to execute tests - {type(e).__name__}: {e}\n"
            f"Command: {command}"
        )
        logger.error(f"Test execution error: {e}")
    
    return state


# =============================================================================
# Graph Definition
# =============================================================================

def _should_continue_after_planner(state: CIState) -> str:
    """
    Determine the next node after the planner.
    
    Returns:
        "test_runner" if tests should be run, "end" otherwise.
    """
    next_action = state.get("next_action")
    
    if next_action == "run_tests":
        return "test_runner"
    else:
        # For analyze_failures and summarize, we're done
        return "end"


def _should_continue_after_test_runner(state: CIState) -> str:
    """
    Determine the next node after the test runner.
    
    Always returns to planner to analyze results.
    """
    return "planner"


def build_graph():
    """
    Build the CI Boss state graph.
    
    The graph flows as:
    1. Entry: github (fetch metadata)
    2. planner (decide action)
    3. Conditional:
       - If run_tests -> test_runner -> back to planner
       - Otherwise -> END
    
    Returns:
        Compiled LangGraph.
    """
    sg = StateGraph(CIState)
    
    # Add nodes
    sg.add_node("github", github_node)
    sg.add_node("planner", planner_node)
    sg.add_node("test_runner", test_runner_node)
    
    # Set entry point
    sg.set_entry_point("github")
    
    # github -> planner
    sg.add_edge("github", "planner")
    
    # planner -> conditional (test_runner or end)
    sg.add_conditional_edges(
        "planner",
        _should_continue_after_planner,
        {
            "test_runner": "test_runner",
            "end": END,
        }
    )
    
    # test_runner -> planner (to analyze results)
    sg.add_edge("test_runner", "planner")
    
    return sg.compile()


# Export the compiled graph
graph = build_graph()
