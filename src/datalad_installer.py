#!/usr/bin/env python3
"""
Installation script for Datalad and related components

Visit <https://github.com/datalad/datalad-installer> for more information.
"""

__version__ = "0.1.0.dev1"
__author__ = "The DataLad Team and Contributors"
__author_email__ = "team@datalad.org"
__license__ = "MIT"
__url__ = "https://github.com/datalad/datalad-installer"

from abc import ABC, abstractmethod
from collections import namedtuple
from getopt import GetoptError, getopt
import json
import logging
import os
import os.path
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen
from zipfile import ZipFile

log = logging.getLogger("datalad_installer")


def parse_log_level(level):
    try:
        lv = int(level)
    except ValueError:
        levelup = level.upper()
        if levelup in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            return getattr(logging, levelup)
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


class VersionRequest(namedtuple("VersionRequest", ""), Immediate):
    pass


class HelpRequest(namedtuple("HelpRequest", "component"), Immediate):
    pass


SHORT_RGX = re.compile(r"-[^-]")
LONG_RGX = re.compile(r"--[^-].*")


class Option:
    def __init__(
        self,
        *names,
        is_flag=False,
        converter=None,
        multiple=False,
        immediate=None,
        metavar=None,
        choices=None,
    ):
        #: List of individual option characters
        self.shortopts = []
        #: List of long option names (sans leading "--")
        self.longopts = []
        self.dest = None
        self.is_flag = is_flag
        self.converter = converter
        self.multiple = multiple
        self.immediate = immediate
        self.metavar = metavar
        self.choices = choices
        for n in names:
            if n.startswith("-"):
                if LONG_RGX.fullmatch(n):
                    self.longopts.append(n[2:])
                elif SHORT_RGX.fullmatch(n):
                    self.shortopts.append(n[1])
                else:
                    raise ValueError(f"Invalid option: {n!r}")
            elif self.dest is not None:
                raise ValueError("More than one option destination specified")
            else:
                self.dest = n
        if not self.shortopts and not self.longopts:
            raise ValueError("No options supplied to Option constructor")
        if self.dest is None:
            self.dest = (self.longopts + self.shortopts)[0].replace("-", "_")

    @property
    def option_name(self):
        if self.longopts:
            return f"--{self.longopts[0]}"
        else:
            assert self.shortopts
            return f"-{self.shortopts[0]}"

    def process(self, namespace, argument):
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


class OptionParser:
    def __init__(self, component=None, options=None):
        self.component = component
        #: Mapping from individual option characters to Option instances
        self.short_options = {}
        #: Mapping from long option names (sans leading "--") to Option
        #: instances
        self.long_options = {}
        #: Mapping from option names (including leading hyphens to Option
        #: instances
        self.options = {}
        self.add_option(
            Option("-h", "--help", is_flag=True, immediate=HelpRequest(self.component))
        )
        if options is not None:
            for opt in options:
                self.add_option(opt)

    def add_option(self, option):
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

    def parse_args(self, args):
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
        kwargs = {}
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


class UsageError(Exception):
    def __init__(self, message, component=None):
        self.message = message
        self.component = component

    def __str__(self):
        return self.message


ParsedArgs = namedtuple("ParsedArgs", "global_opts components")


class ComponentRequest:
    def __init__(self, name, **kwargs):
        self.name = name
        self.kwargs = kwargs

    def __eq__(self, other):
        if type(self) is type(other):
            return self.name == other.name and self.kwargs == other.kwargs
        else:
            return NotImplemented

    def __repr__(self):
        attrs = [f"name={self.name!r}"]
        for k, v in self.kwargs.items():
            attrs.append(f"{k}={v!r}")
        return "{0.__module__}.{0.__name__}({1})".format(
            type(self),
            ", ".join(attrs),
        )


