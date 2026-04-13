#!/usr/bin/env python3
"""
Main entry point for the RAG-Driven RV32I RTL Generator.

Pipeline:
  1. Build RTL corpus (clone repos, embed with CodeBERT, store in ChromaDB)
  2. Build knowledge base (embed bug patterns + lessons with MiniLM)
  3. Generate 9 Verilog modules via LLM with lint-fix loop
  4. Compile with Verilator
  5. Run 42 ISA tests
  6. Write results/isa_results.md
"""

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Ensure repo root is importable
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("REPO_ROOT", str(REPO_ROOT))
os.environ.setdefault("HF_HOME", str(REPO_ROOT / "data" / "model_cache"))

from rag.corpus import build_corpus, CorpusUnavailableError
from rag.knowledge import build_knowledge_base
from rag.generator import generate_with_lint_fix, LintFailureError, MODULE_SPECS

# ── Module generation order and component mapping ─────────────────────────────

MODULE_ORDER = [
    "alu",
    "regfile",
    "decoder",
    "branch_unit",
    "lsu",
    "csr_unit",
    "hazard_unit",
    "pipeline_regs",
    "top",
]

COMPONENT_MAP: dict[str, str] = {
    "alu":          "alu",
    "regfile":      "regfile",
    "decoder":      "decoder",
    "branch_unit":  "alu",       # branch unit references ALU patterns
    "lsu":          "lsu",
    "csr_unit":     "full_core",
    "hazard_unit":  "hazard",
    "pipeline_regs":"full_core",
    "top":          "full_core",
}

RTL_DIR = REPO_ROOT / "rtl" / "generated"
SIM_DIR = REPO_ROOT / "sim"
OBJ_DIR = SIM_DIR / "obj_dir"
RESULTS = REPO_ROOT / "results"
GROQ_SLEEP_SECONDS = int(os.environ.get("GROQ_SLEEP_SECONDS", "45"))


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="RAG-Driven RV32I RTL Generator pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--skip-corpus",     action="store_true", help="Skip corpus build (use existing ChromaDB)")
    p.add_argument("--skip-knowledge",  action="store_true", help="Skip knowledge base build")
    p.add_argument("--skip-generation", action="store_true", help="Skip RTL generation")
    p.add_argument("--skip-sim",        action="store_true", help="Skip Verilator compilation")
    p.add_argument("--skip-tests",      action="store_true", help="Skip ISA tests")
    p.add_argument("--modules",         type=str, default=None,
                   help="Comma-separated list of modules to generate (default: all)")
    p.add_argument("--max-iterations",  type=int, default=1,
                   help="Lint-fix iterations per module (default: 1, Groq-only single-call mode)")
    p.add_argument("--force-rebuild",   action="store_true",
                   help="Force rebuild of ChromaDB collections")
    p.add_argument("--log-level",       default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                   help="Logging verbosity (default: INFO)")
    return p.parse_args()


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ── Step 1: Corpus ─────────────────────────────────────────────────────────────

def step_build_corpus(args) -> None:
    if args.skip_corpus:
        print("[SKIP] Corpus build (--skip-corpus)")
        return
    print("\n" + "=" * 60)
    print("STEP 1: Building RTL corpus")
    print("=" * 60)
    try:
        collection = build_corpus(force_rebuild=args.force_rebuild)
        print(f"  rtl_corpus: {collection.count()} documents")
    except CorpusUnavailableError as e:
        print(f"  WARNING: {e}")
        print("  Continuing without RTL context (generation will use knowledge base only).")


# ── Step 2: Knowledge base ─────────────────────────────────────────────────────

def step_build_knowledge(args) -> None:
    if args.skip_knowledge:
        print("[SKIP] Knowledge base build (--skip-knowledge)")
        return
    print("\n" + "=" * 60)
    print("STEP 2: Building knowledge base")
    print("=" * 60)
    collection = build_knowledge_base(force_rebuild=args.force_rebuild)
    print(f"  knowledge_corpus: {collection.count()} entries")


# ── Step 3: RTL generation ─────────────────────────────────────────────────────

def step_generate(args) -> list[Path]:
    """Generate all modules. Returns list of successfully generated file paths."""
    if args.skip_generation:
        print("[SKIP] RTL generation (--skip-generation)")
        # Return any already-existing files
        return sorted(RTL_DIR.glob("*.v"))

    print("\n" + "=" * 60)
    print("STEP 3: Generating RTL modules")
    print("=" * 60)

    # Determine which modules to generate
    if args.modules:
        requested = [m.strip() for m in args.modules.split(",")]
        modules_to_generate = [m for m in MODULE_ORDER if m in requested]
        unknown = set(requested) - set(MODULE_ORDER)
        if unknown:
            print(f"  WARNING: Unknown modules (will be skipped): {unknown}")
    else:
        modules_to_generate = list(MODULE_ORDER)

    RTL_DIR.mkdir(parents=True, exist_ok=True)
    accepted_files: list[Path] = []
    failed_modules: list[str] = []

    for module_name in modules_to_generate:
        component = COMPONENT_MAP.get(module_name, "full_core")
        print(f"\n  Generating {module_name}.v (component={component}) ...")

        try:
            verilog, filepath = generate_with_lint_fix(
                module_name=module_name,
                component=component,
                all_files=accepted_files,
                max_iterations=3,
            )
            accepted_files.append(filepath)
            print(f"  [OK] {module_name}.v generated and lint-clean")
        except LintFailureError as e:
            print(f"  [FAIL] {module_name}.v FAILED lint after {e.attempts} attempts:")
            for err in e.errors[:5]:
                print(f"      {err}")
            failed_modules.append(module_name)
            # Still include the file (best-effort) so later modules can reference it
            partial_path = RTL_DIR / f"{module_name}.v"
            if partial_path.exists():
                accepted_files.append(partial_path)
        except Exception as e:
            print(f"  [FAIL] {module_name}.v FAILED with exception: {e}")
            failed_modules.append(module_name)

        if module_name != modules_to_generate[-1]:
            print(f"  Sleeping {GROQ_SLEEP_SECONDS}s to respect Groq rate limits...")
            time.sleep(GROQ_SLEEP_SECONDS)

    print(f"\n  Generated: {len(accepted_files)} files")
    if failed_modules:
        print(f"  Failed (lint): {failed_modules}")

    return accepted_files


