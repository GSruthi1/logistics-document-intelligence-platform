"""Pure unit tests: no DB, no HTTP, no LLM — just the scoring logic on
hand-built inputs. This is the payoff of keeping ConfidenceScorer decoupled
from everything else.
"""
from app.extraction.base import FieldExtractionResult
from app.extraction.field_schema import FieldSpec, FieldType
from app.scoring.confidence_scorer import (
    FORMAT_MISMATCH_PENALTY,
    MISSING_OPTIONAL_CONFIDENCE_CAP,
    ConfidenceScorer,
)

scorer = ConfidenceScorer()


def test_valid_value_passes_through_raw_confidence():
    spec = FieldSpec("pickup_date", "d", FieldType.DATE, required=True)
    result = scorer.score_field(spec, FieldExtractionResult("pickup_date", "2026-01-05", 0.92))
    assert result.final_confidence == 0.92
    assert result.format_valid is True


def test_bad_date_format_is_penalized():
    spec = FieldSpec("pickup_date", "d", FieldType.DATE, required=True)
    result = scorer.score_field(spec, FieldExtractionResult("pickup_date", "March 5", 0.92))
    assert result.final_confidence == round(0.92 * FORMAT_MISMATCH_PENALTY, 4)
    assert result.format_valid is False


def test_bad_currency_format_is_penalized():
    spec = FieldSpec("total_charge", "d", FieldType.CURRENCY, required=True)
    result = scorer.score_field(spec, FieldExtractionResult("total_charge", "$1,245.50 USD", 0.8))
    assert result.format_valid is False
    assert result.final_confidence < 0.8


def test_valid_currency_with_commas_is_accepted():
    spec = FieldSpec("total_charge", "d", FieldType.CURRENCY, required=True)
    result = scorer.score_field(spec, FieldExtractionResult("total_charge", "1245.50", 0.8))
    assert result.format_valid is True
    assert result.final_confidence == 0.8


def test_missing_required_field_forces_zero_confidence():
    spec = FieldSpec("bol_number", "d", FieldType.STRING, required=True)
    result = scorer.score_field(spec, FieldExtractionResult("bol_number", None, 0.4))
    assert result.final_confidence == 0.0


def test_missing_optional_field_is_capped_not_zeroed():
    spec = FieldSpec("pro_number", "d", FieldType.STRING, required=False)
    result = scorer.score_field(spec, FieldExtractionResult("pro_number", None, 0.9))
    assert result.final_confidence <= MISSING_OPTIONAL_CONFIDENCE_CAP


def test_confidence_is_clamped_to_valid_range():
    spec = FieldSpec("shipper_name", "d", FieldType.STRING, required=True)
    # A misbehaving extractor reporting out-of-range confidence should never
    # propagate an invalid value into the DB's CHECK CONSTRAINT range [0,1].
    result = scorer.score_field(spec, FieldExtractionResult("shipper_name", "Acme", 1.7))
    assert 0.0 <= result.final_confidence <= 1.0


def test_score_all_handles_field_missing_from_llm_response_entirely():
    specs = [
        FieldSpec("bol_number", "d", FieldType.STRING, required=True),
        FieldSpec("shipper_name", "d", FieldType.STRING, required=True),
    ]
    # Simulate the model only returning one of two required fields.
    results = [FieldExtractionResult("bol_number", "BOL-1", 0.9)]
    scored = scorer.score_all(specs, results)
    by_name = {s.field_name: s for s in scored}
    assert by_name["bol_number"].final_confidence == 0.9
    assert by_name["shipper_name"].final_confidence == 0.0  # missing key treated as null, required -> 0
