.. image:: https://github.com/datalad/datalad-installer/workflows/Test/badge.svg?branch=master
    :target: https://github.com/datalad/datalad-installer/actions?workflow=Test
    :alt: CI Status

.. image:: https://codecov.io/gh/datalad/datalad-installer/branch/master/graph/badge.svg
    :target: https://codecov.io/gh/datalad/datalad-installer

.. image:: https://img.shields.io/pypi/pyversions/datalad-installer.svg
    :target: https://pypi.org/project/datalad-installer/

.. image:: https://img.shields.io/github/license/datalad/datalad-installer.svg
    :target: https://opensource.org/licenses/MIT
    :alt: MIT License

`GitHub <https://github.com/datalad/datalad-installer>`_
| `PyPI <https://pypi.org/project/datalad-installer/>`_
| `Issues <https://github.com/datalad/datalad-installer/issues>`_
| `Changelog <https://github.com/jwodder/datalad-installer/blob/master/CHANGELOG.md>`_

``datalad-installer`` is a script for installing Datalad_, git-annex_, and
related components all in a single invocation.  It requires no third-party
Python libraries, though it does make heavy use of external packaging commands.

.. _Datalad: https://www.datalad.org
.. _git-annex: https://git-annex.branchable.com

Installation
============
``datalad-installer`` requires Python 3.6 or higher.  Just use `pip
<https://pip.pypa.io>`_ for Python 3 (You have pip, right?) to install it::

    python3 -m pip install datalad-installer

Alternatively, download the latest version directly from
<https://raw.githubusercontent.com/datalad/datalad-installer/master/src/datalad_installer.py>.


Usage
=====

::

    datalad-installer [<global options>] <component>[=<version>] [<options>] <component>[=<version>] [<options>] ...

``datalad-installer`` provisions one or more *components* listed on the command
line.  Each component is either a software package (i.e., Datalad or git-annex)
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

-V, --version                   Display the script version and exit

-h, --help                      Display usage information and exit


Components
----------

``venv``
~~~~~~~~

Creates a Python virtual environment using ``python -m venv``.  Subsequent
``datalad`` components on the command line will be installed into this virtual
environment by default if not overridden by an intervening componnent.

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
on the command line will use this installation, and subsequent ``datalad`` and
``git-annex`` components will be installed using this conda by default if not
overridden by an intervening component.

The Miniconda installation script is downloaded from
``$ANACONDA_URL/Miniconda3-latest-$OS-x86_64.sh``, where ``$ANACONDA_URL`` is
taken from the environment, defaulting to
``https://repo.anaconda.com/miniconda``.

Options
'''''''

--batch                         Run the Miniconda installation script in batch
                                (noninteractive) mode.

-e ARGS, --extra-args ARGS      Specify extra command-line arguments to pass to
                                the Miniconda installation script.

--path PATH                     Install Miniconda at ``PATH``.  If not
                                specified, it will be installed in a directory
                                in ``$TMPDIR``.

--spec SPEC                     Space-separated specifiers for packages to
                                install in the Conda base environment after
                                provisioning.


``conda-env``
~~~~~~~~~~~~~

Creates a Conda environment.  Subsequent ``datalad`` and ``git-annex``
components will be installed into this environment by default if not overridden
by an intervening component.

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
- ``conda``
- ``datalad/git-annex``
- ``deb-url``
- ``neurodebian``
- ``snapshot``

If no method is specified, or if the method is set to "``auto``", then the most
recent component on the command line that provides a compatible installation
method will be used.  If there is no such component, the first supported
component from the following list will be used:

- ``conda``
- ``apt``
- ``neurodebian``
- ``brew``
- ``autobuild``

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
- ``conda``
- ``deb-url``
- ``pip``

If no method is specified, or if the method is set to "``auto``", then the most
recent component on the command line that provides a compatible installation
method will be used.  If there is no such component, the first supported
component from the following list will be used:

- ``conda``
- ``apt``
- ``neurodebian``
- ``brew``
- ``autobuild``

A specific version to install can be specified for those methods that support
it by suffixing "``git-annex``" with "``=``" and the version number on the
command line.

The ``datalad`` component also accepts all options for the supported
installation methods; options not belonging to whichever method ends up used
will be ignored.


Installation Methods
--------------------

``apt``
~~~~~~~

Install with ``sudo apt-get install``.  Supports installing specific versions.

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


``brew``
~~~~~~~~

Install with ``brew`` (`Homebrew <https://brew.sh>`_).  Does not support
installing specific versions.

Options
'''''''

-e ARGS, --extra-args ARGS      Specify extra command-line arguments to pass to
                                the installation command.


``conda``
~~~~~~~~~

Install with ``conda install``.  Supports installing specific versions.

Options
'''''''

-e ARGS, --extra-args ARGS      Specify extra command-line arguments to pass to
                                the installation command.


``datalad/git-annex``
~~~~~~~~~~~~~~~~~~~~~

Downloads & installs the artifact from the latest successful build of
`datalad/git-annex <https://github.com/datalad/git-annex>`_ for the running OS.
Does not support installing specific versions.

This installation method requires a GitHub OAuth token with appropriate
permissions.  It must be specified either via the ``GITHUB_TOKEN`` environment
variable or as the value of the ``hub.oauthtoken`` Git config option.

``deb-url``
~~~~~~~~~~~

Download & install a given ``*.deb`` package.  Does not support installing
specific versions.

Options
'''''''

-e ARGS, --extra-args ARGS      Specify extra command-line arguments to pass to
                                the installation command.

--url URL                       Specify the URL of the ``*.deb`` package.  This
                                option is required for this installation
                                method.

``neurodebian``
~~~~~~~~~~~~~~~

Install from NeuroDebian repositories with ``sudo apt-get install``.  Supports
installing specific versions.

Options
'''''''

--build-dep                     Run ``sudo apt-get build-dep`` instead of
                                ``sudo apt-get install``.

-e ARGS, --extra-args ARGS      Specify extra command-line arguments to pass to
                                the installation command.


``pip``
~~~~~~~

Install with ``python -m pip``.  Supports installing specific versions.

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
