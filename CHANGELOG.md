# v0.2.0 (Fri Feb 26 2021)

#### 🚀 Enhancement

- Add --sudo option to by default seek confirmation to run sudo commands [#34](https://github.com/datalad/datalad-installer/pull/34) ([@jwodder](https://github.com/jwodder))
- Support installing git-annex from datalad/packages on Windows [#26](https://github.com/datalad/datalad-installer/pull/26) ([@jwodder](https://github.com/jwodder))
- Support datalad/git-annex installation method for git-annex on Windows [#24](https://github.com/datalad/datalad-installer/pull/24) ([@jwodder](https://github.com/jwodder))
- Support installing Datalad with brew [#23](https://github.com/datalad/datalad-installer/pull/23) ([@jwodder](https://github.com/jwodder))
- Support Miniconda and venv on Windows [#17](https://github.com/datalad/datalad-installer/pull/17) ([@jwodder](https://github.com/jwodder))

#### 🐛 Bug Fix

- Use "sudo" to install neurodebian [#33](https://github.com/datalad/datalad-installer/pull/33) ([@jwodder](https://github.com/jwodder))
- Mark conda on Windows & macOS as an unsupported method for installing git-annex [#25](https://github.com/datalad/datalad-installer/pull/25) ([@jwodder](https://github.com/jwodder))
- Use pip to correctly determine pip's script install path [#27](https://github.com/datalad/datalad-installer/pull/27) ([@jwodder](https://github.com/jwodder))

#### 🏠 Internal

- .autorc: Set "noVersionPrefix" to `false` [#30](https://github.com/datalad/datalad-installer/pull/30) ([@jwodder](https://github.com/jwodder))
- Use constants for running OS [#28](https://github.com/datalad/datalad-installer/pull/28) ([@jwodder](https://github.com/jwodder))
- Set up auto [#22](https://github.com/datalad/datalad-installer/pull/22) ([@jwodder](https://github.com/jwodder))

#### 📝 Documentation

- Improve documentation of supported OSes and `conda-env` component [#29](https://github.com/datalad/datalad-installer/pull/29) ([@jwodder](https://github.com/jwodder))
- Fix minor copy-and-paste error in README [#19](https://github.com/datalad/datalad-installer/pull/19) ([@jwodder](https://github.com/jwodder))

#### 🧪 Tests

- Move TMPDIR setting on Windows to run-tests.sh [#21](https://github.com/datalad/datalad-installer/pull/21) ([@jwodder](https://github.com/jwodder))

#### Authors: 1

- John T. Wodder II ([@jwodder](https://github.com/jwodder))

---

# v0.1.0 (2021-02-03)

* The env write file now activates the base conda environment after sourcing `conda.sh` (#6)
* The command-line entry point has been renamed from `datalad_installer` to `datalad-installer` (#13)
* Fix autogeneration of Miniconda paths (#14)

# v0.1.0a1 (2021-01-11)

Initial alpha release
