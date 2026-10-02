import pytest
from aura.analyzers.dom_analyzer import DOMAnalyzer
from aura.models.findings import ElementMetadata


def test_element_metadata_v02_fields():
    elem = ElementMetadata(
        tag="button",
        role="button",
        accessible_name="Submit Form",
        text="Submit",
        aria_label="Submit Form",
        visible=True,
        bounding_box={"x": 10, "y": 20, "width": 100, "height": 40}
    )
    assert elem.tag == "button"
    assert elem.role == "button"
    assert elem.accessible_name == "Submit Form"
    assert elem.visible is True
    assert elem.bounding_box["width"] == 100


def test_dom_summary_categorization_v02():
    raw_data = [
        {"tag": "button", "text": "Click Me", "accessible_name": "Click Me", "visible": True, "bounding_box": {"x": 0, "y": 0, "width": 50, "height": 20}},
        {"tag": "a", "text": "Home", "href": "/home", "visible": True, "bounding_box": {"x": 0, "y": 0, "width": 40, "height": 20}},
        {"tag": "input", "type": "text", "id": "username", "placeholder": "Enter username", "visible": True, "bounding_box": {"x": 0, "y": 0, "width": 100, "height": 30}}
    ]

    elements = [ElementMetadata(**r) for r in raw_data]

    buttons = [e.model_dump(by_alias=True) for e in elements if e.tag == "button"]
    links = [e.model_dump(by_alias=True) for e in elements if e.tag == "a"]
    inputs = [e.model_dump(by_alias=True) for e in elements if e.tag == "input"]

    assert len(buttons) == 1
    assert len(links) == 1
    assert len(inputs) == 1
    assert inputs[0]["placeholder"] == "Enter username"
