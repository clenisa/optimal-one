"""
my_second_agent - Anthropic Claude-based Conversational Assistant

This agent provides a conversational assistant powered by Anthropic Claude models
with web search capabilities via Tavily.

Available models (configurable via `model_name`):
    - sonnet (default): Claude 3 Sonnet - balanced performance and capability
    - haiku: Claude 3 Haiku - fastest, most cost-effective
    - opus: Claude 3 Opus - most capable, best for complex reasoning

Environment Variables:
    ANTHROPIC_API_KEY: Required for Anthropic Claude model access
    TAVILY_API_KEY: Required for web search functionality

Example Usage:
    >>> from my_other_agent.main import graph
    >>> result = graph.invoke(
    ...     {"messages": [{"role": "user", "content": "What is LangGraph?"}]},
    ...     config={"configurable": {"model_name": "sonnet"}}
    ... )
"""

import sys
from pathlib import Path

# Fix for imports when module is loaded directly by LangGraph
# The module might be loaded from /deps/project_two/my_other_agent/main.py
# We need to ensure the parent directory (project_two) is in sys.path
_file = Path(__file__).resolve()
_parent = _file.parent  # my_other_agent directory
_grandparent = _parent.parent  # project_two directory

# Add grandparent to path so 'my_other_agent' package can be imported
if str(_grandparent) not in sys.path:
    sys.path.insert(0, str(_grandparent))

# Use absolute import - this works when project_two is in sys.path
from my_other_agent.utils.build_graph import workflow

graph = workflow.compile()