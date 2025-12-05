"""
my_first_agent - OpenAI-based Conversational Assistant

This agent provides a conversational assistant powered by OpenAI models
with web search capabilities via Tavily.

Available models (configurable via `model_name`):
    - gpt-4o (default): Most capable, best for complex tasks
    - gpt-4o-mini: Faster, good balance of speed and capability
    - gpt-3.5-turbo: Fastest, most cost-effective

Environment Variables:
    OPENAI_API_KEY: Required for OpenAI model access
    TAVILY_API_KEY: Required for web search functionality

Example Usage:
    >>> from my_agent.main import graph
    >>> result = graph.invoke(
    ...     {"messages": [{"role": "user", "content": "What is LangGraph?"}]},
    ...     config={"configurable": {"model_name": "gpt-4o"}}
    ... )
"""

import sys
from pathlib import Path

# Fix for imports when module is loaded directly by LangGraph
# The module might be loaded from /deps/project_one/my_agent/main.py
# We need to ensure the parent directory (project_one) is in sys.path
_file = Path(__file__).resolve()
_parent = _file.parent  # my_agent directory
_grandparent = _parent.parent  # project_one directory

# Add grandparent to path so 'my_agent' package can be imported
if str(_grandparent) not in sys.path:
    sys.path.insert(0, str(_grandparent))

# Use absolute import - this works when project_one is in sys.path
from my_agent.utils.build_graph import workflow

graph = workflow.compile()