.. image:: https://github.com/datalad/datalad-installer/workflows/Test/badge.svg?branch=master
    :target: https://github.com/datalad/datalad-installer/actions?workflow=Test
    :alt: GitHub Actions Status

.. image:: https://ci.appveyor.com/api/projects/status/rec96m4r74nrupvn/branch/master?svg=true
    :target: https://ci.appveyor.com/project/mih/datalad-installer/branch/master
    :alt: Appveyor Status

.. image:: https://codecov.io/gh/datalad/datalad-installer/branch/master/graph/badge.svg
    :target: https://codecov.io/gh/datalad/datalad-installer

.. image:: https://img.shields.io/pypi/pyversions/datalad-installer.svg
    :target: https://pypi.org/project/datalad-installer/

.. image:: https://img.shields.io/conda/vn/conda-forge/datalad-installer.svg
    :target: https://anaconda.org/conda-forge/datalad-installer
    :alt: Conda Version

.. image:: https://img.shields.io/github/license/datalad/datalad-installer.svg
    :target: https://opensource.org/licenses/MIT
    :alt: MIT License

`GitHub <https://github.com/datalad/datalad-installer>`_
| `PyPI <https://pypi.org/project/datalad-installer/>`_
| `Anaconda <https://anaconda.org/conda-forge/datalad-installer>`_
| `Issues <https://github.com/datalad/datalad-installer/issues>`_
| `Changelog <https://github.com/datalad/datalad-installer/blob/master/CHANGELOG.md>`_

``datalad-installer`` is a script for installing Datalad_, git-annex_, and
related components all in a single invocation.  It requires no third-party
Python libraries, though it does make heavy use of external packaging commands.

.. _Datalad: https://www.datalad.org
.. _git-annex: https://git-annex.branchable.com

Installation
============
``datalad-installer`` requires Python 3.7 or higher.  Just use `pip
<https://pip.pypa.io>`_ for Python 3 (You have pip, right?) to install it::

    python3 -m pip install datalad-installer

``datalad-installer`` is also available for conda!  To install, run::

    conda install -c conda-forge datalad-installer

Alternatively, download the latest version directly from
<https://raw.githubusercontent.com/datalad/datalad-installer/master/src/datalad_installer.py>.


Usage
=====

::

    datalad-installer [<global options>] <component>[=<version>] [<options>] <component>[=<version>] [<options>] ...

``datalad-installer`` provisions one or more *components* listed on the command
line.  Each component is either a software package (e.g., Datalad or git-annex)
or an environment in which software packages can be installed.  If no
components are specified on the command line, the script defaults to installing
the ``datalad`` component.


Global Options
--------------

-E FILE, --env-write-file FILE  Append any ``PATH`` modifications or other
                                shell commands needed to use the new components
                                to the given file.  This option can be
                                specified multiple times.  If this option is
                                not given, the data is written to a temporary
                                file whose location is logged at the beginning
                                of the program.

-l LEVEL, --log-level LEVEL     Set the log level to the given value.  Possible
                                values are "``CRITICAL``", "``ERROR``",
                                "``WARNING``", "``INFO``", "``DEBUG``" (all
                                case-insensitive) and their Python integer
                                equivalents.  [default value: INFO]

--sudo <ask|error|ok>           What to do when the script needs to run a
                                command with ``sudo`` or privilege escalation:
                                ask for confirmation (default), error, or run
                                without confirmation.  This is always "``ok``"
                                on Windows, where the system always asks for
                                confirmation.

-V, --version                   Display the script version and exit

-h, --help                      Display usage information and exit


Components
----------

``venv``
~~~~~~~~

Creates a Python virtual environment using ``python -m venv``.  Subsequent
``datalad`` components on the command line will be installed into this virtual
environment by default if not overridden by an intervening component.

Options
'''''''

-e ARGS, --extra-args ARGS      Specify extra command-line arguments to pass to
                                ``python -m venv``

--path PATH                     Create the virtual environment at ``PATH``.  If
                                not specified, the environment will be created
                                in a directory in ``$TMPDIR``.


``miniconda``
~~~~~~~~~~~~~

Installs the latest version of Miniconda.  Subsequent ``conda-env`` components
on the command line will use this installation, and subsequent ``datalad``,
``git-annex``, ``rclone``, and ``git-annex-remote-rclone`` components will be
installed using this conda by default if not overridden by an intervening
component.

