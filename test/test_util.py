from typing import Dict
import pytest
from datalad_installer import compose_pip_requirement, parse_header_links


@pytest.mark.parametrize(
    "package,version,urlspec,extras,req",
    [
        ("foobar", None, None, None, "foobar"),
        ("foobar", "1.2.3", None, None, "foobar==1.2.3"),
        (
            "foobar",
            None,
            "git+https://github.com/example/foobar.git",
            None,
            "foobar @ git+https://github.com/example/foobar.git",
        ),
        ("foobar", None, None, "all", "foobar[all]"),
        ("foobar", "1.2.3", None, "all", "foobar[all]==1.2.3"),
        (
            "foobar",
            "1.2.3",
            "git+https://github.com/example/foobar.git",
            None,
            "foobar @ git+https://github.com/example/foobar.git@1.2.3",
        ),
        (
            "foobar",
            "1.2.3",
            "git+https://github.com/example/foobar.git",
            "all",
            "foobar[all] @ git+https://github.com/example/foobar.git@1.2.3",
        ),
        (
            "foobar",
            None,
            "git+https://github.com/example/foobar.git",
            "all",
            "foobar[all] @ git+https://github.com/example/foobar.git",
        ),
    ],
)
def test_compose_pip_requirement(package, version, urlspec, extras, req):
    assert compose_pip_requirement(package, version, urlspec, extras) == req


@pytest.mark.parametrize(
    "url,links",
    [
        (
            "<https://api.github.com/repositories/346061402/actions/workflows/"
            'test.yml/runs?page=2>; rel="next", <https://api.github.com/'
            "repositories/346061402/actions/workflows/test.yml/runs?page=6>;"
            ' rel="last"',
            {
                "next": {
                    "url": (
                        "https://api.github.com/repositories/346061402/actions/"
                        "workflows/test.yml/runs?page=2"
                    ),
                    "rel": "next",
                },
                "last": {
                    "url": (
                        "https://api.github.com/repositories/346061402/actions/"
                        "workflows/test.yml/runs?page=6"
                    ),
                    "rel": "last",
                },
            },
        ),
        (
            "<https://api.github.com/repositories/346061402/actions/workflows/"
            'test.yml/runs?page=1>; rel="prev", <https://api.github.com/'
            "repositories/346061402/actions/workflows/test.yml/runs?page=3>;"
            ' rel="next", <https://api.github.com/repositories/346061402/actions/'
            'workflows/test.yml/runs?page=6>; rel="last", <https://api.github.com/'
            "repositories/346061402/actions/workflows/test.yml/runs?page=1>;"
            ' rel="first"',
            {
                "first": {
                    "url": (
                        "https://api.github.com/repositories/346061402/actions/"
                        "workflows/test.yml/runs?page=1"
                    ),
                    "rel": "first",
                },
                "prev": {
                    "url": (
                        "https://api.github.com/repositories/346061402/actions/"
                        "workflows/test.yml/runs?page=1"
                    ),
                    "rel": "prev",
                },
                "next": {
                    "url": (
                        "https://api.github.com/repositories/346061402/actions/"
                        "workflows/test.yml/runs?page=3"
                    ),
                    "rel": "next",
                },
                "last": {
                    "url": (
                        "https://api.github.com/repositories/346061402/actions/"
                        "workflows/test.yml/runs?page=6"
                    ),
                    "rel": "last",
                },
            },
        ),
        (
            "<https://api.github.com/repositories/346061402/actions/workflows/"
            'test.yml/runs?page=5>; rel="prev", <https://api.github.com/'
            "repositories/346061402/actions/workflows/test.yml/runs?page=1>;"
            ' rel="first"',
            {
                "first": {
                    "url": (
                        "https://api.github.com/repositories/346061402/actions/"
                        "workflows/test.yml/runs?page=1"
                    ),
                    "rel": "first",
                },
                "prev": {
                    "url": (
                        "https://api.github.com/repositories/346061402/actions/"
                        "workflows/test.yml/runs?page=5"
                    ),
                    "rel": "prev",
                },
            },
        ),
    ],
)
def test_parse_header_links(url: str, links: Dict[str, dict]) -> None:
    assert parse_header_links(url) == links
