# LangGraph Cloud Example Monorepo

![](static/agent_ui.png)

This is an example monorepo with multiple agents to deploy with LangGraph Cloud.

[LangGraph](https://github.com/langchain-ai/langgraph) is a library for building stateful, multi-actor applications with LLMs. The main use cases for LangGraph are conversational agents, and long-running, multi-step LLM applications or any LLM application that would benefit from built-in support for persistent checkpoints, cycles and human-in-the-loop interactions (ie. LLM and human collaboration).

LangGraph shortens the time-to-market for developers using LangGraph, with a one-liner command to start a production-ready HTTP microservice for your LangGraph applications, with built-in persistence. This lets you focus on the logic of your LangGraph graph, and leave the scaling and API design to us. The API is inspired by the OpenAI assistants API, and is designed to fit in alongside your existing services.

In order to deploy this agent to LangGraph Cloud you will want to first fork this repo. After that, you can follow the instructions [here](https://langchain-ai.github.io/langgraph/cloud/) to deploy to LangGraph Cloud.

# What Has Been Built

This monorepo contains **three LangGraph agents** deployed as separate graphs:

## 1. `my_first_agent` (OpenAI-based Assistant)
- **Location**: `all_projects/my_project/project_one/my_agent/main.py`
- **Purpose**: A conversational assistant agent that can answer questions and perform web searches
- **Capabilities**:
  - Uses OpenAI models (gpt-4o, gpt-4o-mini, or gpt-3.5-turbo)
  - Has access to Tavily search tool for web searches
  - Supports configurable model selection via `model_name` parameter
- **Workflow**: Agent → Tool Execution (if needed) → Agent → End
  - The agent receives messages and decides whether to use tools (Tavily search)
  - If tools are needed, it executes them and continues the conversation
  - Continues until no more tool calls are needed

## 2. `my_second_agent` (Anthropic-based Assistant)
- **Location**: `all_projects/project_two/my_other_agent/main.py`
- **Purpose**: A conversational assistant agent similar to `my_first_agent` but using Anthropic models
- **Capabilities**:
  - Uses Anthropic Claude models (claude-3-haiku, claude-3-sonnet, or claude-3-opus)
  - Has access to Tavily search tool for web searches
  - Supports configurable model selection via `model_name` parameter
- **Workflow**: Same as `my_first_agent` - Agent → Tool Execution (if needed) → Agent → End

## 3. `ci_boss` (CI/CD Orchestration Agent)
- **Location**: `all_projects/my_project/project_one/my_agent/graph.py`
- **Purpose**: A fully-featured CI/CD orchestration agent that manages test execution, failure tracking, and PR feedback
- **Capabilities**:
  - **GitHub Integration**: Fetches PR/commit metadata, posts results as PR comments
  - **Playwright Test Runner**: Executes tests via CLI and captures results
  - **Linear Integration**: Creates/updates issues for test failures via GraphQL API
  - **Intelligent Planning**: Uses GPT-4o to decide workflow actions
- **Workflow**: GitHub → Planner → (conditional) Test Runner → Planner → End
  - **GitHub Node**: Fetches commit SHA, changed files, and commit message from GitHub API
  - **Planner Node**: Analyzes state and decides action (run_tests, analyze_failures, summarize)
  - **Test Runner Node**: Executes Playwright tests, captures stdout/stderr, determines pass/fail
  - **Linear Client**: Creates issues for failures, updates with comments when tests pass
  - **GitHub Comments**: Posts formatted CI results to the PR

**Documentation**: See [`all_projects/my_project/project_one/ci_boss.md`](all_projects/my_project/project_one/ci_boss.md) for detailed configuration and usage.

## Current Workflow State

### Assistant Agents (`my_first_agent` and `my_second_agent`)
Both assistant agents follow the same workflow pattern:
1. **Entry Point**: Agent receives user messages
2. **Agent Node**: Processes the message and decides if tools are needed
3. **Conditional Routing**: 
   - If tool calls are needed → routes to `action` node
   - If no tool calls → routes to `END`
4. **Action Node**: Executes tools (currently Tavily search)
5. **Loop Back**: After tool execution, returns to agent node
6. **Termination**: Ends when agent determines no more tool calls are needed

**Current State**: Fully functional with Tavily search integration. Ready for deployment.

### CI Boss Agent (`ci_boss`)
The CI/CD orchestration agent follows this workflow:
1. **Entry Point**: GitHub node receives repository/PR information
2. **GitHub Node**: 
   - Fetches PR details and head commit SHA from GitHub API
   - Gets list of changed files from PR or commit endpoint
   - Fetches commit message for context
   - Handles missing tokens gracefully (skips integration, logs warning)
3. **Planner Node**: 
   - Analyzes current state (repo, commit, PR, test status, logs)
   - Uses GPT-4o to decide next action:
     - `run_tests`: Execute Playwright tests
     - `analyze_failures`: Analyze failures, create/update Linear issue
     - `summarize`: Post results to GitHub PR, end workflow
   - Handles Linear issue creation and GitHub comment posting
4. **Test Runner Node**: 
   - Executes Playwright via subprocess (configurable command)
   - Captures stdout/stderr (truncated to 20K chars)
   - Sets test_status to "passed" or "failed"
   - Handles timeouts (30 min default) and errors gracefully
5. **Conditional Routing**: 
   - If `next_action == "run_tests"` → test_runner → planner
   - Otherwise → END
6. **Linear Integration**:
   - Creates issues for failures with title, description, and optional labels
   - Updates existing issues when tests pass (adds comment, moves to Done)
7. **GitHub Comments**:
   - Posts formatted results to PR (status emoji, summary, changed files, Linear link)

**Current State**: Fully implemented with GitHub REST API, Playwright CLI execution, and Linear GraphQL integration. All integrations handle missing credentials gracefully.

# Environment Setup

## Required Environment Variables

Create a `.env` file in the root directory (you can copy from `.env.example`):

```bash
cp .env.example .env
```

Then set the following environment variables:

### For `my_first_agent`:
- `OPENAI_API_KEY` - Required for OpenAI model access

### For `my_second_agent`:
- `ANTHROPIC_API_KEY` - Required for Anthropic Claude model access

### For both assistant agents:
- `TAVILY_API_KEY` - Required for Tavily search tool functionality

### For `ci_boss`:
- `OPENAI_API_KEY` - Required for GPT-4o planning model
- `GITHUB_TOKEN` - Personal Access Token with `repo` scope (optional, enables GitHub integration)
- `PLAYWRIGHT_COMMAND` - Custom test command (optional, default: `npx playwright test`)
- `PLAYWRIGHT_WORKING_DIR` - Working directory for tests (optional)
- `LINEAR_API_KEY` - Personal API key for Linear (optional, enables Linear integration)
- `LINEAR_TEAM_ID` - Default team ID for issue creation (required if using Linear)
- `LINEAR_LABEL_ID_BUG` - Label ID for bug issues (optional)
- `LINEAR_LABEL_ID_TEST_FAILURE` - Label ID for test failure issues (optional)

### Optional:
- `LANGCHAIN_API_KEY` - Required if using LangChain tracing/monitoring features

## Python Version

The project is configured to use Python 3.11 (as specified in `langgraph.json`).

## Installation

1. **Install dependencies for project_one**:
   ```bash
   cd all_projects/my_project/project_one
   pip install -e .
   ```

2. **Install dependencies for project_two**:
   ```bash
   cd all_projects/project_two
   pip install -r requirements.txt
   ```

Or install both from the root:
```bash
pip install -e ./all_projects/my_project/project_one
pip install -r ./all_projects/project_two/requirements.txt
```

## Running Locally

After setting up your `.env` file and installing dependencies, you can test the agents locally using LangGraph's development server or by importing and invoking the graphs directly in Python.

# Explanation

## File Structure

This repository shows a few potential file structures all in one monorepo. To start with, all of the projects we build are inside of the subdirectory `all_projects`. Inside of this subdirectory we have two more subdirectories.

The first is called `my_project`, which could contain multiple projects, but in our case just contains one called `project_one`. Inside of `project_one` we setup a Python package using a `pyproject.toml` file to manage our dependencies. You will also notice that `project_one` doesn't just contain a `main.py` file, but also a `utils` folder that is imported into the `main.py` file. 

The second subdirectory is called `project_two` which is a standalone Python package with the same overall structure as `project_one` but it uses `requirements.txt` instead of `pyproject.toml` to manage dependencies.

## Configuration file

Inside our `langgraph.json` file you will first notice that our dependencies value is a list that includes the directories of both of our dependency files, and we also register both of our graphs, showcasing the ability of Langgraph to host multiple graphs from the same deployment. 

This use case shows how LangGraph can be configured for hosting multiple graphs from within the same repo, even if the projects are nested in different subdirectories and use different dependency systems.

# Documentation Maintenance

**Important**: All agents in this repository are instructed to maintain documentation up to date. When agents make changes to code, workflows, dependencies, or functionality, they automatically update relevant documentation files (README.md, code comments, docstrings) to reflect those changes. This ensures that documentation always accurately describes:
- What the code does
- What environment variables are needed
- How to use the system
- Current workflow states and capabilities

If you notice documentation is out of sync, please update it or notify the agents to maintain it.