A specific version to install can be specified by suffixing "``miniconda``"
with "``=``" and the version on the command line, where the version is the
version component of a file at ``$ANACONDA_URL`` or
<https://repo.anaconda.com/miniconda/>, e.g., ``py37_23.1.0-1``.  Run
``datalad-installer miniconda --help-versions`` to see a list of available
versions for your platform.

If not specified, the version defaults to ``latest``.

The Miniconda installation script is downloaded from
``$ANACONDA_URL/Miniconda3-$VERSION-$OS-$ARCH.{sh,exe}``, where
``$ANACONDA_URL`` is taken from the environment, defaulting to
``https://repo.anaconda.com/miniconda``.

Options
'''''''

--batch                         Run the Miniconda installation script in batch
                                (noninteractive) mode.  This is always done
                                when installing on Windows.

                                In addition, if a spec is given (see below),
                                this option causes ``--yes`` to be passed to
                                ``conda install``.

-c CHANNEL, --channel CHANNEL   Specify additional Conda channels to use when
                                installing the packages listed in the spec (see
                                below).  This option can be specified multiple
                                times.

-e ARGS, --extra-args ARGS      Specify extra command-line arguments to pass to
                                the Miniconda installation script.

--path PATH                     Install Miniconda at ``PATH``.  If not
                                specified, it will be installed in a directory
                                in ``$TMPDIR``.

--python-match <major|minor|micro>
                                Include ``python=V`` in the ``--spec``, where
                                ``V`` is the Python version used to run
                                ``datalad-installer`` to the given version
                                level (e.g., under Python 3.9.13,
                                ``--python-match major`` will install
                                ``python=3``, ``minor`` will install
                                ``python=3.9``, and ``micro`` will install
                                ``python=3.9.13``)

--spec SPEC                     Space-separated specifiers for packages to
                                install in the Conda base environment after
                                provisioning.

--help-versions                 Show a list of available Miniconda versions for
                                this platform and exit


``conda-env``
~~~~~~~~~~~~~

Creates a Conda environment.  If there is no preceding ``miniconda`` component
on the command line, Conda must already be installed on the system, and this
installation will be used to create the environment.

Subsequent ``datalad``, ``git-annex``, ``rclone``, and
``git-annex-remote-rclone`` components will be installed into this environment
by default if not overridden by an intervening component.

Options
'''''''

-e ARGS, --extra-args ARGS      Specify extra command-line arguments to pass to
                                the ``conda create`` command.

-n NAME, --name NAME            The name for the new environment.  If not
                                specified, a random name will be generated.

--spec SPEC                     Space-separated specifiers for packages to
                                install in the new environment.


``neurodebian``
~~~~~~~~~~~~~~~

Installs & configures `NeuroDebian <https://neuro.debian.net>`_.

Options
'''''''

-e ARGS, --extra-args ARGS      Specify extra command-line arguments to pass to
                                the ``nd-configurerepo`` command.


``git-annex``
~~~~~~~~~~~~~

Installs git-annex_.  The component takes an ``-m``, ``--method`` option
specifying the installation method to use; the supported methods are:

- ``apt``
- ``autobuild``
- ``brew``
- ``conda`` (only supported on Linux)
- ``datalad/git-annex``
- ``datalad/git-annex:release``
- ``datalad/git-annex:tested``
- ``datalad/packages``
- ``deb-url``
- ``dmg``
- ``neurodebian``
- ``snapshot``

If no method is specified, or if the method is set to "``auto``", then the most
recent component on the command line that provides a compatible installation
method will be used.  If there is no such component, the first supported
installation method from the following list will be used:

- ``conda``
- ``apt``
- ``neurodebian``
- ``brew``
- ``autobuild``
- ``datalad/packages``

A specific version to install can be specified for those methods that support
it by suffixing "``git-annex``" with "``=``" and the version number on the
command line.

The ``git-annex`` component also accepts all options for the supported
installation methods; options not belonging to whichever method ends up used
will be ignored.


``datalad``
~~~~~~~~~~~

Installs Datalad_.  The component takes an ``-m``, ``--method`` option
specifying the installation method to use; the supported methods are:

- ``apt``
- ``brew``
- ``conda``
- ``deb-url``
- ``pip``

If no method is specified, or if the method is set to "``auto``", then the most
recent component on the command line that provides a compatible installation
method will be used.  If there is no such component, the first supported
installation method from the following list will be used:

- ``conda``
- ``apt``
- ``brew``

A specific version to install can be specified for those methods that support
it by suffixing "``datalad``" with "``=``" and the version number on the
command line.

The ``datalad`` component also accepts all options for the supported
installation methods; options not belonging to whichever method ends up used
will be ignored.


