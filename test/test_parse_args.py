import logging
from pathlib import Path
import pytest
from datalad_installer import (
    ComponentRequest,
    DataladInstaller,
    HelpRequest,
    ParsedArgs,
    UsageError,
    VersionRequest,
)


@pytest.mark.parametrize(
    "args,parsed",
    [
        ([], ParsedArgs({}, [])),
        (["datalad"], ParsedArgs({}, [ComponentRequest(name="datalad")])),
        (
            ["--log-level", "INFO", "datalad"],
            ParsedArgs(
                {"log_level": logging.INFO},
                [ComponentRequest(name="datalad")],
            ),
        ),
        (
            ["--log-level", "info", "datalad"],
            ParsedArgs(
                {"log_level": logging.INFO},
                [ComponentRequest(name="datalad")],
            ),
        ),
        (
            ["--log-level", "15", "datalad"],
            ParsedArgs(
                {"log_level": 15},
                [ComponentRequest(name="datalad")],
            ),
        ),
        (
            ["-E", "/path/to/file", "datalad"],
            ParsedArgs(
                {"env_write_file": [Path("/path/to/file")]},
                [ComponentRequest(name="datalad")],
            ),
        ),
        (
            ["-E", "/path/to/file", "--env-write-file=writefile", "datalad"],
            ParsedArgs(
                {"env_write_file": [Path("/path/to/file"), Path("writefile")]},
                [ComponentRequest(name="datalad")],
            ),
        ),
        (["--help"], HelpRequest(None)),
        (["--help", "datalad"], HelpRequest(None)),
        (["--help", "datalad", "--invalid"], HelpRequest(None)),
        (["datalad", "--help"], HelpRequest("datalad")),
        (["datalad", "--help", "invalid"], HelpRequest("datalad")),
        (["datalad", "--help", "git-annex", "--invalid"], HelpRequest("datalad")),
        (["--version"], VersionRequest()),
        (["--version", "datalad"], VersionRequest()),
        (["--version", "datalad", "--invalid"], VersionRequest()),
        (["--version", "invalid"], VersionRequest()),
        (
            ["git-annex", "-e", "--extra-opt"],
            ParsedArgs(
                {},
                [
                    ComponentRequest(
                        name="git-annex",
                        extra_args=["--extra-opt"],
                    )
                ],
            ),
        ),
        (
            ["git-annex", "-e", "--extra --opt"],
            ParsedArgs(
                {},
                [
                    ComponentRequest(
                        name="git-annex",
                        extra_args=["--extra", "--opt"],
                    )
                ],
            ),
        ),
        (
            [
                "git-annex",
                "-e",
                "--extra --opt",
                "datalad",
                "--extra-args",
                "--extra=opt",
            ],
            ParsedArgs(
                {},
                [
                    ComponentRequest(
                        name="git-annex",
                        extra_args=["--extra", "--opt"],
                    ),
                    ComponentRequest(
                        name="datalad",
                        extra_args=["--extra=opt"],
                    ),
                ],
            ),
        ),
        (
            ["venv", "--path", "/path/to/venv", "datalad", "--extras", "all"],
            ParsedArgs(
                {},
                [
                    ComponentRequest(
                        name="venv",
                        path=Path("/path/to/venv"),
                    ),
                    ComponentRequest(name="datalad", extras="all"),
                ],
            ),
        ),
        (
            ["datalad=0.13.0"],
            ParsedArgs({}, [ComponentRequest(name="datalad", version="0.13.0")]),
        ),
        (
            ["datalad=0.13.0", "-e", "-a -b -c"],
            ParsedArgs(
                {},
                [
                    ComponentRequest(
                        name="datalad",
                        version="0.13.0",
                        extra_args=["-a", "-b", "-c"],
                    )
                ],
            ),
        ),
        (
            ["git-annex", "--build-dep"],
            ParsedArgs(
                {},
                [ComponentRequest(name="git-annex", build_dep=True)],
            ),
        ),
        (
            ["git-annex", "--method", "auto"],
            ParsedArgs(
                {},
                [ComponentRequest(name="git-annex", method="auto")],
            ),
        ),
        (
            ["git-annex", "--method", "apt"],
            ParsedArgs(
                {},
                [ComponentRequest(name="git-annex", method="apt")],
            ),
        ),
        (
            ["conda-env", "--name", "foo"],
            ParsedArgs(
                {},
                [ComponentRequest(name="conda-env", envname="foo")],
            ),
        ),
    ],
)
def test_parse_args(args, parsed):
    assert DataladInstaller.parse_args(args) == parsed


@pytest.mark.parametrize(
    "args,message,component",
    [
        (["--invalid"], "option --invalid not recognized", None),
        (["--log-level", "42", "--invalid"], "option --invalid not recognized", None),
        (["--log-level", "invalid"], "Invalid log level: 'invalid'", None),
        (["--log-level"], "option --log-level requires argument", None),
        (["datalad", "--invalid"], "option --invalid not recognized", "datalad"),
        (["datalad=", "--invalid"], "Version must be nonempty", "datalad"),
        (["=0.13.0", "--invalid"], "Component name must be nonempty", None),
        (["invalid"], "Unknown component: 'invalid'", None),
        (["venv=1.2.3"], "venv component does not take a version", "venv"),
        (
            ["git-annex", "--method", "pip"],
            "Invalid choice for --method option: 'pip'",
            "git-annex",
        ),
        (
            ["venv", "--extra-args", "--foo 'bar"],
            '"--foo \'bar": No closing quotation',
            "venv",
        ),
    ],
)
def test_parse_args_errors(args, message, component):
    with pytest.raises(UsageError) as excinfo:
        DataladInstaller.parse_args(args)
    assert str(excinfo.value) == message
    assert excinfo.value.component == component