# ── Step 4: Verilator compilation ─────────────────────────────────────────────

def step_compile(generated_files: list[Path], args) -> bool:
    """Compile generated RTL with Verilator. Returns True if successful."""
    if args.skip_sim:
        print("[SKIP] Verilator compilation (--skip-sim)")
        return False

    print("\n" + "=" * 60)
    print("STEP 4: Compiling with Verilator")
    print("=" * 60)

    # Check verilator
    if not _check_tool("verilator"):
        print("  ERROR: verilator not found. sudo apt install verilator")
        return False

    # Order files by instantiation order
    order_map = {name: i for i, name in enumerate(MODULE_ORDER)}
    def file_order(p: Path) -> int:
        return order_map.get(p.stem, len(MODULE_ORDER))
    ordered_files = sorted(generated_files, key=file_order)

    if not ordered_files:
        print("  ERROR: No generated files to compile.")
        return False

    # Check top.v exists
    top_v = RTL_DIR / "top.v"
    if not top_v.exists():
        print("  ERROR: top.v not found — cannot compile.")
        return False

    OBJ_DIR.mkdir(parents=True, exist_ok=True)

    v_file_args = [str(f) for f in ordered_files]

    cmd = [
        "verilator",
        "--cc", "--exe",
        "--language", "1800-2012",
        "--top-module", "top",
        "-Wno-fatal", "-Wno-lint",
        "-CFLAGS", "-std=c++14",
        str(SIM_DIR / "sim_main.cpp"),
        "--Mdir", str(OBJ_DIR),
    ] + v_file_args

    print(f"  Running: verilator --cc --exe ... ({len(v_file_args)} .v files)")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))

    if result.returncode != 0:
        print(f"  ERROR: Verilator elaboration failed:\n{result.stderr[-2000:]}")
        return False

    print("  Verilator elaboration OK. Building sim binary...")
    make_cmd = ["make", "-j4", "-C", str(OBJ_DIR), "-f", "Vtop.mk", "Vtop"]
    result = subprocess.run(make_cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  ERROR: make failed:\n{result.stderr[-2000:]}")
        return False

    sim_bin = OBJ_DIR / "Vtop"
    print(f"  ✓ Simulation binary built: {sim_bin}")
    return True


# ── Step 5: ISA tests ──────────────────────────────────────────────────────────

def step_run_tests(args) -> dict[str, bool]:
    if args.skip_tests:
        print("[SKIP] ISA tests (--skip-tests)")
        return {}

    print("\n" + "=" * 60)
    print("STEP 5: Running ISA tests")
    print("=" * 60)

    result = subprocess.run(
        [sys.executable, str(SIM_DIR / "run_tests.py")],
        cwd=str(REPO_ROOT),
    )

    # Results are written to results/isa_results.md by run_tests.py
    return {}


# ── Step 6: Write summary ──────────────────────────────────────────────────────

def step_write_summary(
    generated_files: list[Path],
    compile_ok: bool,
) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    summary_lines = [
        "# Pipeline Run Summary",
        "",
        f"Generated modules: {len(generated_files)}",
        "",
        "| Module | File |",
        "|--------|------|",
    ]
    for f in generated_files:
        summary_lines.append(f"| {f.stem} | {f.name} |")
    summary_lines += [
        "",
        f"Verilator compile: {'OK' if compile_ok else 'FAILED'}",
        "",
        "See `results/isa_results.md` for ISA test results.",
        "See `results/generation_log.jsonl` for per-attempt generation log.",
    ]
    (RESULTS / "summary.md").write_text("\n".join(summary_lines) + "\n")
    print(f"\nSummary written to results/summary.md")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _check_tool(name: str) -> bool:
    import shutil
    return shutil.which(name) is not None


def _check_api_key() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY", ""))


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    args = parse_args()
    setup_logging(args.log_level)

    print("=" * 60)
    print("RAG-Driven RV32I RTL Generator")
    print("=" * 60)

    # Pre-flight checks
    if not args.skip_generation:
        if not _check_api_key():
            print("ERROR: No valid OpenRouter API key found.")
            print("       Set OPENROUTER_API_KEY in .env.")
            return 1

    if not _check_tool("verilator") and not args.skip_sim:
        print("WARNING: verilator not found in PATH.")
        print("         Install with: sudo apt install verilator")
        print("         (Continuing — will fail at compile step)")

    # Run pipeline steps
    step_build_corpus(args)
    step_build_knowledge(args)
    generated_files = step_generate(args)
    compile_ok = step_compile(generated_files, args)
    step_run_tests(args)
    step_write_summary(generated_files, compile_ok)

    print("\n" + "=" * 60)
    print("Pipeline complete.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
