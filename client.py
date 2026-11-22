import asyncio
import json
import logging
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

SERVER = Path(__file__).with_name("server.py")
MAX_CALL_THRESHOLD =5

class MCPClient:
    def __init__(self, session: ClientSession, max_calls: int = 5):
        self.session = session
        self.max_calls = max_calls
        self.calls = 0
        self.available_tools = {}

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
                logging.info("tool=%s args=%s duration_ms=%s is_error=%s",
                             name, redact(arguments), elapsed, result.isError)
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
    parts = []
    for item in result.content:
        if hasattr(item, "text") and item.text:
            parts.append(item.text)
    return "\\n".join(parts) or "Tool returned no text content"

async def run_demo():
    params = StdioServerParameters(
        command="python",
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
            patient_text = extract_text(patient_result)
            print("\\nPATIENT RESULT:", patient_text)

            if "found" in patient_text.lower() and "false" not in patient_text.lower():
                lab_result = await client.call_tool(
                    "get_lab_results", {"patient_id": "P1001", "limit": 5}
                )
                lab_text = extract_text(lab_result)
                print("\\nLAB RESULT:", lab_text)

                # Simple demo routing rule; not a medical interpretation.
                if "critical" in lab_text.lower():
                    escalation = await client.call_tool(
                        "escalate_to_human",
                        {"patient_id": "P1001",
                         "reason": "A lab record is flagged critical; please review.",
                         "priority": "urgent"}
                    )
                    print("\\nESCALATION:", extract_text(escalation))

            print("\\nCLIENT FINISHED. Tool calls:", client.calls)

if __name__ == "__main__":
    asyncio.run(run_demo())
