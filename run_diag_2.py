from pathlib import Path
import subprocess

elf = Path("c:/Users/User/Desktop/Hackathon/PROJECTS/RSV/data/riscv-tests/isa/rv32ui-p-add")

print(f"Using {elf}")

# Run Verilator!
subprocess.run(["docker", "exec", "-w", "/app/sim", "ab09dec6aa83", "make", "-f", "Vtop.mk", "Vtop"], check=True)

# Run first 40 cycles
cmd = f"docker exec ab09dec6aa83 bash -c '/app/sim/obj_dir/Vtop /app/data/riscv-tests/isa/rv32ui-p-add | head -n 40'"
subprocess.run(cmd, shell=True)
