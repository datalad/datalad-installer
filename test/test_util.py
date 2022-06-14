from pathlib import Path
from typing import Dict, Optional
import pytest
from datalad_installer import compose_pip_requirement, parse_header_links, untmppaths


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
def test_compose_pip_requirement(
    package: str,
    version: Optional[str],
    urlspec: Optional[str],
    extras: Optional[str],
    req: str,
) -> None:
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


def test_untmppaths() -> None:
    p1, p2, p3, p4 = untmppaths(
        Path("{tmpdir}", "foo.txt"),
        None,
        Path("{tmpdir}", "bar", "quux.dat"),
        Path("xyzzy", "plugh"),
    )
    assert isinstance(p1, Path)
    assert p1.name == "foo.txt"
    tmpdir = p1.parent
    assert p2 is None
    assert p3 == tmpdir / "bar" / "quux.dat"
    assert p4 == Path("xyzzy", "plugh")


def test_untmppaths_no_tmpdir() -> None:
    assert untmppaths(Path("foo.txt"), Path("bar", "baz.txt")) == (
        Path("foo.txt"),
        Path("bar", "baz.txt"),
    )
