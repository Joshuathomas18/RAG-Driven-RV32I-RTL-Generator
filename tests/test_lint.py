"""
pytest: all .v files in rtl/generated/ must pass Verilator lint.
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
RTL_DIR   = REPO_ROOT / "rtl" / "generated"

# Correct instantiation order: sub-modules before top
MODULE_ORDER = [
    "alu", "regfile", "decoder", "branch_unit", "lsu",
    "csr_unit", "hazard_unit", "pipeline_regs", "top",
]


def get_generated_verilog_files() -> list[Path]:
    """Return all .v files in rtl/generated/, sorted by module instantiation order."""
    all_files = sorted(RTL_DIR.glob("*.v"))
    # Sort known modules in dependency order; unknown modules go last
    def sort_key(p: Path) -> int:
        try:
            return MODULE_ORDER.index(p.stem)
        except ValueError:
            return len(MODULE_ORDER)
    return sorted(all_files, key=sort_key)


def pytest_generate_tests(metafunc):
    """Parametrize test_lint_file with each .v file."""
    if "verilog_file" in metafunc.fixturenames:
        files = get_generated_verilog_files()
        if files:
            metafunc.parametrize(
                "verilog_file",
                files,
                ids=[f.name for f in files],
            )
        else:
            metafunc.parametrize("verilog_file", [], ids=[])


def test_no_empty_generated_dir():
    """rtl/generated/ must contain at least one .v file."""
    files = get_generated_verilog_files()
    assert len(files) > 0, (
        f"No .v files found in {RTL_DIR}. "
        "Run 'python scripts/run_pipeline.py' to generate RTL first."
    )


def test_lint_file(verilog_file: Path):
    """Each .v file must pass Verilator lint-only."""
    all_files = get_generated_verilog_files()
    module_name = verilog_file.stem

    # Pass all other files (in order) before the current file
    other_files = [str(f) for f in all_files if f != verilog_file]

    cmd = [
        "verilator",
        "--lint-only",
        "-Wall",
        "--language", "1800-2012",
        "--top-module", module_name,
        "-Wno-fatal",
        "-Wno-PINCONNECTEMPTY",
        "-Wno-UNDRIVEN",
        "-Wno-UNUSED",
    ] + other_files + [str(verilog_file)]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
    )

    output = result.stdout + result.stderr
    errors = [line for line in output.splitlines() if "%Error" in line]

    assert result.returncode == 0 and not errors, (
        f"Lint FAILED for {verilog_file.name}:\n{output}"
    )