class DataladInstaller:
    COMPONENTS = {}
    INSTALLERS = {}

    OPTIONS = OptionParser(
        options=[
            Option("-V", "--version", is_flag=True, immediate=VersionRequest()),
            Option("-l", "--log-level", converter=parse_log_level, metavar="LEVEL"),
            Option("-E", "--env-write-file", converter=Path, multiple=True),
        ],
    )

    def __init__(self, env_write_files=None):
        self.newpath = None
        # self.annex_bin = "/usr/bin"
        # self.adjust_bashrc = adjust_bashrc
        if env_write_files is None:
            self.env_write_files = []
        else:
            self.env_write_files = [Path(p) for p in env_write_files]
        self.installer_stack = []  ##### TODO

    @classmethod
    def register_component(cls, name):
        def decorator(component):
            cls.COMPONENTS[name] = component
            return component

        return decorator

    @classmethod
    def register_installer(cls, name):
        def decorator(installer):
            cls.INSTALLERS[name] = installer
            return installer

        return decorator

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            if self.newpath is not None:
                pathline = f"PATH={':'.join(self.newpath)}\n"
                for p in self.env_write_files:
                    txt = p.read_text()
                    if txt and not txt.endswith("\n"):
                        txt += "\n"
                    p.write_file(txt + pathline)
            else:
                # Ensure env write files at least exist
                for p in self.env_write_files:
                    p.touch()
        return False

    @classmethod
    def parse_args(cls, args):
        r = cls.OPTIONS.parse_args(args)
        if isinstance(r, Immediate):
            return r
        global_opts, leftovers = r
        components = []
        while leftovers:
            c = leftovers.pop(0)
            name, eq, version = c.partition("=")
            if not name:
                raise UsageError("Component name must be nonempty")
            try:
                component = cls.COMPONENTS[name]
            except KeyError:
                raise UsageError(f"Unknown component: {name!r}")
            if version and not component.VERSIONED:
                raise UsageError(f"{name} component does not take a version", name)
            if eq and not version:
                raise UsageError("Version must be nonempty", name)
            cr = component.OPTIONS.parse_args(leftovers)
            if isinstance(cr, Immediate):
                return cr
            kwargs, leftovers = cr
            if version:
                kwargs["version"] = version
            components.append(ComponentRequest(name=name, **kwargs))
        return ParsedArgs(global_opts, components)

    def main(self, argv=None):
        if argv is None:
            argv = sys.argv
        progname, *args = argv
        try:
            r = self.parse_args(args)
        except UsageError as e:
            ### TODO: Show short usage summary
            sys.exit(str(e))
        if isinstance(r, VersionRequest):
            print("datalad_installer", __version__)
            return
        elif isinstance(r, HelpRequest):
            raise NotImplementedError("--help not yet implemented")  ### TODO
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
        for cr in components:
            self.addcomponent(name=cr.name, **cr.kwargs)

    def addpath(self, p, last=False):
        if self.newpath is None:
            path = ['"$PATH"']
        else:
            path = self.newpath
        if not last:
            path.insert(0, shlex.quote(p))
        else:
            path.append(shlex.quote(p))
        self.newpath = path

    def addcomponent(self, name, **kwargs):
        try:
            component = self.COMPONENTS[name]
        except AttributeError:
            raise ValueError(f"Unknown component: {name}")
        component(self).provide(**kwargs)

    ##### TODO: Get rid of?
    def post_install(self):
        if self.adjust_bashrc and self.pathline is not None:
            # If PATH was changed, we need to make it available to SSH commands.
            # Note: Prepending is necessary. SSH commands load .bashrc, but many
            # distributions (including Debian and Ubuntu) come with a snippet
            # to exit early in that case.
            bashrc = Path.home() / ".bashrc"
            contents = bashrc.read_text()
            bashrc.write_text(self.pathline + "\n" + contents)
            log.info("Adjusted first line of ~/.bashrc:")
            log.info("%s", self.pathline)
        # Rudimentary test of installation and inform user about location
        for binname in ["git-annex", "git-annex-shell"]:
            if not os.access(os.path.join(self.annex_bin, binname), os.X_OK):
                raise RuntimeError(f"Cannot execute {binname}")
        log.info("git-annex is available under %r", self.annex_bin)


class Component(ABC):
    @property
    @classmethod
    @abstractmethod
    def OPTIONS(cls):
        raise NotImplementedError

    @property
    @classmethod
    @abstractmethod
    def VERSIONED(cls):
        raise NotImplementedError

    def __init__(self, manager):
        self.manager = manager

    @abstractmethod
    def provide(self, **kwargs):
        raise NotImplementedError


