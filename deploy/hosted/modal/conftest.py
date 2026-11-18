import os

import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """With CORELATA_FORBID_SKIP=1 (CI) a skipped test fails, so importorskip cannot hide
    test_the_rendered_config_is_valid."""
    outcome = yield
    report = outcome.get_result()
    if os.environ.get("CORELATA_FORBID_SKIP") and report.skipped:
        report.outcome = "failed"
        report.longrepr = f"skipped, but skips are forbidden here: {item.nodeid}"
