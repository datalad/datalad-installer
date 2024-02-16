# v1.0.4 (Fri Feb 16 2024)

#### 🐛 Bug Fix

- Always provide -y   to apt-get install [#194](https://github.com/datalad/datalad-installer/pull/194) ([@yarikoptic](https://github.com/yarikoptic))
- Handle lack of Link header when paginating [#188](https://github.com/datalad/datalad-installer/pull/188) ([@jwodder](https://github.com/jwodder))

#### 🏠 Internal

- [gh-actions](deps): Bump codecov/codecov-action from 3 to 4 [#189](https://github.com/datalad/datalad-installer/pull/189) ([@dependabot[bot]](https://github.com/dependabot[bot]) [@jwodder](https://github.com/jwodder))

#### 📝 Documentation

- Document effect of miniconda component on installing rclone components [#193](https://github.com/datalad/datalad-installer/pull/193) ([@jwodder](https://github.com/jwodder))
- Assorted minor README improvements [#192](https://github.com/datalad/datalad-installer/pull/192) ([@jwodder](https://github.com/jwodder))
- Remove inapplicable installers from datalad's "auto" resolution list [#191](https://github.com/datalad/datalad-installer/pull/191) ([@jwodder](https://github.com/jwodder))

#### Authors: 3

- [@dependabot[bot]](https://github.com/dependabot[bot])
- John T. Wodder II ([@jwodder](https://github.com/jwodder))
- Yaroslav Halchenko ([@yarikoptic](https://github.com/yarikoptic))

---

# v1.0.3 (Wed Dec 20 2023)

#### 🐛 Bug Fix

- Remove "Authorization" header when following cross-origin redirects [#187](https://github.com/datalad/datalad-installer/pull/187) ([@jwodder](https://github.com/jwodder))

#### 🏠 Internal

- [gh-actions](deps): Bump actions/setup-python from 4 to 5 [#185](https://github.com/datalad/datalad-installer/pull/185) ([@dependabot[bot]](https://github.com/dependabot[bot]))

#### Authors: 2

- [@dependabot[bot]](https://github.com/dependabot[bot])
- John T. Wodder II ([@jwodder](https://github.com/jwodder))

---

# v1.0.2 (Mon Nov 20 2023)

#### 🐛 Bug Fix

- Add `--help-versions` option to miniconda component [#180](https://github.com/datalad/datalad-installer/pull/180) ([@jwodder](https://github.com/jwodder))

#### 🏠 Internal

- Convert almost all classes to dataclasses [#184](https://github.com/datalad/datalad-installer/pull/184) ([@jwodder](https://github.com/jwodder))

#### 📝 Documentation

- Mention conda-forge installation in README [#183](https://github.com/datalad/datalad-installer/pull/183) ([@jwodder](https://github.com/jwodder))
- Add Appveyor status badge to README [#182](https://github.com/datalad/datalad-installer/pull/182) ([@jwodder](https://github.com/jwodder))

#### 🧪 Tests

- Test against Python 3.12 and PyPy for 3.10 [#181](https://github.com/datalad/datalad-installer/pull/181) ([@jwodder](https://github.com/jwodder))

#### Authors: 1

- John T. Wodder II ([@jwodder](https://github.com/jwodder))

---

# v1.0.1 (Wed Nov 08 2023)

#### 🐛 Bug Fix

- Set better headers for HTTP requests [#178](https://github.com/datalad/datalad-installer/pull/178) ([@jwodder](https://github.com/jwodder))
- Pass `-y` to `conda update` [#177](https://github.com/datalad/datalad-installer/pull/177) ([@jwodder](https://github.com/jwodder))

#### 🏠 Internal

- [gh-actions](deps): Bump actions/checkout from 3 to 4 [#176](https://github.com/datalad/datalad-installer/pull/176) ([@dependabot[bot]](https://github.com/dependabot[bot]))

#### 🧪 Tests

- Improve type-checking of imports [#179](https://github.com/datalad/datalad-installer/pull/179) ([@jwodder](https://github.com/jwodder))

#### Authors: 2

- [@dependabot[bot]](https://github.com/dependabot[bot])
- John T. Wodder II ([@jwodder](https://github.com/jwodder))

---

# v1.0.0 (Tue Aug 29 2023)

#### 💥 Breaking Change

- [gh-actions](deps): Bump codespell-project/actions-codespell from 1 to 2 [#164](https://github.com/datalad/datalad-installer/pull/164) ([@dependabot[bot]](https://github.com/dependabot[bot]))

#### 🐛 Bug Fix

- Provide explicit release to nd-configure if it fails to determine one, specify minimal version of datalad (>= 0.10.0) for conda [#174](https://github.com/datalad/datalad-installer/pull/174) ([@yarikoptic](https://github.com/yarikoptic))
- dpkg-based methods now raise MethodNotSupportedError when called on non-dpkg systems without `--install-dir` [#163](https://github.com/datalad/datalad-installer/pull/163) ([@jwodder](https://github.com/jwodder))
- Fix sleeping when retrying downloads [#165](https://github.com/datalad/datalad-installer/pull/165) ([@jwodder](https://github.com/jwodder))

#### 🏠 Internal

- Cancel any still-running tests when pushing to a branch or PR [#168](https://github.com/datalad/datalad-installer/pull/168) ([@jwodder](https://github.com/jwodder))
- Assorted code improvements [#161](https://github.com/datalad/datalad-installer/pull/161) ([@jwodder](https://github.com/jwodder))

#### 📝 Documentation

- Extend miniconda docstring on how to figure out VERSION to use [#169](https://github.com/datalad/datalad-installer/pull/169) ([@yarikoptic](https://github.com/yarikoptic))

#### 🧪 Tests

- Fix failing tests [#167](https://github.com/datalad/datalad-installer/pull/167) ([@jwodder](https://github.com/jwodder))

#### Authors: 3

- [@dependabot[bot]](https://github.com/dependabot[bot])
- John T. Wodder II ([@jwodder](https://github.com/jwodder))
- Yaroslav Halchenko ([@yarikoptic](https://github.com/yarikoptic))

---

# v0.12.0 (Mon May 01 2023)

#### 🚀 Enhancement

- Support installing specific versions of Miniconda [#158](https://github.com/datalad/datalad-installer/pull/158) ([@jwodder](https://github.com/jwodder))

#### 🐛 Bug Fix

- codespell: workflow, config, 1 fix [#151](https://github.com/datalad/datalad-installer/pull/151) ([@yarikoptic](https://github.com/yarikoptic))

#### Authors: 2

- John T. Wodder II ([@jwodder](https://github.com/jwodder))
- Yaroslav Halchenko ([@yarikoptic](https://github.com/yarikoptic))

---

# v0.11.2 (Tue Mar 28 2023)

#### 🐛 Bug Fix

- Detect file downloads that end early [#153](https://github.com/datalad/datalad-installer/pull/153) ([@jwodder](https://github.com/jwodder))

#### 🧪 Tests

- Fix failing tests [#149](https://github.com/datalad/datalad-installer/pull/149) ([@jwodder](https://github.com/jwodder))

#### Authors: 1

- John T. Wodder II ([@jwodder](https://github.com/jwodder))

---

# v0.11.1 (Thu Jan 05 2023)

#### 🐛 Bug Fix

- Try to handle Windows being Windows [#145](https://github.com/datalad/datalad-installer/pull/145) ([@jwodder](https://github.com/jwodder))

#### Authors: 1

- John T. Wodder II ([@jwodder](https://github.com/jwodder))

---

# v0.11.0 (Wed Jan 04 2023)

#### 🚀 Enhancement

- Support installing git-annex-remote-rclone via Conda [#141](https://github.com/datalad/datalad-installer/pull/141) ([@jwodder](https://github.com/jwodder))
- Support installing from datalad/packages on Linux [#143](https://github.com/datalad/datalad-installer/pull/143) ([@jwodder](https://github.com/jwodder))
- If GitHub rate limit is exceeded, dump rate limit info or advise user to set GITHUB_TOKEN [#144](https://github.com/datalad/datalad-installer/pull/144) ([@jwodder](https://github.com/jwodder))
- Support installing from datalad/packages on macOS [#136](https://github.com/datalad/datalad-installer/pull/136) ([@jwodder](https://github.com/jwodder))
- Drop support for Python 3.6 [#139](https://github.com/datalad/datalad-installer/pull/139) ([@jwodder](https://github.com/jwodder))

#### 🐛 Bug Fix

- rclone -m downloads.rclone.org: Add bin_dir to PATH if necessary [#140](https://github.com/datalad/datalad-installer/pull/140) ([@jwodder](https://github.com/jwodder) [@yarikoptic](https://github.com/yarikoptic))

#### Authors: 2

- John T. Wodder II ([@jwodder](https://github.com/jwodder))
- Yaroslav Halchenko ([@yarikoptic](https://github.com/yarikoptic))

---

# v0.10.0 (Mon Nov 28 2022)

#### 🚀 Enhancement

- Add `--channel` option to miniconda component [#134](https://github.com/datalad/datalad-installer/pull/134) ([@jwodder](https://github.com/jwodder))

#### Authors: 1

- John T. Wodder II ([@jwodder](https://github.com/jwodder))

---

# v0.9.2 (Tue Nov 22 2022)

#### 🐛 Bug Fix

- Retry failed downloads [#132](https://github.com/datalad/datalad-installer/pull/132) ([@jwodder](https://github.com/jwodder))
- Install arm64 Miniconda on M1 Macs [#130](https://github.com/datalad/datalad-installer/pull/130) ([@jwodder](https://github.com/jwodder))
- Handle moving files across filesystems [#125](https://github.com/datalad/datalad-installer/pull/125) ([@jwodder](https://github.com/jwodder))
- Make `OSError.winerror` reference portable [#123](https://github.com/datalad/datalad-installer/pull/123) ([@jwodder](https://github.com/jwodder))

#### 🏠 Internal

- Update GitHub Actions action versions [#126](https://github.com/datalad/datalad-installer/pull/126) ([@jwodder](https://github.com/jwodder))

#### 🧪 Tests

- Test against Python 3.11 [#127](https://github.com/datalad/datalad-installer/pull/127) ([@jwodder](https://github.com/jwodder))
- Fix test failures due to some sort of dependency hell [#128](https://github.com/datalad/datalad-installer/pull/128) ([@jwodder](https://github.com/jwodder))

#### Authors: 1

- John T. Wodder II ([@jwodder](https://github.com/jwodder))

---

# v0.9.1 (Thu Jul 28 2022)

#### 🐛 Bug Fix

- Smoke-test rclone with `--version` instead of `--help` [#122](https://github.com/datalad/datalad-installer/pull/122) ([@jwodder](https://github.com/jwodder))

#### 📝 Documentation

- Add reference to README to command `--help` [#119](https://github.com/datalad/datalad-installer/pull/119) ([@jwodder](https://github.com/jwodder))

#### 🧪 Tests

- Add test of `--python-match` [#117](https://github.com/datalad/datalad-installer/pull/117) ([@jwodder](https://github.com/jwodder))

#### Authors: 1

- John T. Wodder II ([@jwodder](https://github.com/jwodder))

---

# v0.9.0 (Fri Jul 01 2022)

#### 🚀 Enhancement

- Give miniconda component a `--python-match` option [#114](https://github.com/datalad/datalad-installer/pull/114) ([@jwodder](https://github.com/jwodder))
- miniconda: Make `--batch` cause `--yes` to be passed to `conda install` [#115](https://github.com/datalad/datalad-installer/pull/115) ([@jwodder](https://github.com/jwodder))

#### Authors: 1

- John T. Wodder II ([@jwodder](https://github.com/jwodder))

---

# v0.8.2 (Tue Jun 21 2022)

#### 🐛 Bug Fix

- Use GitHub token when downloading workflow artifacts [#111](https://github.com/datalad/datalad-installer/pull/111) ([@jwodder](https://github.com/jwodder))

#### Authors: 1

- John T. Wodder II ([@jwodder](https://github.com/jwodder))

---

# v0.8.1 (Tue Jun 14 2022)

#### 🧪 Tests

- Mark some tests as impossible to pass on conda-forge [#109](https://github.com/datalad/datalad-installer/pull/109) ([@jwodder](https://github.com/jwodder))
- Type-check tests [#108](https://github.com/datalad/datalad-installer/pull/108) ([@jwodder](https://github.com/jwodder))

#### Authors: 1

- John T. Wodder II ([@jwodder](https://github.com/jwodder))

---

# v0.8.0 (Fri Jun 10 2022)

#### 🚀 Enhancement

- Support installing rclone and git-annex-remote-rclone [#107](https://github.com/datalad/datalad-installer/pull/107) ([@jwodder](https://github.com/jwodder))

#### Authors: 1

- John T. Wodder II ([@jwodder](https://github.com/jwodder))

---

# v0.7.0 (Wed May 11 2022)

#### 🚀 Enhancement

- Add `datalad/git-annex:release` method [#102](https://github.com/datalad/datalad-installer/pull/102) ([@jwodder](https://github.com/jwodder))

#### 🏠 Internal

- Expand git.io link in comment [#105](https://github.com/datalad/datalad-installer/pull/105) ([@jwodder](https://github.com/jwodder))

#### Authors: 1

- John T. Wodder II ([@jwodder](https://github.com/jwodder))

---

# v0.6.0 (Tue Apr 19 2022)

#### 🚀 Enhancement

- Install Rosetta on M1 Macs before installing git-annex from a DMG [#104](https://github.com/datalad/datalad-installer/pull/104) ([@jwodder](https://github.com/jwodder))

#### Authors: 1

- John T. Wodder II ([@jwodder](https://github.com/jwodder))

---

# v0.5.5 (Tue Jan 25 2022)

#### 🐛 Bug Fix

- datalad/git-annex: Uninstall git-annex package before installing git-annex-standalone [#100](https://github.com/datalad/datalad-installer/pull/100) ([@jwodder](https://github.com/jwodder))
- Try to ignore tempdir cleanup errors on Windows [#96](https://github.com/datalad/datalad-installer/pull/96) ([@jwodder](https://github.com/jwodder))
- Ensure the pip version in venvs is up-to-date [#97](https://github.com/datalad/datalad-installer/pull/97) ([@jwodder](https://github.com/jwodder))
- Use `ar` & `tar` instead of `dpkg -x` [#86](https://github.com/datalad/datalad-installer/pull/86) ([@jwodder](https://github.com/jwodder))

#### 🏠 Internal

- Improve linting configuration [#98](https://github.com/datalad/datalad-installer/pull/98) ([@jwodder](https://github.com/jwodder))
- More linting [#93](https://github.com/datalad/datalad-installer/pull/93) ([@jwodder](https://github.com/jwodder))
- Update codecov action to v2 [#88](https://github.com/datalad/datalad-installer/pull/88) ([@jwodder](https://github.com/jwodder))

#### 🧪 Tests

- Test against Python 3.10 and PyPy3.7 [#87](https://github.com/datalad/datalad-installer/pull/87) ([@jwodder](https://github.com/jwodder))
- Add a `--dev-pip` option for testing against the dev version of pip [#90](https://github.com/datalad/datalad-installer/pull/90) ([@jwodder](https://github.com/jwodder))

#### Authors: 1

- John T. Wodder II ([@jwodder](https://github.com/jwodder))

---

# v0.5.4 (Mon Jul 26 2021)

#### 🐛 Bug Fix

- datalad/git-annex: Install commands that fail with WinError 740 are retried with elevation [#84](https://github.com/datalad/datalad-installer/pull/84) ([@jwodder](https://github.com/jwodder))
- Retry failed "conda install" commands [#83](https://github.com/datalad/datalad-installer/pull/83) ([@jwodder](https://github.com/jwodder))

#### Authors: 1

- John T. Wodder II ([@jwodder](https://github.com/jwodder))

---

# v0.5.3 (Mon Jul 19 2021)

#### 🐛 Bug Fix

- Use newer build for OSX (from Catalina on GH actions, instead of Yosemite) [#80](https://github.com/datalad/datalad-installer/pull/80) ([@yarikoptic](https://github.com/yarikoptic))

#### Authors: 1

- Yaroslav Halchenko ([@yarikoptic](https://github.com/yarikoptic))

---

# v0.5.2 (Thu Jul 15 2021)

#### 🧪 Tests

- Only run apt-based tests on systems with Apt, and likewise for brew [#79](https://github.com/datalad/datalad-installer/pull/79) ([@jwodder](https://github.com/jwodder))

#### Authors: 1

- John T. Wodder II ([@jwodder](https://github.com/jwodder))

---

# v0.5.1 (Thu Jul 15 2021)

#### 🐛 Bug Fix

- Make miniconda error if conda is already installed; mark miniconda tests [#78](https://github.com/datalad/datalad-installer/pull/78) ([@jwodder](https://github.com/jwodder))

#### Authors: 1

- John T. Wodder II ([@jwodder](https://github.com/jwodder))

---

# v0.5.0 (Thu Jul 08 2021)

#### 🚀 Enhancement

- Support installing git-annex .deb's to a given directory instead of system-wide [#73](https://github.com/datalad/datalad-installer/pull/73) ([@jwodder](https://github.com/jwodder))

#### Authors: 1

- John T. Wodder II ([@jwodder](https://github.com/jwodder))

---

# v0.4.0 (Tue Jun 29 2021)

#### 🚀 Enhancement

- Add installation method for getting latest build of datalad/git-annex; rename datalad/git-annex to datalad/git-annex:tested [#76](https://github.com/datalad/datalad-installer/pull/76) ([@jwodder](https://github.com/jwodder))
- Add "dmg" installation method for git-annex [#69](https://github.com/datalad/datalad-installer/pull/69) ([@jwodder](https://github.com/jwodder))

#### 🐛 Bug Fix

- Delete a certain tempfile once we're done with it [#72](https://github.com/datalad/datalad-installer/pull/72) ([@jwodder](https://github.com/jwodder))

#### 🏠 Internal

- [DATALAD RUNCMD] codespell is lucky to find a typo [#67](https://github.com/datalad/datalad-installer/pull/67) ([@yarikoptic](https://github.com/yarikoptic))

#### Authors: 2

- John T. Wodder II ([@jwodder](https://github.com/jwodder))
- Yaroslav Halchenko ([@yarikoptic](https://github.com/yarikoptic))

---

# v0.3.1 (Thu May 13 2021)

#### 🐛 Bug Fix

- Adjust post-install checks of program executability [#65](https://github.com/datalad/datalad-installer/pull/65) ([@jwodder](https://github.com/jwodder))
- Update for pip 21.1 [#66](https://github.com/datalad/datalad-installer/pull/66) ([@jwodder](https://github.com/jwodder))
- Don't run "brew update" more than once [#59](https://github.com/datalad/datalad-installer/pull/59) ([@jwodder](https://github.com/jwodder))
- Run `brew update` before `brew install` [#58](https://github.com/datalad/datalad-installer/pull/58) ([@jwodder](https://github.com/jwodder))
- Print brew diagnostic output on failure [#51](https://github.com/datalad/datalad-installer/pull/51) ([@jwodder](https://github.com/jwodder))
- Improve "Cannot execute program!" error message [#49](https://github.com/datalad/datalad-installer/pull/49) ([@jwodder](https://github.com/jwodder))

#### 🧪 Tests

- Add tests on Appveyor [#63](https://github.com/datalad/datalad-installer/pull/63) ([@jwodder](https://github.com/jwodder))
- Add a test of installing git-annex with brew on macOS [#57](https://github.com/datalad/datalad-installer/pull/57) ([@jwodder](https://github.com/jwodder))
- Only run push tests on push to master [#56](https://github.com/datalad/datalad-installer/pull/56) ([@jwodder](https://github.com/jwodder))

#### Authors: 1

- John T. Wodder II ([@jwodder](https://github.com/jwodder))

---

# v0.3.0 (Tue Mar 09 2021)

#### 🚀 Enhancement

- Install git-annex on Windows via datalad/packages with privilege elevation [#44](https://github.com/datalad/datalad-installer/pull/44) ([@jwodder](https://github.com/jwodder))

#### 🐛 Bug Fix

- Install NeuroDebian following the instructions on neuro.debian.net [#41](https://github.com/datalad/datalad-installer/pull/41) ([@jwodder](https://github.com/jwodder))

#### 📝 Documentation

- Fix formatting of --sudo option in README [#35](https://github.com/datalad/datalad-installer/pull/35) ([@jwodder](https://github.com/jwodder))

#### 🧪 Tests

- Test that sourcing env files activates conda environments [#42](https://github.com/datalad/datalad-installer/pull/42) ([@jwodder](https://github.com/jwodder))
- Add a --ci option to pytest (off by default) [#36](https://github.com/datalad/datalad-installer/pull/36) ([@jwodder](https://github.com/jwodder))

#### Authors: 1

- John T. Wodder II ([@jwodder](https://github.com/jwodder))

---

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
