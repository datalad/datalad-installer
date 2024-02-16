#!/usr/bin/env python3
"""
Installation script for Datalad and related components

``datalad-installer`` is a script for installing Datalad_, git-annex_, and
related components all in a single invocation.  It requires no third-party
Python libraries, though it does make heavy use of external packaging commands.

.. _Datalad: https://www.datalad.org
.. _git-annex: https://git-annex.branchable.com

Visit <https://github.com/datalad/datalad-installer> for more information.
"""

from __future__ import annotations

__version__ = "1.0.4"
__author__ = "The DataLad Team and Contributors"
__author_email__ = "team@datalad.org"
__license__ = "MIT"
__url__ = "https://github.com/datalad/datalad-installer"

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
import ctypes
from dataclasses import InitVar, dataclass, field
from email import policy
from email.headerregistry import ContentTypeHeader
from enum import Enum
from functools import total_ordering
from getopt import GetoptError, getopt
from html.parser import HTMLParser
from http.client import HTTPMessage
from itertools import groupby
import json
import logging
from operator import attrgetter
import os
import os.path
from pathlib import Path
import platform
from random import randrange
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
from time import sleep
from typing import IO, Any, ClassVar, NamedTuple, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
    install_opener,
    urlopen,
)
from zipfile import ZipFile

log = logging.getLogger("datalad_installer")

SYSTEM = platform.system()
ON_LINUX = SYSTEM == "Linux"
ON_MACOS = SYSTEM == "Darwin"
ON_WINDOWS = SYSTEM == "Windows"
ON_POSIX = ON_LINUX or ON_MACOS

USER_AGENT = "datalad-installer/{} ({}) {}/{}".format(
    __version__,
    __url__,
    platform.python_implementation(),
    platform.python_version(),
)


class SudoConfirm(Enum):
    ASK = "ask"
    ERROR = "error"
    OK = "ok"


def parse_log_level(level: str) -> int:
    """
    Convert a log level name (case-insensitive) or number to its numeric value
    """
    try:
        lv = int(level)
    except ValueError:
        levelup = level.upper()
        if levelup in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            ll = getattr(logging, levelup)
            assert isinstance(ll, int)
            return ll
        else:
            raise UsageError(f"Invalid log level: {level!r}")
    else:
        return lv


@dataclass
class Immediate:
    """
    Superclass for constructs returned by the argument-parsing code
    representing options that are handled "immediately" (i.e., --version and
    --help)
    """

    pass


@dataclass
class VersionRequest(Immediate):
    """`Immediate` representing a ``--version`` option"""

    pass


@dataclass
class HelpRequest(Immediate):
    """`Immediate` representing a ``--help`` or ``--help-TOPIC`` option"""

    #: The component for which help was requested, or `None` if the ``--help``
    #: option was given at the global level
    component: Optional[str]

    #: The topic for which help was requested via a ``--help-TOPIC`` option, or
    #: `None` if just a ``--help`` option was given
    topic: Optional[str] = None


SHORT_RGX = re.compile(r"-[^-]")
LONG_RGX = re.compile(r"--[^-].*")

OPTION_COLUMN_WIDTH = 30
OPTION_HELP_COLUMN_WIDTH = 40
HELP_GUTTER = 2
HELP_INDENT = 2
HELP_WIDTH = 75


@total_ordering
class Option:
    def __init__(
        self,
        *names: str,
        is_flag: bool = False,
        converter: Optional[Callable[[str], Any]] = None,
        multiple: bool = False,
        immediate: Optional[Immediate] = None,
        metavar: Optional[str] = None,
        choices: Optional[list[str]] = None,
        help: Optional[str] = None,  # noqa: A002
    ) -> None:
        #: List of individual option characters
        self.shortopts: list[str] = []
        #: List of long option names (sans leading "--")
        self.longopts: list[str] = []
        dest: Optional[str] = None
        self.is_flag: bool = is_flag
        self.converter: Optional[Callable[[str], Any]] = converter
        self.multiple: bool = multiple
        self.immediate: Optional[Immediate] = immediate
        self.metavar: Optional[str] = metavar
        self.choices: Optional[list[str]] = choices
        self.help: Optional[str] = help
        for n in names:
            if n.startswith("-"):
                if LONG_RGX.fullmatch(n):
                    self.longopts.append(n[2:])
                elif SHORT_RGX.fullmatch(n):
                    self.shortopts.append(n[1])
                else:
                    raise ValueError(f"Invalid option: {n!r}")
            elif dest is not None:
                raise ValueError("More than one option destination specified")
            else:
                dest = n
        if not self.shortopts and not self.longopts:
            raise ValueError("No options supplied to Option constructor")
        self.dest: str
        if dest is None:
            self.dest = (self.longopts + self.shortopts)[0].replace("-", "_")
        else:
            self.dest = dest

    def __eq__(self, other: Any) -> bool:
        if type(self) is type(other):
            return bool(vars(self) == vars(other))
        else:
            return NotImplemented

    def __lt__(self, other: Any) -> bool:
        if type(self) is type(other):
            return bool(self._cmp_key() < other._cmp_key())
        else:
            return NotImplemented

    def _cmp_key(self) -> tuple[int, str]:
        name = self.option_name
        if name.startswith("--help"):
            return (2, name)
        elif name == "--version":
            return (1, "--version")
        else:
            return (0, name)

    @property
    def option_name(self) -> str:
        """Display name for the option"""
        if self.longopts:
            return f"--{self.longopts[0]}"
        else:
            assert self.shortopts
            return f"-{self.shortopts[0]}"

    def process(self, namespace: dict[str, Any], argument: str) -> Optional[Immediate]:
        if self.immediate is not None:
            return self.immediate
        if self.is_flag:
            namespace[self.dest] = True
        else:
            if self.choices is not None and argument not in self.choices:
                raise UsageError(
                    f"Invalid choice for {self.option_name} option: {argument!r}"
                )
            if self.converter is None:
                value = argument
            else:
                value = self.converter(argument)
            if self.multiple:
                namespace.setdefault(self.dest, []).append(value)
            else:
                namespace[self.dest] = value
        return None

    def get_help(self) -> str:
        options = []
        for o in self.shortopts:
            options.append(f"-{o}")
        for o in self.longopts:
            options.append(f"--{o}")
        header = ", ".join(options)
        if not self.is_flag:
            if self.metavar is not None:
                metavar = self.metavar
            elif self.choices is not None:
                metavar = f"[{'|'.join(self.choices)}]"
            elif self.longopts:
                metavar = self.longopts[0].upper().replace("-", "_")
            else:
                metavar = "ARG"
            header += " " + metavar
        if self.help is not None:
            helplines = textwrap.wrap(self.help, OPTION_HELP_COLUMN_WIDTH)
        else:
            helplines = []
        if len(header) > OPTION_COLUMN_WIDTH:
            lines2 = [header]
            remainder = helplines
        elif helplines:
            lines2 = [
                header.ljust(OPTION_COLUMN_WIDTH) + " " * HELP_GUTTER + helplines[0]
            ]
            remainder = helplines[1:]
        else:
            lines2 = [header]
            remainder = []
        for r in remainder:
            lines2.append(" " * (OPTION_COLUMN_WIDTH + HELP_GUTTER) + r)
        return textwrap.indent("\n".join(lines2), " " * HELP_INDENT)


@dataclass
class OptionParser:
    component: Optional[str] = None
    versioned: bool = False
    help: Optional[str] = None
    options: InitVar[Optional[list[Option]]] = None
    #: Mapping from option names (including leading hyphens) to Option
    #: instances
    options_map: dict[str, Option] = field(init=False, default_factory=dict)

    def __post_init__(self, options: Optional[list[Option]]) -> None:
        self.add_option(
            Option(
                "-h",
                "--help",
                is_flag=True,
                immediate=HelpRequest(self.component),
                help="Show this help information and exit",
            )
        )
        if options is not None:
            for opt in options:
                self.add_option(opt)

    def add_option(self, option: Option) -> None:
        if self.options_map.get(option.option_name) == option:
            return
        for o in option.shortopts:
            if f"-{o}" in self.options_map:
                raise ValueError(f"Option -{o} registered more than once")
        for o in option.longopts:
            if f"--{o}" in self.options_map:
                raise ValueError(f"Option --{o} registered more than once")
        for o in option.shortopts:
            self.options_map[f"-{o}"] = option
        for o in option.longopts:
            self.options_map[f"--{o}"] = option

    def parse_args(
        self, args: list[str]
    ) -> Immediate | tuple[dict[str, Any], list[str]]:
        """
        Parse command-line arguments, stopping when a non-option is reached.
        Returns either an `Immediate` (if an immediate option is encountered)
        or a tuple of the option values and remaining arguments.

        :param list[str] args: command-line arguments without ``sys.argv[0]``
        """
        shortspec = ""
        longspec = []
        for option in self.options_map.values():
            for o in option.shortopts:
                if option.is_flag:
                    shortspec += o
                else:
                    shortspec += f"{o}:"
            for o in option.longopts:
                if option.is_flag:
                    longspec.append(o)
                else:
                    longspec.append(f"{o}=")
        try:
            optlist, leftovers = getopt(args, shortspec, longspec)
        except GetoptError as e:
            raise UsageError(str(e), self.component)
        kwargs: dict[str, Any] = {}
        for o, a in optlist:
            option = self.options_map[o]
            try:
                ret = option.process(kwargs, a)
            except ValueError as e:
                raise UsageError(f"{a!r}: {e}", self.component)
            except UsageError as e:
                e.component = self.component
                raise e
            else:
                if ret is not None:
                    return ret
        return (kwargs, leftovers)

    def short_help(self, progname: str) -> str:
        if self.component is None:
            return (
                f"Usage: {progname} [<options>] [COMPONENT[=VERSION] [<options>]] ..."
            )
        else:
            cmd = f"Usage: {progname} [<options>] {self.component}"
            if self.versioned:
                cmd += "[=VERSION]"
            cmd += " [<options>]"
            return cmd

    def long_help(self, progname: str) -> str:
        lines = [self.short_help(progname)]
        if self.help is not None:
            lines.append("")
            for ln in self.help.splitlines():
                if ln == "":
                    lines.append("")
                else:
                    lines.extend(
                        " " * HELP_INDENT + wl for wl in textwrap.wrap(ln, HELP_WIDTH)
                    )
        if self.options_map:
            lines.append("")
            lines.append("Options:")
            for _, options in groupby(
                sorted(self.options_map.values()), attrgetter("option_name")
            ):
                lines.extend(next(options).get_help().splitlines())
        return "\n".join(lines)


@dataclass
class UsageError(Exception):
    """Raised when an error occurs while processing command-line options"""

    #: The error message
    message: str
    #: The component for which the error occurred, or `None` if the error was
    #: at the global level
    component: Optional[str] = None

    def __str__(self) -> str:
        return self.message


class ParsedArgs(NamedTuple):
    """
    A pair of global options and `ComponentRequest`\\s parsed from command-line
    arguments
    """

    global_opts: dict[str, Any]
    components: list[ComponentRequest]


@dataclass
class ComponentRequest:
    """A request for a component parsed from command-line arguments"""

    name: str
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class CondaInstance:
    """A Conda installation or environment"""

    #: The root of the Conda installation
    basepath: Path

    #: The name of the environment (`None` for the base environment)
    name: Optional[str]

    @property
    def conda_exe(self) -> Path:
        """The path to the Conda executable"""
        if ON_WINDOWS:
            return self.basepath / "Scripts" / "conda.exe"
        else:
            return self.basepath / "bin" / "conda"

    @property
    def bindir(self) -> Path:
        """
        The directory in which command-line programs provided by packages are
        installed
        """
        dirname = "Scripts" if ON_WINDOWS else "bin"
        if self.name is None:
            return self.basepath / dirname
        else:
            return self.basepath / "envs" / self.name / dirname


