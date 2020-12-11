from pathlib import Path
import subprocess
import sys


def test_install_miniconda(tmp_path):
    miniconda_path = tmp_path / "conda"
    subprocess.run(
        [
            sys.executable,
            "datalad_install.py",
            "miniconda",
            "--batch",
            "--path-miniconda",
            str(miniconda_path),
        ],
        cwd=Path(__file__).resolve().parent.parent,
        check=True,
    )
    r = subprocess.run(
        [str(miniconda_path / "bin" / "conda"), "create", "-n", "test", "-y"],
        stdout=subprocess.PIPE,
        universal_newlines=True,
        check=True,
    )
    assert "conda activate test" in r.stdout
