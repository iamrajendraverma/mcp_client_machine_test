# Assessment rubric (100 points)

| Area | Points | What good looks like |
|---|---:|---|
| MCP lifecycle | 15 | initialize handshake; understands session and stdio transport |
| Discovery | 15 | tools/list; prints names, descriptions, JSON input schemas |
| Invocation | 20 | tools/call with correctly shaped arguments; parses CallToolResult |
| Workflow | 15 | patient lookup gates lab lookup; critical flag routes to human |
| Safety | 15 | explicit confirmation for write action; no diagnosis; server validation |
| Reliability | 10 | bounded retries, error handling, timeout awareness, call budget |
| Observability | 10 | redacted logs, duration, success/error tracking |

## Viva questions
1. What is the difference between `tools/list` and `tools/call`?
2. Who defines the input schema, client or server?
3. What happens during `initialize()`?
4. Why should the server validate arguments even if the client validates them?
5. What does `CallToolResult.isError` mean?
6. Why is stdio useful for a local MCP server?
7. What is the difference between a protocol error and a tool execution error?
8. Why should a write operation require confirmation?
9. Why must retries be bounded and selective?
10. What prevents an agent from repeatedly calling tools forever?

## Stretch tasks
- Add `lookup_order` or `search_records` tool.
- Add JSON structured output and robust parsing.
- Add a request correlation ID to logs.
- Add a configurable timeout and cancellation.
- Add pagination to `get_lab_results`.
- Replace the fixed workflow with an LLM planner, while keeping tool permissions and call budget outside the model.



#### Viva Answer

1. What is the difference between **tool/call** and **tool/list** ?
Ans : tool/list  and tool/call are two important operation in MCP. We call tool/list as tool discovery also. It gives the list of all tools avaiable in MCP at the response. tool/call is to request the perticular tool to fix the problem. It gives one tool schema in the response. 


1.1 . tool/list request
```json 
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list"
}
```
1.2 tool/list response 

```json 
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [
      {
        "name": "create_jira_ticket",
        "description": "Create a Jira ticket",
        "inputSchema": {
          "type": "object",
          "properties": {
            "title": {
              "type": "string"
            },
            "description": {
              "type": "string"
            },
            "priority": {
              "type": "string"
            }
          },
          "required": ["title", "description"]
        }
      },
      {
        "name": "get_jira_ticket",
        "description": "Get Jira ticket details",
        "inputSchema": {
          "type": "object",
          "properties": {
            "ticket_id": {
              "type": "string"
            }
          },
          "required": ["ticket_id"]
        }
      }
    ]
  }
}
```
2.1 tool/call request 

```json 
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "create_jira_ticket",
    "arguments": {
      "title": "Login authentication failure",
      "description": "Users are unable to log in.",
      "priority": "High"
    }
  }
}
```
2.2 tool/call response 

```json 
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Jira ticket created successfully. Ticket ID: JIRA-101"
      }
    ],
    "isError": false
  }
}
```
2. Who defines the input schema, client or server ? 
Ans : Input schema defines by MCP server developers.

```python 
@mcp.tool()
def find_patient(patient_id: str) -> dict:
    """Find a synthetic patient using the exact patient ID."""
    patient = next((p for p in patients if p["patient_id"] == patient_id), None)
    if not patient:
        return {"found": False, "message": "Patient not found"}
    return {"found": True, "patient": patient}
```
Let's discuss how it works 

```text
       Developer 
write the method and it's signature
          |
          |
       Fast API 
Automatically generates the input schema bases on the hints and input signature
          |
          |
      MCP server
MCP server expose the schema using tool/list
          |
          |
    MCP Client/LLM
Read the schema & prepare valid argument
          |
          | 
     MCP server
     validate the arguments
           &
     execute the function
```

3. What happens during `initialize()`?

Ans : Client Start the MCP communication. `initialize()` performs the initial handshake between the MCP Client and MCP Server.

It has 3 main responsibilities:
1. **Protocol negotiation:** Client and server agree on a supported MCP protocol version.
2. **Capability exchange:** Client and server share which features they support, such as tools, resources, prompts, and sampling.
3.  **Client/Server identification:** They exchange application name and version information.


Complete flow

Step 1: Client → Server


Sends initialize request containing:
- protocolVersion
- capabilities
- clientInfo

Step 2: Server → Client

Returns:
- Negotiated protocolVersion
- Server capabilities
- serverInfo

Step 3: Client → Server

Sends:

```json
{
  "jsonrpc": "2.0",
  "method": "notifications/initialized"
}
```
This confirms that initialization is complete.

#### What happens next?


The client can now start normal MCP communication:

```text 
initialize
    ↓
notifications/initialized
    ↓
tools/list
    ↓
tools/call
    ↓
Tool execution
    ↓
Tool response
```

`initialize()` establishes the communication session. It does not execute tools or retrieve the tool list.