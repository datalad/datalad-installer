import logging
import subprocess
import tempfile
import pytest
from datalad_installer import main


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
    assert (miniconda_path / "bin" / "conda").exists()
    r = subprocess.run(
        [str(miniconda_path / "bin" / "conda"), "create", "-n", "test", "-y"],
        stdout=subprocess.PIPE,
        universal_newlines=True,
        check=True,
    )
    assert "conda activate test" in r.stdout


def test_install_miniconda_autogen_path(monkeypatch, tmp_path):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    tempfile.tempdir = None  # Reset cache
    r = main(
        [
            "datalad_installer.py",
            "miniconda",
            "--batch",
        ]
    )
    assert r == 0
    (miniconda_path,) = [
        p for p in tmp_path.iterdir() if p.name.startswith("dl-miniconda-")
    ]
    assert (miniconda_path / "bin" / "conda").exists()
    r = subprocess.run(
        [str(miniconda_path / "bin" / "conda"), "create", "-n", "test", "-y"],
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
    assert (miniconda_path / "bin" / "conda").exists()
    assert (miniconda_path / "bin" / "datalad").exists()


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
    assert (miniconda_path / "bin" / "conda").exists()
    assert not (miniconda_path / "bin" / "datalad").exists()
    assert (miniconda_path / "envs" / "foo").exists()
    assert (miniconda_path / "envs" / "foo" / "bin" / "datalad").exists()


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
    assert (venv_path / "bin" / "python").exists()
    assert not (venv_path / "bin" / "datalad").exists()
    assert (miniconda_path / "bin" / "conda").exists()
    assert (miniconda_path / "bin" / "datalad").exists()


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
    assert (venv_path / "bin" / "python").exists()
    assert not (venv_path / "bin" / "datalad").exists()
    assert (miniconda_path / "bin" / "conda").exists()
    assert not (miniconda_path / "bin" / "datalad").exists()
    assert (miniconda_path / "envs" / "foo").exists()
    assert (miniconda_path / "envs" / "foo" / "bin" / "datalad").exists()


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
    assert (venv_path / "bin" / "python").exists()
    assert (venv_path / "bin" / "datalad").exists()


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
    assert (venv_path / "bin" / "python").exists()
    assert (venv_path / "bin" / "datalad").exists()
    assert (miniconda_path / "bin" / "conda").exists()
    assert not (miniconda_path / "bin" / "datalad").exists()
    assert (miniconda_path / "envs" / "foo").exists()
    assert not (miniconda_path / "envs" / "foo" / "bin" / "datalad").exists()