``rclone``
~~~~~~~~~~~

Installs rclone_.  The component takes an ``-m``, ``--method`` option
specifying the installation method to use; the supported methods are:

.. _rclone: https://rclone.org

- ``apt``
- ``brew``
- ``conda``
- ``deb-url``
- ``downloads.rclone.org``

If no method is specified, or if the method is set to "``auto``", then the most
recent component on the command line that provides a compatible installation
method will be used.  If there is no such component, the first supported
installation method from the following list will be used:

- ``conda``
- ``apt``
- ``brew``
- ``downloads.rclone.org``

A specific version to install can be specified for those methods that support
it by suffixing "``rclone``" with "``=``" and the version number on the
command line.

The ``rclone`` component also accepts all options for the supported
installation methods; options not belonging to whichever method ends up used
will be ignored.


``git-annex-remote-rclone``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Installs git-annex-remote-rclone_.  The component takes an ``-m``, ``--method``
option specifying the installation method to use; the supported methods are:

.. _git-annex-remote-rclone:
   https://github.com/DanielDent/git-annex-remote-rclone

- ``apt``
- ``brew``
- ``conda``
- ``deb-url``
- ``DanielDent/git-annex-remote-rclone``

If no method is specified, or if the method is set to "``auto``", then the most
recent component on the command line that provides a compatible installation
method will be used.  If there is no such component, the first supported
installation method from the following list will be used:

- ``conda``
- ``apt``
- ``brew``
- ``DanielDent/git-annex-remote-rclone``

A specific version to install can be specified for those methods that support
it by suffixing "``git-annex-remote-rclone``" with "``=``" and the version
number on the command line.

The ``git-annex-remote-rclone`` component also accepts all options for the
supported installation methods; options not belonging to whichever method ends
up used will be ignored.


Installation Methods
--------------------

``apt``
~~~~~~~

Installs with ``sudo apt-get install``.  Supports installing specific versions.

Options
'''''''

--build-dep                     Run ``sudo apt-get build-dep`` instead of
                                ``sudo apt-get install``.

-e ARGS, --extra-args ARGS      Specify extra command-line arguments to pass to
                                the installation command.


``autobuild``
~~~~~~~~~~~~~

Downloads & installs the latest official build of ``git-annex`` from
kitenet.net.  Does not support installing specific versions.

This installation method is only supported on Linux and macOS.


``brew``
~~~~~~~~

Installs with ``brew`` (`Homebrew <https://brew.sh>`_).  Does not support
installing specific versions.

Options
'''''''

-e ARGS, --extra-args ARGS      Specify extra command-line arguments to pass to
                                the installation command.


``conda``
~~~~~~~~~

Installs with ``conda install``.  Supports installing specific versions.

Options
'''''''

-e ARGS, --extra-args ARGS      Specify extra command-line arguments to pass to
                                the installation command.

``DanielDent/git-annex-remote-rclone``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Downloads & installs ``git-annex-remote-rclone`` from a release of its GitHub
project.

This installation method is only supported on Linux and macOS.

Options
'''''''

--bin-dir DIR                   Directory in which to install the ``rclone``
                                executable.  Defaults to ``/usr/local/bin``.
                                If this contains the string ``{tmpdir}``, it
                                will be replaced with the path to a directory
                                in ``$TMPDIR``.

``datalad/git-annex``
~~~~~~~~~~~~~~~~~~~~~

Downloads & installs ``git-annex`` from the latest build of `datalad/git-annex
<https://github.com/datalad/git-annex>`_ that produced artifacts for the
running OS.  Does not support installing specific versions.

This installation method requires a GitHub OAuth token with appropriate
permissions.  It must be specified either via the ``GITHUB_TOKEN`` environment
variable or as the value of the ``hub.oauthtoken`` Git config option.

Options
'''''''

--install-dir DIR               Directory in which to unpack the ``*.deb``
                                package instead of installing it system-wide.
                                If this contains the string ``{tmpdir}``, it
                                will be replaced with the path to a directory
                                in ``$TMPDIR``. (Linux only)


``datalad/git-annex:release``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Downloads & installs ``git-annex`` for the running OS from the latest release
(or the specified version) of `datalad/git-annex
<https://github.com/datalad/git-annex>`_.  If no explicit version is specified
and the latest release lacks an asset for the running OS, the most recent
release with a matching asset is used.

Options
'''''''

--install-dir DIR               Directory in which to unpack the ``*.deb``
                                package instead of installing it system-wide.
                                If this contains the string ``{tmpdir}``, it
                                will be replaced with the path to a directory
                                in ``$TMPDIR``. (Linux only)


