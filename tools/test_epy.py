"""Tests for the epy runner. Run with: uv run --with pytest pytest tools"""
import os
from pathlib import Path
import pytest
from tools import epy

def test_a_sample_is_found_by_name_and_by_path() -> None:
    by_name = epy.find_program("fib")
    by_path = epy.find_program(str(epy.PROGRAMS / "fib.epy"))
    assert by_name == by_path == (epy.PROGRAMS / "fib.epy").resolve()

def test_an_unknown_program_suggests_a_near_name(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = epy.main(["check", "fibb"])
    assert code == 2
    assert "Did you mean fib?" in capsys.readouterr().err

@pytest.mark.parametrize("age, expected", [(-10, True), (10, False)])
def test_the_binary_is_stale_when_a_source_is_newer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    age: int, expected: bool,
) -> None:
    binary = tmp_path / "bin"
    source = tmp_path / "a.py"
    binary.touch()
    source.touch()
    now = source.stat().st_mtime
    os.utime(binary, (now + age, now + age))
    monkeypatch.setattr(epy, "BINARY", binary)
    monkeypatch.setattr(epy, "sources", lambda: [source])
    assert epy.stale() is expected

def test_the_listing_names_every_task() -> None:
    listing = epy.listing()
    assert all(f"  {name} " in listing for name in epy.TASKS)

@pytest.mark.parametrize("code, seconds, expected", [
    (0, 4.2, "epy build: 4s"),
    (0, 92.0, "epy build: 1m 32s"),
    (1, 3.0, "epy build: failed with exit status 1 after 3s"),
])
def test_the_closing_line_gives_the_time(
    code: int, seconds: float, expected: str,
) -> None:
    assert epy.report("build", code, seconds) == expected
