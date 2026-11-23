"""LLM planner: proposes the next step. It never executes anything itself.

The planner only returns a Decision. workflow.py checks each decision against the
tool allowlist, the patient gate, the confirmation rule and the call budget before
anything is sent to the MCP server.
"""
import json
from dataclasses import dataclass, field

DEFAULT_MODEL = "llama3.1:8b"

SYSTEM_PROMPT = """You are a planning assistant for a hospital support desk.
You may only use the tools listed in the request. Reply with exactly one JSON object and nothing else:
{"action": "call_tool", "tool": "<tool name>", "arguments": {...}}
or
{"action": "finish", "summary": "<short summary for staff>"}
Do not diagnose or prescribe. Only propose a ticket if staff asked for one."""


@dataclass
class Decision:
    action: str                     # "call_tool" or "finish"
    tool: str | None = None
    arguments: dict = field(default_factory=dict)
    summary: str | None = None


class PlannerError(Exception):
    pass


def parse_decision(text: str) -> Decision:
    """Parse the model's reply into a Decision. Accepts a bare JSON object or one inside a code fence."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):].strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise PlannerError(f"Planner reply was not JSON: {text[:200]}") from exc
    if not isinstance(data, dict):
        raise PlannerError("Planner reply must be a JSON object")

    action = data.get("action")
    if action == "call_tool":
        tool, arguments = data.get("tool"), data.get("arguments", {})
        if not isinstance(tool, str) or not isinstance(arguments, dict):
            raise PlannerError("call_tool needs a string 'tool' and an object 'arguments'")
        return Decision("call_tool", tool=tool, arguments=arguments)
    if action == "finish":
        return Decision("finish", summary=str(data.get("summary", "")))
    raise PlannerError(f"Unknown planner action: {action!r}")


class ScriptedPlanner:
    """Plays back a fixed list of decisions. Used by tests and as an offline fallback."""

    def __init__(self, decisions: list[Decision]):
        self._decisions = list(decisions)

    async def decide(self, task: str, history: list[dict], tools: list[str]) -> Decision:
        if not self._decisions:
            return Decision("finish", summary="Scripted plan ended")
        return self._decisions.pop(0)


class OllamaPlanner:
    """Asks a local Ollama model (via langchain-ollama) for the next step."""

    def __init__(self, llm=None, model: str = DEFAULT_MODEL):
        self._llm = llm
        self._model = model

    def _get_llm(self):
        if self._llm is None:
            # Imported here so tests and ScriptedPlanner do not need langchain installed.
            from langchain_ollama import ChatOllama
            self._llm = ChatOllama(model=self._model, temperature=0, format="json")
        return self._llm

    async def decide(self, task: str, history: list[dict], tools: list[str]) -> Decision:
        from langchain_core.messages import HumanMessage, SystemMessage

        payload = json.dumps({"task": task, "tools": tools, "history": history})
        reply = await self._get_llm().ainvoke(
            [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=payload)]
        )
        return parse_decision(reply.content)
