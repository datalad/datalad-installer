import subprocess
from datalad_installer import DataladInstaller


def test_install_miniconda(tmp_path):
    miniconda_path = tmp_path / "conda"
    with DataladInstaller() as manager:
        manager.main(
            [
                "datalad_installer.py",
                "miniconda",
                "--batch",
                "--path",
                str(miniconda_path),
            ]
        )
    r = subprocess.run(
        [str(miniconda_path / "bin" / "conda"), "create", "-n", "test", "-y"],
        stdout=subprocess.PIPE,
        universal_newlines=True,
        check=True,
    )
    assert "conda activate test" in r.stdout
