#!/bin/bash
if [ "$(uname)" = Darwin ]
then
    # The lengthy default $TMPDIR on macOS causes lengthy shebangs when
    # installing Miniconda.  If the shebang exceeds 127 characters, Miniconda
    # refuses to use it, instead setting the first line of the "conda" script
    # to "#!/usr/bin/env python", which results in a non-working installation.
    # Hence, we need a shorter $TMPDIR.
    export TMPDIR=/tmp
fi

exec tox "$@"