@DataladInstaller.register_component("venv")
class VenvComponent(Component):
    OPTIONS = OptionParser(
        "venv",
        options=[
            Option("--path", converter=Path, metavar="PATH"),
            Option("-e", "--extra-args", converter=shlex.split),
        ],
    )

    VERSIONED = False

    def provide(self, path=None, extra_args=None):
        if path is None:
            path = mktempdir("dl-venv-")
        cmd = [sys.executable, "-m", "venv"]
        if extra_args is not None:
            cmd.extend(extra_args)
        cmd.append(path)
        runcmd(*cmd)
        self.manager.installer_stack.append(PipInstaller(self, path / "bin" / "python"))


@DataladInstaller.register_component("miniconda")
class MinicondaComponent(Component):
    OPTIONS = OptionParser(
        "miniconda",
        options=[
            Option("--path", converter=Path, metavar="PATH"),
            Option("--batch", is_flag=True),
            Option("--spec", converter=str.split),
            Option("-e", "--extra-args", converter=shlex.split),
        ],
    )

    VERSIONED = False

    def provide(self, path=None, batch=False, spec=None, extra_args=None):
        if path is None:
            path = mktempdir("dl-miniconda-")
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
                )
                + miniconda_script,
                script_path,
            )
            log.info("Installing miniconda in %s", path)
            args = ["-p", path, "-s"]
            if batch:
                args.append("-b")
            runcmd("bash", script_path, *args)
        ##### TODO: Add to self.installer_stack?


@DataladInstaller.register_component("conda-env")
class CondaEnvComponent(Component):
    OPTIONS = OptionParser(
        "conda-env",
        options=[
            Option("-n", "--name", metavar="NAME"),
            Option("--spec", converter=str.split),
            Option("-e", "--extra-args", converter=shlex.split),
        ],
    )

    VERSIONED = False

    def provide(self, name=None, spec=None, extra_args=None):
        raise NotImplementedError  ##### TODO


@DataladInstaller.register_component("git-annex")
class GitAnnexComponent(Component):
    OPTIONS = OptionParser(
        "git-annex",
        options=[
            Option("--build-dep", is_flag=True),
            Option("-e", "--extra-args", converter=shlex.split),
            Option(
                "-m",
                "--method",
                choices=[
                    "auto",
                    "apt",
                    "autobuild",
                    "brew",
                    "conda",
                    "datalad/git-annex",
                    "deb-url",
                    "neurodebian",
                    "neurodebian-devel",
                    "snapshot",
                ],
            ),
            Option("--url", metavar="URL"),
        ],
    )

    VERSIONED = True

    def provide(self, build_dep=False, extra_args=None, url=None):
        raise NotImplementedError  ##### TODO


@DataladInstaller.register_component("datalad")
class DataladComponent(Component):
    OPTIONS = OptionParser(
        "datalad",
        options=[
            Option("--build-dep", is_flag=True),
            Option("-e", "--extra-args", converter=shlex.split),
            Option("--devel", is_flag=True),
            Option("-E", "--extras", metavar="EXTRAS"),
            Option(
                "-m",
                "--method",
                choices=[
                    "auto",
                    "apt",
                    "conda",
                    "deb-url",
                    "neurodebian",
                    "neurodebian-devel",
                    "pip",
                ],
            ),
        ],
    )

    VERSIONED = True

    def provide(self, method=None, **kwargs):
        if method not in (None, "auto"):
            try:
                installer = self.manager.INSTALLERS[method]
            except KeyError:
                raise ValueError(f"Unknown installation method: {method}")
            installer(self).install("datalad", **kwargs)
        else:
            raise NotImplementedError  ##### TODO


class Installer(ABC):
    def __init__(self, manager):
        self.manager = manager

    @abstractmethod
    def install(self, component, **kwargs):
        raise NotImplementedError

    @abstractmethod
    def is_supported(self):
        raise NotImplementedError


