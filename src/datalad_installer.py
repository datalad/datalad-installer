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

__version__ = "0.1.0"
__author__ = "The DataLad Team and Contributors"
__author_email__ = "team@datalad.org"
__license__ = "MIT"
__url__ = "https://github.com/datalad/datalad-installer"

from abc import ABC, abstractmethod
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
from typing import (
    Any,
    Callable,
    ClassVar,
    Dict,
    List,
    NamedTuple,
    Optional,
    Tuple,
    Type,
    Union,
)
from urllib.request import Request, urlopen
from zipfile import ZipFile

log = logging.getLogger("datalad_installer")


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
    """ `Immediate` representing a ``--version`` option """

    def __eq__(self, other: Any) -> bool:
        if type(self) is type(other):
            return True
        else:
            return NotImplemented


class HelpRequest(Immediate):
    """ `Immediate` representing a ``--help`` option """

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
        """ Display name for the option """
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
            if self.converter is None:
                value = argument
            else:
                value = self.converter(argument)
            if self.choices is not None and value not in self.choices:
                raise UsageError(
                    f"Invalid choice for {self.option_name} option: {value!r}"
                )
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
            lines.extend(
                " " * HELP_INDENT + ln for ln in textwrap.wrap(self.help, HELP_WIDTH)
            )
        if self.options:
            lines.append("")
            lines.append("Options:")
            for option in sorted(self.option_list):
                lines.extend(option.get_help().splitlines())
        return "\n".join(lines)


class UsageError(Exception):
    """ Raised when an error occurs while processing command-line options """

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
    """ A request for a component parsed from command-line arguments """

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
    """ A Conda installation or environment """

    #: The root of the Conda installation
    basepath: Path

    #: The name of the environment (`None` for the base environment)
    name: Optional[str]


#: A list of command names and the paths at which they are located
CommandList = List[Tuple[str, Path]]


