# MCP Client Machine Test — Hospital Support Desk

## Goal
Build a Python MCP client that discovers tools from an MCP server, selects the right tool,
validates inputs, calls tools, handles failures, and stops safely. All records are synthetic.

## Scenario
A hospital support assistant receives requests from staff:
- Find a patient by ID
- Read recent lab results
- Create a support ticket for a missing/incorrect record
- Escalate a critical issue to a human

The MCP server owns the data and exposes tools. The MCP client does not read the JSON files
directly; it communicates with the server through the MCP protocol.

## Architecture / complete loop

Staff request
  -> MCP client (Python)
  -> initialize / capability negotiation
  -> tools/list (discover tool names + descriptions + input schemas)
  -> client chooses a tool
  -> tools/call (JSON arguments)
  -> MCP server validates and executes against synthetic data
  -> CallToolResult (text/structured content or isError)
  -> client parses result, handles errors, and decides whether another tool is needed
  -> final response to staff

Important: MCP is not "the model calling Python functions directly". The client and server
exchange protocol messages. Tool schemas tell the client what arguments a tool expects.

## Setup
Python 3.10+ recommended.

```bash
uv venv
source .venv/bin/activate        # Windows: .venv\\Scripts\\activate
uv pip install -r requirements.txt
```

## Run
```bash
uv run python client.py
```
The client launches `server.py` as a subprocess through `stdio_client`, so you do not need a
separate terminal for the server. The server uses stdio transport and is not a standalone HTTP
service.

To run the tests:
```bash
uv pip install pytest
uv run pytest tests/
```

## Machine test tasks (do these yourself first)
1. Connect to the server and complete the MCP initialization handshake.
2. Call `list_tools()` and print each tool's name, description, and input schema.
3. Implement `find_patient(patient_id)`.
4. Implement `get_lab_results(patient_id, limit)` and reject limits outside 1..10.
5. Implement a workflow: find patient -> get lab results -> produce a short summary.
6. If the patient does not exist, do not call the lab tool.
7. Create a support ticket only after explicit confirmation (`confirmed=True`).
8. Escalate a critical lab result to a human; do not attempt to diagnose or prescribe.
9. Add a retry for transient tool failures (maximum 2 retries; no retry for invalid input).
10. Add a maximum tool-call budget (e.g. 5 calls) so the workflow cannot loop forever.
11. Log tool name, arguments (redact sensitive fields), duration, and success/failure.
12. Write tests for unknown patient, empty lab results, invalid limit, and denied ticket creation.

## Expected tools
- `find_patient(patient_id: str)`
- `get_lab_results(patient_id: str, limit: int = 5)`
- `create_support_ticket(patient_id: str, category: str, description: str, confirmed: bool)`
- `escalate_to_human(patient_id: str, reason: str, priority: str)`

## Rules
- Synthetic data only. Do not add real patient records.
- Never expose full patient details in logs.
- Do not create a ticket unless confirmed is true.
- Do not interpret lab results as a medical diagnosis.
- A tool result with `isError=True` is a tool failure, not a successful answer.
- `tools/list` discovers tools; `tools/call` invokes a tool.
- The MCP server validates again. Client-side validation is useful but not a security boundary.

## Deliverables
- Working client and server
- Tool discovery output
- One successful patient workflow
- One failure workflow
- Tests and a short explanation of the message flow
