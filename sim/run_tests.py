#!/usr/bin/env python3
"""
ISA test runner for 42 rv32ui-p-* riscv-tests.

Pass detection: parse $display("PC=%08h INSTR=%08h", ...) output from top.v.
A test passes when instruction 0x0000006f (JAL x0,0 — infinite loop) is
observed at the same PC for >100 consecutive cycles.

ELF-to-hex: uses riscv64-unknown-elf-objcopy -O verilog --verilog-data-width=4,
then Python-remaps addresses from 0x80000000 to 0x00000000.
"""

import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).parent.parent
OBJ_DIR   = REPO_ROOT / "sim" / "obj_dir"
SIM_BIN   = OBJ_DIR / "Vtop"
RTL_GEN   = REPO_ROOT / "rtl" / "generated"
HEX_FILE  = RTL_GEN / "mem_init.hex"
RESULTS   = REPO_ROOT / "results"

PASS_INSTR      = 0x0000006F   # JAL x0,0
PASS_MIN_CYCLES = 100          # consecutive cycles to confirm pass
MEMORY_WORDS    = 65536        # 256KB
NOP_WORD        = 0x00000013   # ADDI x0,x0,0
BASE_ADDR       = 0x80000000   # riscv-tests load address

# ── 42 test names ──────────────────────────────────────────────────────────────

RV32UI_TESTS = [
    "add", "addi", "and", "andi", "auipc",
    "beq", "bge", "bgeu", "blt", "bltu", "bne",
    "fence_i",
    "jal", "jalr",
    "lb", "lbu", "lh", "lhu", "lui", "lw",
    "or", "ori",
    "sb", "sh", "simple",
    "sll", "slli",
    "slt", "slti", "sltiu", "sltu",
    "sra", "srai", "srl", "srli",
    "sub", "sw",
    "xor", "xori",
    # Additional
    "ma_data",
    "ebreak",
    "ecall",
]

assert len(RV32UI_TESTS) == 42, f"Expected 42 tests, got {len(RV32UI_TESTS)}"


# ── riscv-tests location ───────────────────────────────────────────────────────

def find_riscv_tests_dir() -> Optional[Path]:
    """
    Search for riscv-tests ELF directory in priority order:
    1. $RISCV_TESTS_PATH env var
    2. Common install paths
    3. Repo-local data/riscv-tests/isa/
    Returns the directory containing rv32ui-p-add, or None.
    """
    probe_file = "rv32ui-p-add"

    candidates = []
    env_path = os.environ.get("RISCV_TESTS_PATH")
    if env_path:
        candidates.append(Path(env_path))

    candidates += [
        Path("/usr/share/riscv-tests/isa"),
        Path("/opt/riscv/share/riscv-tests/isa"),
        Path("/opt/riscv-tests/isa"),
        REPO_ROOT / "data" / "riscv-tests" / "isa",
    ]

    for candidate in candidates:
        if (candidate / probe_file).exists():
            return candidate

    return None


def try_clone_riscv_tests() -> Optional[Path]:
    """
    Clone riscv-tests from GitHub (precompiled ELFs are in isa/).
    Returns isa/ directory on success, None on failure.
    """
    dest = REPO_ROOT / "data" / "riscv-tests"
    isa_dir = dest / "isa"

    if isa_dir.exists() and (isa_dir / "rv32ui-p-add").exists():
        return isa_dir

    print("Cloning riscv-tests (precompiled ELFs in isa/)...")
    try:
        subprocess.run(
            ["git", "clone", "--depth=1",
             "https://github.com/riscv-software-src/riscv-tests.git",
             str(dest)],
            check=True,
            timeout=120,
        )
        if isa_dir.exists() and (isa_dir / "rv32ui-p-add").exists():
            return isa_dir
        print("WARNING: cloned riscv-tests but rv32ui-p-add not found in isa/")
        return None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        print(f"ERROR: failed to clone riscv-tests: {e}")
        return None


