import logging
import os.path
from pathlib import Path
import platform
import subprocess
import tempfile
import pytest
import datalad_installer
from datalad_installer import ON_LINUX, main


def bin_path(binname):
    if platform.system() == "Windows":
        return Path("Scripts", binname + ".exe")
    else:
        return Path("bin", binname)


@pytest.fixture(autouse=True)
def capture_all_logs(caplog):
    caplog.set_level(logging.DEBUG)


def test_install_miniconda(tmp_path):
    miniconda_path = tmp_path / "conda"
    r = main(
        [
            "datalad_installer.py",
            "miniconda",
            "--batch",
            "--path",
            str(miniconda_path),
        ]
    )
    assert r == 0
    assert (miniconda_path / bin_path("conda")).exists()
    r = subprocess.run(
        [str(miniconda_path / bin_path("conda")), "create", "-n", "test", "-y"],
        stdout=subprocess.PIPE,
        universal_newlines=True,
        check=True,
    )
    assert "conda activate test" in r.stdout


def test_install_miniconda_autogen_path(monkeypatch):
    # Override TMPDIR with a path that will be cleaned up afterwards (We can't
    # use tmp_path here, as that's apparently always in the user temp folder on
    # Windows regardless of the external value of TMPDIR.)
    with tempfile.TemporaryDirectory() as newtmp:
        monkeypatch.setenv("TMPDIR", newtmp)
        tempfile.tempdir = None  # Reset cache
        r = main(
            [
                "datalad_installer.py",
                "miniconda",
                "--batch",
            ]
        )
        assert r == 0
        (miniconda_path,) = Path(newtmp).glob("dl-miniconda-*")
        assert (miniconda_path / bin_path("conda")).exists()
        r = subprocess.run(
            [str(miniconda_path / bin_path("conda")), "create", "-n", "test", "-y"],
            stdout=subprocess.PIPE,
            universal_newlines=True,
            check=True,
        )
        assert "conda activate test" in r.stdout
    tempfile.tempdir = None  # Reset cache


def test_install_miniconda_datalad(tmp_path):
    miniconda_path = tmp_path / "conda"
    r = main(
        [
            "datalad_installer.py",
            "miniconda",
            "--batch",
            "--path",
            str(miniconda_path),
            "datalad",
        ]
    )
    assert r == 0
    assert (miniconda_path / bin_path("conda")).exists()
    assert (miniconda_path / bin_path("datalad")).exists()


def test_install_miniconda_conda_env_datalad(tmp_path):
    miniconda_path = tmp_path / "conda"
    r = main(
        [
            "datalad_installer.py",
            "miniconda",
            "--batch",
            "--path",
            str(miniconda_path),
            "conda-env",
            "-n",
            "foo",
            "datalad",
        ]
    )
    assert r == 0
    assert (miniconda_path / bin_path("conda")).exists()
    assert not (miniconda_path / bin_path("datalad")).exists()
    assert (miniconda_path / "envs" / "foo").exists()
    assert (miniconda_path / "envs" / "foo" / bin_path("datalad")).exists()


def test_install_venv_miniconda_datalad(tmp_path):
    venv_path = tmp_path / "venv"
    miniconda_path = tmp_path / "conda"
    r = main(
        [
            "datalad_installer.py",
            "venv",
            "--path",
            str(venv_path),
            "miniconda",
            "--batch",
            "--path",
            str(miniconda_path),
            "datalad",
        ]
    )
    assert r == 0
    assert (venv_path / bin_path("python")).exists()
    assert not (venv_path / bin_path("datalad")).exists()
    assert (miniconda_path / bin_path("conda")).exists()
    assert (miniconda_path / bin_path("datalad")).exists()


def test_install_venv_miniconda_conda_env_datalad(tmp_path):
    venv_path = tmp_path / "venv"
    miniconda_path = tmp_path / "conda"
    r = main(
        [
            "datalad_installer.py",
            "venv",
            "--path",
            str(venv_path),
            "miniconda",
            "--batch",
            "--path",
            str(miniconda_path),
            "conda-env",
            "-n",
            "foo",
            "datalad",
        ]
    )
    assert r == 0
    assert (venv_path / bin_path("python")).exists()
    assert not (venv_path / bin_path("datalad")).exists()
    assert (miniconda_path / bin_path("conda")).exists()
    assert not (miniconda_path / bin_path("datalad")).exists()
    assert (miniconda_path / "envs" / "foo").exists()
    assert (miniconda_path / "envs" / "foo" / bin_path("datalad")).exists()


def test_install_venv_datalad(tmp_path):
    venv_path = tmp_path / "venv"
    r = main(
        [
            "datalad_installer.py",
            "venv",
            "--path",
            str(venv_path),
            "datalad",
        ]
    )
    assert r == 0
    assert (venv_path / bin_path("python")).exists()
    assert (venv_path / bin_path("datalad")).exists()


def test_install_miniconda_conda_env_venv_datalad(tmp_path):
    venv_path = tmp_path / "venv"
    miniconda_path = tmp_path / "conda"
    r = main(
        [
            "datalad_installer.py",
            "miniconda",
            "--batch",
            "--path",
            str(miniconda_path),
            "conda-env",
            "-n",
            "foo",
            "venv",
            "--path",
            str(venv_path),
            "datalad",
        ]
    )
    assert r == 0
    assert (venv_path / bin_path("python")).exists()
    assert (venv_path / bin_path("datalad")).exists()
    assert (miniconda_path / bin_path("conda")).exists()
    assert not (miniconda_path / bin_path("datalad")).exists()
    assert (miniconda_path / "envs" / "foo").exists()
    assert not (miniconda_path / "envs" / "foo" / bin_path("datalad")).exists()


@pytest.mark.invasive
@pytest.mark.skipif(not ON_LINUX, reason="requires Debian-based system")
def test_install_neurodebian_sudo_ok(mocker):
    spy = mocker.spy(datalad_installer, "runcmd")
    r = main(["datalad_installer.py", "--sudo=ok", "neurodebian"])
    assert r == 0
    assert spy.call_args_list == [
        mocker.call("sudo", "dpkg", "-i", mocker.ANY, env=mocker.ANY),
        mocker.call("sudo", "dpkg", "-i", mocker.ANY, env=mocker.ANY),
        mocker.call("sudo", "dpkg", "-i", mocker.ANY, env=mocker.ANY),
        mocker.call("nd-configurerepo"),
    ]
    for i, deb in enumerate(
        [
            "neurodebian-archive-keyring_0.41.0~nd20.04%2B1_all.deb",
            "neurodebian-popularity-contest_0.41.0~nd20.04%2B1_all.deb",
            "neurodebian_0.41.0~nd20.04%2B1_all.deb",
        ]
    ):
        assert os.path.basename(spy.call_args_list[i][0][3]) == deb
        assert spy.call_args_list[i][1]["env"]["DEBIAN_FRONTEND"] == "noninteractive"
    r = subprocess.run(
        [
            "dpkg-query",
            "-Wf",
            "${db:Status-Abbrev}",
            "neurodebian",
        ],
        stdout=subprocess.PIPE,
        universal_newlines=True,
        check=True,
    )
    assert r.stdout == "ii "
