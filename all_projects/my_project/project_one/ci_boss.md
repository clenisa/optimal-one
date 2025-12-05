# CI Boss Agent

> **Status**: ✅ Fully functional (17/17 tests passing)  
> **Last Updated**: December 2024

The CI Boss agent is a CI/CD orchestration agent that integrates with GitHub, Playwright tests, and Linear for issue tracking. It automates the process of running tests, analyzing failures, and creating issues for tracking.

## Overview

The CI Boss agent follows this workflow:

```
┌──────────────────────────────────────────────────────────────────┐
│                         CI Boss Workflow                          │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│   ┌─────────┐    ┌─────────┐    ┌─────────────┐                  │
│   │ GitHub  │───▶│ Planner │───▶│ Test Runner │──┐               │
│   │  Node   │    │  Node   │    │    Node     │  │               │
│   └─────────┘    └────┬────┘    └─────────────┘  │               │
│                       │               ▲          │               │
│                       │               └──────────┘               │
│                       │         (if run_tests)                   │
│                       │                                          │
│                       ▼                                          │
│                   ┌──────┐                                       │
│                   │ END  │  (analyze_failures or summarize)      │
│                   └──────┘                                       │
└──────────────────────────────────────────────────────────────────┘
```

1. **GitHub Node**: Fetches commit/PR metadata and changed files
2. **Planner Node**: Decides what action to take (run tests, analyze failures, or summarize)
3. **Test Runner Node**: Executes Playwright tests
4. **Linear Integration**: Creates/updates issues for test failures
5. **GitHub Comments**: Posts results back to pull requests

## Quick Start

```bash
# 1. Set required environment variables
export OPENAI_API_KEY="sk-..."
export GITHUB_TOKEN="ghp_..."  # Optional but recommended

# 2. Invoke the agent
curl -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "repo": "your-org/your-repo",
      "pr_number": 42
    }
  }'
```

## Environment Variables

### Required

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | Required for the GPT-4o planner LLM |

### GitHub Integration

| Variable | Description |
|----------|-------------|
| `GITHUB_TOKEN` | Personal Access Token with `repo` scope. Required for fetching PR/commit data and posting comments. |

If `GITHUB_TOKEN` is not set, the agent will log a warning and skip GitHub integration. The graph will still run with placeholder data.

### Playwright Test Runner

| Variable | Description | Default |
|----------|-------------|---------|
| `PLAYWRIGHT_COMMAND` | Command to run tests | `npx playwright test` |
| `PLAYWRIGHT_WORKING_DIR` | Working directory for test execution | Repository root |

### Linear Integration

| Variable | Description |
|----------|-------------|
| `LINEAR_API_KEY` | Personal API key for Linear |
| `LINEAR_TEAM_ID` | Default team ID where issues are created |
| `LINEAR_LABEL_ID_BUG` | (Optional) Label ID for bug issues |
| `LINEAR_LABEL_ID_TEST_FAILURE` | (Optional) Label ID for test failure issues |
| `LINEAR_LABEL_ID_FEATURE` | (Optional) Label ID for feature issues |

If `LINEAR_API_KEY` or `LINEAR_TEAM_ID` are not set, the agent will log a warning and skip Linear integration.

## State Schema

The CI Boss agent uses the following state structure:

```python
class CIState(TypedDict, total=False):
    # Core CI/CD fields
    repo: str                          # "owner/repo" format
    commit_sha: str                    # Git commit SHA
    commit_message: Optional[str]      # Commit message
    pr_number: Optional[int]           # Pull request number
    changed_files: List[str]           # List of changed files
    
    # Test execution fields
    test_status: Literal["pending", "passed", "failed"]
    test_logs: Optional[str]           # Stdout + stderr from tests
    
    # Planner/LLM fields
    summary: Optional[str]             # LLM-generated summary
    next_action: Optional[str]         # "run_tests", "analyze_failures", "summarize"
    
    # Linear integration fields
    linear_issue_id: Optional[str]     # Linear issue ID
    linear_issue_url: Optional[str]    # URL to Linear issue
    linear_issue_identifier: Optional[str]  # e.g., "ENG-123"
```

## Example Usage

### Starting a CI Run

To start a CI run, invoke the graph with an initial state containing the repository and PR/commit information:

