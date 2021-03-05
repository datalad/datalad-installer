import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--ci",
        action="store_true",
        default=False,
        help="Enable CI-only tests",
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--ci"):
        skip_no_ci = pytest.mark.skip(reason="Only run when --ci is given")
        for item in items:
            if "ci_only" in item.keywords:
                item.add_marker(skip_no_ci)
