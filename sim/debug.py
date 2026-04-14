import os
import sys
from pathlib import Path
from run_tests import elf_to_hex
import subprocess

def debug_one(test_name):
    elf = Path(f"/app/data/riscv-tests/isa/{test_name}")
    hex_out = Path("mem_init.hex")
    print(f"Generating hex for {test_name}...")
    if not elf_to_hex(elf, hex_out):
        print("Failed to generate hex")
        return

    print("Running simulation...")
    proc = subprocess.Popen(["./obj_dir/Vtop"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    count = 0
    for line in proc.stdout:
        print(line.strip())
        count += 1
        if count >= 200:
            break
    proc.terminate()

if __name__ == "__main__":
    debug_one("rv32ui-p-add")
