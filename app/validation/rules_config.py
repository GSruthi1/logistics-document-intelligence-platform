"""
Loads rules_config.yaml into RulesEngine-ready Rule objects.

Kept separate from rules_engine.py so the engine module has zero knowledge of
YAML/file I/O — it just executes a list of Rule objects, which makes it
trivial to unit test with rules constructed directly in Python (no fixture
file needed) while the loader is tested separately against the real YAML.
"""
from functools import lru_cache
from pathlib import Path

import yaml

from app.validation.rules_engine import RULE_TYPE_REGISTRY, Rule, RulesEngine

DEFAULT_CONFIG_PATH = Path(__file__).parent / "rules_config.yaml"


def load_rules(config_path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, list[Rule]]:
    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    rules_by_doc_type: dict[str, list[Rule]] = {}
    for doc_type, rule_defs in raw.items():
        rules = []
        for rule_def in rule_defs:
            rule_def = dict(rule_def)  # don't mutate the parsed YAML in place
            rule_type = rule_def.pop("type")
            rule_cls = RULE_TYPE_REGISTRY.get(rule_type)
            if rule_cls is None:
                raise ValueError(
                    f"Unknown rule type '{rule_type}' for doc_type '{doc_type}' in "
                    f"{config_path}. Known types: {list(RULE_TYPE_REGISTRY)}"
                )
            rules.append(rule_cls(**rule_def))
        rules_by_doc_type[doc_type] = rules
    return rules_by_doc_type


@lru_cache
def get_rules_engine() -> RulesEngine:
    return RulesEngine(load_rules())
