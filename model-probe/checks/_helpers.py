"""Shared fixtures for checks: standard tools and prompts.

Underscore-prefixed, so the auto-discovery in __init__.py skips it (it is not a
check module — it defines no @check functions).
"""


def weather_tool():
    """A normal tool WITH a parameter (the common, well-behaved case)."""
    return {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string", "description": "City name"}},
                "required": ["city"],
            },
        },
    }


def discover_tool():
    """A PARAMETERLESS tool (empty properties).

    This is the schema that broke streamed tool-calling on GLM-5.2 / Scaleway.
    Many Omnis tools are parameterless (list_skills, list_softskills, ...).
    """
    return {
        "type": "function",
        "function": {
            "name": "discover_capabilities",
            "description": "List the agent's available capabilities. Takes no arguments.",
            "parameters": {"type": "object", "properties": {}},
        },
    }


# Prompts that strongly nudge a tool call, so a PASS/FAIL reflects transport
# support rather than the model's discretion.
WEATHER_MESSAGES = [
    {"role": "system", "content": "You can call tools. Use them when relevant."},
    {"role": "user", "content": "What's the weather in Paris right now? Use the get_weather tool."},
]

# Forces a textual preamble BEFORE the tool call — the combination that exposed
# the GLM-5.2 streaming bug (content first, then a parameterless tool call).
DISCOVER_MESSAGES = [
    {"role": "system", "content": "You are an agent. Begin your reply with 'Understood:' then call a tool to proceed."},
    {"role": "user", "content": "List your capabilities, then help me with a question."},
]


def fraction(ok, n):
    return "%d/%d" % (ok, n)