class DataladInstaller:
    """ The script's primary class, a manager & runner of components """

    COMPONENTS: ClassVar[Dict[str, Type["Component"]]] = {}

    OPTION_PARSER = OptionParser(
        help="Installation script for Datalad and related components",
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
        ],
    )

    def __init__(
        self, env_write_files: Optional[List[Union[str, os.PathLike]]] = None
    ) -> None:
        #: A list of files to which to write ``PATH`` modifications and related
        #: shell commands
        self.env_write_files: List[Path]
        if env_write_files is None:
            self.env_write_files = []
        else:
            self.env_write_files = [Path(p) for p in env_write_files]
        #: The default installers to fall back on for the "auto" installation
        #: method
        self.installer_stack: List["Installer"] = [
            # Lowest priority first
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
        self.new_commands: CommandList = []

    @classmethod
    def register_component(
        cls, name: str
    ) -> Callable[[Type["Component"]], Type["Component"]]:
        """ A decorator for registering concrete `Component` subclasses """

        def decorator(component: Type["Component"]) -> Type["Component"]:
            cls.COMPONENTS[name] = component
            return component

        return decorator

    def __enter__(self) -> "DataladInstaller":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if exc_type is None:
            # Ensure env write files at least exist
            for p in self.env_write_files:
                p.touch()

    def ensure_env_write_file(self) -> None:
        """ If there are no env write files registered, add one """
        if not self.env_write_files:
            fd, fpath = tempfile.mkstemp(prefix="dl-env-", suffix=".sh")
            os.close(fd)
            log.info("Writing environment modifications to %s", fpath)
            self.env_write_files.append(Path(fpath))

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
        for cr in components:
            self.addcomponent(name=cr.name, **cr.kwargs)
        ok = True
        for name, path in self.new_commands:
            log.info("%s is now installed at %s", name, path)
            if path.name != name:
                log.error("Program does not have expected name!")
                ok = False
            if not os.access(path, os.X_OK):
                log.error("Cannot execute program!")
                ok = False
        return 0 if ok else 1

    def addenv(self, line: str) -> None:
        """ Write a line to the env write files """
        log.debug("Adding line %r to env_write_files", line)
        for p in self.env_write_files:
            with p.open("a") as fp:
                print(line, file=fp)

    def addpath(self, p: Union[str, os.PathLike], last: bool = False) -> None:
        """
        Add a line to the env write files that prepends (or appends, if
        ``last`` is true) a given path to ``PATH``
        """
        if not last:
            line = f'export PATH={shlex.quote(str(p))}:"$PATH"'
        else:
            line = f'export PATH="$PATH":{shlex.quote(str(p))}'
        self.addenv(line)

    def addcomponent(self, name: str, **kwargs: Any) -> None:
        """ Provision the given component """
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

    OPTION_PARSER: ClassVar[OptionParser]

    def __init__(self, manager: DataladInstaller) -> None:
        self.manager = manager

    @abstractmethod
    def provide(self, **kwargs: Any) -> None:
        ...


@DataladInstaller.register_component("venv")
class VenvComponent(Component):
    """ Creates a Python virtual environment using ``python -m venv`` """

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
        ],
    )

    def provide(
        self,
        path: Optional[Path] = None,
        extra_args: Optional[List[str]] = None,
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
        self.manager.installer_stack.append(PipInstaller(self.manager, path))


@DataladInstaller.register_component("miniconda")
class MinicondaComponent(Component):
    """ Installs Miniconda """

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
                "--spec",
                converter=str.split,
                help=(
                    "Space-separated list of package specifiers to install in"
                    " the Miniconda environment"
                ),
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
        extra_args: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> None:
        log.info("Installing Miniconda")
        if path is None:
            path = mktempdir("dl-miniconda-")
            # The Miniconda installer requires that the given path not already
            # exist (unless -u is given); hence, we need to delete the new
            # directory before using it.  (Yes, this is vulnerable to race
            # conditions, but so is specifying a nonexistent directory on the
            # command line.)
            path.rmdir()
        log.info("Path: %s", path)
        log.info("Batch: %s", batch)
        log.info("Spec: %s", spec)
        log.info("Extra args: %s", extra_args)
        if kwargs:
            log.warning("Ignoring extra component arguments: %r", kwargs)
        systype = platform.system()
        if systype == "Linux":
            miniconda_script = "Miniconda3-latest-Linux-x86_64.sh"
        elif systype == "Darwin":
            miniconda_script = "Miniconda3-latest-MacOSX-x86_64.sh"
        else:
            raise RuntimeError(f"E: Unsupported OS: {systype}")
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
            args = ["-p", path, "-s"]
            if batch:
                args.append("-b")
            if extra_args is not None:
                args.extend(extra_args)
            runcmd("bash", script_path, *args)
        if spec is not None:
            runcmd(path / "bin" / "conda", "install", *spec)
        conda_instance = CondaInstance(basepath=path, name=None)
        self.manager.conda_stack.append(conda_instance)
        self.manager.installer_stack.append(
            CondaInstaller(self.manager, conda_instance)
        )
        self.manager.addenv(f"source {shlex.quote(str(path))}/etc/profile.d/conda.sh")
        self.manager.addenv("conda activate base")


@DataladInstaller.register_component("conda-env")
class CondaEnvComponent(Component):
    """ Creates a Conda environment """

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
        cmd = [conda.basepath / "bin" / "conda", "create", "--name", cname]
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


@DataladInstaller.register_component("neurodebian")
class NeurodebianComponent(Component):
    """ Installs & configures NeuroDebian """

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

    def provide(self, extra_args: Optional[List[str]] = None, **kwargs: Any) -> None:
        log.info("Installing & configuring NeuroDebian")
        log.info("Extra args: %s", extra_args)
        if kwargs:
            log.warning("Ignoring extra component arguments: %r", kwargs)
        runcmd(
            "apt-get",
            "install",
            "-qy",
            "neurodebian",
            env=dict(os.environ, DEBIAN_FRONTENV="noninteractive"),
        )
        runcmd("nd-configurerepo", *(extra_args or []))


class InstallableComponent(Component):
    """
    Superclass for components that install packages via installation methods
    """

    NAME: ClassVar[str]

    INSTALLERS: ClassVar[Dict[str, Type["Installer"]]] = {}

    @classmethod
    def register_installer(cls, installer: Type["Installer"]) -> Type["Installer"]:
        """ A decorator for registering concrete `Installer` subclasses """
        cls.INSTALLERS[installer.NAME] = installer
        methods = cls.OPTION_PARSER.options["--method"].choices
        assert methods is not None
        methods.append(installer.NAME)
        for opt in installer.OPTIONS:
            cls.OPTION_PARSER.add_option(opt)
        return installer

    def get_installer(self, name: str) -> "Installer":
        """ Retrieve & instantiate the installer with the given name """
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


@DataladInstaller.register_component("git-annex")
class GitAnnexComponent(InstallableComponent):
    """ Installs git-annex """

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


@DataladInstaller.register_component("datalad")
class DataladComponent(InstallableComponent):
    """ Installs Datalad """

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


class Installer(ABC):
    """ An abstract base class for installation methods for packages """

    NAME: ClassVar[str]

    OPTIONS: ClassVar[List[Option]]

    #: Mapping from supported installable component names to
    #: (installer-specific package IDs, list of installed programs) pairs
    PACKAGES: ClassVar[Dict[str, Tuple[str, List[str]]]]

    def __init__(self, manager: DataladInstaller) -> None:
        self.manager = manager

    def install(self, component: str, **kwargs: Any) -> CommandList:
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
        return [(cmd, bindir / cmd) for cmd in commands]

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
class AptInstaller(Installer):
    """ Installs via apt-get """

    NAME = "apt"

    OPTIONS = [
        Option(
            "--build-dep", is_flag=True, help="Install build-dep instead of the package"
        ),
        EXTRA_ARGS_OPTION,
    ]

    PACKAGES = {
        "datalad": ("datalad", ["datalad"]),
        "git-annex": ("git-annex", ["git-annex"]),
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
        cmd = ["sudo", "apt-get"]
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
        runcmd(*cmd)
        log.debug("Installed program directory: /usr/bin")
        return Path("/usr/bin")

    def assert_supported_system(self) -> None:
        if shutil.which("apt-get") is None:
            raise MethodNotSupportedError("apt-get command not found")


@GitAnnexComponent.register_installer
class HomebrewInstaller(Installer):
    """ Installs via brew (Homebrew) """

    NAME = "brew"

    OPTIONS = [
        EXTRA_ARGS_OPTION,
    ]

    PACKAGES = {
        "git-annex": ("git-annex", ["git-annex"]),
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
        cmd = ["brew", "install"]
        if extra_args:
            cmd.extend(extra_args)
        cmd.append(package)
        runcmd(*cmd)
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
        "datalad": ("datalad", ["datalad"]),
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
        if extra_args is not None and "--user" in extra_args:
            binpath = Path(
                readcmd(self.python, "-m", "site", "--user-base").strip(),
                "bin",
            )
        elif self.venv_path is not None:
            binpath = self.venv_path / "bin"
        else:
            binpath = Path("/usr/local/bin")
        log.debug("Installed program directory: %s", binpath)
        return binpath

    def assert_supported_system(self) -> None:
        ### TODO: Detect whether pip is installed in the current Python,
        ### preferrably without importing it
        pass


@GitAnnexComponent.register_installer
class NeurodebianInstaller(AptInstaller):
    """ Installs via apt-get and the NeuroDebian repositories """

    NAME = "neurodebian"

    PACKAGES = {
        "git-annex": ("git-annex-standalone", ["git-annex"]),
    }

    def assert_supported_system(self) -> None:
        super().assert_supported_system()
        if "l=NeuroDebian" not in readcmd("apt-cache", "policy"):
            raise MethodNotSupportedError("Neurodebian not configured")


@GitAnnexComponent.register_installer
@DataladComponent.register_installer
class DebURLInstaller(Installer):
    """ Installs a ``*.deb`` package by URL """

    NAME = "deb-url"

    OPTIONS = [
        Option("--url", metavar="URL", help="URL from which to download `*.deb` file"),
        EXTRA_ARGS_OPTION,
    ]

    PACKAGES = {
        "git-annex": ("git-annex", ["git-annex"]),
        "datalad": ("datalad", ["datalad"]),
    }

    def install_package(
        self,
        package: str,
        url: Optional[str] = None,
        extra_args: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Path:
        log.info("Installing %s via deb-url", package)
        if url is None:
            raise RuntimeError("deb-url method requires URL")
        log.info("URL: %s", url)
        log.info("Extra args: %s", extra_args)
        if kwargs:
            log.warning("Ignoring extra installer arguments: %r", kwargs)
        with tempfile.TemporaryDirectory() as tmpdir:
            debpath = os.path.join(tmpdir, f"{package}.deb")
            download_file(url, debpath)
            cmd = ["sudo", "dpkg", "-i"]
            if extra_args is not None:
                cmd.extend(extra_args)
            cmd.append(debpath)
            runcmd(*cmd)
            log.debug("Installed program directory: /usr/bin")
            return Path("/usr/bin")

    def assert_supported_system(self) -> None:
        if shutil.which("dpkg") is None:
            raise MethodNotSupportedError("dpkg command not found")


class AutobuildSnapshotInstaller(Installer):
    OPTIONS: ClassVar[List[Option]] = []

    PACKAGES = {
        "git-annex": ("git-annex", ["git-annex"]),
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
        systype = platform.system()
        if systype not in ("Linux", "Darwin"):
            raise MethodNotSupportedError(f"{systype} OS not supported")


@GitAnnexComponent.register_installer
class AutobuildInstaller(AutobuildSnapshotInstaller):
    """ Installs the latest official build of git-annex from kitenet.net """

    NAME = "autobuild"

    def install_package(self, package: str, **kwargs: Any) -> Path:
        log.info("Installing %s via autobuild", package)
        if kwargs:
            log.warning("Ignoring extra installer arguments: %r", kwargs)
        assert package == "git-annex"
        systype = platform.system()
        if systype == "Linux":
            binpath = self._install_linux("autobuild/amd64")
        elif systype == "Darwin":
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
        systype = platform.system()
        if systype == "Linux":
            binpath = self._install_linux("linux/current")
        elif systype == "Darwin":
            binpath = self._install_macos("OSX/current/10.10_Yosemite")
        else:
            raise AssertionError("Method should not be called on unsupported platforms")
        log.debug("Installed program directory: %s", binpath)
        return binpath


@GitAnnexComponent.register_installer
@DataladComponent.register_installer
class CondaInstaller(Installer):
    """ Installs via conda """

    NAME = "conda"

    OPTIONS = [
        EXTRA_ARGS_OPTION,
    ]

    PACKAGES = {
        "datalad": ("datalad", ["datalad"]),
        "git-annex": ("git-annex", ["git-annex"]),
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
        cmd = [conda.basepath / "bin" / "conda", "install"]
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
        runcmd(*cmd)
        if conda.name is None:
            binpath = conda.basepath / "bin"
        else:
            binpath = conda.basepath / "envs" / conda.name / "bin"
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

    NAME = "datalad/git-annex"

    OPTIONS: ClassVar[List[Option]] = []

    PACKAGES = {
        "git-annex": ("git-annex", ["git-annex"]),
    }

    def install_package(self, package: str, **kwargs: Any) -> Path:
        log.info("Installing %s via datalad/git-annex", package)
        if kwargs:
            log.warning("Ignoring extra installer arguments: %r", kwargs)
        assert package == "git-annex"
        with tempfile.TemporaryDirectory() as tmpdir_:
            tmpdir = Path(tmpdir_)
            systype = platform.system()
            if systype == "Linux":
                self.download_latest_git_annex("ubuntu", tmpdir)
                (debpath,) = tmpdir.glob("*.deb")
                runcmd("sudo", "dpkg", "-i", debpath)
                binpath = Path("/usr/bin")
            elif systype == "Darwin":
                self.download_latest_git_annex("macos", tmpdir)
                (dmgpath,) = tmpdir.glob("*.dmg")
                binpath = install_git_annex_dmg(dmgpath, self.manager)
            else:
                raise AssertionError(
                    "Method should not be called on unsupported platforms"
                )
        log.debug("Installed program directory: %s", binpath)
        return binpath

    def assert_supported_system(self) -> None:
        systype = platform.system()
        if systype not in ("Linux", "Darwin"):
            raise MethodNotSupportedError(f"{systype} OS not supported")

    @staticmethod
    def download_latest_git_annex(ostype: str, target_dir: Path) -> None:
        """
        Download & unzip the artifact from the latest successful build of
        datalad/git-annex for the given OS in the given directory
        """
        repo = "datalad/git-annex"
        branch = "master"
        workflow = f"build-{ostype}.yaml"
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            r = subprocess.run(
                ["git", "config", "hub.oauthtoken"],
                stdout=subprocess.PIPE,
                universal_newlines=True,
            )
            if r.returncode != 0 or not r.stdout.strip():
                raise RuntimeError(
                    "GitHub OAuth token not set.  Set via GITHUB_TOKEN"
                    " environment variable or hub.oauthtoken Git config option."
                )
            token = r.stdout.strip()

        def apicall(url: str) -> Any:
            log.debug("HTTP request: GET %s", url)
            req = Request(url, headers={"Authorization": f"Bearer {token}"})
            with urlopen(req) as r:
                return json.load(r)

        jobs_url = (
            f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}"
            f"/runs?status=success&branch={branch}"
        )
        log.info("Getting artifacts_url from %s", jobs_url)
        jobs = apicall(jobs_url)
        try:
            artifacts_url = jobs["workflow_runs"][0]["artifacts_url"]
        except LookupError:
            log.exception("Unable to get artifacts_url")
            raise
        log.info("Getting archive download URL from %s", artifacts_url)
        artifacts = apicall(artifacts_url)
        if artifacts["total_count"] < 1:
            raise RuntimeError("No artifacts found!")
        elif artifacts["total_count"] > 1:
            raise RuntimeError("Too many artifacts found!")
        else:
            archive_download_url = artifacts["artifacts"][0]["archive_download_url"]
        log.info("Downloading artifact package from %s", archive_download_url)
        target_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = target_dir / ".artifact.zip"
        download_file(
            archive_download_url,
            artifact_path,
            headers={"Authorization": f"Bearer {token}"},
        )
        with ZipFile(str(artifact_path)) as zipf:
            zipf.extractall(str(target_dir))
        artifact_path.unlink()


class MethodNotSupportedError(Exception):
    """
    Raised when an installer's `install()` method is called on an unsupported
    system or with an unsupported component
    """

    pass


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
    req = Request(url, headers=headers)
    with urlopen(req) as r:
        with open(path, "wb") as fp:
            shutil.copyfileobj(r, fp)


def compose_pip_requirement(
    package: str,
    version: Optional[str] = None,
    urlspec: Optional[str] = None,
    extras: Optional[str] = None,
) -> str:
    """ Compose a PEP 503 requirement specifier """
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
    """ Create a directory in ``$TMPDIR`` with the given prefix """
    return Path(tempfile.mkdtemp(prefix=prefix))


def runcmd(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
    """ Run (and log) a given command.  Raise an error if it fails. """
    arglist = [str(a) for a in args]
    log.info("Running: %s", " ".join(map(shlex.quote, arglist)))
    return subprocess.run(arglist, check=True, **kwargs)


def readcmd(*args: Any, **kwargs: Any) -> str:
    """ Run a command, capturing & returning its stdout """
    s = runcmd(*args, stdout=subprocess.PIPE, universal_newlines=True).stdout
    assert isinstance(s, str)
    return s


def install_git_annex_dmg(
    dmgpath: Union[str, os.PathLike], manager: DataladInstaller
) -> Path:
    """ Install git-annex from a DMG file at ``dmgpath`` """
    runcmd("hdiutil", "attach", dmgpath)
    runcmd("rsync", "-a", "/Volumes/git-annex/git-annex.app", "/Applications/")
    runcmd("hdiutil", "detach", "/Volumes/git-annex/")
    annex_bin = Path("/Applications/git-annex.app/Contents/MacOS")
    manager.addpath(annex_bin)
    return annex_bin


def main(argv: Optional[List[str]] = None) -> int:
    with DataladInstaller() as manager:
        return manager.main(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