# ── ELF to hex conversion ──────────────────────────────────────────────────────

def _parse_verilog_hex(hex_text: str) -> dict[int, int]:
    """
    Parse objcopy -O verilog output into {byte_address: byte_value} dict.
    Format: @XXXXXXXX followed by space-separated byte values (little-endian within word).
    """
    memory: dict[int, int] = {}
    current_addr = 0

    for line in hex_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("@"):
            current_addr = int(line[1:], 16)
        else:
            for byte_str in line.split():
                memory[current_addr] = int(byte_str, 16)
                current_addr += 1

    return memory


def elf_to_hex(elf_path: Path, hex_out: Path, base_addr: int = BASE_ADDR) -> bool:
    """
    Convert an ELF to a $readmemh-compatible hex file (one 32-bit word per line).

    Process:
    1. Run objcopy -O verilog --verilog-data-width=4 to get a verilog hex dump.
    2. Parse the dump into a byte-addressed dict.
    3. Remap addresses: subtract base_addr.
    4. Build a 65536-word array, defaulting to NOP (0x00000013).
    5. Write one 8-hex-digit word per line (little-endian byte order per RV32I).
    """
    if not shutil.which("riscv64-unknown-elf-objcopy"):
        print("ERROR: riscv64-unknown-elf-objcopy not found in PATH")
        return False

    with tempfile.NamedTemporaryFile(suffix=".hex", delete=False) as tmp:
        tmp_hex = Path(tmp.name)

    try:
        result = subprocess.run(
            [
                "riscv64-unknown-elf-objcopy",
                "-O", "verilog",
                "--verilog-data-width=4",
                str(elf_path),
                str(tmp_hex),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"ERROR: objcopy failed: {result.stderr}")
            return False

        hex_text = tmp_hex.read_text()

    finally:
        tmp_hex.unlink(missing_ok=True)

    # Parse verilog hex format
    byte_memory = _parse_verilog_hex(hex_text)

    # Remap: subtract base_addr
    remapped: dict[int, int] = {}
    for addr, val in byte_memory.items():
        new_addr = addr - base_addr
        if 0 <= new_addr < MEMORY_WORDS * 4:
            remapped[new_addr] = val

    # Build word array (little-endian: byte 0 is LSB)
    words = [NOP_WORD] * MEMORY_WORDS
    for byte_addr, byte_val in remapped.items():
        word_idx = byte_addr >> 2
        byte_lane = byte_addr & 3
        if 0 <= word_idx < MEMORY_WORDS:
            words[word_idx] = (words[word_idx] & ~(0xFF << (byte_lane * 8))) | (byte_val << (byte_lane * 8))

    # Write one word per line (8 hex digits)
    hex_out.parent.mkdir(parents=True, exist_ok=True)
    with open(hex_out, "w") as f:
        for word in words:
            f.write(f"{word:08x}\n")

    return True


# ── Simulation and pass detection ─────────────────────────────────────────────

def detect_pass(output: str, timeout_occurred: bool) -> bool:
    """
    Parse $display output from top.v (format: "PC=XXXXXXXX INSTR=YYYYYYYY").
    PASS = see instruction 0x0000006f at the same PC for >PASS_MIN_CYCLES
    consecutive samples (JAL x0,0 — stable infinite loop).
    """
    if timeout_occurred:
        return False

    pc_instr_re = re.compile(r"PC=([0-9a-fA-F]{8})\s+INSTR=([0-9a-fA-F]{8})")
    consecutive = 0
    last_pc: Optional[str] = None
    last_instr: Optional[str] = None

    for m in pc_instr_re.finditer(output):
        pc_str, instr_str = m.group(1), m.group(2)
        instr_val = int(instr_str, 16)

        if instr_val == PASS_INSTR and pc_str == last_pc and instr_str == last_instr:
            consecutive += 1
            if consecutive >= PASS_MIN_CYCLES:
                return True
        else:
            consecutive = 1
            last_pc = pc_str
            last_instr = instr_str

    return False


def run_test(
    test_name: str,
    elf_path: Path,
    timeout: int = 30,
) -> tuple[bool, str]:
    """
    Convert ELF, write mem_init.hex, run simulation, parse output.
    Returns (passed, output_text).
    """
    if not SIM_BIN.exists():
        return False, f"Simulation binary not found: {SIM_BIN}"

    # Convert ELF to hex
    if not elf_to_hex(elf_path, HEX_FILE):
        return False, f"elf_to_hex failed for {test_name}"

    # Run simulation binary
    try:
        result = subprocess.run(
            [str(SIM_BIN)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(RTL_GEN),  # mem_init.hex is relative to RTL_GEN
        )
        output = result.stdout + result.stderr
        timed_out = False
    except subprocess.TimeoutExpired as e:
        output = (e.stdout or "") + (e.stderr or "")
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        timed_out = True

    passed = detect_pass(output, timed_out)
    return passed, output


# ── Test runner ────────────────────────────────────────────────────────────────

def run_all_tests(isa_dir: Path) -> dict[str, bool]:
    """
    Run all 42 rv32ui-p-* tests. Skip tests whose ELF doesn't exist.
    Returns dict[test_name → passed].
    """
    results: dict[str, bool] = {}
    passed_count = 0
    failed_count = 0
    skipped_count = 0

    for test_name in RV32UI_TESTS:
        elf_path = isa_dir / f"rv32ui-p-{test_name}"
        if not elf_path.exists():
            print(f"  SKIP  rv32ui-p-{test_name} (ELF not found)")
            results[test_name] = False
            skipped_count += 1
            continue

        passed, output = run_test(test_name, elf_path)
        results[test_name] = passed

        if passed:
            print(f"  PASS  rv32ui-p-{test_name}")
            passed_count += 1
        else:
            print(f"  FAIL  rv32ui-p-{test_name}")
            failed_count += 1

    total = len(RV32UI_TESTS)
    print(f"\nResults: {passed_count}/{total} passed "
          f"({failed_count} failed, {skipped_count} skipped)")
    return results


def write_results_md(results: dict[str, bool]) -> None:
    """Write results/isa_results.md with pass/fail table."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    passed = sum(1 for v in results.values() if v)
    total = len(results)

    lines = [
        "# ISA Test Results",
        "",
        f"**Score: {passed}/{total}**",
        "",
        "| Test | Result |",
        "|------|--------|",
    ]
    for test_name in RV32UI_TESTS:
        status = "PASS" if results.get(test_name) else "FAIL"
        lines.append(f"| rv32ui-p-{test_name} | {status} |")

    (RESULTS / "isa_results.md").write_text("\n".join(lines) + "\n")
    print(f"Results written to results/isa_results.md")


def main() -> int:
    print("=" * 60)
    print("RV32I ISA Test Runner")
    print("=" * 60)

    # Find riscv-tests
    isa_dir = find_riscv_tests_dir()
    if isa_dir is None:
        print("riscv-tests not found locally. Attempting clone...")
        isa_dir = try_clone_riscv_tests()

    if isa_dir is None:
        print(
            "\nERROR: Cannot find riscv-tests ELF binaries.\n"
            "Options:\n"
            "  1. sudo apt install riscv-tests (if available)\n"
            "  2. Set RISCV_TESTS_PATH=/path/to/riscv-tests/isa\n"
            "  3. Ensure network access for auto-clone\n"
        )
        return 1

    print(f"Using riscv-tests from: {isa_dir}")
    print()

    if not SIM_BIN.exists():
        print(
            f"ERROR: Simulation binary not found at {SIM_BIN}\n"
            "Run 'python scripts/run_pipeline.py' first to compile the processor."
        )
        return 1

    results = run_all_tests(isa_dir)
    write_results_md(results)

    passed = sum(1 for v in results.values() if v)
    return 0 if passed == len(RV32UI_TESTS) else 1


if __name__ == "__main__":
    sys.exit(main())
