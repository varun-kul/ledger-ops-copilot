from fastapi.testclient import TestClient

from app.api.main import app

client = TestClient(app)


def test_summary_endpoint_returns_expected_shape():
    response = client.get("/api/summary")
    assert response.status_code == 200
    data = response.json()
    assert "reconciliation" in data
    assert "fraud" in data
    assert "alertworthy" in data
    assert data["alertworthy"]["flags"] <= data["alertworthy"]["total_flags"]


def test_breaks_endpoint_filters_by_severity():
    all_breaks = client.get("/api/breaks").json()
    critical_only = client.get("/api/breaks?severity=critical").json()
    assert critical_only["count"] <= all_breaks["count"]
    assert all(b["severity"] == "critical" for b in critical_only["breaks"])


def test_fraud_flags_endpoint_alertworthy_filter_reduces_count():
    all_flags = client.get("/api/fraud-flags").json()
    alertworthy = client.get("/api/fraud-flags?alertworthy_only=true").json()
    assert alertworthy["count"] < all_flags["count"]  # this is the week 3 feedback-cycle fix


def test_copilot_ask_endpoint_returns_grounded_answer_with_sources():
    response = client.post("/api/copilot/ask", json={"question": "which transactions had amount mismatches?"})
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert len(data["sources"]) > 0
    assert all("txn_ref" in s["doc_id"] or "break::" in s["doc_id"] for s in data["sources"])


def test_dashboard_route_serves_html():
    response = client.get("/")
    assert response.status_code == 200
    assert "LedgerOps Copilot" in response.text