"""Planner-driven workflow. The model proposes steps; this module decides what runs.

Rules here (not in the prompt):
- tool allowlist
- find_patient must confirm a patient before any lab lookup
- create_support_ticket needs explicit staff confirmation
- a critical lab result is always escalated by code
- planner steps and tool calls are both capped
"""
import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from client import MCPClient, SERVER, MAX_CALL_THRESHOLD, ToolResponseError, parse_result
from planner import OllamaPlanner, PlannerError, DEFAULT_MODEL

MAX_STEPS = 6
ALLOWED_TOOLS = {"find_patient", "get_lab_results", "escalate_to_human", "create_support_ticket"}


class PolicyViolation(Exception):
    pass


def check_policy(name: str, arguments: dict, found: set, confirm) -> dict:
    """Permission and gate checks. Returns the arguments to send, or raises PolicyViolation."""
    if name not in ALLOWED_TOOLS:
        raise PolicyViolation(f"tool '{name}' is not allowed in this workflow")
    if name in {"get_lab_results", "escalate_to_human", "create_support_ticket"}:
        if arguments.get("patient_id") not in found:
            raise PolicyViolation("call find_patient for this patient and confirm it exists first")
    if name == "create_support_ticket":
        for field in ("category", "description"):
            if not isinstance(arguments.get(field), str) or not arguments[field].strip():
                raise PolicyViolation(f"ticket needs a non-empty '{field}' before staff are asked")
        question = f"Create a support ticket for {arguments['patient_id']} ({arguments['category']})? [y/N] "
        if not confirm(question):
            raise PolicyViolation("staff did not confirm ticket creation")
        return {**arguments, "confirmed": True}   # code sets this, never the model
    return arguments


def summarize(name: str, result: dict) -> dict:
    """Only summaries go back to the model: no full patient or lab records."""
    if name == "find_patient":
        return {"found": result.get("found")}
    if name == "get_lab_results":
        return {"count": result.get("count"),
                "flags": [row.get("flag") for row in result.get("results", [])]}
    if name == "escalate_to_human":
        return {"escalation_id": result.get("escalation_id"), "status": result.get("status")}
    if name == "create_support_ticket":
        return {"ticket_id": result.get("ticket_id"), "status": result.get("status")}
    return {}


async def run_planned_workflow(client: MCPClient, planner, task: str, confirm=None,
                               max_steps: int = MAX_STEPS) -> dict:
    confirm = confirm or (lambda question: False)     # default: deny
    tools = sorted(client.available_tools)
    history: list[dict] = []
    found: set[str] = set()
    critical: set[str] = set()
    escalated: set[str] = set()
    stop_reason = "planner finished"
    summary = None

    for _ in range(max_steps):
        if client.calls >= client.max_calls:
            stop_reason = "tool-call budget reached"
            break
        try:
            decision = await planner.decide(task, history, tools)
        except PlannerError as exc:
            history.append({"error": f"invalid planner reply: {exc}"})
            continue
        if decision.action == "finish":
            summary = decision.summary
            break

        name = decision.tool
        try:
            args = check_policy(name, decision.arguments, found, confirm)
            result = parse_result(await client.call_tool(name, args))
        except PolicyViolation as exc:
            history.append({"tool": name, "blocked": str(exc)})
            continue
        except (RuntimeError, ValueError, PermissionError, ToolResponseError) as exc:
            history.append({"tool": name, "error": str(exc)})
            continue

        history.append({"tool": name, "result": summarize(name, result)})
        pid = args.get("patient_id")
        if name == "find_patient" and result.get("found") is True:
            found.add(pid)
        if name == "get_lab_results" and any(r.get("flag") == "critical" for r in result.get("results", [])):
            critical.add(pid)
        if name == "escalate_to_human":
            escalated.add(pid)
    else:
        stop_reason = "planner step limit reached"

    # Safety net: a critical result must reach a human even if the model did not route it.
    for pid in sorted(critical - escalated):
        try:
            esc = parse_result(await client.call_tool("escalate_to_human", {
                "patient_id": pid,
                "reason": "A lab record is flagged critical; please review.",
                "priority": "urgent",
            }))
        except RuntimeError as exc:
            raise RuntimeError(f"Critical lab result for {pid} was NOT escalated: {exc}") from exc
        escalated.add(pid)
        history.append({"tool": "escalate_to_human", "result": summarize("escalate_to_human", esc)})

    return {
        "summary": summary,
        "stop_reason": stop_reason,
        "escalated": sorted(escalated),
        "calls": client.calls,
        "history": history,
    }


def ask_staff(question: str) -> bool:
    try:
        return input(question).strip().lower() in {"y", "yes"}
    except EOFError:
        return False   # no terminal to ask: treat as not confirmed


async def main():
    task = "Check patient P1001: confirm they exist, review their recent labs, and escalate any critical result."
    planner = OllamaPlanner(model=DEFAULT_MODEL)
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            client = MCPClient(session, max_calls=MAX_CALL_THRESHOLD)
            await client.discover_tools()
            outcome = await run_planned_workflow(client, planner, task, confirm=ask_staff)
            print("========================")
            print("SUMMARY:", outcome["summary"])
            print("STOP REASON:", outcome["stop_reason"])
            print("ESCALATED PATIENTS:", outcome["escalated"])
            print("TOOL CALLS:", outcome["calls"])
            print("========================")


if __name__ == "__main__":
    asyncio.run(main())
