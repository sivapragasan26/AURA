import pytest
from aura.utils.helpers import validate_url
from aura.browser.interaction_policy import InteractionPolicy


def test_url_validation():
    assert validate_url("http://example.com") is True
    assert validate_url("https://example.com/path?arg=1") is True
    assert validate_url("http://127.0.0.1:8999") is True
    
    assert validate_url("ftp://example.com") is False
    assert validate_url("javascript:alert(1)") is False
    assert validate_url("not_a_url") is False
    assert validate_url("") is False


def test_same_origin_policy():
    current = "https://example.com/page1"
    
    assert InteractionPolicy.is_same_origin(current, "https://example.com/page2") is True
    assert InteractionPolicy.is_same_origin(current, "#section") is True
    assert InteractionPolicy.is_same_origin(current, "/relative/path") is True
    assert InteractionPolicy.is_same_origin(current, "https://evil-site.com/path") is False


def test_interaction_policy_same_origin_enforcement():
    current_url = "https://example.com"
    
    safe_nav = {"tag": "a", "text": "About Us", "href": "https://example.com/about"}
    is_safe, reason = InteractionPolicy.is_action_safe("click", safe_nav, current_url=current_url)
    assert is_safe is True

    offsite_nav = {"tag": "a", "text": "External Partner", "href": "https://external-domain.com"}
    is_safe, reason = InteractionPolicy.is_action_safe("click", offsite_nav, current_url=current_url)
    assert is_safe is False
    assert "same-origin" in reason.lower()

