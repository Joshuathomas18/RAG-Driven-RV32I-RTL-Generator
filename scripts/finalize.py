import sys
import os
import argparse
import subprocess
from pathlib import Path

# Ensure repo root is importable
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ["REPO_ROOT"] = str(REPO_ROOT)

from scripts.run_pipeline import step_compile, step_run_tests, MODULE_ORDER, RTL_DIR, MODULE_SPECS
from rag.generator import generate_top_v

def finalize():
    print("============================================================")
    print("FINAL INTEGRATION: Generating top.v and running tests")
    print("============================================================")
    
    # 1. Collect fixed contracts
    print("  Collecting module contracts...")
    all_contracts = ""
    for prev in MODULE_ORDER:
        if prev == "top": continue
        meta_file = RTL_DIR / f"{prev}_meta.json"
        if meta_file.exists():
            all_contracts += f"\n--- {prev} CONTRACT ---\n{meta_file.read_text()}\n"
    
    # 3. Generate top.v (SKIPPED - use manual/fixed version)
    top_path = RTL_DIR / "top.v"
    if not top_path.exists():
        print("  ERROR: top.v not found!")
        return
    print("  [OK] Using existing top.v.")
    
    # 4. Compile and Test
    all_files = list(RTL_DIR.glob("*.v"))
    
    # Mock args for step_compile
    class Args:
        skip_sim = False
        skip_tests = False
    
    args = Args()
    
    if step_compile(all_files, args):
        step_run_tests(args)
    else:
        print("  [FAIL] Compilation failed. Check top.v wiring.")

if __name__ == "__main__":
    finalize()