@DataladInstaller.register_installer("apt")
class AptInstaller(Installer):
    COMPONENTS = {
        "datalad": "datalad",
        "git-annex": "git-annex",
    }

    ##### TODO: Support build_dep

    def install(self, component, version=None, extra_args=None):
        try:
            pkgname = self.COMPONENTS[component]
        except KeyError:
            raise MethodNotSupportedError()
        cmd = ["sudo", "apt-get", "install"]
        if extra_args:
            cmd.extend(extra_args)
        if version is not None:
            cmd.append(f"{pkgname}={version}")
        else:
            cmd.append(pkgname)
        runcmd(*cmd)

    def is_supported(self):
        return shutil.which("apt-get") is not None


@DataladInstaller.register_installer("brew")
class HomebrewInstaller(Installer):
    COMPONENTS = {
        "git-annex": "git-annex",
    }

    def install(self, component, extra_args=None):
        try:
            pkgname = self.COMPONENTS[component]
        except KeyError:
            raise MethodNotSupportedError()
        cmd = ["brew", "install"]
        if extra_args:
            cmd.extend(extra_args)
        cmd.append(pkgname)
        runcmd(*cmd)
        ##### TODO: self.annex_bin = "/usr/local/bin"

    def is_supported(self):
        return shutil.which("brew") is not None


@DataladInstaller.register_installer("pip")
class PipInstaller(Installer):
    COMPONENTS = {
        "datalad": "datalad",
    }

    DEVEL_COMPONENTS = {
        "datalad": "git+https://github.com/datalad/datalad.git",
    }

    def __init__(self, manager, python=None):
        super().__init__(self, manager)
        self.python = python or sys.executable

    def install(
        self, component, version=None, devel=False, extras=None, extra_args=None
    ):
        try:
            pkgname = self.COMPONENTS[component]
        except KeyError:
            raise MethodNotSupportedError()
        if devel:
            try:
                urlspec = self.DEVEL_COMPONENTS[component]
            except KeyError:
                raise ValueError(f"No source repository known for {component}")
        else:
            urlspec = None
        cmd = [self.python, "-m", "pip", "install"]
        if extra_args:
            cmd.extend(extra_args)
        cmd.append(
            compose_pip_requirement(
                pkgname, version=version, urlspec=urlspec, extras=extras
            )
        )
        runcmd(*cmd)

    def is_supported(self):
        return True


@DataladInstaller.register_installer("neurodebian")
class NeurodebianInstaller(AptInstaller):
    COMPONENTS = {
        "datalad": "datalad",
        "git-annex": "git-annex-standalone",
    }

    # TODO: use nd_freeze_install for an arbitrary version specified
    # we assume neurodebian is generally configured


@DataladInstaller.register_installer("neurodebian-devel")
class NeurodebianDevelInstaller(NeurodebianInstaller):
    def install(self, component, extra_args=None):
        try:
            pkgname = self.COMPONENTS[component]
        except KeyError:
            raise MethodNotSupportedError()
        # if debian-devel is not setup -- set it up
        r = runcmd(
            "apt-cache",
            "policy",
            pkgname,
            stdout=subprocess.PIPE,
            universal_newlines=True,
        )
        if "/debian-devel " not in r.stdout:
            # configure
            with open("/etc/apt/sources.list.d/neurodebian.sources.list") as fp:
                srclist = fp.read()
            srclist = srclist.replace("/debian ", "/debian-devel ")
            runcmd(
                "sudo",
                "tee",
                "/etc/apt/sources.list.d/neurodebian-devel.sources.list",
                input=srclist,
                universal_newlines=True,
            )
            runcmd("sudo", "apt-get", "update")
        # check versions
        # devel:
        r = runcmd(
            "apt-cache",
            "policy",
            pkgname,
            stdout=subprocess.PIPE,
            universal_newlines=True,
        )
        policy = r.stdout
        devel_annex_version = None
        current_annex_version = None
        prev = None
        for line in policy.splitlines():
            if "/debian-devel " in line:
                assert prev is not None
                if "ndall" in prev:
                    assert devel_annex_version is None
                    devel_annex_version = prev.split()[0]
            if "***" in line:
                assert current_annex_version is None
                current_annex_version = line.split()[1]
            prev = line
        assert (
            devel_annex_version is not None
        ), f"Could not find devel version of {pkgname}"
        if current_annex_version is None or (
            subprocess.run(
                [
                    "dpkg",
                    "--compare-versions",
                    devel_annex_version,
                    "gt",
                    current_annex_version,
                ]
            ).returncode
            == 0
        ):
            runcmd(
                "sudo",
                "apt-get",
                "install",
                f"{pkgname}={devel_annex_version}",
            )
        elif current_annex_version is not None:
            log.info(
                "devel version %s is not newer than installed %s",
                devel_annex_version,
                current_annex_version,
            )


