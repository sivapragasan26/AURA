import json
import pytest
from aura.agent.mock_provider import MockAIProvider


def test_mock_ai_provider_connection_and_analysis():
    provider = MockAIProvider()
    
    # 1. Test connection check
    success, msg = provider.test_connection()
    assert success is True
    assert "Mock" in msg

    # 2. Test analysis Candidate Findings output
    prompt = "Sample runtime evidence with Form elements must have labels and Images must have alt text"
    raw_json = provider.analyze(prompt)
    data = json.loads(raw_json)

    assert "overall_summary" in data
    assert "issues" in data
    assert len(data["issues"]) > 0

    first_issue = data["issues"][0]
    assert "id" in first_issue
    assert "observation" in first_issue
    assert "why_it_matters" in first_issue
    assert "recommendation" in first_issue

