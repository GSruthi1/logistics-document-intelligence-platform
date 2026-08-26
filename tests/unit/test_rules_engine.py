"""Unit tests for individual Rule classes and the YAML config loader —
no DB, no HTTP.
"""

from app.validation.rules_config import load_rules
from app.validation.rules_engine import (
    AllowedValuesRule,
    DateNotFutureRule,
    DateOrderRule,
    PositiveNumberRule,
    RequiredRule,
    RulesEngine,
)


def test_required_rule_fails_on_missing_value():
    rule = RequiredRule("shipper_name")
    outcome = rule.evaluate({"shipper_name": None})
    assert outcome.passed is False
    assert outcome.field_name == "shipper_name"


def test_required_rule_fails_on_blank_string():
    rule = RequiredRule("shipper_name")
    outcome = rule.evaluate({"shipper_name": "   "})
    assert outcome.passed is False


def test_required_rule_passes_on_value():
    rule = RequiredRule("shipper_name")
    outcome = rule.evaluate({"shipper_name": "Acme Corp"})
    assert outcome.passed is True


def test_positive_number_rule_rejects_zero_and_negative():
    rule = PositiveNumberRule("total_weight_lbs")
    assert rule.evaluate({"total_weight_lbs": "0"}).passed is False
    assert rule.evaluate({"total_weight_lbs": "-5"}).passed is False
    assert rule.evaluate({"total_weight_lbs": "100"}).passed is True


def test_positive_number_rule_enforces_max():
    rule = PositiveNumberRule("total_weight_lbs", max_value=80000)
    assert rule.evaluate({"total_weight_lbs": "999999"}).passed is False


def test_positive_number_rule_ignores_absence():
    # Presence is RequiredRule's job; PositiveNumberRule shouldn't double-flag.
    rule = PositiveNumberRule("total_weight_lbs")
    assert rule.evaluate({"total_weight_lbs": None}).passed is True


def test_date_not_future_rule():
    rule = DateNotFutureRule("pickup_date")
    assert rule.evaluate({"pickup_date": "2020-01-01"}).passed is True
    assert rule.evaluate({"pickup_date": "2099-01-01"}).passed is False


def test_date_order_rule():
    rule = DateOrderRule("invoice_date", "payment_due_date")
    assert rule.evaluate({"invoice_date": "2026-01-01", "payment_due_date": "2026-02-01"}).passed is True
    assert rule.evaluate({"invoice_date": "2026-03-01", "payment_due_date": "2026-02-01"}).passed is False


def test_allowed_values_rule_is_case_insensitive():
    rule = AllowedValuesRule("signature_present", allowed=["yes", "no"])
    assert rule.evaluate({"signature_present": "YES"}).passed is True
    assert rule.evaluate({"signature_present": "maybe"}).passed is False


def test_yaml_config_loads_all_three_doc_types():
    rules = load_rules()
    assert set(rules.keys()) == {"bill_of_lading", "proof_of_delivery", "freight_invoice"}
    assert len(rules["bill_of_lading"]) > 0


def test_engine_runs_configured_rules_for_doc_type():
    rules = load_rules()
    engine = RulesEngine(rules)
    good_pod = {
        "pro_number": "PRO-1", "consignee_name": "Widget Co", "delivery_date": "2026-01-05",
        "received_by": "J. Smith", "signature_present": "yes",
    }
    outcomes = engine.validate("proof_of_delivery", good_pod)
    assert all(o.passed for o in outcomes)


def test_engine_returns_empty_for_unconfigured_doc_type():
    engine = RulesEngine({})
    assert engine.validate("bill_of_lading", {}) == []
