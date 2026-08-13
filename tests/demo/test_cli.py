from __future__ import annotations

from pathlib import Path

from software_delivery_demo.cli_demo import main


def test_generate_cli_writes_fixture(tmp_path: Path, capsys) -> None:
    project_root = Path("projects/software-delivery-demo")
    output_root = tmp_path / "generated"
    assert main(["generate", "--project-root", str(project_root), "--output", str(output_root)]) == 0
    assert (output_root / "public" / "requirements.parquet").exists()
    assert "generated" in capsys.readouterr().out
