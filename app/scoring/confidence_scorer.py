"""
ConfidenceScorer: turns the LLM's raw, self-reported confidence into the
`final_confidence` that routing decisions actually use.

Why not just trust the model's own number? Two reasons, both real:
  1. LLM self-reported confidence is known to be poorly calibrated — models
     say "0.95" while being wrong at a much higher rate than 5%. It's a
     useful *signal*, not a *probability*.
  2. It can't see structural problems: a model can be "confident" about a
     value that is nonetheless the wrong shape (e.g. "March 3rd" reported at
     0.9 confidence for a field that must be ISO YYYY-MM-DD, or a required
     field that came back null).

So this module treats raw_confidence as one input and applies deterministic,
testable heuristics on top of it. That combination is what gets logged as
`final_confidence` and is what the router/validator compare against the
approval threshold — never raw_confidence directly.
"""
from dataclasses import dataclass
from datetime import date

from app.extraction.base import FieldExtractionResult
from app.extraction.field_schema import FieldSpec, FieldType

# Format-mismatch and missing-required-field penalties are multiplicative on
# top of the model's raw confidence, not hardcoded final values — this keeps
# "the model was very sure" vs "the model was so-so" distinguishable even
# after a penalty is applied, which matters for ranking HITL queue priority.
FORMAT_MISMATCH_PENALTY = 0.5
MISSING_REQUIRED_CONFIDENCE = 0.0
MISSING_OPTIONAL_CONFIDENCE_CAP = 0.3


@dataclass
class ScoredField:
    field_name: str
    value: str | None
    raw_confidence: float
    final_confidence: float
    format_valid: bool


class ConfidenceScorer:
    def score_field(self, spec: FieldSpec, result: FieldExtractionResult) -> ScoredField:
        raw = max(0.0, min(1.0, result.confidence))

        if result.value is None or result.value.strip() == "":
            final = MISSING_REQUIRED_CONFIDENCE if spec.required else min(raw, MISSING_OPTIONAL_CONFIDENCE_CAP)
            return ScoredField(spec.name, result.value, raw, final, format_valid=not spec.required)

        format_valid = _is_valid_format(result.value, spec.field_type)
        final = raw if format_valid else raw * FORMAT_MISMATCH_PENALTY
        final = round(max(0.0, min(1.0, final)), 4)

        return ScoredField(spec.name, result.value, raw, final, format_valid)

    def score_all(
        self, specs: list[FieldSpec], results: list[FieldExtractionResult]
    ) -> list[ScoredField]:
        by_name = {r.field_name: r for r in results}
        scored = []
        for spec in specs:
            result = by_name.get(spec.name)
            if result is None:
                # Model didn't return this field at all (shouldn't happen given
                # our tool schema requires every field, but never trust that
                # blindly — treat a missing key the same as an explicit null).
                result = FieldExtractionResult(field_name=spec.name, value=None, confidence=0.0)
            scored.append(self.score_field(spec, result))
        return scored


def _is_valid_format(value: str, field_type: FieldType) -> bool:
    value = value.strip()
    if field_type == FieldType.DATE:
        try:
            date.fromisoformat(value)
            return True
        except ValueError:
            return False
    if field_type in (FieldType.NUMBER, FieldType.CURRENCY):
        try:
            float(value.replace(",", ""))
            return True
        except ValueError:
            return False
    return True  # STRING fields have no format constraint to validate
