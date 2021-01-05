import pytest
from datalad_installer import compose_pip_requirement


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