@DataladInstaller.register_installer("deb-url")
class DebURLInstaller(Installer):
    def install(self, component, url, extra_args=None):
        with tempfile.TemporaryDirectory() as tmpdir:
            debpath = os.path.join(tmpdir, f"{component}.deb")
            download_file(url, debpath)
            cmd = ["sudo", "dpkg", "-i"]
            if extra_args is not None:
                cmd.extend(extra_args)
            cmd.append(debpath)
            runcmd(*cmd)

    def is_supported(self):
        return shutil.which("dpkg") is not None


class AutobuildSnapshotInstaller(Installer):
    def _install_linux(self, path):
        tmpdir = tempfile.mkdtemp(prefix="ga-")
        ##### TODO: self.annex_bin = os.path.join(tmpdir, "git-annex.linux")
        log.info("downloading and extracting under %s", self.annex_bin)
        gzfile = os.path.join(tmpdir, "git-annex-standalone-amd64.tar.gz")
        download_file(
            f"https://downloads.kitenet.net/git-annex/{path}"
            "/git-annex-standalone-amd64.tar.gz",
            gzfile,
        )
        runcmd("tar", "-C", tmpdir, "-xzf", gzfile)
        self.manager.addpath(self.annex_bin)

    def _install_macos(self, path):
        with tempfile.TemporaryDirectory() as tmpdir:
            dmgpath = os.path.join(tmpdir, "git-annex.dmg")
            download_file(
                f"https://downloads.kitenet.net/git-annex/{path}/git-annex.dmg",
                dmgpath,
            )
            install_git_annex_dmg(dmgpath, self.manager)

    def is_supported(self):
        return platform.system() in ("Linux", "Darwin")


@DataladInstaller.register_installer("autobuild")
class AutobuildInstaller(AutobuildSnapshotInstaller):
    def install(self, component):
        if component != "git-annex":
            raise MethodNotSupportedError()
        systype = platform.system()
        if systype == "Linux":
            self._install_linux("autobuild/amd64")
        elif systype == "Darwin":
            self._install_macos("autobuild/x86_64-apple-yosemite")
        else:
            raise MethodNotSupportedError()


@DataladInstaller.register_installer("snapshot")
class SnapshotInstaller(AutobuildSnapshotInstaller):
    def install(self, component):
        if component != "git-annex":
            raise MethodNotSupportedError()
        systype = platform.system()
        if systype == "Linux":
            self._install_linux("linux/current")
        elif systype == "Darwin":
            self._install_macos("OSX/current/10.10_Yosemite")
        else:
            raise MethodNotSupportedError()


@DataladInstaller.register_installer("conda")
class CondaInstaller(Installer):
    COMPONENTS = {
        "datalad": "datalad",
        "git-annex": "git-annex",
    }

    def install(self, component, version, extra_args=None):
        try:
            pkgname = self.COMPONENTS[component]
        except KeyError:
            raise MethodNotSupportedError()
        miniconda_path = ...  ##### TODO
        ##### TODO: self.install_miniconda(miniconda_path, batch)
        cmd = [
            os.path.join(miniconda_path, "bin", "conda"),
            "install",
            "-q",
            "-c",
            "conda-forge",
            "-y",
        ]
        if extra_args is not None:
            cmd.extend(extra_args)
        if version is None:
            cmd.append(pkgname)
        else:
            cmd.append(f"{pkgname}={version}")
        runcmd(*cmd)

    def is_supported(self):
        raise NotImplementedError  ##### TODO


