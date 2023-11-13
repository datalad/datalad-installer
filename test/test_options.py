from __future__ import annotations
import logging
from pathlib import Path
from typing import Optional
import pytest
from datalad_installer import (
    ComponentRequest,
    DataladInstaller,
    HelpRequest,
    Immediate,
    Option,
    ParsedArgs,
    SudoConfirm,
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
            ["--sudo", "ask", "datalad"],
            ParsedArgs(
                {"sudo": SudoConfirm.ASK},
                [ComponentRequest(name="datalad")],
            ),
        ),
        (
            ["--sudo", "error", "datalad"],
            ParsedArgs(
                {"sudo": SudoConfirm.ERROR},
                [ComponentRequest(name="datalad")],
            ),
        ),
        (
            ["--sudo", "ok", "datalad"],
            ParsedArgs(
                {"sudo": SudoConfirm.OK},
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
                        kwargs={"extra_args": ["--extra-opt"]},
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
                        kwargs={"extra_args": ["--extra", "--opt"]},
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
                        kwargs={"extra_args": ["--extra", "--opt"]},
                    ),
                    ComponentRequest(
                        name="datalad",
                        kwargs={"extra_args": ["--extra=opt"]},
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
                        kwargs={"path": Path("/path/to/venv")},
                    ),
                    ComponentRequest(name="datalad", kwargs={"extras": "all"}),
                ],
            ),
        ),
        (
            ["datalad=0.13.0"],
            ParsedArgs(
                {}, [ComponentRequest(name="datalad", kwargs={"version": "0.13.0"})]
            ),
        ),
        (
            ["datalad=0.13.0", "-e", "-a -b -c"],
            ParsedArgs(
                {},
                [
                    ComponentRequest(
                        name="datalad",
                        kwargs={
                            "version": "0.13.0",
                            "extra_args": ["-a", "-b", "-c"],
                        },
                    )
                ],
            ),
        ),
        (
            ["git-annex", "--build-dep"],
            ParsedArgs(
                {},
                [ComponentRequest(name="git-annex", kwargs={"build_dep": True})],
            ),
        ),
        (
            ["git-annex", "--method", "auto"],
            ParsedArgs(
                {},
                [ComponentRequest(name="git-annex", kwargs={"method": "auto"})],
            ),
        ),
        (
            ["git-annex", "--method", "apt"],
            ParsedArgs(
                {},
                [ComponentRequest(name="git-annex", kwargs={"method": "apt"})],
            ),
        ),
        (
            ["conda-env", "--name", "foo"],
            ParsedArgs(
                {},
                [ComponentRequest(name="conda-env", kwargs={"envname": "foo"})],
            ),
        ),
        (
            ["datalad", "miniconda", "--help-versions"],
            HelpRequest("miniconda", topic="versions"),
        ),
    ],
)
def test_parse_args(args: list[str], parsed: Immediate | ParsedArgs) -> None:
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
        (["--sudo", "invalid"], "Invalid choice for --sudo option: 'invalid'", None),
    ],
)
def test_parse_args_errors(
    args: list[str], message: str, component: Optional[str]
) -> None:
    with pytest.raises(UsageError) as excinfo:
        DataladInstaller.parse_args(args)
    assert str(excinfo.value) == message
    assert excinfo.value.component == component


@pytest.mark.parametrize(
    "option,helptext",
    [
        (
            Option("-f", "--foo"),
            "  -f, --foo FOO",
        ),
        (
            Option("-f", "--foo", is_flag=True),
            "  -f, --foo",
        ),
        (
            Option("-f", "--foo", help="Foo all the things"),
            "  -f, --foo FOO                   Foo all the things",
        ),
        (
            Option("-f", "--foo", is_flag=True, help="Foo all the things"),
            "  -f, --foo                       Foo all the things",
        ),
        (
            Option("-f", "--foo", metavar="PARAM", help="Foo all the things"),
            "  -f, --foo PARAM                 Foo all the things",
        ),
        (
            Option(
                "-f",
                "--foo",
                choices=["apple", "banana", "coconut"],
                help="Foo all the things",
            ),
            "  -f, --foo [apple|banana|coconut]\n"
            "                                  Foo all the things",
        ),
        (
            Option(
                "-f",
                "--foo",
                help=(
                    "Lorem ipsum dolor sit amet, consectetur adipisicing elit,"
                    " sed do eiusmod tempor incididunt ut labore et dolore"
                    " magna aliqua."
                ),
            ),
            "  -f, --foo FOO                   Lorem ipsum dolor sit amet, consectetur\n"
            "                                  adipisicing elit, sed do eiusmod tempor\n"
            "                                  incididunt ut labore et dolore magna\n"
            "                                  aliqua.",
        ),
    ],
)
def test_option_get_help(option: Option, helptext: str) -> None:
    assert option.get_help() == helptext


