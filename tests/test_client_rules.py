import pytest
from client import redact

def test_redacts_patient_id():
    assert redact({"patient_id": "P1001", "limit": 3}) == {
        "patient_id": "[REDACTED]", "limit": 3
    }

def test_does_not_change_non_sensitive_fields():
    assert redact({"limit": 5, "category": "records"}) == {
        "limit": 5, "category": "records"
    }

import asyncio
import json

from mcp.types import CallToolResult, TextContent

import server
from client import MCPClient, ToolResponseError, get_all_lab_results, parse_result

# --- Server-side pagination (P1001 has 2 lab rows in data/lab_results.json) ---

def test_first_page_points_to_next_page():
    page = server.get_lab_results("P1001", limit=1, offset=0)
    assert page["total"] == 2
    assert page["count"] == 1
    assert page["next_offset"] == 1

def test_last_page_has_null_next_offset():
    page = server.get_lab_results("P1001", limit=1, offset=1)
    assert page["count"] == 1
    assert page["next_offset"] is None

def test_offset_past_end_returns_empty_page():
    page = server.get_lab_results("P1001", limit=5, offset=10)
    assert page["count"] == 0
    assert page["results"] == []
    assert page["next_offset"] is None

def test_negative_offset_is_rejected_by_server():
    try:
        server.get_lab_results("P1001", limit=5, offset=-1)
        assert False, "expected ValueError"
    except ValueError:
        pass

# --- Client-side pagination through a fake session that serves server pages ---

class FakeSession:
    """Stands in for ClientSession: answers get_lab_results by calling server.py directly."""
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        data = server.get_lab_results(**arguments)
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(data))],
                              isError=False)

def _client_with_tools(session, max_calls=5):
    client = MCPClient(session, max_calls=max_calls)
    client.available_tools = {"get_lab_results": object()}
    return client

def test_get_all_lab_results_walks_every_page():
    session = FakeSession()
    client = _client_with_tools(session)
    rows = asyncio.run(get_all_lab_results(client, "P1001", page_size=1))
    assert [r["result_id"] for r in rows] == ["L9002", "L9001"]
    assert len(session.calls) == 2          # one tool call per page
    assert client.calls == 2

def test_get_all_lab_results_stops_at_max_pages():
    session = FakeSession()
    client = _client_with_tools(session)
    try:
        asyncio.run(get_all_lab_results(client, "P1001", page_size=1, max_pages=1))
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass

def test_client_rejects_negative_offset_before_tool_call():
    session = FakeSession()
    client = _client_with_tools(session)
    try:
        asyncio.run(client.call_tool("get_lab_results", {"patient_id": "P1001", "offset": -1}))
        assert False, "expected ValueError"
    except ValueError:
        pass
    assert session.calls == []
    assert client.calls == 0

# --- Parsing helper ---

def test_parse_result_reads_json_text():
    result = CallToolResult(content=[TextContent(type="text", text='{"found": true}')],
                            isError=False)
    assert parse_result(result) == {"found": True}

def test_parse_result_rejects_non_json_text():
    result = CallToolResult(content=[TextContent(type="text", text="not json")], isError=False)
    try:
        parse_result(result)
        assert False, "expected ToolResponseError"
    except ToolResponseError:
        pass

# Still to add (from the original list):
# - client rejects limit=0 and limit=11 before making a tool call
# - ticket creation is blocked when confirmed=False
# - unknown tool name is rejected
# - tool-call budget prevents a sixth call
# - server returns not-found for an unknown patient