@dataclass
class Command:
    """An external command that can be installed by this script"""

    #: Name of the command
    name: str

    #: Arguments with which to invoke the command as a smoke test
    test_args: list[str]

    def in_bindir(self, bindir: Path) -> InstalledCommand:
        """
        Return an `InstalledCommand` recording that the command is installed in
        the given directory
        """
        cmdpath = bindir / self.name
        if ON_WINDOWS and cmdpath.suffix == "":
            cmdpath = cmdpath.with_suffix(".exe")
        return InstalledCommand(name=self.name, path=cmdpath, test_args=self.test_args)


@dataclass
class InstalledCommand(Command):
    """An external command that has been installed by this script"""

    #: Path at which the command is installed
    path: Path

    def test(self) -> bool:
        test_cmd = [str(self.path)] + self.test_args
        cmdtext = " ".join(map(shlex.quote, test_cmd))
        try:
            sr = subprocess.run(test_cmd, stdout=subprocess.DEVNULL)
        except Exception as e:
            log.error("Failed to run `%s`: %s", cmdtext, e)
            return False
        else:
            if sr.returncode != 0:
                log.error("`%s` command failed!", cmdtext)
                return False
            else:
                return True


DATALAD_CMD = Command("datalad", ["--help"])
GIT_ANNEX_CMD = Command("git-annex", ["--help"])
# Smoke-test rclone with --version instead of --help because the latter didn't
# exist before rclone 1.33
RCLONE_CMD = Command("rclone", ["--version"])
GIT_ANNEX_REMOTE_RCLONE_CMD = Command("git-annex-remote-rclone", ["--help"])


@dataclass
class DataladInstaller:
    """The script's primary class, a manager & runner of components"""

    COMPONENTS: ClassVar[dict[str, type[Component]]] = {}

    OPTION_PARSER: ClassVar[OptionParser] = OptionParser(
        help=(
            "Installation script for Datalad and related components\n\n"
            "`datalad-installer` is a script for installing Datalad, git-annex,"
            " and related components all in a single invocation.  It requires"
            " no third-party Python libraries, though it does make heavy use of"
            " external packaging commands.\n\n"
            "See the README at <https://github.com/datalad/datalad-installer>"
            " for a complete description of all options."
        ),
        options=[
            Option(
                "-V",
                "--version",
                is_flag=True,
                immediate=VersionRequest(),
                help="Show program version and exit",
            ),
            Option(
                "-l",
                "--log-level",
                converter=parse_log_level,
                metavar="LEVEL",
                help="Set logging level [default: INFO]",
            ),
            Option(
                "-E",
                "--env-write-file",
                converter=Path,
                multiple=True,
                help=(
                    "Append PATH modifications and other shell commands to the"
                    " given file; can be given multiple times"
                ),
            ),
            Option(
                "--sudo",
                choices=[v.value for v in SudoConfirm],
                converter=SudoConfirm,
                help="How to handle sudo commands [default: ask]",
            ),
        ],
    )

    #: A list of files to which to write ``PATH`` modifications and related
    #: shell commands
    env_write_files: list[Path] = field(default_factory=list)

    sudo_confirm: SudoConfirm = SudoConfirm.ASK

    #: The default installers to fall back on for the "auto" installation
    #: method
    installer_stack: list[Installer] = field(init=False)

    #: A stack of Conda installations & environments installed via the
    #: instance
    conda_stack: list[CondaInstance] = field(init=False, default_factory=list)

    #: A list of commands installed via the instance
    new_commands: list[InstalledCommand] = field(init=False, default_factory=list)

    #: Whether "brew update" has been run
    brew_updated: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self.installer_stack: list[Installer] = [
            # Lowest priority first
            DownloadsRCloneInstaller(self),
            GARRCGitHubInstaller(self),
            DataladPackagesBuildInstaller(self),
            AutobuildInstaller(self),
            HomebrewInstaller(self),
            NeurodebianInstaller(self),
            AptInstaller(self),
            CondaInstaller(self),
        ]

    @classmethod
    def register_component(cls, component: type[Component]) -> type[Component]:
        """A decorator for registering concrete `Component` subclasses"""
        cls.COMPONENTS[component.NAME] = component
        return component

    def __enter__(self) -> DataladInstaller:
        return self

    def __exit__(self, exc_type: Any, _exc_value: Any, _exc_tb: Any) -> None:
        if exc_type is None:
            # Ensure env write files at least exist
            for p in self.env_write_files:
                p.touch()

    def ensure_env_write_file(self) -> None:
        """If there are no env write files registered, add one"""
        if not self.env_write_files:
            fd, fpath = tempfile.mkstemp(prefix="dl-env-", suffix=".sh")
            os.close(fd)
            log.info("Writing environment modifications to %s", fpath)
            self.env_write_files.append(Path(fpath))

    def sudo(self, *args: str | Path, **kwargs: Any) -> None:
        arglist = [str(a) for a in args]
        cmd = " ".join(map(shlex.quote, arglist))
        if ON_WINDOWS:
            # The OS will ask the user for confirmation anyway, so there's no
            # need for us to ask anything.
            log.info("Running as administrator: %s", " ".join(arglist))
            ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
                None, "runas", arglist[0], " ".join(arglist[1:]), None, 1
            )
        else:
            if self.sudo_confirm is SudoConfirm.ERROR:
                log.error("Not running sudo command: %s", cmd)
                sys.exit(1)
            elif self.sudo_confirm is SudoConfirm.ASK:
                print("About to run the following command as an administrator:")
                print(f"    {cmd}")
                yan = ask("Proceed?", ["y", "a", "n"])
                if yan == "n":
                    sys.exit(0)
                elif yan == "a":
                    self.sudo_confirm = SudoConfirm.OK
            runcmd("sudo", *args, **kwargs)

    def run_maybe_elevated(self, *args: str | Path, **kwargs: Any) -> None:
        try:
            runcmd(*args, **kwargs)
        except OSError as e:
            if getattr(e, "winerror", None) == 740:
                log.info("Operation requires elevation; rerunning as administrator")
                self.sudo(*args, **kwargs)
            else:
                raise

    def move_maybe_elevated(self, path: Path, dest: Path) -> None:
        # `dest` must be a file path, not a directory path.
        log.info("Moving %s to %s", path, dest)
        try:
            if ON_POSIX:
                # Handle cross-filesystem moves  (Don't use shutil.move() on
                # Windows, as it fails when dest exists)
                shutil.move(str(path), str(dest))
            else:
                path.replace(dest)
        except PermissionError:
            log.info("Operation requires elevation; rerunning as administrator")
            if ON_POSIX:
                args = ["mv", "-f", "--", str(path), str(dest)]
            else:
                args = ["move", str(path), str(dest)]
            self.sudo(*args)

    @classmethod
    def parse_args(cls, args: list[str]) -> Immediate | ParsedArgs:
        """
        Parse all command-line arguments.

        :param list[str] args: command-line arguments without ``sys.argv[0]``
        """
        r = cls.OPTION_PARSER.parse_args(args)
        if isinstance(r, Immediate):
            return r
        global_opts, leftovers = r
        components: list[ComponentRequest] = []
        while leftovers:
            c = leftovers.pop(0)
            name, eq, version = c.partition("=")
            if not name:
                raise UsageError("Component name must be nonempty")
            try:
                component = cls.COMPONENTS[name]
            except KeyError:
                raise UsageError(f"Unknown component: {name!r}")
            cparser = component.OPTION_PARSER
            if version and not cparser.versioned:
                raise UsageError(f"{name} component does not take a version", name)
            if eq and not version:
                raise UsageError("Version must be nonempty", name)
            cr = cparser.parse_args(leftovers)
            if isinstance(cr, Immediate):
                return cr
            kwargs, leftovers = cr
            if version:
                kwargs["version"] = version
            components.append(ComponentRequest(name=name, kwargs=kwargs))
        return ParsedArgs(global_opts, components)

    def main(self, argv: Optional[list[str]] = None) -> int:
        """
        Parsed command-line arguments and perform the requested actions.
        Returns 0 if everything was OK, nonzero otherwise.

        :param list[str] argv: command-line arguments, including
            ``sys.argv[0]``
        """
        if argv is None:
            argv = sys.argv
        progname, *args = argv
        if not progname:
            progname = "datalad-installer"
        else:
            progname = Path(progname).name
        try:
            r = self.parse_args(args)
        except UsageError as e:
            print(self.short_help(progname, e.component), file=sys.stderr)
            print(file=sys.stderr)
            print(str(e), file=sys.stderr)
            return 2
        if isinstance(r, VersionRequest):
            print("datalad-installer", __version__)
            return 0
        elif isinstance(r, HelpRequest):
            if r.topic is None:
                print(self.long_help(progname, r.component))
            else:
                assert r.component is not None
                self.COMPONENTS[r.component].show_topic_help(r.topic)
            return 0
        else:
            assert isinstance(r, ParsedArgs)
        global_opts, components = r
        if not components:
            components = [ComponentRequest("datalad")]
        logging.basicConfig(
            format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
            level=global_opts.pop("log_level", logging.INFO),
        )
        if global_opts.get("env_write_file"):
            self.env_write_files.extend(global_opts["env_write_file"])
        self.ensure_env_write_file()
        if global_opts.get("sudo"):
            self.sudo_confirm = global_opts["sudo"]
        for cr in components:
            self.addcomponent(name=cr.name, **cr.kwargs)
        ok = True
        for cmd in self.new_commands:
            log.info("%s is now installed at %s", cmd.name, cmd.path)
            if not check_exists(cmd.path):
                log.error("%s does not exist!", cmd.path)
                ok = False
            elif not ON_WINDOWS and not os.access(cmd.path, os.X_OK):
                log.error("%s is not executable!", cmd.path)
                ok = False
            elif not cmd.test():
                ok = False
        return 0 if ok else 1

    def addenv(self, line: str) -> None:
        """Write a line to the env write files"""
        log.debug("Adding line %r to env_write_files", line)
        for p in self.env_write_files:
            with p.open("a") as fp:
                print(line, file=fp)

    def addpath(self, p: str | Path, last: bool = False) -> None:
        """
        Add a line to the env write files that prepends (or appends, if
        ``last`` is true) a given path to ``PATH``
        """
        path = Path(p).resolve()
        if not last:
            line = f'export PATH={shlex.quote(str(path))}:"$PATH"'
        else:
            line = f'export PATH="$PATH":{shlex.quote(str(path))}'
        self.addenv(line)

    def addcomponent(self, name: str, **kwargs: Any) -> None:
        """Provision the given component"""
        try:
            component = self.COMPONENTS[name]
        except AttributeError:
            raise ValueError(f"Unknown component: {name}")
        component(self).provide(**kwargs)

    def get_conda(self) -> CondaInstance:
        """
        Return the most-recently created Conda installation or environment.  If
        there is no such instance, return an instance for an
        externally-installed Conda installation, raising an error if none is
        found.
        """
        if self.conda_stack:
            return self.conda_stack[-1]
        else:
            conda_path = shutil.which("conda")
            if conda_path is not None:
                basepath = Path(readcmd(conda_path, "info", "--base").strip())
                return CondaInstance(basepath=basepath, name=None)
            else:
                raise RuntimeError("conda not installed")

    @classmethod
    def short_help(cls, progname: str, component: Optional[str] = None) -> str:
        if component is None:
            return cls.OPTION_PARSER.short_help(progname)
        else:
            return cls.COMPONENTS[component].OPTION_PARSER.short_help(progname)

    @classmethod
    def long_help(cls, progname: str, component: Optional[str] = None) -> str:
        if component is None:
            s = cls.OPTION_PARSER.long_help(progname)
            s += "\n\nComponents:"
            width = max(map(len, cls.COMPONENTS.keys()))
            for name, cmpnt in sorted(cls.COMPONENTS.items()):
                if cmpnt.OPTION_PARSER.help is not None:
                    chelp = cmpnt.OPTION_PARSER.help.splitlines()[0]
                else:
                    chelp = ""
                s += (
                    f"\n{' ' * HELP_INDENT}{name:{width}}{' ' * HELP_GUTTER}"
                    + textwrap.shorten(chelp, HELP_WIDTH - width - HELP_GUTTER)
                )
            return s
        else:
            return cls.COMPONENTS[component].OPTION_PARSER.long_help(progname)


