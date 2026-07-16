# tests/unit/test_spec_cli.py
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/specification/scripts/spec/__main__.py"


def test_seed_verb_removed(tmp_path):
    r = subprocess.run(
        [sys.executable, str(MAIN), "seed", "--workdir", str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert r.returncode != 0  # argparse rejects an unknown subcommand
