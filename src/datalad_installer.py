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

__version__ = "0.11.1"
__author__ = "The DataLad Team and Contributors"
__author_email__ = "team@datalad.org"
__license__ = "MIT"
__url__ = "https://github.com/datalad/datalad-installer"

from abc import ABC, abstractmethod
from contextlib import contextmanager, suppress
import ctypes
from enum import Enum
from functools import total_ordering
from getopt import GetoptError, getopt
import json
import logging
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
from typing import (
    Any,
    Callable,
    ClassVar,
    Dict,
    Iterator,
    List,
    NamedTuple,
    Optional,
    Tuple,
    Type,
    Union,
    cast,
)
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zipfile import ZipFile

log = logging.getLogger("datalad_installer")

SYSTEM = platform.system()
ON_LINUX = SYSTEM == "Linux"
ON_MACOS = SYSTEM == "Darwin"
ON_WINDOWS = SYSTEM == "Windows"
ON_POSIX = ON_LINUX or ON_MACOS


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


class Immediate:
    """
    Superclass for constructs returned by the argument-parsing code
    representing options that are handled "immediately" (i.e., --version and
    --help)
    """

    pass


class VersionRequest(Immediate):
    """`Immediate` representing a ``--version`` option"""

    def __eq__(self, other: Any) -> bool:
        if type(self) is type(other):
            return True
        else:
            return NotImplemented


class HelpRequest(Immediate):
    """`Immediate` representing a ``--help`` option"""

    def __init__(self, component: Optional[str]) -> None:
        #: The component for which help was requested, or `None` if the
        #: ``--help`` option was given at the global level
        self.component: Optional[str] = component

    def __eq__(self, other: Any) -> bool:
        if type(self) is type(other):
            return bool(self.component == other.component)
        else:
            return NotImplemented


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
        choices: Optional[List[str]] = None,
        help: Optional[str] = None,
    ) -> None:
        #: List of individual option characters
        self.shortopts: List[str] = []
        #: List of long option names (sans leading "--")
        self.longopts: List[str] = []
        dest: Optional[str] = None
        self.is_flag: bool = is_flag
        self.converter: Optional[Callable[[str], Any]] = converter
        self.multiple: bool = multiple
        self.immediate: Optional[Immediate] = immediate
        self.metavar: Optional[str] = metavar
        self.choices: Optional[List[str]] = choices
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
            return vars(self) == vars(other)
        else:
            return NotImplemented

    def __lt__(self, other: Any) -> bool:
        if type(self) is type(other):
            return bool(self._cmp_key() < other._cmp_key())
        else:
            return NotImplemented

    def _cmp_key(self) -> Tuple[int, str]:
        name = self.option_name
        if name == "--help":
            return (2, "--help")
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

    def process(self, namespace: Dict[str, Any], argument: str) -> Optional[Immediate]:
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


