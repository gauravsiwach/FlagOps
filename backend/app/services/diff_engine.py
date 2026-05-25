"""Diff engine — compares feature flag rules between two environments.

Moved here to follow the `services` package layout from architecture.md.
"""
import json
from typing import Any, Dict, List, Optional


def _condition_as_dict(condition: Any) -> Dict[str, Any]:
    if isinstance(condition, str):
        try:
            return json.loads(condition)
        except (ValueError, TypeError):
            return {}
    return condition if isinstance(condition, dict) else {}


def _rule_signature(rule: Optional[Dict[str, Any]]) -> Any:
    if rule is None:
        return None
    return {
        "type": rule.get("type"),
        "value": rule.get("value"),
        "condition": _condition_as_dict(rule.get("condition", {})),
    }


def _extract_market_rule(rules: List[Dict[str, Any]], market_code: str) -> Optional[Dict[str, Any]]:
    if not rules:
        return None

    for rule in rules:
        condition = _condition_as_dict(rule.get("condition", {}))
        if condition.get("countryCode") == market_code:
            return rule

    return rules[0] if rules else None


def compute_diff(
    source_flags: List[Dict[str, Any]],
    target_flags: List[Dict[str, Any]],
    market_code: str,
) -> List[Dict[str, Any]]:
    source_map = {f["flag_key"]: f for f in source_flags}
    target_map = {f["flag_key"]: f for f in target_flags}

    diff: List[Dict[str, Any]] = []

    for flag_key, source_flag in source_map.items():
        source_enabled = source_flag.get("enabled", False)
        source_rule = _extract_market_rule(source_flag.get("rules", []), market_code)

        if flag_key not in target_map:
            diff.append({
                "flag_key": flag_key,
                "source_rules": source_rule,
                "target_rules": None,
                "source_enabled": source_enabled,
                "target_enabled": False,
                "status": "missing",
                "last_modified_source": source_flag.get("last_modified"),
            })
        else:
            target_flag = target_map[flag_key]
            target_enabled = target_flag.get("enabled", False)
            target_rule = _extract_market_rule(target_flag.get("rules", []), market_code)

            if source_enabled and not target_enabled:
                status = "missing"
            elif not source_enabled and target_enabled:
                status = "updated"
            elif _rule_signature(source_rule) == _rule_signature(target_rule):
                status = "in_sync"
            else:
                status = "conflict"

            diff.append({
                "flag_key": flag_key,
                "source_rules": source_rule,
                "target_rules": target_rule,
                "source_enabled": source_enabled,
                "target_enabled": target_enabled,
                "status": status,
                "last_modified_source": source_flag.get("last_modified"),
            })

    for flag_key, target_flag in target_map.items():
        if flag_key not in source_map:
            target_rule = _extract_market_rule(target_flag.get("rules", []), market_code)
            diff.append({
                "flag_key": flag_key,
                "source_rules": None,
                "target_rules": target_rule,
                "source_enabled": False,
                "target_enabled": target_flag.get("enabled", False),
                "status": "updated",
                "last_modified_source": None,
            })

    return diff