@DataladInstaller.register_installer("datalad/git-annex")
class DataladGitAnnexBuildInstaller(Installer):
    def install(self, component):
        if component != "git-annex":
            raise MethodNotSupportedError()
        with tempfile.TemporaryDirectory() as tmpdir:
            systype = platform.system()
            if systype == "Linux":
                self.download_latest_git_annex("ubuntu", tmpdir)
                (debpath,) = Path(tmpdir).glob("*.deb")
                runcmd("sudo", "dpkg", "-i", debpath)
            elif systype == "Darwin":
                self.download_latest_git_annex("macos", tmpdir)
                (dmgpath,) = Path(tmpdir).glob("*.dmg")
                install_git_annex_dmg(dmgpath, self.manager)
            else:
                raise MethodNotSupportedError(f"Unsupported OS: {systype}")

    def is_supported(self):
        return platform.system() in ("Linux", "Darwin")

    @staticmethod
    def download_latest_git_annex(ostype, target_path: Path):
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

        def apicall(url):
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
        target_path.mkdir(parents=True, exist_ok=True)
        artifact_path = target_path / ".artifact.zip"
        download_file(
            archive_download_url,
            artifact_path,
            headers={"Authorization": f"Bearer {token}"},
        )
        with ZipFile(str(artifact_path)) as zipf:
            zipf.extractall(str(target_path))
        artifact_path.unlink()


class MethodNotSupportedError(Exception):
    pass


def download_file(url, path, headers=None):
    if headers is None:
        headers = {}
    req = Request(url, headers=headers)
    with urlopen(req) as r:
        with open(path, "wb") as fp:
            shutil.copyfileobj(r, fp)


def compose_pip_requirement(package, version=None, urlspec=None, extras=None):
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


def mktempdir(prefix):
    return Path(tempfile.mkdtemp(prefix=prefix))


def runcmd(*args, **kwargs):
    args = [str(a) for a in args]
    log.info("Running: %s", " ".join(map(shlex.quote, args)))
    return subprocess.run(args, check=True, **kwargs)


def install_git_annex_dmg(self, dmgpath, manager):
    runcmd("hdiutil", "attach", dmgpath)
    runcmd("rsync", "-a", "/Volumes/git-annex/git-annex.app", "/Applications/")
    runcmd("hdiutil", "detach", "/Volumes/git-annex/")
    ##### TODO: self.annex_bin = "/Applications/git-annex.app/Contents/MacOS"
    manager.addpath(self.annex_bin)


""" #### TODO
    def install_via_conda_forge(self, version=None, miniconda_path=None, batch=False):
        tmpdir = tempfile.mkdtemp(prefix="ga-")
        self.annex_bin = os.path.join(tmpdir, "annex-bin")
        self.addpath(self.annex_bin)
        self._install_via_conda(version, tmpdir, miniconda_path, batch)

    def install_via_conda_forge_last(
        self, version=None, miniconda_path=None, batch=False
    ):
        tmpdir = tempfile.mkdtemp(prefix="ga-")
        self.annex_bin = os.path.join(tmpdir, "annex-bin")
        if shutil.which("git-annex") is not None:
            log.warning(
                "git annex already installed.  In this case this setup has no sense"
            )
            sys.exit(1)
        # We are interested only to get git-annex into our environment
        # So as to not interfere with "system wide" Python etc, we will add
        # miniconda at the end of the path
        self.addpath(self.annex_bin, last=True)
        self._install_via_conda(version, tmpdir, miniconda_path, batch)

    def _install_via_conda(self, version, tmpdir, miniconda_path=None, batch=False):
        if miniconda_path is None:
            miniconda_path = os.path.join(tmpdir, "miniconda")
        conda_bin = os.path.join(miniconda_path, "bin")
        # We will symlink git-annex only under a dedicated directory, so it could be
        # used with default Python etc. If names changed here, possibly adjust
        # hardcoded duplicates below where we establish relative symlinks.
        self.install_miniconda(miniconda_path, batch=batch)
        runcmd(
            os.path.join(conda_bin, "conda"),
            "install",
            "-q",
            "-c",
            "conda-forge",
            "-y",
            f"git-annex={version}" if version is not None else "git-annex",
        )
        if self.annex_bin != conda_bin:
            annex_bin = Path(self.annex_bin)
            annex_bin.mkdir(parents=True, exist_ok=True)
            for p in Path(conda_bin).glob("git-annex*"):
                (annex_bin / p.name).symlink_to(p.resolve())
        self.post_install()
"""


def main():  # Needed for console_script entry point
    with DataladInstaller() as manager:
        manager.main()


if __name__ == "__main__":
    main()
