import time
import pytest
from test_lab.launcher import TestLabLauncher
from aura.engine import AURAEngine
from aura.config import settings


@pytest.fixture(scope="module", autouse=True)
def setup_test_lab():
    TestLabLauncher.start_server()
    time.sleep(0.5)
    yield
    TestLabLauncher.stop_server()


def test_suite_01_accessibility():
    engine = AURAEngine()
    url = f"http://127.0.0.1:{settings.TEST_LAB_PORT}/01_accessibility_suite/"
    report_data = engine.run_analysis(url=url, headless=True)
    
    aggregation = report_data["aggregation"]
    assert len(aggregation.findings) >= 1


def test_suite_02_ui_ux():
    engine = AURAEngine()
    url = f"http://127.0.0.1:{settings.TEST_LAB_PORT}/02_ui_ux_suite/"
    report_data = engine.run_analysis(url=url, headless=True)
    
    aggregation = report_data["aggregation"]
    assert len(aggregation.findings) >= 1


def test_suite_03_navigation_interaction():
    engine = AURAEngine()
    url = f"http://127.0.0.1:{settings.TEST_LAB_PORT}/03_navigation_interaction_suite/"
    report_data = engine.run_analysis(url=url, headless=True)
    
    aggregation = report_data["aggregation"]
    assert len(aggregation.findings) >= 1


def test_suite_04_responsive_runtime():
    engine = AURAEngine()
    url = f"http://127.0.0.1:{settings.TEST_LAB_PORT}/04_responsive_runtime_suite/"
    report_data = engine.run_analysis(url=url, headless=True)
    
    aggregation = report_data["aggregation"]
    assert len(aggregation.findings) >= 1


def test_suite_05_mixed_realistic():
    engine = AURAEngine()
    url = f"http://127.0.0.1:{settings.TEST_LAB_PORT}/05_mixed_realistic_suite/"
    report_data = engine.run_analysis(url=url, headless=True)
    
    aggregation = report_data["aggregation"]
    assert len(aggregation.findings) >= 1
