import asyncio
import json
import logging
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import sys
import uuid
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

SERVER = Path(__file__).with_name("server.py")
MAX_CALL_THRESHOLD =5

class MCPClient:
    def __init__(self, session: ClientSession, max_calls: int = 5):
        self.session = session
        self.max_calls = max_calls
        self.calls = 0
        self.available_tools = {}
        self.run_id = uuid.uuid4().hex[:8]   # one ID for this workflow run

    async def discover_tools(self):
        response = await self.session.list_tools()
        self.available_tools = {tool.name: tool for tool in response.tools}
        print("\\n DISCOVERED TOOLS")
        for tool in response.tools:
            print(f"- {tool.name}: {tool.description}")
            print("  inputSchema:", json.dumps(tool.inputSchema, indent=2))
        return response.tools

    async def call_tool(self, name: str, arguments: dict, retries: int = 2):
        if name not in self.available_tools:
            raise ValueError(f"Tool not discovered: {name}")
        if self.calls >= self.max_calls:
            raise RuntimeError("Tool-call budget exhausted; stopping workflow")
        self.calls += 1
        call_id = f"{self.run_id}-{self.calls}"

        # Lightweight client-side checks. The server must still validate independently.
        if name == "get_lab_results":
            limit = arguments.get("limit", 5)
            if not isinstance(limit, int) or not 1 <= limit <= 10:
                raise ValueError("Client validation: limit must be an integer from 1 to 10")
        if name == "create_support_ticket" and arguments.get("confirmed") is not True:
            raise PermissionError("Ticket creation requires confirmed=True")

        attempt = 0
        while True:
            started = time.perf_counter()
            try:
                result = await self.session.call_tool(name, arguments)
                elapsed = round((time.perf_counter() - started) * 1000, 2)
                logging.info("run=%s call=%s tool=%s args=%s duration_ms=%s is_error=%s",
                             self.run_id, call_id, name, redact(arguments), elapsed, result.isError)
                if result.isError:
                    # Do not blindly retry validation/business errors.
                    raise RuntimeError(extract_text(result))
                return result
            except (TimeoutError, ConnectionError):
                if attempt >= retries:
                    raise
                attempt += 1
                await asyncio.sleep(0.25 * attempt)

def redact(args):
    safe = dict(args)
    for key in ("patient_id", "description", "reason"):
        if key in safe:
            safe[key] = "[REDACTED]"
    return safe

def extract_text(result):
    """
    extract_text function extract the result of toolcall function
    """
    parts = []
    for item in result.content:
        if hasattr(item, "text") and item.text:
            parts.append(item.text)
    return "\\n".join(parts) or "Tool returned no text content"

class ToolResponseError(Exception):
    pass

def parse_result(result) -> dict:
    """Turn a CallToolResult into a dict, or raise ToolResponseError."""
    if result.isError:
        raise ToolResponseError(extract_text(result))
    if result.structuredContent is not None:
        data = result.structuredContent
    else:
        text = extract_text(result)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ToolResponseError(f"Non-JSON tool response: {text[:200]}") from exc
    if not isinstance(data, dict):
        raise ToolResponseError(f"Expected a JSON object, got {type(data).__name__}")
    return data

async def run_demo():
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER)],
        env=None
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            # ClientSession.initialize() performs the MCP initialization handshake.
            init = await session.initialize()
            print("========================")
            print(f"Connected server name {init.serverInfo.name} and server version {init.serverInfo.version}")
            print("========================")

            client = MCPClient(session, max_calls=MAX_CALL_THRESHOLD)
            await client.discover_tools()

            # Workflow: identify patient -> fetch labs -> escalate critical result.
            patient_result = await client.call_tool("find_patient", {"patient_id": "P1001"})
            patient_text = parse_result(patient_result)
            print("🧍‍♂️PATIENT RESULT: found =", patient_text.get("found"))

            if patient_text.get("found") is True:
                lab_result = await client.call_tool(
                    "get_lab_results", {"patient_id": "P1001", "limit": 5}
                )
                labs = parse_result(lab_result)
                flags = [row.get("flag") for row in labs.get("results", [])]
                print("🧪 LAB RESULT: count =", labs.get("count"), "flags =", flags)

                # Simple demo routing rule; not a medical interpretation.
                if any(row.get("flag") == "critical" for row in labs.get("results", [])):
                    escalation = await client.call_tool(
                        "escalate_to_human",
                        {"patient_id": "P1001",
                         "reason": "A lab record is flagged critical; please review.",
                         "priority": "urgent"}
                    )
                    esc = parse_result(escalation)
                    print("ESCALATION: id =", esc.get("escalation_id"), "status =", esc.get("status"))

            print("CLIENT FINISHED. Tool calls:", client.calls)

if __name__ == "__main__":
    asyncio.run(run_demo())
