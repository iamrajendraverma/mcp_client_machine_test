import asyncio
import json
from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult, TextContent

import server
from client import MCPClient
from planner import Decision, OllamaPlanner, PlannerError, ScriptedPlanner, parse_decision
from workflow import PolicyViolation, check_policy, run_planned_workflow

ALL_TOOLS = {"find_patient", "get_lab_results", "escalate_to_human",
             "create_support_ticket", "lookup_order"}


class FakeSession:
    """Answers tool calls by calling server.py functions directly (no subprocess)."""

    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        try:
            data = getattr(server, name)(**arguments)
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(data))],
                                  isError=False)
        except (ValueError, TypeError) as exc:
            return CallToolResult(content=[TextContent(type="text", text=str(exc))], isError=True)


def make_client(session, max_calls=5):
    client = MCPClient(session, max_calls=max_calls)
    client.available_tools = {name: object() for name in ALL_TOOLS}
    return client


def run(planner, max_calls=5, confirm=None, max_steps=6):
    session = FakeSession()
    client = make_client(session, max_calls=max_calls)
    outcome = asyncio.run(run_planned_workflow(client, planner, "test task",
                                               confirm=confirm, max_steps=max_steps))
    return outcome, session


def find(pid="P1001"):
    return Decision("call_tool", tool="find_patient", arguments={"patient_id": pid})


def labs(pid="P1001", limit=5):
    return Decision("call_tool", tool="get_lab_results", arguments={"patient_id": pid, "limit": limit})


def finish(text="done"):
    return Decision("finish", summary=text)


# --- Policy gate and allowlist ---

def test_lab_lookup_blocked_before_patient_is_found():
    outcome, session = run(ScriptedPlanner([labs(), find(), labs(), finish()]))
    assert "find_patient" in outcome["history"][0]["blocked"]
    # Labs run only after find_patient; the safety net then escalates the critical P1001 result.
    assert [name for name, _ in session.calls] == ["find_patient", "get_lab_results", "escalate_to_human"]

def test_tool_outside_allowlist_is_blocked():
    outcome, session = run(ScriptedPlanner([
        Decision("call_tool", tool="lookup_order", arguments={"order_id": "O2001"}),
        finish(),
    ]))
    assert "not allowed" in outcome["history"][0]["blocked"]
    assert session.calls == []

def test_check_policy_rejects_unknown_tool():
    with pytest.raises(PolicyViolation):
        check_policy("delete_everything", {}, set(), confirm=lambda q: True)

def test_escalation_blocked_without_patient_confirmed():
    outcome, session = run(ScriptedPlanner([
        Decision("call_tool", tool="escalate_to_human",
                 arguments={"reason": "x", "priority": "urgent"}),
        finish(),
    ]))
    assert "find_patient" in outcome["history"][0]["blocked"]
    assert session.calls == []

def test_ticket_with_missing_fields_is_blocked_before_staff_prompt():
    asked = []
    outcome, session = run(
        ScriptedPlanner([
            find(),
            Decision("call_tool", tool="create_support_ticket",
                     arguments={"patient_id": "P1001", "category": "records"}),
            finish(),
        ]),
        confirm=lambda q: asked.append(q) or True,
    )
    assert "description" in outcome["history"][1]["blocked"]
    assert asked == []   # staff were never asked about an incomplete ticket

# --- Ticket confirmation ---

def ticket_decision():
    return Decision("call_tool", tool="create_support_ticket", arguments={
        "patient_id": "P1001", "category": "records", "description": "wrong dob",
        "confirmed": True,   # the model claims confirmation; code must ignore this
    })

def test_ticket_denied_without_staff_confirmation():
    outcome, session = run(ScriptedPlanner([find(), ticket_decision(), finish()]), confirm=lambda q: False)
    assert "did not confirm" in outcome["history"][1]["blocked"]
    assert all(name != "create_support_ticket" for name, _ in session.calls)

def test_ticket_sent_with_confirmed_true_after_staff_yes():
    outcome, session = run(ScriptedPlanner([find(), ticket_decision(), finish()]), confirm=lambda q: True)
    sent = [args for name, args in session.calls if name == "create_support_ticket"]
    assert len(sent) == 1 and sent[0]["confirmed"] is True

# --- Critical routing and safety net ---

def test_critical_result_is_escalated_even_if_planner_finishes_early():
    outcome, session = run(ScriptedPlanner([find(), labs(), finish("all good")]))
    assert outcome["escalated"] == ["P1001"]
    assert any(name == "escalate_to_human" for name, _ in session.calls)

def test_budget_exhausted_before_safety_net_reports_not_escalated():
    # find + labs use 2 calls; with max_calls=2 the safety-net escalation cannot run.
    with pytest.raises(RuntimeError, match="NOT escalated"):
        run(ScriptedPlanner([find(), labs(), finish()]), max_calls=2)

# --- Limits ---

def test_planner_step_limit_stops_loop():
    decisions = [find()] * 10
    outcome, _ = run(ScriptedPlanner(decisions), max_steps=3)
    assert outcome["stop_reason"] == "planner step limit reached"

def test_call_budget_stops_planner_before_sixth_call():
    decisions = [find()] * 10
    outcome, session = run(ScriptedPlanner(decisions), max_calls=2, max_steps=10)
    assert outcome["stop_reason"] == "tool-call budget reached"
    assert len(session.calls) == 2

# --- Parsing ---

def test_parse_decision_call_tool():
    d = parse_decision('{"action": "call_tool", "tool": "find_patient", "arguments": {"patient_id": "P1001"}}')
    assert d.action == "call_tool" and d.tool == "find_patient"

def test_parse_decision_accepts_code_fence():
    d = parse_decision('```json\n{"action": "finish", "summary": "ok"}\n```')
    assert d.action == "finish" and d.summary == "ok"

def test_parse_decision_rejects_non_json():
    with pytest.raises(PlannerError):
        parse_decision("I think you should look at P1001")

def test_parse_decision_rejects_unknown_action():
    with pytest.raises(PlannerError):
        parse_decision('{"action": "delete", "tool": "x"}')

def test_parse_decision_rejects_bad_arguments_type():
    with pytest.raises(PlannerError):
        parse_decision('{"action": "call_tool", "tool": "find_patient", "arguments": "P1001"}')

# --- OllamaPlanner with a fake LLM (no Ollama server needed) ---

class FakeLLM:
    def __init__(self, reply):
        self.reply = reply
        self.received = None

    async def ainvoke(self, messages):
        self.received = messages
        return SimpleNamespace(content=self.reply)

def test_ollama_planner_parses_model_reply():
    llm = FakeLLM('{"action": "call_tool", "tool": "find_patient", "arguments": {"patient_id": "P1001"}}')
    decision = asyncio.run(OllamaPlanner(llm=llm).decide("task", [], ["find_patient"]))
    assert decision.tool == "find_patient"
    assert len(llm.received) == 2   # system + human message

def test_ollama_planner_invalid_reply_raises_planner_error():
    llm = FakeLLM("not json at all")
    with pytest.raises(PlannerError):
        asyncio.run(OllamaPlanner(llm=llm).decide("task", [], []))
