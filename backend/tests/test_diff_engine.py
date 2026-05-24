"""Unit tests for diff_engine.compute_diff and _extract_market_rule."""
import pytest
from app.services.diff_engine import compute_diff, _extract_market_rule

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

IN_RULE_TRUE = {
    "type": "force",
    "id": "in-rule-true",
    "value": "true",
    "condition": {"countryCode": "IN"},
}
IN_RULE_FALSE = {
    "type": "force",
    "id": "in-rule-false",
    "value": "false",
    "condition": {"countryCode": "IN"},
}
US_RULE = {
    "type": "force",
    "id": "us-rule",
    "value": "true",
    "condition": {"countryCode": "US"},
}


def flag(key, rules, enabled=True, last_modified="2026-01-01T00:00:00.000Z"):
    return {
        "flag_key": key,
        "rules": rules,
        "enabled": enabled,
        "last_modified": last_modified,
    }


# ---------------------------------------------------------------------------
# _extract_market_rule
# ---------------------------------------------------------------------------

class TestExtractMarketRule:
    def test_finds_matching_country_rule(self):
        result = _extract_market_rule([US_RULE, IN_RULE_TRUE], "IN")
        assert result == IN_RULE_TRUE

    def test_first_match_wins_when_multiple_au_rules(self):
        result = _extract_market_rule([IN_RULE_TRUE, IN_RULE_FALSE], "IN")
        assert result == IN_RULE_TRUE

    def test_falls_back_to_first_rule_when_no_match(self):
        result = _extract_market_rule([US_RULE], "IN")
        assert result == US_RULE

    def test_returns_none_for_empty_rules(self):
        assert _extract_market_rule([], "IN") is None

    def test_returns_none_for_none_rules(self):
        assert _extract_market_rule(None, "IN") is None


# ---------------------------------------------------------------------------
# compute_diff — single-flag scenarios
# ---------------------------------------------------------------------------

class TestComputeDiffSingleFlag:
    def test_in_sync_same_rules_both_enabled(self):
        diff = compute_diff(
            [flag("flag-a", [IN_RULE_TRUE])],
            [flag("flag-a", [IN_RULE_TRUE])],
            "IN",
        )
        assert len(diff) == 1
        assert diff[0]["status"] == "in_sync"
        assert diff[0]["source_rules"] == IN_RULE_TRUE
        assert diff[0]["target_rules"] == IN_RULE_TRUE

    def test_conflict_different_rule_values(self):
        diff = compute_diff(
            [flag("flag-a", [IN_RULE_TRUE])],
            [flag("flag-a", [IN_RULE_FALSE])],
            "IN",
        )
        assert diff[0]["status"] == "conflict"
        assert diff[0]["source_rules"] == IN_RULE_TRUE
        assert diff[0]["target_rules"] == IN_RULE_FALSE

    def test_missing_flag_absent_from_target(self):
        diff = compute_diff(
            [flag("flag-a", [IN_RULE_TRUE])],
            [],
            "IN",
        )
        assert diff[0]["status"] == "missing"
        assert diff[0]["target_rules"] is None

    def test_missing_flag_disabled_in_target(self):
        """Flag enabled in source, but disabled in target → missing (not yet promoted)."""
        diff = compute_diff(
            [flag("flag-a", [IN_RULE_TRUE], enabled=True)],
            [flag("flag-a", [],             enabled=False)],
            "IN",
        )
        assert diff[0]["status"] == "missing"

    def test_updated_flag_only_in_target(self):
        """Flag not in source but present and enabled in target → updated."""
        diff = compute_diff(
            [],
            [flag("flag-b", [IN_RULE_TRUE])],
            "IN",
        )
        assert diff[0]["status"] == "updated"
        assert diff[0]["source_rules"] is None
        assert diff[0]["target_rules"] == IN_RULE_TRUE

    def test_in_sync_both_empty_rules(self):
        """Two enabled flags with no rules are identical → in_sync."""
        diff = compute_diff(
            [flag("flag-a", [], enabled=True)],
            [flag("flag-a", [], enabled=True)],
            "IN",
        )
        assert diff[0]["status"] == "in_sync"

    def test_last_modified_propagated(self):
        ts = "2026-05-24T12:00:00.000Z"
        diff = compute_diff(
            [flag("flag-a", [IN_RULE_TRUE], last_modified=ts)],
            [flag("flag-a", [IN_RULE_FALSE])],
            "IN",
        )
        assert diff[0]["last_modified_source"] == ts


# ---------------------------------------------------------------------------
# compute_diff — multi-flag / mixed scenarios
# ---------------------------------------------------------------------------

class TestComputeDiffMultiFlag:
    def test_all_four_statuses_in_one_call(self):
        source = [
            flag("in-sync-flag",  [IN_RULE_TRUE]),
            flag("conflict-flag", [IN_RULE_TRUE]),
            flag("missing-flag",  [IN_RULE_TRUE]),
        ]
        target = [
            flag("in-sync-flag",  [IN_RULE_TRUE]),
            flag("conflict-flag", [IN_RULE_FALSE]),
            flag("updated-flag",  [IN_RULE_TRUE]),
        ]
        diff = compute_diff(source, target, "IN")
        by_key = {d["flag_key"]: d["status"] for d in diff}

        assert by_key["in-sync-flag"]  == "in_sync"
        assert by_key["conflict-flag"] == "conflict"
        assert by_key["missing-flag"]  == "missing"
        assert by_key["updated-flag"]  == "updated"
        assert len(diff) == 4

    def test_empty_source_and_target(self):
        assert compute_diff([], [], "IN") == []

    def test_non_au_market_code_uses_fallback(self):
        """With no GB rule, first rule is used for comparison — still diffed correctly."""
        diff = compute_diff(
            [flag("flag-a", [US_RULE])],
            [flag("flag-a", [US_RULE])],
            "IN",
        )
        # Falls back to US_RULE on both sides → in_sync
        assert diff[0]["status"] == "in_sync"

    def test_source_disabled_target_enabled_is_updated(self):
        """Flag disabled in source but enabled in target → updated."""
        diff = compute_diff(
            [flag("flag-a", [], enabled=False)],
            [flag("flag-a", [IN_RULE_TRUE], enabled=True)],
            "IN",
        )
        # Source has no enabled flag; target does — treated as updated
        # (source_enabled=False means it contributes to source_map but isn't "promoted")
        assert diff[0]["flag_key"] == "flag-a"
        assert diff[0]["status"] == "updated"
