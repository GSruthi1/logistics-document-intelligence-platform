"""
The business rules engine.

Deliberate design point: rule *logic* (this file) and rule *configuration*
(rules_config.yaml) are separate. A client's ops/compliance team wants to
change "max shipment weight is 80,000 lbs" to 60,000 lbs, or add a rule that
freight charges over $50,000 always require review — that should be a YAML
edit and a redeploy, never a pull request touching Python. This is the same
separation-of-concerns principle as the rest of the pipeline, applied to
business logic instead of code.

Each Rule is a small class with one job: given the document's field values,
decide pass/fail and produce a message. The engine just runs the configured
list of rules for a doc_type and collects outcomes — it has zero knowledge of
what a "PRO number" or "pickup date" means.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass
class RuleOutcome:
    rule_name: str
    field_name: str | None
    passed: bool
    message: str | None
    severity: str  # "error" | "warning"


class Rule(ABC):
    def __init__(self, name: str, severity: str = "error"):
        self.name = name
        self.severity = severity

    @abstractmethod
    def evaluate(self, fields: dict[str, str | None]) -> RuleOutcome:
        raise NotImplementedError

    def _outcome(self, passed: bool, field_name: str | None, message: str | None) -> RuleOutcome:
        return RuleOutcome(self.name, field_name, passed, None if passed else message, self.severity)


class RequiredRule(Rule):
    """Field must be present and non-blank."""

    def __init__(self, field: str, **kw):
        super().__init__(name=f"required:{field}", **kw)
        self.field = field

    def evaluate(self, fields: dict[str, str | None]) -> RuleOutcome:
        value = fields.get(self.field)
        passed = value is not None and value.strip() != ""
        return self._outcome(passed, self.field, f"'{self.field}' is required but missing")


class PositiveNumberRule(Rule):
    """Field must parse as a number > 0, optionally under a max (sanity bound
    against e.g. a mis-extracted weight of 8,000,000 lbs).
    """

    def __init__(self, field: str, max_value: float | None = None, **kw):
        super().__init__(name=f"positive_number:{field}", **kw)
        self.field = field
        self.max_value = max_value

    def evaluate(self, fields: dict[str, str | None]) -> RuleOutcome:
        raw = fields.get(self.field)
        if raw is None or raw.strip() == "":
            return self._outcome(True, self.field, None)  # absence is RequiredRule's job, not this rule's
        try:
            num = float(raw.replace(",", ""))
        except ValueError:
            return self._outcome(False, self.field, f"'{self.field}' value '{raw}' is not numeric")
        if num <= 0:
            return self._outcome(False, self.field, f"'{self.field}' must be > 0, got {num}")
        if self.max_value is not None and num > self.max_value:
            return self._outcome(
                False, self.field, f"'{self.field}' value {num} exceeds sanity max {self.max_value}"
            )
        return self._outcome(True, self.field, None)


class DateNotFutureRule(Rule):
    """Field, if present, must not be a date after today — catches obvious
    extraction errors (e.g. year mis-read as 2126) as well as bad source data.
    """

    def __init__(self, field: str, **kw):
        super().__init__(name=f"date_not_future:{field}", **kw)
        self.field = field

    def evaluate(self, fields: dict[str, str | None]) -> RuleOutcome:
        raw = fields.get(self.field)
        if raw is None or raw.strip() == "":
            return self._outcome(True, self.field, None)
        try:
            parsed = date.fromisoformat(raw.strip())
        except ValueError:
            return self._outcome(False, self.field, f"'{self.field}' value '{raw}' is not a valid ISO date")
        passed = parsed <= date.today()
        return self._outcome(passed, self.field, f"'{self.field}' date {raw} is in the future")


class DateOrderRule(Rule):
    """`earlier_field` must be on or before `later_field` (e.g. invoice_date
    <= payment_due_date). This is the canonical example of a rule that can't
    live on a single field — it's why validation_results.field_name is
    nullable and rules aren't attached 1:1 to ExtractedField rows.
    """

    def __init__(self, earlier_field: str, later_field: str, **kw):
        super().__init__(name=f"date_order:{earlier_field}<={later_field}", **kw)
        self.earlier_field = earlier_field
        self.later_field = later_field

    def evaluate(self, fields: dict[str, str | None]) -> RuleOutcome:
        earlier_raw = fields.get(self.earlier_field)
        later_raw = fields.get(self.later_field)
        if not earlier_raw or not later_raw:
            return self._outcome(True, None, None)  # can't compare if either side is missing
        try:
            earlier = date.fromisoformat(earlier_raw.strip())
            later = date.fromisoformat(later_raw.strip())
        except ValueError:
            return self._outcome(True, None, None)  # format errors are each field's own DATE rule's job
        passed = earlier <= later
        msg = f"'{self.earlier_field}' ({earlier_raw}) is after '{self.later_field}' ({later_raw})"
        return self._outcome(passed, None, msg)


class AllowedValuesRule(Rule):
    """Field, if present, must be one of a fixed set (case-insensitive)."""

    def __init__(self, field: str, allowed: list[str], **kw):
        super().__init__(name=f"allowed_values:{field}", **kw)
        self.field = field
        self.allowed = {v.lower() for v in allowed}

    def evaluate(self, fields: dict[str, str | None]) -> RuleOutcome:
        raw = fields.get(self.field)
        if raw is None or raw.strip() == "":
            return self._outcome(True, self.field, None)
        passed = raw.strip().lower() in self.allowed
        return self._outcome(
            passed, self.field, f"'{self.field}' value '{raw}' not in allowed set {sorted(self.allowed)}"
        )


RULE_TYPE_REGISTRY: dict[str, type[Rule]] = {
    "required": RequiredRule,
    "positive_number": PositiveNumberRule,
    "date_not_future": DateNotFutureRule,
    "date_order": DateOrderRule,
    "allowed_values": AllowedValuesRule,
}


class RulesEngine:
    def __init__(self, rules_by_doc_type: dict[str, list[Rule]]):
        self.rules_by_doc_type = rules_by_doc_type

    def validate(self, doc_type: str, fields: dict[str, str | None]) -> list[RuleOutcome]:
        rules = self.rules_by_doc_type.get(doc_type, [])
        return [rule.evaluate(fields) for rule in rules]
