import re
from typing import Callable, Pattern, Union

SIMULATION_RULES = {
    "top": [
        (r"mem\s*\[0:65535\]", "Memory must be 65536 words"),
        (r"\$readmemh", "Must have $readmemh"),
        (r"\$display.*PC=", "Must have $display for pass detection"),
        (r"id_ex_is_auipc.*id_ex_pc", "AUIPC must use PC not rs1"),
        (r"wb_sel.*<=.*_sel", "wb_sel must pipeline with data"),
        (r"ex_mem_funct3", "Must pipeline funct3 for LSU"),
        (
            lambda v: "3'b010" not in v.split(".mem_op")[1][:20] if ".mem_op" in v else True,
            "LSU mem_op must not be hardcoded 3'b010",
        ),
        # New Hardening Rules
        (r"alu_in_a.*1100111|id_ex_opcode", "JALR must use forwarded alu_in_a and id_ex_opcode check"),
        (r"branch_taken_ex", "PC mux must check branch_taken_ex"),
        (r"mem\[.*17:2\]", "Memory index must use pc[17:2] not pc[11:2] or pc[9:2]"),
    ],
    "decoder": [
        (r"branch_funct3.*inst[r]?\[14:12\]", "branch_funct3 must be instr[14:12]"),
        (r"7'b1110011", "Must handle CSR opcode"),
        (r"is_auipc", "Must output is_auipc flag"),
    ],
    "hazard_unit": [
        (r"branch_taken_ex", "Must use direct branch_taken_ex not registered"),
    ],
    "csr_unit": [
        (r"12'hF14.*32'h0|mhartid.*0", "mhartid must return 0"),
    ],
}

PatternOrCallable = Union[Pattern[str], Callable[[str], bool]]


def validate(verilog: str, module_name: str) -> list[str]:
    """Returns list of violation messages, empty = pass."""
    violations = []
    for rule in SIMULATION_RULES.get(module_name, []):
        pattern, message = rule
        if callable(pattern):
            if not pattern(verilog):
                violations.append(f"SEMANTIC FAIL: {message}")
        else:
            if not re.search(pattern, verilog, re.DOTALL):
                violations.append(f"SEMANTIC FAIL: {message}")
    return violations
