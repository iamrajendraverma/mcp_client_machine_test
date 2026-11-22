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

# Add tests for:
# - client rejects limit=0 and limit=11 before making a tool call
# - ticket creation is blocked when confirmed=False
# - unknown tool name is rejected
# - tool-call budget prevents a sixth call
# - server returns not-found for an unknown patient
