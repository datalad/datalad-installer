#!/bin/bash
set -e

# Support using the GitHub token registered with `gh` for testing so that the
# user doesn't have to store their token in ~/.gitconfig
if [ "$GITHUB_TOKEN" = "" ] && command -V gh 2>/dev/null
then
    GITHUB_TOKEN="$(gh auth token)"
    if [ $? = 0 ]
    then export GITHUB_TOKEN
    fi
fi

case "$(uname)" in
    Darwin)
        # The lengthy default $TMPDIR on macOS causes lengthy shebangs when
        # installing Miniconda.  If the shebang exceeds 127 characters,
        # Miniconda refuses to use it, instead setting the first line of the
        # "conda" script to "#!/usr/bin/env python", which results in a
        # non-working installation.  Hence, we need a shorter $TMPDIR.
        #
        # Related issue: <https://github.com/conda/conda/issues/9360>
        export TMPDIR=/tmp
        ;;
    MINGW*)
        # To avoid <https://github.com/conda/conda/issues/10501>
        mkdir -p /c/tmp
        export TMPDIR='C:\tmp'
        ;;
esac

exec tox "$@"