@dataclass
class Component(ABC):
    """
    An abstract base class for a component that can be specified on the command
    line and provisioned
    """

    NAME: ClassVar[str]

    OPTION_PARSER: ClassVar[OptionParser]

    manager: DataladInstaller

    @abstractmethod
    def provide(self, **kwargs: Any) -> None:
        ...

    @classmethod
    def show_topic_help(cls, topic: str) -> None:
        raise NotImplementedError


@DataladInstaller.register_component
@dataclass
class VenvComponent(Component):
    """Creates a Python virtual environment using ``python -m venv``"""

    NAME: ClassVar[str] = "venv"

    OPTION_PARSER: ClassVar[OptionParser] = OptionParser(
        "venv",
        versioned=False,
        help="Create a Python virtual environment",
        options=[
            Option(
                "--path",
                converter=Path,
                metavar="PATH",
                help="Create the venv at the given path",
            ),
            Option(
                "-e",
                "--extra-args",
                converter=shlex.split,
                help="Extra arguments to pass to the venv command",
            ),
            # For use in testing against the dev version of pip:
            Option(
                "--dev-pip",
                is_flag=True,
                help="Install the development version of pip from GitHub",
            ),
        ],
    )

    def provide(
        self,
        path: Optional[Path] = None,
        extra_args: Optional[list[str]] = None,
        dev_pip: bool = False,
        **kwargs: Any,
    ) -> None:
        log.info("Creating a virtual environment")
        if path is None:
            path = mktempdir("dl-venv-")
        log.info("Path: %s", path)
        log.info("Extra args: %s", extra_args)
        if kwargs:
            log.warning("Ignoring extra component arguments: %r", kwargs)
        ### TODO: Handle systems on which venv isn't installed
        cmd = [sys.executable, "-m", "venv"]
        if extra_args is not None:
            cmd.extend(extra_args)
        cmd.append(str(path))
        runcmd(*cmd)
        installer = PipInstaller(self.manager, path)
        if dev_pip:
            runcmd(
                installer.python,
                "-m",
                "pip",
                "install",
                "pip @ git+https://github.com/pypa/pip",
            )
        else:
            # Ensure we have a recent pip
            runcmd(installer.python, "-m", "pip", "install", "--upgrade", "pip")
        self.manager.installer_stack.append(installer)


@DataladInstaller.register_component
@dataclass
class MinicondaComponent(Component):
    """Installs Miniconda"""

    NAME: ClassVar[str] = "miniconda"

    OPTION_PARSER: ClassVar[OptionParser] = OptionParser(
        "miniconda",
        versioned=True,
        help=(
            "Install Miniconda\n\nVERSION is the version component of a file"
            " at <https://repo.anaconda.com/miniconda/>, e.g., py37_23.1.0-1."
            "  Run `datalad-installer miniconda --help-versions` to see a list"
            " of available versions for your platform."
        ),
        options=[
            Option(
                "--help-versions",
                is_flag=True,
                immediate=HelpRequest("miniconda", topic="versions"),
                help="Show a list of available Miniconda versions for this platform and exit",
            ),
            Option(
                "--path",
                converter=Path,
                metavar="PATH",
                help="Install Miniconda at the given path",
            ),
            Option("--batch", is_flag=True, help="Run in batch (noninteractive) mode"),
            Option(
                "-c",
                "--channel",
                multiple=True,
                help="Additional Conda channels to install packages from",
            ),
            Option(
                "--spec",
                converter=str.split,
                help=(
                    "Space-separated list of package specifiers to install in"
                    " the Miniconda environment"
                ),
            ),
            Option(
                "--python-match",
                choices=["major", "minor", "micro"],
                help="Install the same version of Python, matching to the given version level",
            ),
            Option(
                "-e",
                "--extra-args",
                converter=shlex.split,
                help="Extra arguments to pass to the install command",
            ),
        ],
    )

    def provide(
        self,
        path: Optional[Path] = None,
        batch: bool = False,
        spec: Optional[list[str]] = None,
        python_match: Optional[str] = None,
        extra_args: Optional[list[str]] = None,
        channel: Optional[list[str]] = None,
        version: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        log.info("Installing Miniconda")
        if "CONDA_PREFIX" in os.environ:
            raise RuntimeError("Conda already active; not installing miniconda")
        if path is None:
            path = mktempdir("dl-miniconda-")
            # The Miniconda installer requires that the given path not already
            # exist (unless -u is given); hence, we need to delete the new
            # directory before using it.  (Yes, this is vulnerable to race
            # conditions, but so is specifying a nonexistent directory on the
            # command line.)
            path.rmdir()
        if version is None:
            version = "latest"
        log.info("Version: %s", version)
        log.info("Path: %s", path)
        if ON_WINDOWS:
            log.info("Batch: True")
        else:
            log.info("Batch: %s", batch)
        log.info("Channels: %s", channel)
        log.info("Spec: %s", spec)
        log.info("Python Match: %s", python_match)
        log.info("Extra args: %s", extra_args)
        if kwargs:
            log.warning("Ignoring extra component arguments: %r", kwargs)
        suffix = self.get_platform_suffix()
        miniconda_script = f"Miniconda3-{version}-{suffix}"
        if python_match is not None:
            vparts: tuple[int, ...]
            if python_match == "major":
                vparts = sys.version_info[:1]
            elif python_match == "minor":
                vparts = sys.version_info[:2]
            elif python_match == "micro":
                vparts = sys.version_info[:3]
            else:
                raise AssertionError(f"Unexpected python_match value: {python_match!r}")
            newspec = f"python={'.'.join(map(str, vparts))}"
            log.debug("Adding %r to spec", newspec)
            if spec is None:
                spec = []
            spec.append(newspec)
        log.info("Downloading and running miniconda installer")
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = os.path.join(tmpdir, miniconda_script)
            download_file(
                self.get_anaconda_url().rstrip("/") + "/" + miniconda_script,
                script_path,
            )
            log.info("Installing miniconda in %s", path)
            if ON_WINDOWS:
                # `path` needs to be absolute when passing it to the installer,
                # but Path.resolve() is a no-op for non-existent files on
                # Windows.  Hence, we need to create the directory first.
                path.mkdir(parents=True, exist_ok=True)
                cmd = f'start /wait "" {script_path}'
                if extra_args is not None:
                    cmd += " ".join(extra_args)
                cmd += f" /S /D={path.resolve()}"
                log.info("Running: %s", cmd)
                subprocess.run(cmd, check=True, shell=True)
            else:
                args: list[str | Path] = ["-p", path, "-s"]
                if batch:
                    args.append("-b")
                if extra_args is not None:
                    args.extend(extra_args)
                runcmd("bash", script_path, *args)
        conda_instance = CondaInstance(basepath=path, name=None)
        # As of 2023 June 11, when Conda v23.3.1 on Linux is asked to install
        # the latest DataLad, it installs an incredibly out-of-date version
        # instead.  This can be fixed by upgrading Conda first.
        if (
            ON_LINUX
            and readcmd(conda_instance.conda_exe, "--version").strip() == "conda 23.3.1"
        ):
            log.info("Upgrading conda from buggy v23.3.1")
            runcmd(
                conda_instance.conda_exe,
                "update",
                "-n",
                "-y",
                "base",
                "-c",
                "defaults",
                "conda",
            )
        if spec is not None:
            install_args: list[str] = []
            if batch:
                install_args.append("--yes")
            if channel is not None:
                for c in channel:
                    install_args.extend(["--channel", c])
            install_args.extend(spec)
            runcmd(conda_instance.conda_exe, "install", *install_args)
        self.manager.conda_stack.append(conda_instance)
        self.manager.installer_stack.append(
            CondaInstaller(self.manager, conda_instance)
        )
        self.manager.addenv(f"source {shlex.quote(str(path))}/etc/profile.d/conda.sh")
        self.manager.addenv("conda activate base")

    @staticmethod
    def get_anaconda_url() -> str:
        return os.environ.get("ANACONDA_URL") or "https://repo.anaconda.com/miniconda/"

    @staticmethod
    def get_platform_suffix() -> str:
        if ON_LINUX:
            return "Linux-x86_64.sh"
        elif ON_MACOS:
            arch = platform.machine().lower()
            if arch in ("x86_64", "arm64"):
                return f"MacOSX-{arch}.sh"
            else:
                raise RuntimeError(f"E: Unsupported architecture: {arch}")
        elif ON_WINDOWS:
            return "Windows-x86_64.exe"
        else:
            raise RuntimeError(f"E: Unsupported OS: {SYSTEM}")

    @classmethod
    def show_topic_help(cls, topic: str) -> None:
        assert topic == "versions"
        url = cls.get_anaconda_url()
        log.debug("HTTP request: GET %s", url)
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req) as r:
            charset = "iso-8859-1"
            if "content-type" in r.headers:
                ct = policy.default.header_factory(
                    "Content-Type", r.headers["Content-Type"]
                )
                assert isinstance(ct, ContentTypeHeader)
                if not ct.defects and "charset" in ct.params:  # type: ignore[attr-defined]
                    charset = ct.params["charset"]
            source = r.read().decode(encoding=charset, errors="replace")
        print("Available Miniconda versions for your platform:")
        print()
        prefix = "Miniconda3-"
        suffix = "-" + cls.get_platform_suffix()
        found_any = False
        for link in parse_links(source, base_url=url):
            if link.text.startswith(prefix) and link.text.endswith(suffix):
                version = link.text[len(prefix) :][: -len(suffix)]
                print("-", version)
                found_any = True
        if not found_any:
            print("Nothing found!")


