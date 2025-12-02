from typing import TypedDict, Annotated, Sequence, Literal

from functools import lru_cache
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode
from langgraph.graph import StateGraph, END, add_messages


@lru_cache(maxsize=1)
def _get_tools():
    """Lazily initialize tools to avoid requiring API keys at import time."""
    from langchain_community.tools.tavily_search import TavilySearchResults
    return [TavilySearchResults(max_results=1)]


@lru_cache(maxsize=4)
def _get_model(model_name: str):
    if model_name == "gpt-4o":
        model = ChatOpenAI(temperature=0, model_name="gpt-4o")
    elif model_name == "gpt-4o-mini":
        model =  ChatOpenAI(temperature=0, model_name="gpt-4o-mini")
    elif model_name == "gpt-3.5-turbo":
        model = ChatOpenAI(temperature=0, model_name="gpt-3.5-turbo-0125")
    else:
        raise ValueError(f"Unsupported model type: {model_name}")

    model = model.bind_tools(_get_tools())
    return model


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


# Define the function that determines whether to continue or not
def should_continue(state):
    messages = state["messages"]
    last_message = messages[-1]
    # If there are no tool calls, then we finish
    if not last_message.tool_calls:
        return "end"
    # Otherwise if there is, we continue
    else:
        return "continue"


system_prompt = """Be a helpful assistant"""


# Define the function that calls the model
def call_model(state, config):
    messages = state["messages"]
    messages = [{"role": "system", "content": system_prompt}] + messages
    model_name = config.get('configurable', {}).get("model_name", "anthropic")
    model = _get_model(model_name)
    response = model.invoke(messages)
    # We return a list, because this will get added to the existing list
    return {"messages": [response]}


# Define the function to execute tools - wrapped to enable lazy initialization
def action_node(state):
    """Execute tools with lazy initialization."""
    tool_node = ToolNode(_get_tools())
    return tool_node.invoke(state)


# Define the config
class GraphConfig(TypedDict):
    model_name: Literal["gpt-4o", "gpt-4o-mini","gpt-3.5-turbo"]


@lru_cache(maxsize=1)
def _build_workflow():
    """Build the workflow graph lazily."""
    # Define a new graph
    workflow = StateGraph(AgentState, config_schema=GraphConfig)

    # Define the two nodes we will cycle between
    workflow.add_node("agent", call_model)
    workflow.add_node("action", action_node)

    # Set the entrypoint as `agent`
    # This means that this node is the first one called
    workflow.set_entry_point("agent")

    # We now add a conditional edge
    workflow.add_conditional_edges(
        # First, we define the start node. We use `agent`.
        # This means these are the edges taken after the `agent` node is called.
        "agent",
        # Next, we pass in the function that will determine which node is called next.
        should_continue,
        # Finally we pass in a mapping.
        # The keys are strings, and the values are other nodes.
        # END is a special node marking that the graph should finish.
        # What will happen is we will call `should_continue`, and then the output of that
        # will be matched against the keys in this mapping.
        # Based on which one it matches, that node will then be called.
        {
            # If `tools`, then we call the tool node.
            "continue": "action",
            # Otherwise we finish.
            "end": END,
        },
    )

    # We now add a normal edge from `tools` to `agent`.
    # This means that after `tools` is called, `agent` node is called next.
    workflow.add_edge("action", "agent")
    
    return workflow


class _LazyWorkflow:
    """Lazy wrapper that builds the workflow on first access."""
    
    def __getattr__(self, name):
        return getattr(_build_workflow(), name)
    
    def compile(self, *args, **kwargs):
        return _build_workflow().compile(*args, **kwargs)


# Export a lazy workflow object that only builds when accessed
workflow = _LazyWorkflow()