``datalad/git-annex:tested``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Downloads & installs ``git-annex`` from the latest successful build of
`datalad/git-annex <https://github.com/datalad/git-annex>`_ for the running OS.
Does not support installing specific versions.

This installation method requires a GitHub OAuth token with appropriate
permissions.  It must be specified either via the ``GITHUB_TOKEN`` environment
variable or as the value of the ``hub.oauthtoken`` Git config option.

Options
'''''''

--install-dir DIR               Directory in which to unpack the ``*.deb``
                                package instead of installing it system-wide.
                                If this contains the string ``{tmpdir}``, it
                                will be replaced with the path to a directory
                                in ``$TMPDIR``. (Linux only)


``datalad/packages``
~~~~~~~~~~~~~~~~~~~~~

Downloads & installs ``git-annex`` from
<https://datasets.datalad.org/?dir=/datalad/packages> for the running OS.
Supports installing specific versions (though note that the version strings for
this method tend to include Git commit information, e.g.,
"``8.20210127+git111-gbe5a0e4b8``").

Options
'''''''

--install-dir DIR               Directory in which to unpack the ``*.deb``
                                package instead of installing it system-wide.
                                If this contains the string ``{tmpdir}``, it
                                will be replaced with the path to a directory
                                in ``$TMPDIR``. (Linux only)


``deb-url``
~~~~~~~~~~~

Download & install a given ``*.deb`` package.  Does not support installing
specific versions.

Options
'''''''

-e ARGS, --extra-args ARGS      Specify extra command-line arguments to pass to
                                the installation command.

--install-dir DIR               Directory in which to unpack the ``*.deb``
                                package instead of installing it system-wide.
                                If this contains the string ``{tmpdir}``, it
                                will be replaced with the path to a directory
                                in ``$TMPDIR``.  If this contains the string
                                ``{version}``, it will be replaced with the
                                package's version. (``git-annex`` only)

--url URL                       Specify the URL of the ``*.deb`` package.  This
                                option is required for this installation
                                method.

``dmg``
~~~~~~~

Installs ``git-annex`` to the ``/Applications`` directory from a properly-built
``*.dmg`` image.  Does not support installing specific versions.

This installation method is only supported on macOS.

Options
'''''''

--path PATH                     Specify the path to the ``*.dmg`` image.  This
                                option is required for this installation
                                method.

``downloads.rclone.org``
~~~~~~~~~~~~~~~~~~~~~~~~

Downloads & installs ``rclone`` from <https://downloads.rclone.org>.

Options
'''''''

--bin-dir DIR                   Directory in which to install the ``rclone``
                                executable.  This option is required on
                                Windows.  On Linux & macOS, the directory
                                defaults to ``/usr/local/bin``.  If the path
                                contains the string ``{tmpdir}``, it will be
                                replaced with the path to a directory in
                                ``$TMPDIR``.

--man-dir DIR                   Directory under which to install the ``rclone``
                                manpage; specifically, the file ``rclone.1``
                                will be placed in the ``man1/`` subdirectory of
                                the given directory.  If this option is not
                                specified, the manpage is not installed.  If
                                the path contains the string ``{tmpdir}``, it
                                will be replaced with the path to a directory
                                in ``$TMPDIR`` (the same one as used for
                                ``--bin-dir``, if applicable).

``neurodebian``
~~~~~~~~~~~~~~~

Installs from NeuroDebian repositories with ``sudo apt-get install``.  Supports
installing specific versions.

Options
'''''''

--build-dep                     Run ``sudo apt-get build-dep`` instead of
                                ``sudo apt-get install``.

-e ARGS, --extra-args ARGS      Specify extra command-line arguments to pass to
                                the installation command.


``pip``
~~~~~~~

Installs with ``python -m pip``.  Supports installing specific versions.

If a ``venv`` component is previously given on the command line, the
installation will be performed in that virtual environment; otherwise, it will
be performed using the same Python used to run ``datalad-installer``.

Options
'''''''

--devel                         Install the given component from its GitHub
                                repository instead of from PyPI.

-e ARGS, --extra-args ARGS      Specify extra command-line arguments to pass to
                                the installation command.

-E EXTRAS, --extras EXTRAS      Specify (comma-separated) package extras to
                                install.


``snapshot``
~~~~~~~~~~~~

Downloads & installs the latest official snapshot build of ``git-annex`` from
kitenet.net.  Does not support installing specific versions.

This installation method is only supported on Linux and macOS.