def test_global_short_help() -> None:
    assert DataladInstaller.short_help("datalad_installer") == (
        "Usage: datalad_installer [<options>] [COMPONENT[=VERSION] [<options>]] ..."
    )


def test_component_short_help() -> None:
    assert DataladInstaller.short_help("datalad_installer", "venv") == (
        "Usage: datalad_installer [<options>] venv [<options>]"
    )


def test_versioned_component_short_help() -> None:
    assert DataladInstaller.short_help("datalad_installer", "git-annex") == (
        "Usage: datalad_installer [<options>] git-annex[=VERSION] [<options>]"
    )


def test_global_long_help() -> None:
    assert DataladInstaller.long_help("datalad_installer") == (
        "Usage: datalad_installer [<options>] [COMPONENT[=VERSION] [<options>]] ...\n"
        "\n"
        "  Installation script for Datalad and related components\n"
        "\n"
        "  `datalad-installer` is a script for installing Datalad, git-annex, and\n"
        "  related components all in a single invocation.  It requires no third-party\n"
        "  Python libraries, though it does make heavy use of external packaging\n"
        "  commands.\n"
        "\n"
        "  See the README at <https://github.com/datalad/datalad-installer> for a\n"
        "  complete description of all options.\n"
        "\n"
        "Options:\n"
        "  -E, --env-write-file ENV_WRITE_FILE\n"
        "                                  Append PATH modifications and other\n"
        "                                  shell commands to the given file; can be\n"
        "                                  given multiple times\n"
        "  -l, --log-level LEVEL           Set logging level [default: INFO]\n"
        "  --sudo [ask|error|ok]           How to handle sudo commands [default:\n"
        "                                  ask]\n"
        "  -V, --version                   Show program version and exit\n"
        "  -h, --help                      Show this help information and exit\n"
        "\n"
        "Components:\n"
        "  conda-env                Create a Conda environment\n"
        "  datalad                  Install Datalad\n"
        "  git-annex                Install git-annex\n"
        "  git-annex-remote-rclone  Install git-annex-remote-rclone\n"
        "  miniconda                Install Miniconda\n"
        "  neurodebian              Install & configure NeuroDebian\n"
        "  rclone                   Install rclone\n"
        "  venv                     Create a Python virtual environment"
    )


def test_component_long_help() -> None:
    assert DataladInstaller.long_help("datalad_installer", "venv") == (
        "Usage: datalad_installer [<options>] venv [<options>]\n"
        "\n"
        "  Create a Python virtual environment\n"
        "\n"
        "Options:\n"
        "  --dev-pip                       Install the development version of pip\n"
        "                                  from GitHub\n"
        "  -e, --extra-args EXTRA_ARGS     Extra arguments to pass to the venv\n"
        "                                  command\n"
        "  --path PATH                     Create the venv at the given path\n"
        "  -h, --help                      Show this help information and exit"
    )


def test_versioned_component_long_help() -> None:
    assert DataladInstaller.long_help("datalad_installer", "git-annex") == (
        "Usage: datalad_installer [<options>] git-annex[=VERSION] [<options>]\n"
        "\n"
        "  Install git-annex\n"
        "\n"
        "Options:\n"
        "  --build-dep                     Install build-dep instead of the package\n"
        "  -e, --extra-args EXTRA_ARGS     Extra arguments to pass to the install\n"
        "                                  command\n"
        "  --install-dir DIR               Directory in which to unpack the `*.deb`\n"
        "  -m, --method [auto|apt|brew|neurodebian|deb-url|autobuild|snapshot|"
        "conda|datalad/git-annex:tested|datalad/git-annex|"
        "datalad/git-annex:release|datalad/packages|dmg]\n"
        "                                  Select the installation method to use\n"
        "  --path PATH                     Path to local `*.dmg` to install\n"
        "  --url URL                       URL from which to download `*.deb` file\n"
        "  -h, --help                      Show this help information and exit"
    )
