import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP

BASE = Path(__file__).parent
patients = json.loads((BASE / "data/patients.json").read_text())
labs = json.loads((BASE / "data/lab_results.json").read_text())
tickets = []
escalations = []

mcp = FastMCP("hospital-support-server")

@mcp.tool()
def find_patient(patient_id: str) -> dict:
    """Find a synthetic patient using the exact patient ID."""
    patient = next((p for p in patients if p["patient_id"] == patient_id), None)
    if not patient:
        return {"found": False, "message": "Patient not found"}
    return {"found": True, "patient": patient}

@mcp.tool()
def get_lab_results(patient_id: str, limit: int = 5) -> dict:
    """Get the most recent synthetic lab results for a patient. Limit must be 1..10."""
    if not 1 <= limit <= 10:
        raise ValueError("limit must be between 1 and 10")
    rows = [r for r in labs if r["patient_id"] == patient_id]
    rows.sort(key=lambda r: r["collected_at"], reverse=True)
    return {"patient_id": patient_id, "count": min(limit, len(rows)), "results": rows[:limit]}

@mcp.tool()
def create_support_ticket(patient_id: str, category: str, description: str, confirmed: bool) -> dict:
    """Create a support ticket. Requires explicit confirmed=true."""
    if not confirmed:
        raise ValueError("Human confirmation is required before ticket creation")
    if not any(p["patient_id"] == patient_id for p in patients):
        raise ValueError("Unknown patient_id")
    ticket = {"ticket_id": f"T{len(tickets)+5001}", "patient_id": patient_id,
              "category": category, "description": description, "status": "open"}
    tickets.append(ticket)
    return ticket

@mcp.tool()
def escalate_to_human(patient_id: str, reason: str, priority: str = "high") -> dict:
    """Escalate a patient-record issue to a human team. This is not medical diagnosis."""
    if not any(p["patient_id"] == patient_id for p in patients):
        raise ValueError("Unknown patient_id")
    if priority not in {"normal", "high", "urgent"}:
        raise ValueError("priority must be normal, high, or urgent")
    item = {"escalation_id": f"E{len(escalations)+7001}", "patient_id": patient_id,
            "reason": reason, "priority": priority, "status": "queued"}
    escalations.append(item)
    return item

if __name__ == "__main__":
    mcp.run(transport="stdio")
