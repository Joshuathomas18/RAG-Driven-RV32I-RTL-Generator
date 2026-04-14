import os
import subprocess
from pathlib import Path

GEN_DIR = Path("rtl/generated")
GT_DIR = Path("data/pipelined-rv32i/rtl")
OUT_FILE = Path("results/ground_truth_comparison.md")

FILES = [
    "alu.v", "regfile.v", "decoder.v", "branch_unit.v", 
    "lsu.v", "csr_unit.v", "hazard_unit.v", "top.v"
]

import difflib

def get_diff(f1, f2):
    if not f1.exists() or not f2.exists():
        return "File missing"
    with open(f1, 'r') as h1, open(f2, 'r') as h2:
        diff = difflib.unified_diff(
            h1.readlines(), h2.readlines(), 
            fromfile=str(f1), tofile=str(f2)
        )
        return "".join(diff)

def main():
    report = ["# Ground Truth Comparison Report", ""]
    report.append("| Module | Status | Category | Notes |")
    report.append("|--------|--------|----------|-------|")
    
    for f in FILES:
        gen_path = GEN_DIR / f
        gt_path = GT_DIR / f
        
        status = "DIFF"
        category = "TBD"
        notes = ""
        
        if not gt_path.exists():
            status = "No GT"
            notes = f"Reference file {f} not found in GT repo"
        elif not gen_path.exists():
            status = "Missing"
            notes = "Generated file missing"
        else:
            diff_text = get_diff(gen_path, gt_path)
            if not diff_text:
                status = "MATCH"
                category = "cosmetic"
            else:
                status = "DIFF"
                # Preliminary analysis (manual check needed for actual category)
                notes = f"Lines: {len(diff_text.splitlines())}"
        
        report.append(f"| {f} | {status} | {category} | {notes} |")
    
    OUT_FILE.write_text("\n".join(report) + "\n")
    print(f"Comparison summary written to {OUT_FILE}")

if __name__ == "__main__":
    main()
