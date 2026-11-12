"""Each Python original under ports/ prints what its port under
tests/programs/ is recorded as printing, so a port that drifts from
the program it was written from fails here.
Run with: uv run --with pytest pytest tools"""
import subprocess
import sys
from pathlib import Path
import pytest
from tools import epy

PORTS = epy.ROOT / "ports"

@pytest.mark.parametrize(
    "original", sorted(PORTS.glob("*.py")), ids=lambda p: p.stem)
def test_an_original_prints_what_its_port_prints(original: Path) -> None:
    recorded = (epy.PROGRAMS / f"{original.stem}.expected").read_text()
    expected = recorded.split("\n", 1)[1]
    printed = subprocess.run(
        [sys.executable, "-I", original],
        capture_output=True, text=True, check=True).stdout
    assert printed == expected
