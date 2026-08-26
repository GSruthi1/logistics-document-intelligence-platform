"""
Integration tests: real FastAPI TestClient, real Postgres (the test DB, via
the `client`/`db_session` fixtures in conftest.py), fake LLM extractor. These
exercise the full pipeline — extract -> score -> validate -> route -> persist
-> HITL queue -> correction — the way an actual client of this API would.
"""
from app.extraction.base import ExtractionOutput
from app.models.audit_log import AuditLog
from tests.conftest import make_field, png_bytes

GOOD_BOL_FIELDS = {
    "bol_number": "BOL-1001",
    "shipper_name": "Acme Corp",
    "shipper_address": "123 Main St, Springfield",
    "consignee_name": "Widget Co",
    "consignee_address": "456 Oak Ave, Metropolis",
    "carrier_name": "FastFreight Inc",
    "pro_number": "PRO-500",
    "pickup_date": "2026-01-05",
    "total_weight_lbs": "4200",
    "piece_count": "12",
    "freight_charge_terms": "Prepaid",
}


def _bol_extraction_output(overrides: dict[str, tuple[str | None, float]] | None = None) -> ExtractionOutput:
    overrides = overrides or {}
    fields = []
    for name, value in GOOD_BOL_FIELDS.items():
        v, conf = overrides.get(name, (value, 0.95))
        fields.append(make_field(name, v, conf))
    return ExtractionOutput(fields=fields, model_used="fake-model-v1", extraction_method="llm")


def _upload(client, fake_extractor, extraction_output, filename="bol.png"):
    fake_extractor.next_output = extraction_output
    return client.post(
        "/extract",
        files={"file": (filename, png_bytes(), "image/png")},
        data={"doc_type": "bill_of_lading"},
    )


def test_health_check(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_high_confidence_clean_document_is_auto_approved(client, fake_extractor):
    resp = _upload(client, fake_extractor, _bol_extraction_output())
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "auto_approved"
    assert body["queued_for_review"] is False
    assert body["queue_item_id"] is None
    assert len(body["fields"]) == len(GOOD_BOL_FIELDS)
    assert all(v["passed"] for v in body["validation_results"])


def test_low_confidence_field_routes_to_hitl_queue(client, fake_extractor):
    output = _bol_extraction_output(overrides={"shipper_name": ("Acme Corp", 0.4)})
    resp = _upload(client, fake_extractor, output)
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "in_review"
    assert body["queued_for_review"] is True
    assert body["queue_item_id"] is not None


def test_validation_error_routes_to_hitl_queue_even_with_high_confidence(client, fake_extractor):
    # Confidence is high, but pickup_date is in the future -> a hard business
    # rule failure. This proves routing isn't purely confidence-driven.
    output = _bol_extraction_output(overrides={"pickup_date": ("2099-01-01", 0.99)})
    resp = _upload(client, fake_extractor, output)
    body = resp.json()
    assert body["queued_for_review"] is True
    failed_rules = [v for v in body["validation_results"] if not v["passed"]]
    assert any("date_not_future" in v["rule_name"] for v in failed_rules)


def test_queued_document_appears_in_queue_listing(client, fake_extractor):
    output = _bol_extraction_output(overrides={"shipper_name": (None, 0.0)})
    upload_resp = _upload(client, fake_extractor, output)
    queue_item_id = upload_resp.json()["queue_item_id"]

    list_resp = client.get("/queue")
    assert list_resp.status_code == 200
    ids = [item["id"] for item in list_resp.json()]
    assert queue_item_id in ids

    detail_resp = client.get(f"/queue/{queue_item_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["status"] == "pending"


def test_correcting_a_queued_field_resolves_it(client, fake_extractor, db_session):
    output = _bol_extraction_output(overrides={"shipper_name": (None, 0.0)})
    upload_resp = _upload(client, fake_extractor, output)
    queue_item_id = upload_resp.json()["queue_item_id"]

    correct_resp = client.patch(
        f"/queue/{queue_item_id}/correct",
        json={
            "corrections": [{"field_name": "shipper_name", "corrected_value": "Acme Corporation"}],
            "corrected_by": "reviewer@example.com",
        },
    )
    assert correct_resp.status_code == 200
    body = correct_resp.json()
    assert body["status"] == "resolved"
    corrected_field = next(f for f in body["fields"] if f["field_name"] == "shipper_name")
    assert corrected_field["field_value"] == "Acme Corporation"
    assert corrected_field["final_confidence"] == 1.0

    # Audit trail: the correction must be traceable to who made it.
    audit_rows = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "corrected")
        .all()
    )
    assert any(row.actor == "reviewer@example.com" for row in audit_rows)


def test_correcting_unknown_field_returns_400(client, fake_extractor):
    output = _bol_extraction_output(overrides={"shipper_name": (None, 0.0)})
    upload_resp = _upload(client, fake_extractor, output)
    queue_item_id = upload_resp.json()["queue_item_id"]

    resp = client.patch(
        f"/queue/{queue_item_id}/correct",
        json={"corrections": [{"field_name": "not_a_real_field", "corrected_value": "x"}],
              "corrected_by": "reviewer@example.com"},
    )
    assert resp.status_code == 400


def test_unknown_doc_type_is_rejected(client, fake_extractor):
    fake_extractor.next_output = _bol_extraction_output()
    resp = client.post(
        "/extract",
        files={"file": ("x.png", png_bytes(), "image/png")},
        data={"doc_type": "not_a_real_type"},
    )
    assert resp.status_code == 400


def test_unsupported_content_type_is_rejected(client, fake_extractor):
    resp = client.post(
        "/extract",
        files={"file": ("x.txt", b"hello", "text/plain")},
        data={"doc_type": "bill_of_lading"},
    )
    assert resp.status_code == 400


def test_duplicate_upload_is_deduplicated_by_content_hash(client, fake_extractor):
    output = _bol_extraction_output()
    fake_extractor.next_output = output
    file_bytes = png_bytes()

    resp1 = client.post("/extract", files={"file": ("bol.png", file_bytes, "image/png")}, data={"doc_type": "bill_of_lading"})
    resp2 = client.post("/extract", files={"file": ("bol.png", file_bytes, "image/png")}, data={"doc_type": "bill_of_lading"})

    assert resp1.json()["document_id"] == resp2.json()["document_id"]
    # The extractor should only have been invoked once — the whole point of
    # hashing uploads is to avoid paying for a second LLM call on a repeat.
    assert len(fake_extractor.calls) == 1