class OptionParser:
    def __init__(
        self,
        component: Optional[str] = None,
        versioned: bool = False,
        help: Optional[str] = None,
        options: Optional[List[Option]] = None,
    ) -> None:
        self.component: Optional[str] = component
        self.versioned: bool = versioned
        self.help: Optional[str] = help
        #: Mapping from individual option characters to Option instances
        self.short_options: Dict[str, Option] = {}
        #: Mapping from long option names (sans leading "--") to Option
        #: instances
        self.long_options: Dict[str, Option] = {}
        #: Mapping from option names (including leading hyphens) to Option
        #: instances
        self.options: Dict[str, Option] = {}
        self.option_list: List[Option] = []
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
        if self.options.get(option.option_name) == option:
            return
        for o in option.shortopts:
            if o in self.short_options:
                raise ValueError(f"Option -{o} registered more than once")
        for o in option.longopts:
            if o in self.long_options:
                raise ValueError(f"Option --{o} registered more than once")
        for o in option.shortopts:
            self.short_options[o] = option
            self.options[f"-{o}"] = option
        for o in option.longopts:
            self.long_options[o] = option
            self.options[f"--{o}"] = option
        self.option_list.append(option)

    def parse_args(
        self, args: List[str]
    ) -> Union[Immediate, Tuple[Dict[str, Any], List[str]]]:
        """
        Parse command-line arguments, stopping when a non-option is reached.
        Returns either an `Immediate` (if an immediate option is encountered)
        or a tuple of the option values and remaining arguments.

        :param List[str] args: command-line arguments without ``sys.argv[0]``
        """
        shortspec = ""
        for o, option in self.short_options.items():
            if option.is_flag:
                shortspec += o
            else:
                shortspec += f"{o}:"
        longspec = []
        for o, option in self.long_options.items():
            if option.is_flag:
                longspec.append(o)
            else:
                longspec.append(f"{o}=")
        try:
            optlist, leftovers = getopt(args, shortspec, longspec)
        except GetoptError as e:
            raise UsageError(str(e), self.component)
        kwargs: Dict[str, Any] = {}
        for (o, a) in optlist:
            option = self.options[o]
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
        if self.options:
            lines.append("")
            lines.append("Options:")
            for option in sorted(self.option_list):
                lines.extend(option.get_help().splitlines())
        return "\n".join(lines)


class UsageError(Exception):
    """Raised when an error occurs while processing command-line options"""

    def __init__(self, message: str, component: Optional[str] = None) -> None:
        #: The error message
        self.message: str = message
        #: The component for which the error occurred, or `None` if the error
        #: was at the global level
        self.component: Optional[str] = component

    def __str__(self) -> str:
        return self.message


class ParsedArgs(NamedTuple):
    """
    A pair of global options and `ComponentRequest`\\s parsed from command-line
    arguments
    """

    global_opts: Dict[str, Any]
    components: List["ComponentRequest"]


class ComponentRequest:
    """A request for a component parsed from command-line arguments"""

    def __init__(self, name: str, **kwargs: Any) -> None:
        self.name: str = name
        self.kwargs: Dict[str, Any] = kwargs

    def __eq__(self, other: Any) -> bool:
        if type(self) is type(other):
            return bool(self.name == other.name and self.kwargs == other.kwargs)
        else:
            return NotImplemented

    def __repr__(self) -> str:
        attrs = [f"name={self.name!r}"]
        for k, v in self.kwargs.items():
            attrs.append(f"{k}={v!r}")
        return "{0.__module__}.{0.__name__}({1})".format(
            type(self),
            ", ".join(attrs),
        )


class CondaInstance(NamedTuple):
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


class Command:
    """An external command that can be installed by this script"""

    def __init__(self, name: str, test_args: Optional[List[str]] = None) -> None:
        #: Name of the command
        self.name = name
        if test_args is None:
            #: Arguments with which to invoke the command as a smoke test
            self.test_args = ["--help"]
        else:
            self.test_args = test_args

    def in_bindir(self, bindir: Path) -> "InstalledCommand":
        """
        Return an `InstalledCommand` recording that the command is installed in
        the given directory
        """
        cmdpath = bindir / self.name
        if ON_WINDOWS and cmdpath.suffix == "":
            cmdpath = cmdpath.with_suffix(".exe")
        return InstalledCommand(name=self.name, path=cmdpath, test_args=self.test_args)


class InstalledCommand(Command):
    """An external command that has been installed by this script"""

    def __init__(
        self, name: str, path: Path, test_args: Optional[List[str]] = None
    ) -> None:
        super().__init__(name, test_args)
        #: Path at which the command is installed
        self.path = path

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


DATALAD_CMD = Command("datalad")
GIT_ANNEX_CMD = Command("git-annex")
# Smoke-test rclone with --version instead of --help because the latter didn't
# exist before rclone 1.33
RCLONE_CMD = Command("rclone", test_args=["--version"])
GIT_ANNEX_REMOTE_RCLONE_CMD = Command("git-annex-remote-rclone")


