import pytest
from aura.browser.interaction_policy import InteractionPolicy


def test_interaction_policy_safe_actions():
    # Safe navigation button click
    is_safe, reason = InteractionPolicy.is_action_safe("click", {"text": "View Dashboard", "tag": "a", "role": "link"})
    assert is_safe is True
    assert "permitted" in reason

    # Safe accordion expand
    is_safe_expand, _ = InteractionPolicy.is_action_safe("click", {"text": "Toggle Accordion", "tag": "button", "role": "tab"})
    assert is_safe_expand is True


def test_interaction_policy_blocked_actions():
    # Blocked purchase button
    is_safe_buy, reason_buy = InteractionPolicy.is_action_safe("click", {"text": "Buy Product Now", "tag": "button"})
    assert is_safe_buy is False
    assert "Blocked" in reason_buy

    # Blocked payment button
    is_safe_pay, reason_pay = InteractionPolicy.is_action_safe("click", {"text": "Proceed to Payment", "tag": "button"})
    assert is_safe_pay is False
    assert "Blocked" in reason_pay

    # Blocked delete account button
    is_safe_del, reason_del = InteractionPolicy.is_action_safe("click", {"text": "Delete My Account", "tag": "button"})
    assert is_safe_del is False
    assert "Blocked" in reason_del

    # Blocked password field
    is_safe_pass, reason_pass = InteractionPolicy.is_action_safe("input", {"tag": "input", "type": "password"})
    assert is_safe_pass is False
    assert "Blocked" in reason_pass