@DataladInstaller.register_component
@dataclass
class CondaEnvComponent(Component):
    """Creates a Conda environment"""

    NAME: ClassVar[str] = "conda-env"

    OPTION_PARSER: ClassVar[OptionParser] = OptionParser(
        "conda-env",
        versioned=False,
        help="Create a Conda environment",
        options=[
            Option(
                "-n",
                "--name",
                "envname",
                metavar="NAME",
                help="Name of the environment",
            ),
            Option(
                "--spec",
                converter=str.split,
                help="Space-separated list of package specifiers to install in the environment",
            ),
            Option(
                "-e",
                "--extra-args",
                converter=shlex.split,
                help="Extra arguments to pass to the `conda create` command",
            ),
        ],
    )

    def provide(
        self,
        envname: Optional[str] = None,
        spec: Optional[list[str]] = None,
        extra_args: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> None:
        log.info("Creating Conda environment")
        if envname is None:
            cname = "datalad-installer-{:03d}".format(randrange(1000))
        else:
            cname = envname
        log.info("Name: %s", cname)
        log.info("Spec: %s", spec)
        log.info("Extra args: %s", extra_args)
        if kwargs:
            log.warning("Ignoring extra component arguments: %r", kwargs)
        conda = self.manager.get_conda()
        cmd: list[str | Path] = [conda.conda_exe, "create", "--name", cname]
        if extra_args is not None:
            cmd.extend(extra_args)
        if spec is not None:
            cmd.extend(spec)
        runcmd(*cmd)
        conda_instance = CondaInstance(basepath=conda.basepath, name=cname)
        self.manager.conda_stack.append(conda_instance)
        self.manager.installer_stack.append(
            CondaInstaller(self.manager, conda_instance)
        )
        self.manager.addenv(f"conda activate {shlex.quote(cname)}")


@DataladInstaller.register_component
@dataclass
class NeurodebianComponent(Component):
    """Installs & configures NeuroDebian"""

    NAME: ClassVar[str] = "neurodebian"

    OPTION_PARSER: ClassVar[OptionParser] = OptionParser(
        "neurodebian",
        versioned=False,
        help="Install & configure NeuroDebian",
        options=[
            Option(
                "-e",
                "--extra-args",
                converter=shlex.split,
                help="Extra arguments to pass to the nd-configurerepo command",
            )
        ],
    )

    KEY_FINGERPRINT: ClassVar[str] = "0xA5D32F012649A5A9"
    KEY_URL: ClassVar[str] = "http://neuro.debian.net/_static/neuro.debian.net.asc"
    DOWNLOAD_SERVER: ClassVar[str] = "us-nh"

    def provide(self, extra_args: Optional[list[str]] = None, **kwargs: Any) -> None:
        log.info("Installing & configuring NeuroDebian")
        log.info("Extra args: %s", extra_args)
        if kwargs:
            log.warning("Ignoring extra component arguments: %r", kwargs)
        r = subprocess.run(
            ["apt-cache", "show", "neurodebian"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        apt_file = Path("/etc/apt/sources.list.d/neurodebian.sources.list")
        if r.returncode != 0 and "o=NeuroDebian" not in readcmd("apt-cache", "policy"):
            log.info("NeuroDebian not available in APT and repository not configured")
            log.info("Configuring NeuroDebian APT repository")
            release = get_version_codename()
            log.debug("Detected version codename: %r", release)
            with tempfile.TemporaryDirectory() as tmpdir:
                sources_file = os.path.join(tmpdir, "neurodebian.sources.list")
                download_file(
                    f"http://neuro.debian.net/lists/{release}.{self.DOWNLOAD_SERVER}.libre",
                    sources_file,
                )
                with open(sources_file) as fp:
                    log.info(
                        "Adding the following contents to sources.list.d:\n\n%s",
                        textwrap.indent(fp.read(), " " * 4),
                    )
                self.manager.sudo(
                    "cp",
                    "-i",
                    sources_file,
                    str(apt_file),
                )
                try:
                    self.manager.sudo(
                        "apt-key",
                        "adv",
                        "--recv-keys",
                        "--keyserver",
                        "hkp://pool.sks-keyservers.net:80",
                        self.KEY_FINGERPRINT,
                    )
                except subprocess.CalledProcessError:
                    log.info("apt-key command failed; downloading key directly")
                    keyfile = os.path.join(tmpdir, "neuro.debian.net.asc")
                    download_file(self.KEY_URL, keyfile)
                    self.manager.sudo("apt-key", "add", keyfile)
            self.manager.sudo("apt-get", "update")
        self.manager.sudo(
            "apt-get",
            "install",
            "-qy",
            "neurodebian",
            env=dict(os.environ, DEBIAN_FRONTEND="noninteractive"),
        )
        try:
            runcmd("nd-configurerepo", *(extra_args or []), stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as exc:
            re_res = re.search(
                r"Malformed entry (?P<line>\d+) in list file (?P<apt_file>\S+\.list) ",
                getattr(exc, "stderr", b"").decode(),
            )
            if re_res:
                apt_file = Path(re_res.groupdict()["apt_file"])
                log.info(
                    "DEBUG information for the error, the content of %s:\n%s",
                    apt_file,
                    apt_file.read_text(),
                )
                version_codename = get_version_codename()
                if version_codename:
                    log.info(
                        "Retrying nd-configurerepo with explicit release %s",
                        version_codename,
                    )
                    args = (extra_args or []) + ["-r", version_codename, "--overwrite"]
                    runcmd("nd-configurerepo", *args)
                    return
            raise


@dataclass
class InstallableComponent(Component):
    """
    Superclass for components that are installed as packages via installation
    methods
    """

    INSTALLERS: ClassVar[dict[str, type[Installer]]] = {}

    @classmethod
    def register_installer(cls, installer: type[Installer]) -> type[Installer]:
        """A decorator for registering concrete `Installer` subclasses"""
        cls.INSTALLERS[installer.NAME] = installer
        methods = cls.OPTION_PARSER.options_map["--method"].choices
        assert methods is not None
        methods.append(installer.NAME)
        for opt in installer.OPTIONS:
            cls.OPTION_PARSER.add_option(opt)
        return installer

    def get_installer(self, name: str) -> Installer:
        """Retrieve & instantiate the installer with the given name"""
        try:
            installer_cls = self.INSTALLERS[name]
        except KeyError:
            raise ValueError(f"Unknown installation method: {name}")
        return installer_cls(self.manager)

    def provide(self, method: Optional[str] = None, **kwargs: Any) -> None:
        if method is not None and method != "auto":
            bins = self.get_installer(method).install(self.NAME, **kwargs)
        else:
            for installer in reversed(self.manager.installer_stack):
                try:
                    log.debug("Attempting to install via %s", installer.NAME)
                    bins = installer.install(self.NAME, **kwargs)
                except MethodNotSupportedError as e:
                    log.debug("Installation method not supported: %s", e)
                    pass
                else:
                    break
            else:
                raise RuntimeError(f"No viable installation method for {self.NAME}")
        self.manager.new_commands.extend(bins)


@DataladInstaller.register_component
@dataclass
class GitAnnexComponent(InstallableComponent):
    """Installs git-annex"""

    NAME: ClassVar[str] = "git-annex"

    OPTION_PARSER: ClassVar[OptionParser] = OptionParser(
        "git-annex",
        versioned=True,
        help="Install git-annex",
        options=[
            Option(
                "-m",
                "--method",
                choices=["auto"],
                help="Select the installation method to use",
            ),
        ],
    )


@DataladInstaller.register_component
@dataclass
class DataladComponent(InstallableComponent):
    """Installs Datalad"""

    NAME: ClassVar[str] = "datalad"

    OPTION_PARSER: ClassVar[OptionParser] = OptionParser(
        "datalad",
        versioned=True,
        help="Install Datalad",
        options=[
            Option(
                "-m",
                "--method",
                choices=["auto"],
                help="Select the installation method to use",
            ),
        ],
    )


@DataladInstaller.register_component
@dataclass
class RCloneComponent(InstallableComponent):
    """Installs rclone"""

    NAME: ClassVar[str] = "rclone"

    OPTION_PARSER: ClassVar[OptionParser] = OptionParser(
        "rclone",
        versioned=True,
        help="Install rclone",
        options=[
            Option(
                "-m",
                "--method",
                choices=["auto"],
                help="Select the installation method to use",
            ),
        ],
    )


@DataladInstaller.register_component
@dataclass
class GitAnnexRemoteRCloneComponent(InstallableComponent):
    """Installs git-annex-remote-rclone"""

    NAME: ClassVar[str] = "git-annex-remote-rclone"

    OPTION_PARSER: ClassVar[OptionParser] = OptionParser(
        "git-annex-remote-rclone",
        versioned=True,
        help="Install git-annex-remote-rclone",
        options=[
            Option(
                "-m",
                "--method",
                choices=["auto"],
                help="Select the installation method to use",
            ),
        ],
    )


@dataclass
class Installer(ABC):
    """An abstract base class for installation methods for packages"""

    NAME: ClassVar[str]

    OPTIONS: ClassVar[list[Option]]

    #: Mapping from supported installable component names to
    #: (installer-specific package IDs, list of installed programs) pairs
    PACKAGES: ClassVar[dict[str, tuple[str, list[Command]]]]

    manager: DataladInstaller

    def install(self, component: str, **kwargs: Any) -> list[InstalledCommand]:
        """
        Installs a given component.  Raises `MethodNotSupportedError` if the
        installation method is not supported on the system or the method does
        not support installing the given component.  Returns a list of
        (command, Path) pairs for each installed program.
        """
        self.assert_supported_system(**kwargs)
        try:
            package, commands = self.PACKAGES[component]
        except KeyError:
            raise MethodNotSupportedError(
                f"{self.NAME} does not know how to install {component}"
            )
        bindir = self.install_package(package, **kwargs)
        return [cmd.in_bindir(bindir) for cmd in commands]

    @abstractmethod
    def install_package(self, package: str, **kwargs: Any) -> Path:
        """
        Installs a given package.  Returns the installation directory for the
        package's programs.
        """
        ...

    @abstractmethod
    def assert_supported_system(self, **kwargs: Any) -> None:
        """
        If the installation method is not supported by the current system,
        raises `MethodNotSupportedError`; otherwise, does nothing.
        """
        ...


EXTRA_ARGS_OPTION = Option(
    "-e",
    "--extra-args",
    converter=shlex.split,
    help="Extra arguments to pass to the install command",
)


@GitAnnexComponent.register_installer
@DataladComponent.register_installer
@RCloneComponent.register_installer
@GitAnnexRemoteRCloneComponent.register_installer
@dataclass
class AptInstaller(Installer):
    """Installs via apt-get"""

    NAME: ClassVar[str] = "apt"

    OPTIONS: ClassVar[list[Option]] = [
        Option(
            "--build-dep", is_flag=True, help="Install build-dep instead of the package"
        ),
        EXTRA_ARGS_OPTION,
    ]

    PACKAGES: ClassVar[dict[str, tuple[str, list[Command]]]] = {
        "datalad": ("datalad", [DATALAD_CMD]),
        "git-annex": ("git-annex", [GIT_ANNEX_CMD]),
        "rclone": ("rclone", [RCLONE_CMD]),
        "git-annex-remote-rclone": (
            "git-annex-remote-rclone",
            [GIT_ANNEX_REMOTE_RCLONE_CMD],
        ),
    }

    def install_package(
        self,
        package: str,
        version: Optional[str] = None,
        build_dep: bool = False,
        extra_args: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> Path:
        log.info("Installing %s via %s", package, self.NAME)
        log.info("Version: %s", version)
        log.info("Build dep: %s", build_dep)
        log.info("Extra args: %s", extra_args)
        if kwargs:
            log.warning("Ignoring extra installer arguments: %r", kwargs)
        cmd = ["apt-get"]
        if build_dep:
            cmd.append("build-dep")
        else:
            cmd.extend(["install", "-y"])
        if extra_args:
            cmd.extend(extra_args)
        if version is not None:
            cmd.append(f"{package}={version}")
        else:
            cmd.append(package)
        self.manager.sudo(*cmd)
        log.debug("Installed program directory: /usr/bin")
        return Path("/usr/bin")

    def assert_supported_system(self, **_kwargs: Any) -> None:
        if shutil.which("apt-get") is None:
            raise MethodNotSupportedError("apt-get command not found")


@DataladComponent.register_installer
@GitAnnexComponent.register_installer
@RCloneComponent.register_installer
@GitAnnexRemoteRCloneComponent.register_installer
@dataclass
class HomebrewInstaller(Installer):
    """Installs via brew (Homebrew)"""

    NAME: ClassVar[str] = "brew"

    OPTIONS: ClassVar[list[Option]] = [
        EXTRA_ARGS_OPTION,
    ]

    PACKAGES: ClassVar[dict[str, tuple[str, list[Command]]]] = {
        "datalad": ("datalad", [DATALAD_CMD]),
        "git-annex": ("git-annex", [GIT_ANNEX_CMD]),
        "rclone": ("rclone", [RCLONE_CMD]),
        "git-annex-remote-rclone": (
            "git-annex-remote-rclone",
            [GIT_ANNEX_REMOTE_RCLONE_CMD],
        ),
    }

    def install_package(
        self,
        package: str,
        extra_args: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> Path:
        log.info("Installing %s via brew", package)
        log.info("Extra args: %s", extra_args)
        if kwargs:
            log.warning("Ignoring extra installer arguments: %r", kwargs)
        if not self.manager.brew_updated:
            runcmd("brew", "update")
            self.manager.brew_updated = True
        cmd = ["brew", "install"]
        if extra_args:
            cmd.extend(extra_args)
        cmd.append(package)
        try:
            runcmd(*cmd)
        except subprocess.CalledProcessError:
            log.error(
                "brew command failed; printing diagnostic output for reporting issue"
            )
            runcmd("brew", "config")
            runcmd("brew", "doctor")
            raise
        ### TODO: Handle variations in this path (Is it "$(brew --prefix)/bin"?)
        log.debug("Installed program directory: /usr/local/bin")
        return Path("/usr/local/bin")

    def assert_supported_system(self, **_kwargs: Any) -> None:
        if shutil.which("brew") is None:
            raise MethodNotSupportedError("brew command not found")


@DataladComponent.register_installer
@dataclass
class PipInstaller(Installer):
    """
    Installs via pip, either at the system level or into a given virtual
    environment
    """

    NAME: ClassVar[str] = "pip"

    OPTIONS: ClassVar[list[Option]] = [
        Option("--devel", is_flag=True, help="Install from GitHub repository"),
        Option("-E", "--extras", metavar="EXTRAS", help="Install package extras"),
        EXTRA_ARGS_OPTION,
    ]

    PACKAGES: ClassVar[dict[str, tuple[str, list[Command]]]] = {
        "datalad": ("datalad", [DATALAD_CMD]),
    }

    DEVEL_PACKAGES: ClassVar[dict[str, str]] = {
        "datalad": "git+https://github.com/datalad/datalad.git",
    }

    #: The path to the virtual environment in which to install, or `None` if
    #: installation should be done at the system level
    venv_path: Optional[Path] = None

    @property
    def python(self) -> str | Path:
        if self.venv_path is None:
            return sys.executable
        elif ON_WINDOWS:
            return self.venv_path / "Scripts" / "python.exe"
        else:
            return self.venv_path / "bin" / "python"

    def install_package(
        self,
        package: str,
        version: Optional[str] = None,
        devel: bool = False,
        extras: Optional[str] = None,
        extra_args: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> Path:
        log.info("Installing %s via pip", package)
        log.info("Venv path: %s", self.venv_path)
        log.info("Version: %s", version)
        log.info("Devel: %s", devel)
        log.info("Extras: %s", extras)
        log.info("Extra args: %s", extra_args)
        if kwargs:
            log.warning("Ignoring extra installer arguments: %r", kwargs)
        urlspec: Optional[str]
        if devel:
            try:
                urlspec = self.DEVEL_PACKAGES[package]
            except KeyError:
                raise ValueError(f"No source repository known for {package}")
        else:
            urlspec = None
        cmd = [self.python, "-m", "pip", "install"]
        if extra_args is not None:
            cmd.extend(extra_args)
        cmd.append(
            compose_pip_requirement(
                package, version=version, urlspec=urlspec, extras=extras
            )
        )
        runcmd(*cmd)
        user = extra_args is not None and "--user" in extra_args
        with tempfile.NamedTemporaryFile("w+", delete=False) as script:
            # Passing this code to Python with `input` doesn't work for some
            # reason, so we need to save it as a script instead.
            print(
                "try:\n"
                "    from pip._internal.locations import get_scheme\n"
                f"    path = get_scheme({package!r}, user={user!r}).scripts\n"
                "except ImportError:\n"
                "    from pip._internal.locations import distutils_scheme\n"
                f"    path = distutils_scheme({package!r}, user={user!r})['scripts']\n"
                "print(path, end='')\n",
                file=script,
                flush=True,
            )
            # We need to close before passing to Python for Windows
            # compatibility
            script.close()
            binpath = Path(readcmd(self.python, script.name))
            os.unlink(script.name)
        log.debug("Installed program directory: %s", binpath)
        return binpath

    def assert_supported_system(self, **_kwargs: Any) -> None:
        ### TODO: Detect whether pip is installed in the current Python,
        ### preferably without importing it
        pass


@GitAnnexComponent.register_installer
@dataclass
class NeurodebianInstaller(AptInstaller):
    """Installs via apt-get and the NeuroDebian repositories"""

    NAME: ClassVar[str] = "neurodebian"

    PACKAGES: ClassVar[dict[str, tuple[str, list[Command]]]] = {
        "git-annex": ("git-annex-standalone", [GIT_ANNEX_CMD]),
    }

    def assert_supported_system(self, **kwargs: Any) -> None:
        super().assert_supported_system(**kwargs)
        if "l=NeuroDebian" not in readcmd("apt-cache", "policy"):
            raise MethodNotSupportedError("Neurodebian not configured")


@GitAnnexComponent.register_installer
@DataladComponent.register_installer
@RCloneComponent.register_installer
@GitAnnexRemoteRCloneComponent.register_installer
@dataclass
class DebURLInstaller(Installer):
    """Installs a ``*.deb`` package by URL"""

    NAME: ClassVar[str] = "deb-url"

    OPTIONS: ClassVar[list[Option]] = [
        Option("--url", metavar="URL", help="URL from which to download `*.deb` file"),
        Option(
            "--install-dir",
            converter=Path,
            metavar="DIR",
            help="Directory in which to unpack the `*.deb`",
        ),
        EXTRA_ARGS_OPTION,
    ]

    PACKAGES: ClassVar[dict[str, tuple[str, list[Command]]]] = {
        "git-annex": ("git-annex", [GIT_ANNEX_CMD]),
        "datalad": ("datalad", [DATALAD_CMD]),
        "rclone": ("rclone", [RCLONE_CMD]),
        "git-annex-remote-rclone": (
            "git-annex-remote-rclone",
            [GIT_ANNEX_REMOTE_RCLONE_CMD],
        ),
    }

    def install_package(
        self,
        package: str,
        url: Optional[str] = None,
        install_dir: Optional[Path] = None,
        extra_args: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> Path:
        log.info("Installing %s via deb-url", package)
        if url is None:
            raise RuntimeError("deb-url method requires URL")
        log.info("URL: %s", url)
        if install_dir is not None:
            if package != "git-annex":
                raise RuntimeError("--install-dir is only supported for git-annex")
            install_dir = untmppath(install_dir)
            log.info("Install dir: %s", install_dir)
        log.info("Extra args: %s", extra_args)
        if kwargs:
            log.warning("Ignoring extra installer arguments: %r", kwargs)
        with tempfile.TemporaryDirectory() as tmpdir:
            debpath = os.path.join(tmpdir, f"{package}.deb")
            download_file(url, debpath)
            if install_dir is not None and "{version}" in str(install_dir):
                deb_version = readcmd(
                    "dpkg-deb", "--showformat", "${Version}", "-W", debpath
                )
                install_dir = Path(str(install_dir).format(version=deb_version))
                log.info("Expanded install dir to %s", install_dir)
            binpath = install_deb(
                debpath,
                self.manager,
                Path("usr/bin"),
                install_dir=install_dir,
                extra_args=extra_args,
            )
            log.debug("Installed program directory: %s", binpath)
            return binpath

    def assert_supported_system(self, **kwargs: Any) -> None:
        if kwargs.get("install_dir") is None and shutil.which("dpkg") is None:
            raise MethodNotSupportedError(
                "Non-dpkg-based systems not supported unless --install-dir is given"
            )


@dataclass
class AutobuildSnapshotInstaller(Installer):
    OPTIONS: ClassVar[list[Option]] = []

    PACKAGES: ClassVar[dict[str, tuple[str, list[Command]]]] = {
        "git-annex": ("git-annex", [GIT_ANNEX_CMD]),
    }

    def _install_linux(self, path: str) -> Path:
        tmpdir = mktempdir("dl-build-")
        annex_bin = tmpdir / "git-annex.linux"
        log.info("Downloading and extracting under %s", annex_bin)
        gzfile = tmpdir / "git-annex-standalone-amd64.tar.gz"
        download_file(
            f"https://downloads.kitenet.net/git-annex/{path}"
            "/git-annex-standalone-amd64.tar.gz",
            gzfile,
        )
        runcmd("tar", "-C", tmpdir, "-xzf", gzfile)
        self.manager.addpath(annex_bin)
        return annex_bin

    def _install_macos(self, path: str) -> Path:
        with tempfile.TemporaryDirectory() as tmpdir:
            dmgpath = os.path.join(tmpdir, "git-annex.dmg")
            download_file(
                f"https://downloads.kitenet.net/git-annex/{path}/git-annex.dmg",
                dmgpath,
            )
            return install_git_annex_dmg(dmgpath, self.manager)

    def assert_supported_system(self, **_kwargs: Any) -> None:
        if not ON_POSIX:
            raise MethodNotSupportedError(f"{SYSTEM} OS not supported")


@GitAnnexComponent.register_installer
@dataclass
class AutobuildInstaller(AutobuildSnapshotInstaller):
    """Installs the latest official build of git-annex from kitenet.net"""

    NAME: ClassVar[str] = "autobuild"

    def install_package(self, package: str, **kwargs: Any) -> Path:
        log.info("Installing %s via autobuild", package)
        if kwargs:
            log.warning("Ignoring extra installer arguments: %r", kwargs)
        assert package == "git-annex"
        if ON_LINUX:
            binpath = self._install_linux("autobuild/amd64")
        elif ON_MACOS:
            binpath = self._install_macos("autobuild/x86_64-apple-yosemite")
        else:
            raise AssertionError("Method should not be called on unsupported platforms")
        log.debug("Installed program directory: %s", binpath)
        return binpath


@GitAnnexComponent.register_installer
@dataclass
class SnapshotInstaller(AutobuildSnapshotInstaller):
    """
    Installs the latest official snapshot build of git-annex from kitenet.net
    """

    NAME: ClassVar[str] = "snapshot"

    def install_package(self, package: str, **kwargs: Any) -> Path:
        log.info("Installing %s via snapshot", package)
        if kwargs:
            log.warning("Ignoring extra installer arguments: %r", kwargs)
        assert package == "git-annex"
        if ON_LINUX:
            binpath = self._install_linux("linux/current")
        elif ON_MACOS:
            binpath = self._install_macos("OSX/current/10.15_Catalina")
        else:
            raise AssertionError("Method should not be called on unsupported platforms")
        log.debug("Installed program directory: %s", binpath)
        return binpath


@GitAnnexComponent.register_installer
@DataladComponent.register_installer
@RCloneComponent.register_installer
@GitAnnexRemoteRCloneComponent.register_installer
@dataclass
class CondaInstaller(Installer):
    """Installs via conda"""

    NAME: ClassVar[str] = "conda"

    OPTIONS: ClassVar[list[Option]] = [
        EXTRA_ARGS_OPTION,
    ]

    PACKAGES: ClassVar[dict[str, tuple[str, list[Command]]]] = {
        "datalad": ("datalad", [DATALAD_CMD]),
        "git-annex": ("git-annex", [GIT_ANNEX_CMD]),
        "rclone": ("rclone", [RCLONE_CMD]),
        "git-annex-remote-rclone": (
            "git-annex-remote-rclone",
            [GIT_ANNEX_REMOTE_RCLONE_CMD],
        ),
    }

    conda_instance: Optional[CondaInstance] = None

    def install_package(
        self,
        package: str,
        version: Optional[str] = None,
        extra_args: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> Path:
        if package in ("git-annex", "git-annex-remote-rclone") and not ON_LINUX:
            raise MethodNotSupportedError(
                f"Conda only supports installing {package} on Linux"
            )
        log.info("Installing %s via conda", package)
        if self.conda_instance is not None:
            conda = self.conda_instance
        else:
            conda = self.manager.get_conda()
        log.info("Environment: %s", conda.name)
        log.info("Version: %s", version)
        log.info("Extra args: %s", extra_args)
        if kwargs:
            log.warning("Ignoring extra installer arguments: %r", kwargs)
        cmd: list[str | Path] = [conda.conda_exe, "install"]
        if conda.name is not None:
            cmd.append("--name")
            cmd.append(conda.name)
        cmd += ["-q", "-c", "conda-forge", "-y"]
        if extra_args is not None:
            cmd.extend(extra_args)
        if version is None:
            # Ad-hoc workaround for https://github.com/conda-forge/datalad-feedstock/issues/109
            # we need to request datalad after 'noarch' 0.9.3
            if package == "datalad":
                cmd.append("datalad>=0.10.0")
            else:
                cmd.append(package)
        else:
            cmd.append(f"{package}={version}")
        i = 0
        while True:
            try:
                runcmd(*cmd)
            except subprocess.CalledProcessError as e:
                if i < 3:
                    log.error(
                        "Command failed with exit status %d; sleeping and retrying",
                        e.returncode,
                    )
                    i += 1
                    sleep(5)
                else:
                    raise
            else:
                break
        binpath = conda.bindir
        log.debug("Installed program directory: %s", binpath)
        return binpath

    def assert_supported_system(self, **_kwargs: Any) -> None:
        if not self.manager.conda_stack and shutil.which("conda") is None:
            raise MethodNotSupportedError("Conda installation not found")


@GitAnnexComponent.register_installer
@dataclass
class DataladGitAnnexBuildInstaller(Installer):
    """
    Installs git-annex via the artifact from the latest successful build of
    datalad/git-annex
    """

    NAME: ClassVar[str] = "datalad/git-annex:tested"

    OPTIONS: ClassVar[list[Option]] = [
        Option(
            "--install-dir",
            converter=Path,
            metavar="DIR",
            help="Directory in which to unpack the `*.deb`",
        ),
    ]

    PACKAGES: ClassVar[dict[str, tuple[str, list[Command]]]] = {
        "git-annex": ("git-annex", [GIT_ANNEX_CMD]),
    }

    VERSIONED: ClassVar[bool] = False

    def install_package(
        self,
        package: str,
        version: Optional[str] = None,
        install_dir: Optional[Path] = None,
        **kwargs: Any,
    ) -> Path:
        log.info("Installing %s via %s", package, self.NAME)
        if self.VERSIONED:
            log.info("Version: %s", version)
        elif version is not None:
            kwargs["version"] = version
        if install_dir is not None:
            if not ON_LINUX:
                raise RuntimeError("--install-dir is only supported on Linux")
            install_dir = untmppath(install_dir)
            log.info("Install dir: %s", install_dir)
        if kwargs:
            log.warning("Ignoring extra installer arguments: %r", kwargs)
        assert package == "git-annex"
        # Try to ignore cleanup errors on Windows:
        with suppress(NotADirectoryError), tempfile.TemporaryDirectory() as tmpdir_:
            tmpdir = Path(tmpdir_)
            if ON_LINUX:
                self.download("ubuntu", tmpdir, version)
                (debpath,) = tmpdir.glob("*.deb")
                if install_dir is None and deb_pkg_installed("git-annex"):
                    self.manager.sudo(
                        "dpkg", "--remove", "--ignore-depends=git-annex", "git-annex"
                    )
                binpath = install_deb(
                    debpath,
                    self.manager,
                    Path("usr", "bin"),
                    install_dir=install_dir,
                )
            elif ON_MACOS:
                self.download("macos", tmpdir, version)
                (dmgpath,) = tmpdir.glob("*.dmg")
                binpath = install_git_annex_dmg(dmgpath, self.manager)
            elif ON_WINDOWS:
                self.download("windows", tmpdir, version)
                (exepath,) = tmpdir.glob("*.exe")
                self.manager.run_maybe_elevated(exepath, "/S")
                binpath = Path("C:/Program Files", "Git", "usr", "bin")
                self.manager.addpath(binpath)
            else:
                raise AssertionError(
                    "Method should not be called on unsupported platforms"
                )
        log.debug("Installed program directory: %s", binpath)
        return binpath

    def assert_supported_system(self, **kwargs: Any) -> None:
        if not (ON_LINUX or ON_MACOS or ON_WINDOWS):
            raise MethodNotSupportedError(f"{SYSTEM} OS not supported")
        elif (
            ON_LINUX
            and kwargs.get("install_dir") is None
            and shutil.which("dpkg") is None
        ):
            raise MethodNotSupportedError(
                "Non-dpkg-based systems not supported unless --install-dir is given"
            )

    @staticmethod
    def download(
        ostype: str, target_dir: Path, version: Optional[str]  # noqa: U100
    ) -> None:
        """
        Download & unzip the artifact from the latest successful build of
        datalad/git-annex for the given OS in the given directory
        """
        GitHubClient().download_last_successful_artifact(
            target_dir, repo="datalad/git-annex", workflow=f"build-{ostype}.yaml"
        )


@GitAnnexComponent.register_installer
@dataclass
class DataladGitAnnexLatestBuildInstaller(DataladGitAnnexBuildInstaller):
    """
    Installs git-annex via the artifact from the latest artifact-producing
    build (successful or unsuccessful) of datalad/git-annex
    """

    NAME: ClassVar[str] = "datalad/git-annex"

    @staticmethod
    def download(
        ostype: str, target_dir: Path, version: Optional[str]  # noqa: U100
    ) -> None:
        """
        Download & unzip the artifact from the latest build of
        datalad/git-annex for the given OS in the given directory
        """
        GitHubClient().download_latest_artifact(
            target_dir, repo="datalad/git-annex", workflow=f"build-{ostype}.yaml"
        )


@GitAnnexComponent.register_installer
@dataclass
class DataladGitAnnexReleaseBuildInstaller(DataladGitAnnexBuildInstaller):
    """Installs git-annex via an asset of a release of datalad/git-annex"""

    NAME: ClassVar[str] = "datalad/git-annex:release"

    VERSIONED: ClassVar[bool] = True

    @staticmethod
    def download(ostype: str, target_dir: Path, version: Optional[str]) -> None:
        GitHubClient(auth_required=False).download_release_asset(
            target_dir,
            repo="datalad/git-annex",
            ext={"ubuntu": ".deb", "macos": ".dmg", "windows": ".exe"}[ostype],
            tag=version,
        )


@GitAnnexComponent.register_installer
@dataclass
class DataladPackagesBuildInstaller(Installer):
    """
    Installs git-annex via artifacts uploaded to
    <https://datasets.datalad.org/?dir=/datalad/packages>
    """

    NAME: ClassVar[str] = "datalad/packages"

    OPTIONS: ClassVar[list[Option]] = [
        Option(
            "--install-dir",
            converter=Path,
            metavar="DIR",
            help="Directory in which to unpack the `*.deb`",
        ),
    ]

    PACKAGES: ClassVar[dict[str, tuple[str, list[Command]]]] = {
        "git-annex": ("git-annex", [GIT_ANNEX_CMD]),
    }

    def install_package(
        self,
        package: str,
        version: Optional[str] = None,
        install_dir: Optional[Path] = None,
        **kwargs: Any,
    ) -> Path:
        log.info("Installing %s via datalad/packages", package)
        log.info("Version: %s", version)
        if install_dir is not None:
            if not ON_LINUX:
                raise RuntimeError("--install-dir is only supported on Linux")
            install_dir = untmppath(install_dir)
            log.info("Install dir: %s", install_dir)
        if kwargs:
            log.warning("Ignoring extra installer arguments: %r", kwargs)
        assert package == "git-annex"
        if version is None:
            log.info("Fetching latest version ...")
            vfile = download_to_tempfile(
                "http://datasets.datalad.org/datalad/packages/latest-version"
            )
            version = vfile.read_text().strip()
            log.info("Found latest version: %s", version)
        # Try to ignore cleanup errors on Windows:
        with suppress(NotADirectoryError), tempfile.TemporaryDirectory() as tmpdir_:
            tmpdir = Path(tmpdir_)
            if ON_LINUX:
                debfile = f"git-annex-standalone_{version}-1~ndall+1_amd64.deb"
                debpath = tmpdir / debfile
                download_file(
                    f"https://datasets.datalad.org/datalad/packages/neurodebian/{debfile}",
                    debpath,
                )
                if install_dir is None and deb_pkg_installed("git-annex"):
                    self.manager.sudo(
                        "dpkg", "--remove", "--ignore-depends=git-annex", "git-annex"
                    )
                binpath = install_deb(
                    debpath,
                    self.manager,
                    Path("usr", "bin"),
                    install_dir=install_dir,
                )
            elif ON_WINDOWS:
                exefile = f"git-annex-installer_{version}_x64.exe"
                exepath = tmpdir / exefile
                download_file(
                    f"https://datasets.datalad.org/datalad/packages/windows/{exefile}",
                    exepath,
                )
                self.manager.run_maybe_elevated(exepath, "/S")
                binpath = Path("C:/Program Files", "Git", "usr", "bin")
                self.manager.addpath(binpath)
            elif ON_MACOS:
                dmgfile = f"git-annex_{version}_x64.dmg"
                dmgpath = tmpdir / dmgfile
                download_file(
                    f"https://datasets.datalad.org/datalad/packages/osx/{dmgfile}",
                    dmgpath,
                )
                binpath = install_git_annex_dmg(dmgpath, self.manager)
            else:
                raise AssertionError(
                    "Method should not be called on unsupported platforms"
                )
        log.debug("Installed program directory: %s", binpath)
        return binpath

    def assert_supported_system(self, **kwargs: Any) -> None:
        if not (ON_LINUX or ON_MACOS or ON_WINDOWS):
            raise MethodNotSupportedError(f"{SYSTEM} OS not supported")
        elif (
            ON_LINUX
            and kwargs.get("install_dir") is None
            and shutil.which("dpkg") is None
        ):
            raise MethodNotSupportedError(
                "Non-dpkg-based systems not supported unless --install-dir is given"
            )


@GitAnnexComponent.register_installer
@dataclass
class DMGInstaller(Installer):
    """Installs a local ``*.dmg`` file"""

    NAME: ClassVar[str] = "dmg"

    OPTIONS: ClassVar[list[Option]] = [
        Option(
            "--path",
            converter=Path,
            metavar="PATH",
            help="Path to local `*.dmg` to install",
        ),
    ]

    PACKAGES: ClassVar[dict[str, tuple[str, list[Command]]]] = {
        "git-annex": ("git-annex", [GIT_ANNEX_CMD]),
    }

    def install_package(
        self,
        package: str,
        path: Optional[Path] = None,
        **kwargs: Any,
    ) -> Path:
        log.info("Installing %s via dmg", package)
        if path is None:
            raise RuntimeError("dmg method requires path")
        log.info("Path: %s", path)
        if kwargs:
            log.warning("Ignoring extra installer arguments: %r", kwargs)
        binpath = install_git_annex_dmg(path, self.manager)
        log.debug("Installed program directory: %s", binpath)
        return binpath

    def assert_supported_system(self, **_kwargs: Any) -> None:
        if not ON_MACOS:
            raise MethodNotSupportedError(f"{SYSTEM} OS not supported")


@GitAnnexRemoteRCloneComponent.register_installer
@dataclass
class GARRCGitHubInstaller(Installer):
    """Installs git-annex-remote-rclone from a tag on GitHub"""

    NAME: ClassVar[str] = "DanielDent/git-annex-remote-rclone"

    OPTIONS: ClassVar[list[Option]] = [
        Option(
            "--bin-dir",
            converter=Path,
            metavar="DIR",
            help="Directory in which to install the program",
        ),
    ]

    PACKAGES: ClassVar[dict[str, tuple[str, list[Command]]]] = {
        "git-annex-remote-rclone": (
            "git-annex-remote-rclone",
            [GIT_ANNEX_REMOTE_RCLONE_CMD],
        ),
    }

    REPO: ClassVar[str] = "DanielDent/git-annex-remote-rclone"

    def install_package(
        self,
        package: str,
        version: Optional[str] = None,
        bin_dir: Optional[Path] = None,
        **kwargs: Any,
    ) -> Path:
        log.info("Installing %s from GitHub release", package)
        log.info("Version: %s", version)
        if bin_dir is not None:
            bin_dir = untmppath(bin_dir)
        else:
            bin_dir = Path("/usr/local/bin")
        log.info("Bin dir: %s", bin_dir)
        if kwargs:
            log.warning("Ignoring extra installer arguments: %r", kwargs)
        if version is None:
            latest = GitHubClient(auth_required=False).get_latest_release(self.REPO)
            version = latest["tag_name"]
            log.info("Found latest release of %s: %s", self.REPO, version)
        elif not version.startswith("v"):
            version = "v" + version
        p = download_to_tempfile(
            f"https://raw.githubusercontent.com/{self.REPO}/{version}/git-annex-remote-rclone"
        )
        p.chmod(0o755)
        bin_dir.mkdir(parents=True, exist_ok=True)
        self.manager.move_maybe_elevated(p, bin_dir / "git-annex-remote-rclone")
        log.debug("Installed program directory: %s", bin_dir)
        return bin_dir

    def assert_supported_system(self, **_kwargs: Any) -> None:
        if not ON_POSIX:
            raise MethodNotSupportedError(f"{SYSTEM} OS not supported")


@RCloneComponent.register_installer
@dataclass
class DownloadsRCloneInstaller(Installer):
    """Installs rclone via downloads.rclone.org"""

    NAME: ClassVar[str] = "downloads.rclone.org"

    OPTIONS: ClassVar[list[Option]] = [
        Option(
            "--bin-dir",
            converter=Path,
            metavar="DIR",
            help="Directory in which to install the program",
        ),
        Option(
            "--man-dir",
            converter=Path,
            metavar="DIR",
            help="Directory in which to install the manpage",
        ),
    ]

    PACKAGES: ClassVar[dict[str, tuple[str, list[Command]]]] = {
        "rclone": ("rclone", [RCLONE_CMD])
    }

    def install_package(
        self,
        package: str,
        version: Optional[str] = None,
        bin_dir: Optional[Path] = None,
        man_dir: Optional[Path] = None,
        **kwargs: Any,
    ) -> Path:
        log.info("Installing %s from downloads.rclone.org", package)
        log.info("Version: %s", version)
        bin_dir, man_dir = untmppaths(bin_dir, man_dir)
        if bin_dir is None:
            if ON_POSIX:
                bin_dir = Path("/usr/local/bin")
            else:
                raise RuntimeError(
                    "The downloads.rclone.org method requires --bin-dir to be given on Windows"
                )
        log.info("Bin dir: %s", bin_dir)
        log.info("Man dir: %s", man_dir)
        if kwargs:
            log.warning("Ignoring extra installer arguments: %r", kwargs)
        arch = platform.machine().lower()
        if arch in ("x86_64", "amd64"):
            arch = "amd64"
        elif re.fullmatch(r"i.86", arch) or arch == "x86":
            arch = "386"
        elif arch in ("aarch64", "arm64"):
            arch = "arm64"
        elif arch.startswith("arm"):
            arch = "arm"
        else:
            raise RuntimeError(f"Machine architecture {arch} not supported by rclone")
        if ON_LINUX:
            ostype = "linux"
            binname = "rclone"
        elif ON_MACOS:
            ostype = "osx"
            binname = "rclone"
        elif ON_WINDOWS:
            ostype = "windows"
            binname = "rclone.exe"
        else:
            raise AssertionError("Method should not be called on unsupported platforms")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            url = "https://downloads.rclone.org/"
            if version is None:
                url += f"rclone-current-{ostype}-{arch}.zip"
            else:
                if not version.startswith("v"):
                    version = "v" + version
                url += f"{version}/rclone-{version}-{ostype}-{arch}.zip"
            download_zipfile(url, tmppath)
            (contents,) = tmppath.iterdir()
            bin_dir.mkdir(parents=True, exist_ok=True)
            if ON_POSIX:
                # Although the rclone program is marked executable in the zip,
                # Python does not preserve this bit when unarchiving.
                (contents / binname).chmod(0o755)
            self.manager.move_maybe_elevated(contents / binname, bin_dir / binname)
            if man_dir is not None:
                man1_dir = man_dir / "man1"
                man1_dir.mkdir(parents=True, exist_ok=True)
                self.manager.move_maybe_elevated(
                    contents / "rclone.1", man1_dir / "rclone.1"
                )
        log.debug("Installed program directory: %s", bin_dir)
        if str(bin_dir) not in os.environ.get("PATH", "").split(os.pathsep):
            self.manager.addpath(bin_dir)
        return bin_dir

    def assert_supported_system(self, **_kwargs: Any) -> None:
        pass


class GitHubClient:
    def __init__(self, auth_required: bool = True) -> None:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            r = subprocess.run(
                ["git", "config", "hub.oauthtoken"],
                stdout=subprocess.PIPE,
                universal_newlines=True,
            )
            if (r.returncode != 0 or not r.stdout.strip()) and auth_required:
                raise RuntimeError(
                    "GitHub OAuth token not set.  Set via GITHUB_TOKEN"
                    " environment variable or hub.oauthtoken Git config option."
                )
            token = r.stdout.strip()
        self.headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    @contextmanager
    def get(self, url: str) -> Iterator[Any]:
        log.debug("HTTP request: GET %s", url)
        req = Request(url, headers=self.headers)
        try:
            with urlopen(req) as r:
                yield r
        except HTTPError as e:
            self.raise_for_ratelimit(e)
            raise

    def getjson(self, url: str) -> Any:
        with self.get(url) as r:
            return json.load(r)

    def paginate(self, url: str, key: Optional[str] = None) -> Iterator[dict]:
        while True:
            with self.get(url) as r:
                data = json.load(r)
                if key is not None:
                    data = data[key]
                for obj in data:
                    assert isinstance(obj, dict)
                    yield obj
                link_header = r.headers.get("Link")
                if link_header is not None:
                    links = parse_header_links(link_header)
                else:
                    links = {}
                url2 = links.get("next", {}).get("url")
                if url2 is None:
                    break
                url = url2

    def get_workflow_runs(self, url: str) -> Iterator[dict]:
        return self.paginate(url, key="workflow_runs")

    def get_archive_download_url(self, artifacts_url: str) -> Optional[str]:
        """
        Given a workflow run's ``artifacts_url``, returns the
        ``archive_download_url`` for the one & only artifact.  If there are no
        artifacts, `None` is returned.  If there is more than one artifact, a
        `RuntimeError` is raised.
        """
        log.info("Getting archive download URL from %s", artifacts_url)
        artifacts = self.getjson(artifacts_url)
        if artifacts["total_count"] < 1:
            log.debug("No artifacts found")
            return None
        elif artifacts["total_count"] > 1:
            raise RuntimeError("Too many artifacts found!")
        else:
            url = artifacts["artifacts"][0]["archive_download_url"]
            assert isinstance(url, str)
            return url

    def download_latest_artifact(
        self, target_dir: Path, repo: str, workflow: str, branch: str = "master"
    ) -> None:
        """
        Downloads the most recent artifact built by ``workflow`` on ``branch``
        in ``repo`` to ``target_dir``
        """
        runs_url = (
            f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}"
            f"/runs?branch={branch}"
        )
        log.info("Getting artifacts_url from %s", runs_url)
        for run in self.get_workflow_runs(runs_url):
            artifacts_url = run["artifacts_url"]
            archive_download_url = self.get_archive_download_url(artifacts_url)
            if archive_download_url is not None:
                log.info("Downloading artifact package from %s", archive_download_url)
                try:
                    download_zipfile(
                        archive_download_url,
                        target_dir,
                        headers={**self.headers, "Accept": "*/*"},
                    )
                except HTTPError as e:
                    self.raise_for_ratelimit(e)
                    raise
                return
        else:
            raise RuntimeError("No workflow runs with artifacts found!")

    def download_last_successful_artifact(
        self, target_dir: Path, repo: str, workflow: str, branch: str = "master"
    ) -> None:
        """
        Downloads the most recent artifact built by a successful run of
        ``workflow`` on ``branch`` in ``repo`` to ``target_dir``
        """
        runs_url = (
            f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}"
            f"/runs?status=success&branch={branch}"
        )
        log.info("Getting artifacts_url from %s", runs_url)
        for run in self.get_workflow_runs(runs_url):
            artifacts_url = run["artifacts_url"]
            archive_download_url = self.get_archive_download_url(artifacts_url)
            if archive_download_url is not None:
                log.info("Downloading artifact package from %s", archive_download_url)
                try:
                    download_zipfile(
                        archive_download_url,
                        target_dir,
                        headers={**self.headers, "Accept": "*/*"},
                    )
                except HTTPError as e:
                    self.raise_for_ratelimit(e)
                    raise
                return
        else:
            raise RuntimeError("No workflow runs with artifacts found!")

    def get_latest_release_asset(self, repo: str, ext: str) -> dict:
        """
        Finds the most recent non-draft release of ``repo`` containing an asset
        whose name ends with ``ext`` and returns that asset's information
        """
        first = True
        for release in self.paginate(f"https://api.github.com/repos/{repo}/releases"):
            if release["draft"]:
                continue
            for asset in release["assets"]:
                if asset["name"].endswith(ext):
                    assert isinstance(asset, dict)
                    return asset
            if first:
                log.warning(
                    "Most recent release of %s lacks asset for this OS;"
                    " falling back to older releases",
                    repo,
                )
                first = False
        raise RuntimeError("No release found with asset for this OS!")

    def get_release_asset(self, repo: str, tag: str, ext: str) -> dict:
        """
        Returns information on the asset of release ``tag`` of repository
        ``repo`` whose filename ends with ``ext``
        """
        release = self.getjson(
            f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
        )
        for asset in release["assets"]:
            if asset["name"].endswith(ext):
                assert isinstance(asset, dict)
                return asset
        raise RuntimeError(f"No asset for this OS found in release {tag!r}!")

    def download_release_asset(
        self, target_dir: Path, repo: str, ext: str, tag: Optional[str]
    ) -> None:
        if tag is None:
            asset = self.get_latest_release_asset(repo, ext)
        else:
            asset = self.get_release_asset(repo, tag, ext)
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            download_file(
                asset["browser_download_url"],
                target_dir / asset["name"],
                headers={**self.headers, "Accept": "*/*"},
            )
        except HTTPError as e:
            self.raise_for_ratelimit(e)
            raise

    def get_latest_release(self, repo: str) -> dict:
        """
        Returns information on the most latest non-draft non-prerelease release
        of ``repo``.  Raises 404 if the repo has no releases.
        """
        data = self.getjson(f"https://api.github.com/repos/{repo}/releases/latest")
        assert isinstance(data, dict)
        return data

    def raise_for_ratelimit(self, e: HTTPError) -> None:
        if e.code == 403:
            try:
                resp = json.load(e)
            except Exception:
                return
            if "API rate limit exceeded" in resp.get("message", ""):
                if "Authorization" in self.headers:
                    url = "https://api.github.com/rate_limit"
                    log.debug("HTTP request: GET %s", url)
                    req = Request(url, headers=self.headers)
                    with urlopen(req) as r:
                        resp = json.load(r)
                    log.info(
                        "GitHub rate limit exceeded; details:\n\n%s\n",
                        textwrap.indent(json.dumps(resp, indent=4), " " * 4),
                    )
                else:
                    raise RuntimeError(
                        "GitHub rate limit exceeded and GITHUB_TOKEN not set;"
                        " suggest setting GITHUB_TOKEN in order to get increased"
                        " rate limit"
                    )


class MethodNotSupportedError(Exception):
    """
    Raised when an installer's `install()` method is called on an unsupported
    system or with an unsupported component
    """

    pass


class AuthClearHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        """
        Per `the W3 standard`__, remove the :mailheader:`Authorization` header
        from requests when following a redirect to another origin.  Without
        this, trying to download a GitHub Actions artifact uploaded with
        ``actions/upload-artifact@v4`` will fail due to the download URL
        redirecting to a non-GitHub domain that rejects GitHub authorization
        (despite it being fine with Authorization-less requests).

        __ https://fetch.spec.whatwg.org/#http-redirect-fetch
        """
        if get_url_origin(req.full_url) != get_url_origin(newurl):
            for k in req.headers.keys():
                if k.title() == "Authorization":
                    del req.headers[k]
                    break
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# Use AuthClearHandler for all requests done via urllib:
install_opener(build_opener(AuthClearHandler))


def get_url_origin(url: str) -> tuple[str, str | None, int]:
    # <https://url.spec.whatwg.org/#concept-url-origin>
    port_map = {"http": 80, "https": 443}
    bits = urlparse(url)
    scheme = bits.scheme.lower()
    if scheme not in port_map:
        raise ValueError(f"URL has unsupported scheme: {url!r}")
    host = bits.hostname
    if bits.port is None:
        port = port_map[scheme]
    else:
        port = bits.port
    return (scheme, host, port)


def download_file(
    url: str, path: str | Path, headers: Optional[dict[str, str]] = None
) -> None:
    """
    Download a file from ``url``, saving it at ``path``.  Optional ``headers``
    are sent in the HTTP request.
    """
    log.info("Downloading %s", url)
    if headers is None:
        headers = {}
    headers.setdefault("User-Agent", USER_AGENT)
    delays = iter([1, 2, 6, 15, 36])
    req = Request(url, headers=headers)
    while True:
        try:
            with urlopen(req) as r:
                with open(path, "wb") as fp:
                    shutil.copyfileobj(r, fp)
                if "content-length" in r.headers:
                    size = int(r.headers["Content-Length"])
                    fsize = os.path.getsize(path)
                    if fsize < size:
                        raise URLError(
                            f"only {fsize} out of {size} bytes were received"
                        )
            return
        except URLError as e:
            if isinstance(e, HTTPError) and e.code not in (500, 502, 503, 504):
                raise
            try:
                delay = next(delays)
            except StopIteration:
                raise e
            else:
                log.warning("Request to %s failed: %s", url, e)
                log.info("Retrying in %d seconds", delay)
                sleep(delay)


def download_to_tempfile(
    url: str, suffix: Optional[str] = None, headers: Optional[dict[str, str]] = None
) -> Path:
    # `suffix` should include the dot
    fd, tmpfile = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    p = Path(tmpfile)
    download_file(url, p, headers)
    return p


def download_zipfile(
    zip_url: str, target_dir: Path, headers: Optional[dict[str, str]] = None
) -> None:
    """
    Downloads the zipfile from ``zip_url`` and expands it in ``target_dir``
    """
    zippath = download_to_tempfile(zip_url, suffix=".zip", headers=headers)
    log.debug("Unzipping in %s", target_dir)
    with ZipFile(str(zippath)) as zipf:
        target_dir.mkdir(parents=True, exist_ok=True)
        zipf.extractall(str(target_dir))
    zippath.unlink()


def compose_pip_requirement(
    package: str,
    version: Optional[str] = None,
    urlspec: Optional[str] = None,
    extras: Optional[str] = None,
) -> str:
    """Compose a PEP 503 requirement specifier"""
    req = package
    if extras is not None:
        req += f"[{extras}]"
    if urlspec is None:
        if version is not None:
            req += f"=={version}"
    else:
        req += f" @ {urlspec}"
        if version is not None:
            req += f"@{version}"
    return req


def mktempdir(prefix: str) -> Path:
    """Create a directory in ``$TMPDIR`` with the given prefix"""
    return Path(tempfile.mkdtemp(prefix=prefix))


def runcmd(*args: str | Path, **kwargs: Any) -> subprocess.CompletedProcess:
    """Run (and log) a given command.  Raise an error if it fails."""
    arglist = [str(a) for a in args]
    log.info("Running: %s", " ".join(map(shlex.quote, arglist)))
    return subprocess.run(arglist, check=True, **kwargs)


def readcmd(*args: str | Path) -> str:
    """Run a command, capturing & returning its stdout"""
    s = runcmd(*args, stdout=subprocess.PIPE, universal_newlines=True).stdout
    assert isinstance(s, str)
    return s


def install_git_annex_dmg(dmgpath: str | Path, manager: DataladInstaller) -> Path:
    """Install git-annex from a DMG file at ``dmgpath``"""
    if platform.machine() == "arm64":
        log.info("M1 Mac detected; installing Rosetta")
        runcmd("/usr/sbin/softwareupdate", "--install-rosetta", "--agree-to-license")
    runcmd("hdiutil", "attach", dmgpath)
    runcmd("rsync", "-a", "/Volumes/git-annex/git-annex.app", "/Applications/")
    runcmd("hdiutil", "detach", "/Volumes/git-annex/")
    annex_bin = Path("/Applications/git-annex.app/Contents/MacOS")
    manager.addpath(annex_bin)
    return annex_bin


def install_deb(
    debpath: str | Path,
    manager: DataladInstaller,
    bin_path: Path,
    install_dir: Optional[Path] = None,
    extra_args: Optional[list[str]] = None,
) -> Path:
    if install_dir is None:
        cmd: list[str | Path] = ["dpkg"]
        if extra_args is not None:
            cmd.extend(extra_args)
        cmd.append("-i")
        cmd.append(debpath)
        manager.sudo(*cmd)
        return Path("/usr/bin")
    else:
        if extra_args:
            log.warning("Not using dpkg; ignoring --extra-args")
        assert os.path.isabs(debpath)
        install_dir.mkdir(parents=True, exist_ok=True)
        install_dir = install_dir.resolve()
        with tempfile.TemporaryDirectory() as tmpdir:
            oldpwd = os.getcwd()
            os.chdir(tmpdir)
            runcmd("ar", "-x", debpath)
            runcmd("tar", "-C", install_dir, "-xzf", "data.tar.gz")
            os.chdir(oldpwd)
        manager.addpath(install_dir / bin_path)
        return install_dir / bin_path


def ask(prompt: str, choices: list[str]) -> str:
    full_prompt = f"{prompt} [{'/'.join(choices)}] "
    while True:
        answer = input(full_prompt)
        if answer in choices:
            return answer


def get_version_codename() -> str:
    with open("/etc/os-release") as fp:
        for line in fp:
            m = re.fullmatch(
                r'VERSION_CODENAME=(")?(?P<value>[^"]+)(?(1)"|)', line.strip()
            )
            if m:
                return m["value"]
    # If VERSION_CODENAME is not set in /etc/os-release, then the contents of
    # /etc/debian_version should be of the form "$VERSION/sid".
    with open("/etc/debian_version") as fp:
        return fp.read().partition("/")[0]


def parse_header_links(links_header: str) -> dict[str, dict[str, str]]:
    """
    Parse a "Link" header from an HTTP response into a `dict` of the form::

        {"next": {"url": "...", "rel": "next"}, "last": { ... }}
    """
    # <https://github.com/psf/requests/blob/c45a4df/requests/utils.py#L829>
    links: dict[str, dict[str, str]] = {}
    replace_chars = " '\""
    value = links_header.strip(replace_chars)
    if not value:
        return links
    for val in re.split(r", *<", value):
        try:
            url, params = val.split(";", 1)
        except ValueError:
            url, params = val, ""
        link: dict[str, str] = {"url": url.strip("<> '\"")}
        for param in params.split(";"):
            try:
                key, value = param.split("=")
            except ValueError:
                break
            link[key.strip(replace_chars)] = value.strip(replace_chars)
        key = link.get("rel") or link.get("url")
        assert key is not None
        links[key] = link
    return links


def untmppath(path: Path, tmpdir: str | Path | None = None) -> Path:
    if "{tmpdir}" in str(path):
        if tmpdir is None:
            tmpdir = mktempdir("dl-")
        return Path(str(path).format(tmpdir=str(tmpdir)))
    else:
        return path


def untmppaths(*paths: Optional[Path]) -> tuple[Optional[Path], ...]:
    """
    Expand ``{tmpdir}`` in multiple paths, using the same temporary directory
    each time
    """
    if any("{tmpdir}" in str(p) for p in paths):
        tmpdir = mktempdir("dl-")
        return tuple(None if p is None else untmppath(p, tmpdir) for p in paths)
    else:
        return paths


def deb_pkg_installed(package: str) -> bool:
    r = subprocess.run(
        ["dpkg-query", "-Wf", "${db:Status-Status}", package],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        universal_newlines=True,
    )
    return r.returncode == 0 and r.stdout == "installed"


def check_exists(path: Path) -> bool:
    if ON_WINDOWS:
        # <https://github.com/datalad/datalad-installer/issues/92>
        for _ in range(5):
            if os.path.exists(path):
                return True
            sleep(1)
    return os.path.exists(path)


def parse_links(html: str, base_url: Optional[str] = None) -> list[Link]:
    """
    Parse the source of an HTML page and return a list of all hyperlinks found
    on it.

    This function does not support encoding declarations embedded in HTML, and
    it has limited ability to deal with invalid HTML.

    :param str html: the HTML document to parse
    :param Optional[str] base_url: an optional URL to join to the front of the
        links' URLs (usually the URL of the page being parsed)
    :rtype: list[Link]
    """
    parser = LinkParser(base_url=base_url)
    parser.feed(html)
    links = parser.fetch_links()
    parser.close()
    return links


@dataclass
class Link:
    """A hyperlink extracted from an HTML page"""

    #: The text inside the link tag, with leading & trailing whitespace removed
    #: and with any tags nested inside the link tags ignored
    text: str

    #: The URL that the link points to, resolved relative to the URL of the
    #: source HTML page and relative to the page's ``<base>`` href value, if
    #: any
    url: str

    #: A dictionary of attributes set on the link tag (including the unmodified
    #: ``href`` attribute).  Keys are converted to lowercase.
    attrs: dict[str, str]


# List taken from BeautifulSoup4 source
EMPTY_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "keygen",
    "link",
    "menuitem",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
    "basefont",
    "bgsound",
    "command",
    "frame",
    "image",
    "isindex",
    "nextid",
    "spacer",
}


class LinkParser(HTMLParser):
    def __init__(self, base_url: Optional[str] = None) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url: Optional[str] = base_url
        self.base_seen = False
        self.tag_stack: list[str] = []
        self.finished_links: list[Link] = []
        self.link_tag_stack: list[dict[str, str]] = []

    def fetch_links(self) -> list[Link]:
        links = self.finished_links
        self.finished_links = []
        return links

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag not in EMPTY_TAGS:
            self.tag_stack.append(tag)
        attrdict = {k: v or "" for k, v in attrs}
        if tag == "base" and "href" in attrdict and not self.base_seen:
            if self.base_url is None:
                self.base_url = attrdict["href"]
            else:
                self.base_url = urljoin(self.base_url, attrdict["href"])
            self.base_seen = True
        elif tag == "a":
            attrdict["#text"] = ""
            self.link_tag_stack.append(attrdict)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.tag_stack) - 1, -1, -1):
            if self.tag_stack[i] == tag:
                for t in self.tag_stack[i:]:
                    if t == "a":
                        self.end_link_tag()
                del self.tag_stack[i:]
                break

    def end_link_tag(self) -> None:
        attrs = self.link_tag_stack.pop()
        if "href" in attrs:
            text = attrs.pop("#text")
            if self.base_url is not None:
                url = urljoin(self.base_url, attrs["href"])
            else:
                url = attrs["href"]
            self.finished_links.append(Link(text=text.strip(), url=url, attrs=attrs))

    def handle_data(self, data: str) -> None:
        for link in self.link_tag_stack:
            link["#text"] += data

    def close(self) -> None:
        while self.link_tag_stack:
            self.handle_endtag("a")
        super().close()


def main(argv: Optional[list[str]] = None) -> int:
    with DataladInstaller() as manager:
        return manager.main(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