```python
from my_agent.graph import graph

# Start a run for a pull request
initial_state = {
    "repo": "optimaltech/my-repo",
    "pr_number": 42,
    # commit_sha will be fetched from the PR
}

result = graph.invoke(initial_state)

# Check the result
print(f"Test Status: {result['test_status']}")
print(f"Summary: {result['summary']}")
if result.get('linear_issue_url'):
    print(f"Linear Issue: {result['linear_issue_url']}")
```

### Starting a Run for a Specific Commit

```python
initial_state = {
    "repo": "optimaltech/my-repo",
    "commit_sha": "abc123def456789",
}

result = graph.invoke(initial_state)
```

### JSON Payload for API Invocation

When calling the agent via the LangGraph API, use this payload structure:

```json
{
  "input": {
    "repo": "optimaltech/my-repo",
    "pr_number": 42
  }
}
```

Or with a specific commit:

```json
{
  "input": {
    "repo": "optimaltech/my-repo",
    "commit_sha": "abc123def456789"
  }
}
```

### Full Payload with All Fields

```json
{
  "input": {
    "repo": "optimaltech/my-repo",
    "commit_sha": "abc123def456789",
    "pr_number": 42,
    "changed_files": [],
    "test_status": "pending"
  }
}
```

## Workflow Details

### GitHub Node

The GitHub node fetches metadata about the commit or pull request:

1. If `pr_number` is provided but `commit_sha` is missing, it fetches the PR to get the head commit SHA
2. Fetches changed files from the PR or commit endpoint
3. Fetches commit message for context

**API Endpoints Used:**
- `GET /repos/{owner}/{repo}/pulls/{pr_number}` - Fetch PR details
- `GET /repos/{owner}/{repo}/pulls/{pr_number}/files` - Fetch PR changed files
- `GET /repos/{owner}/{repo}/commits/{commit_sha}` - Fetch commit details and files
- `POST /repos/{owner}/{repo}/issues/{pr_number}/comments` - Post results comment

### Planner Node

The planner uses GPT-4o to decide the next action:

- **`run_tests`**: Tests haven't been run yet, so run Playwright
- **`analyze_failures`**: Tests failed, analyze the failures and create/update Linear issue
- **`summarize`**: Tests passed or analysis complete, post results and end

The planner also:
- Creates/updates Linear issues when tests fail
- Posts results as PR comments
- Generates human-readable summaries of test results

### Test Runner Node

The test runner:

1. Only executes if `next_action == "run_tests"`
2. Runs the configured Playwright command
3. Captures stdout and stderr (truncated to 20,000 characters)
4. Sets `test_status` to "passed" or "failed"
5. Handles errors gracefully (timeout, command not found, etc.)

**Timeout**: 30 minutes (configurable in code)

### Linear Integration

When tests fail, the agent creates a Linear issue with:
- Title: `[CI] Playwright failure on {repo}@{short_sha}`
- Description: PR/commit details, changed files, summary, and truncated logs
- Optional labels: Bug, Test Failure (if label IDs are configured)
- Priority: Medium (2)

When tests later pass for the same commit/PR (if `linear_issue_id` is present):
- Adds a comment to the existing issue
- Moves the issue to "Done" state

## Error Handling

The agent is designed to be resilient:

- **Missing Environment Variables**: Logs warnings and skips the corresponding integration
- **API Failures**: Logs errors but continues the workflow
- **Test Execution Failures**: Captures error details in `test_logs`
- **Timeouts**: Marks tests as failed with timeout message

The graph will not crash due to missing credentials or API errors.

## Testing

Run the unit tests:

```bash
cd all_projects/my_project/project_one
python -m pytest tests/test_ci_boss.py -v
```

Or with unittest:

```bash
python -m unittest tests.test_ci_boss -v
```

## Architecture

```
my_agent/
├── graph.py           # Main graph definition, CIState, and nodes
├── github_client.py   # GitHub REST API integration
├── linear_client.py   # Linear GraphQL API integration
├── main.py            # my_first_agent entry point
└── utils/
    └── build_graph.py # my_first_agent graph builder
```

The `ci_boss` agent is defined in `graph.py` and exported as `graph = build_graph()`.

## Security Notes

- Never hardcode API tokens or secrets
- All credentials should be provided via environment variables
- The agent does not log or expose secrets in error messages
- Test logs are truncated to prevent excessive data storage