class DataladInstaller:
    """The script's primary class, a manager & runner of components"""

    COMPONENTS: ClassVar[Dict[str, Type["Component"]]] = {}

    OPTION_PARSER = OptionParser(
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

    def __init__(
        self,
        env_write_files: Optional[List[Union[str, os.PathLike]]] = None,
        sudo_confirm: SudoConfirm = SudoConfirm.ASK,
    ) -> None:
        #: A list of files to which to write ``PATH`` modifications and related
        #: shell commands
        self.env_write_files: List[Path]
        if env_write_files is None:
            self.env_write_files = []
        else:
            self.env_write_files = [Path(p) for p in env_write_files]
        self.sudo_confirm: SudoConfirm = sudo_confirm
        #: The default installers to fall back on for the "auto" installation
        #: method
        self.installer_stack: List["Installer"] = [
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
        #: A stack of Conda installations & environments installed via the
        #: instance
        self.conda_stack: List[CondaInstance] = []
        #: A list of commands installed via the instance
        self.new_commands: List[InstalledCommand] = []
        #: Whether "brew update" has been run
        self.brew_updated: bool = False

    @classmethod
    def register_component(cls, component: Type["Component"]) -> Type["Component"]:
        """A decorator for registering concrete `Component` subclasses"""
        cls.COMPONENTS[component.NAME] = component
        return component

    def __enter__(self) -> "DataladInstaller":
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

    def sudo(self, *args: Any, **kwargs: Any) -> None:
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

    def run_maybe_elevated(self, *args: Any, **kwargs: Any) -> None:
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
    def parse_args(cls, args: List[str]) -> Union[Immediate, ParsedArgs]:
        """
        Parse all command-line arguments.

        :param List[str] args: command-line arguments without ``sys.argv[0]``
        """
        r = cls.OPTION_PARSER.parse_args(args)
        if isinstance(r, Immediate):
            return r
        global_opts, leftovers = r
        components: List[ComponentRequest] = []
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
            components.append(ComponentRequest(name=name, **kwargs))
        return ParsedArgs(global_opts, components)

    def main(self, argv: Optional[List[str]] = None) -> int:
        """
        Parsed command-line arguments and perform the requested actions.
        Returns 0 if everything was OK, nonzero otherwise.

        :param List[str] argv: command-line arguments, including
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
            print(self.long_help(progname, r.component))
            return 0
        else:
            assert isinstance(r, ParsedArgs)
        global_opts, components = r
        if not components:
            components = [ComponentRequest("datalad")]
        logging.basicConfig(
            format="%(asctime)s [%(levelname)-8s] %(name)s %(message)s",
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

    def addpath(self, p: Union[str, os.PathLike], last: bool = False) -> None:
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
                    chelp = cmpnt.OPTION_PARSER.help
                else:
                    chelp = ""
                s += (
                    f"\n{' ' * HELP_INDENT}{name:{width}}{' ' * HELP_GUTTER}"
                    + textwrap.shorten(chelp, HELP_WIDTH - width - HELP_GUTTER)
                )
            return s
        else:
            return cls.COMPONENTS[component].OPTION_PARSER.long_help(progname)


class Component(ABC):
    """
    An abstract base class for a component that can be specified on the command
    line and provisioned
    """

    NAME: ClassVar[str]

    OPTION_PARSER: ClassVar[OptionParser]

    def __init__(self, manager: DataladInstaller) -> None:
        self.manager = manager

    @abstractmethod
    def provide(self, **kwargs: Any) -> None:
        ...


@DataladInstaller.register_component
class VenvComponent(Component):
    """Creates a Python virtual environment using ``python -m venv``"""

    NAME = "venv"

    OPTION_PARSER = OptionParser(
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
        extra_args: Optional[List[str]] = None,
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
class MinicondaComponent(Component):
    """Installs Miniconda"""

    NAME = "miniconda"

    OPTION_PARSER = OptionParser(
        "miniconda",
        versioned=False,
        help="Install Miniconda",
        options=[
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
        spec: Optional[List[str]] = None,
        python_match: Optional[str] = None,
        extra_args: Optional[List[str]] = None,
        channel: Optional[List[str]] = None,
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
        if ON_LINUX:
            miniconda_script = "Miniconda3-latest-Linux-x86_64.sh"
        elif ON_MACOS:
            arch = platform.machine().lower()
            if arch in ("x86_64", "arm64"):
                miniconda_script = f"Miniconda3-latest-MacOSX-{arch}.sh"
            else:
                raise RuntimeError(f"E: Unsupported architecture: {arch}")
        elif ON_WINDOWS:
            miniconda_script = "Miniconda3-latest-Windows-x86_64.exe"
        else:
            raise RuntimeError(f"E: Unsupported OS: {SYSTEM}")
        if python_match is not None:
            vparts: Tuple[int, ...]
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
                (
                    os.environ.get("ANACONDA_URL")
                    or "https://repo.anaconda.com/miniconda/"
                ).rstrip("/")
                + "/"
                + miniconda_script,
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
                args = ["-p", path, "-s"]
                if batch:
                    args.append("-b")
                if extra_args is not None:
                    args.extend(extra_args)
                runcmd("bash", script_path, *args)
        conda_instance = CondaInstance(basepath=path, name=None)
        if spec is not None:
            install_args: List[str] = []
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


@DataladInstaller.register_component
class CondaEnvComponent(Component):
    """Creates a Conda environment"""

    NAME = "conda-env"

    OPTION_PARSER = OptionParser(
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
        spec: Optional[List[str]] = None,
        extra_args: Optional[List[str]] = None,
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
        cmd = [conda.conda_exe, "create", "--name", cname]
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
class NeurodebianComponent(Component):
    """Installs & configures NeuroDebian"""

    NAME = "neurodebian"

    OPTION_PARSER = OptionParser(
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

    KEY_FINGERPRINT = "0xA5D32F012649A5A9"
    KEY_URL = "http://neuro.debian.net/_static/neuro.debian.net.asc"
    DOWNLOAD_SERVER = "us-nh"

    def provide(self, extra_args: Optional[List[str]] = None, **kwargs: Any) -> None:
        log.info("Installing & configuring NeuroDebian")
        log.info("Extra args: %s", extra_args)
        if kwargs:
            log.warning("Ignoring extra component arguments: %r", kwargs)
        r = subprocess.run(
            ["apt-cache", "show", "neurodebian"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
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
                    "/etc/apt/sources.list.d/neurodebian.sources.list",
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
        runcmd("nd-configurerepo", *(extra_args or []))


class InstallableComponent(Component):
    """
    Superclass for components that install packages via installation methods
    """

    INSTALLERS: ClassVar[Dict[str, Type["Installer"]]] = {}

    @classmethod
    def register_installer(cls, installer: Type["Installer"]) -> Type["Installer"]:
        """A decorator for registering concrete `Installer` subclasses"""
        cls.INSTALLERS[installer.NAME] = installer
        methods = cls.OPTION_PARSER.options["--method"].choices
        assert methods is not None
        methods.append(installer.NAME)
        for opt in installer.OPTIONS:
            cls.OPTION_PARSER.add_option(opt)
        return installer

    def get_installer(self, name: str) -> "Installer":
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
class GitAnnexComponent(InstallableComponent):
    """Installs git-annex"""

    NAME = "git-annex"

    OPTION_PARSER = OptionParser(
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
class DataladComponent(InstallableComponent):
    """Installs Datalad"""

    NAME = "datalad"

    OPTION_PARSER = OptionParser(
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
class RCloneComponent(InstallableComponent):
    """Installs rclone"""

    NAME = "rclone"

    OPTION_PARSER = OptionParser(
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
class GitAnnexRemoteRCloneComponent(InstallableComponent):
    """Installs git-annex-remote-rclone"""

    NAME = "git-annex-remote-rclone"

    OPTION_PARSER = OptionParser(
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


class Installer(ABC):
    """An abstract base class for installation methods for packages"""

    NAME: ClassVar[str]

    OPTIONS: ClassVar[List[Option]]

    #: Mapping from supported installable component names to
    #: (installer-specific package IDs, list of installed programs) pairs
    PACKAGES: ClassVar[Dict[str, Tuple[str, List[Command]]]]

    def __init__(self, manager: DataladInstaller) -> None:
        self.manager = manager

    def install(self, component: str, **kwargs: Any) -> List[InstalledCommand]:
        """
        Installs a given component.  Raises `MethodNotSupportedError` if the
        installation method is not supported on the system or the method does
        not support installing the given component.  Returns a list of
        (command, Path) pairs for each installed program.
        """
        self.assert_supported_system()
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
    def assert_supported_system(self) -> None:
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
class AptInstaller(Installer):
    """Installs via apt-get"""

    NAME = "apt"

    OPTIONS = [
        Option(
            "--build-dep", is_flag=True, help="Install build-dep instead of the package"
        ),
        EXTRA_ARGS_OPTION,
    ]

    PACKAGES = {
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
        extra_args: Optional[List[str]] = None,
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
            cmd.append("install")
        if extra_args:
            cmd.extend(extra_args)
        if version is not None:
            cmd.append(f"{package}={version}")
        else:
            cmd.append(package)
        self.manager.sudo(*cmd)
        log.debug("Installed program directory: /usr/bin")
        return Path("/usr/bin")

    def assert_supported_system(self) -> None:
        if shutil.which("apt-get") is None:
            raise MethodNotSupportedError("apt-get command not found")


@DataladComponent.register_installer
@GitAnnexComponent.register_installer
@RCloneComponent.register_installer
@GitAnnexRemoteRCloneComponent.register_installer
class HomebrewInstaller(Installer):
    """Installs via brew (Homebrew)"""

    NAME = "brew"

    OPTIONS = [
        EXTRA_ARGS_OPTION,
    ]

    PACKAGES = {
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
        extra_args: Optional[List[str]] = None,
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

    def assert_supported_system(self) -> None:
        if shutil.which("brew") is None:
            raise MethodNotSupportedError("brew command not found")


@DataladComponent.register_installer
class PipInstaller(Installer):
    """
    Installs via pip, either at the system level or into a given virtual
    environment
    """

    NAME = "pip"

    OPTIONS = [
        Option("--devel", is_flag=True, help="Install from GitHub repository"),
        Option("-E", "--extras", metavar="EXTRAS", help="Install package extras"),
        EXTRA_ARGS_OPTION,
    ]

    PACKAGES = {
        "datalad": ("datalad", [DATALAD_CMD]),
    }

    DEVEL_PACKAGES = {
        "datalad": "git+https://github.com/datalad/datalad.git",
    }

    def __init__(
        self, manager: DataladInstaller, venv_path: Optional[Path] = None
    ) -> None:
        super().__init__(manager)
        #: The path to the virtual environment in which to install, or `None`
        #: if installation should be done at the system level
        self.venv_path: Optional[Path] = venv_path

    @property
    def python(self) -> Union[str, Path]:
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
        extra_args: Optional[List[str]] = None,
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

    def assert_supported_system(self) -> None:
        ### TODO: Detect whether pip is installed in the current Python,
        ### preferably without importing it
        pass


@GitAnnexComponent.register_installer
class NeurodebianInstaller(AptInstaller):
    """Installs via apt-get and the NeuroDebian repositories"""

    NAME = "neurodebian"

    PACKAGES = {
        "git-annex": ("git-annex-standalone", [GIT_ANNEX_CMD]),
    }

    def assert_supported_system(self) -> None:
        super().assert_supported_system()
        if "l=NeuroDebian" not in readcmd("apt-cache", "policy"):
            raise MethodNotSupportedError("Neurodebian not configured")


@GitAnnexComponent.register_installer
@DataladComponent.register_installer
@RCloneComponent.register_installer
@GitAnnexRemoteRCloneComponent.register_installer
class DebURLInstaller(Installer):
    """Installs a ``*.deb`` package by URL"""

    NAME = "deb-url"

    OPTIONS = [
        Option("--url", metavar="URL", help="URL from which to download `*.deb` file"),
        Option(
            "--install-dir",
            converter=Path,
            metavar="DIR",
            help="Directory in which to unpack the `*.deb`",
        ),
        EXTRA_ARGS_OPTION,
    ]

    PACKAGES = {
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
        extra_args: Optional[List[str]] = None,
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

    def assert_supported_system(self) -> None:
        if shutil.which("dpkg") is None:
            raise MethodNotSupportedError("dpkg command not found")


class AutobuildSnapshotInstaller(Installer):
    OPTIONS: ClassVar[List[Option]] = []

    PACKAGES = {
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

    def assert_supported_system(self) -> None:
        if not ON_POSIX:
            raise MethodNotSupportedError(f"{SYSTEM} OS not supported")


@GitAnnexComponent.register_installer
class AutobuildInstaller(AutobuildSnapshotInstaller):
    """Installs the latest official build of git-annex from kitenet.net"""

    NAME = "autobuild"

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
class SnapshotInstaller(AutobuildSnapshotInstaller):
    """
    Installs the latest official snapshot build of git-annex from kitenet.net
    """

    NAME = "snapshot"

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
class CondaInstaller(Installer):
    """Installs via conda"""

    NAME = "conda"

    OPTIONS = [
        EXTRA_ARGS_OPTION,
    ]

    PACKAGES = {
        "datalad": ("datalad", [DATALAD_CMD]),
        "git-annex": ("git-annex", [GIT_ANNEX_CMD]),
        "rclone": ("rclone", [RCLONE_CMD]),
        "git-annex-remote-rclone": (
            "git-annex-remote-rclone",
            [GIT_ANNEX_REMOTE_RCLONE_CMD],
        ),
    }

    def __init__(
        self, manager: DataladInstaller, conda_instance: Optional[CondaInstance] = None
    ) -> None:
        super().__init__(manager)
        self.conda_instance: Optional[CondaInstance] = conda_instance

    def install_package(
        self,
        package: str,
        version: Optional[str] = None,
        extra_args: Optional[List[str]] = None,
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
        cmd = [conda.conda_exe, "install"]
        if conda.name is not None:
            cmd.append("--name")
            cmd.append(conda.name)
        cmd += ["-q", "-c", "conda-forge", "-y"]
        if extra_args is not None:
            cmd.extend(extra_args)
        if version is None:
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

    def assert_supported_system(self) -> None:
        if not self.manager.conda_stack and shutil.which("conda") is None:
            raise MethodNotSupportedError("Conda installation not found")


@GitAnnexComponent.register_installer
class DataladGitAnnexBuildInstaller(Installer):
    """
    Installs git-annex via the artifact from the latest successful build of
    datalad/git-annex
    """

    NAME = "datalad/git-annex:tested"

    OPTIONS = [
        Option(
            "--install-dir",
            converter=Path,
            metavar="DIR",
            help="Directory in which to unpack the `*.deb`",
        ),
    ]

    PACKAGES = {
        "git-annex": ("git-annex", [GIT_ANNEX_CMD]),
    }

    VERSIONED = False

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

    def assert_supported_system(self) -> None:
        if not (ON_LINUX or ON_MACOS or ON_WINDOWS):
            raise MethodNotSupportedError(f"{SYSTEM} OS not supported")

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
class DataladGitAnnexLatestBuildInstaller(DataladGitAnnexBuildInstaller):
    """
    Installs git-annex via the artifact from the latest artifact-producing
    build (successful or unsuccessful) of datalad/git-annex
    """

    NAME = "datalad/git-annex"

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
class DataladGitAnnexReleaseBuildInstaller(DataladGitAnnexBuildInstaller):
    """Installs git-annex via an asset of a release of datalad/git-annex"""

    NAME = "datalad/git-annex:release"

    VERSIONED = True

    @staticmethod
    def download(ostype: str, target_dir: Path, version: Optional[str]) -> None:
        GitHubClient(auth_required=False).download_release_asset(
            target_dir,
            repo="datalad/git-annex",
            ext={"ubuntu": ".deb", "macos": ".dmg", "windows": ".exe"}[ostype],
            tag=version,
        )


@GitAnnexComponent.register_installer
class DataladPackagesBuildInstaller(Installer):
    """
    Installs git-annex via artifacts uploaded to
    <https://datasets.datalad.org/?dir=/datalad/packages>
    """

    NAME = "datalad/packages"

    OPTIONS = [
        Option(
            "--install-dir",
            converter=Path,
            metavar="DIR",
            help="Directory in which to unpack the `*.deb`",
        ),
    ]

    PACKAGES = {
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

    def assert_supported_system(self) -> None:
        pass


@GitAnnexComponent.register_installer
class DMGInstaller(Installer):
    """Installs a local ``*.dmg`` file"""

    NAME = "dmg"

    OPTIONS = [
        Option(
            "--path",
            converter=Path,
            metavar="PATH",
            help="Path to local `*.dmg` to install",
        ),
    ]

    PACKAGES = {
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

    def assert_supported_system(self) -> None:
        if not ON_MACOS:
            raise MethodNotSupportedError(f"{SYSTEM} OS not supported")


@GitAnnexRemoteRCloneComponent.register_installer
class GARRCGitHubInstaller(Installer):
    """Installs git-annex-remote-rclone from a tag on GitHub"""

    NAME = "DanielDent/git-annex-remote-rclone"

    OPTIONS = [
        Option(
            "--bin-dir",
            converter=Path,
            metavar="DIR",
            help="Directory in which to install the program",
        ),
    ]

    PACKAGES = {
        "git-annex-remote-rclone": (
            "git-annex-remote-rclone",
            [GIT_ANNEX_REMOTE_RCLONE_CMD],
        ),
    }

    REPO = "DanielDent/git-annex-remote-rclone"

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

    def assert_supported_system(self) -> None:
        if not ON_POSIX:
            raise MethodNotSupportedError(f"{SYSTEM} OS not supported")


@RCloneComponent.register_installer
class DownloadsRCloneInstaller(Installer):
    """Installs rclone via downloads.rclone.org"""

    NAME = "downloads.rclone.org"

    OPTIONS = [
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

    PACKAGES = {"rclone": ("rclone", [RCLONE_CMD])}

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

    def assert_supported_system(self) -> None:
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
        if token:
            self.headers = {"Authorization": f"Bearer {token}"}
        else:
            self.headers = {}

    @contextmanager
    def get(self, url: str) -> Iterator[Any]:
        log.debug("HTTP request: GET %s", url)
        req = Request(url, headers=self.headers)
        try:
            with urlopen(req) as r:
                yield r
        except URLError as e:
            raise_for_ratelimit(e, self.headers.get("Authorization"))
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
                links = parse_header_links(r.headers.get("Link"))
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
                download_zipfile(archive_download_url, target_dir, headers=self.headers)
                return
        else:
            raise RuntimeError("No workflow runs with artifacts found!")

    def download_last_successful_artifact(
        self, target_dir: Path, repo: str, workflow: str, branch: str = "master"
    ) -> None:
        """
        Downloads the most recent artifact built by a succesful run of
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
                download_zipfile(archive_download_url, target_dir, headers=self.headers)
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
        download_file(
            asset["browser_download_url"],
            target_dir / asset["name"],
            headers=self.headers,
        )

    def get_latest_release(self, repo: str) -> Dict[str, Any]:
        """
        Returns information on the most latest non-draft non-prerelease release
        of ``repo``.  Raises 404 if the repo has no releases.
        """
        return cast(
            Dict[str, Any],
            self.getjson(f"https://api.github.com/repos/{repo}/releases/latest"),
        )


class MethodNotSupportedError(Exception):
    """
    Raised when an installer's `install()` method is called on an unsupported
    system or with an unsupported component
    """

    pass


def raise_for_ratelimit(e: URLError, auth: Optional[str]) -> None:
    if isinstance(e, HTTPError) and e.code == 403:
        try:
            resp = json.load(e)
        except Exception:
            return
        if "API rate limit exceeded" in resp.get("message", ""):
            if auth is not None:
                url = "https://api.github.com/rate_limit"
                log.debug("HTTP request: GET %s", url)
                req = Request(url, headers={"Authorization": auth})
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


def download_file(
    url: str, path: Union[str, os.PathLike], headers: Optional[Dict[str, str]] = None
) -> None:
    """
    Download a file from ``url``, saving it at ``path``.  Optional ``headers``
    are sent in the HTTP request.
    """
    log.info("Downloading %s", url)
    if headers is None:
        headers = {}
    delays = iter([1, 2, 6, 15, 36])
    req = Request(url, headers=headers)
    while True:
        try:
            with urlopen(req) as r:
                with open(path, "wb") as fp:
                    shutil.copyfileobj(r, fp)
            return
        except URLError as e:
            if isinstance(e, HTTPError) and e.code not in (500, 502, 503, 504):
                raise_for_ratelimit(e, headers.get("Authorization"))
                raise
            try:
                delay = next(delays)
            except StopIteration:
                raise
            else:
                log.warning("Request to %s failed: %s", url, e)
                log.info("Retrying in %d seconds", delay)


def download_to_tempfile(
    url: str, suffix: Optional[str] = None, headers: Optional[Dict[str, str]] = None
) -> Path:
    # `suffix` should include the dot
    fd, tmpfile = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    p = Path(tmpfile)
    download_file(url, p, headers)
    return p


def download_zipfile(
    zip_url: str, target_dir: Path, headers: Optional[Dict[str, str]] = None
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


def runcmd(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
    """Run (and log) a given command.  Raise an error if it fails."""
    arglist = [str(a) for a in args]
    log.info("Running: %s", " ".join(map(shlex.quote, arglist)))
    return subprocess.run(arglist, check=True, **kwargs)


def readcmd(*args: Any) -> str:
    """Run a command, capturing & returning its stdout"""
    s = runcmd(*args, stdout=subprocess.PIPE, universal_newlines=True).stdout
    assert isinstance(s, str)
    return s


def install_git_annex_dmg(
    dmgpath: Union[str, os.PathLike], manager: DataladInstaller
) -> Path:
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
    debpath: Union[str, os.PathLike],
    manager: DataladInstaller,
    bin_path: Path,
    install_dir: Optional[Path] = None,
    extra_args: Optional[List[str]] = None,
) -> Path:
    if install_dir is None:
        cmd: List[Union[str, os.PathLike]] = ["dpkg"]
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


def ask(prompt: str, choices: List[str]) -> str:
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


def parse_header_links(links_header: str) -> Dict[str, Dict[str, str]]:
    """
    Parse a "Link" header from an HTTP response into a `dict` of the form::

        {"next": {"url": "...", "rel": "next"}, "last": { ... }}
    """
    # <https://github.com/psf/requests/blob/c45a4df/requests/utils.py#L829>
    links: Dict[str, Dict[str, str]] = {}
    replace_chars = " '\""
    value = links_header.strip(replace_chars)
    if not value:
        return links
    for val in re.split(r", *<", value):
        try:
            url, params = val.split(";", 1)
        except ValueError:
            url, params = val, ""
        link: Dict[str, str] = {"url": url.strip("<> '\"")}
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


def untmppath(path: Path, tmpdir: Union[str, Path, None] = None) -> Path:
    if "{tmpdir}" in str(path):
        if tmpdir is None:
            tmpdir = mktempdir("dl-")
        return Path(str(path).format(tmpdir=str(tmpdir)))
    else:
        return path


def untmppaths(*paths: Optional[Path]) -> Tuple[Optional[Path], ...]:
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


def main(argv: Optional[List[str]] = None) -> int:
    with DataladInstaller() as manager:
        return manager.main(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
