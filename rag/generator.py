"""
LLM-based Verilog generator with Verilator lint-fix feedback loop.
Uses claude-sonnet-4-6 via the Anthropic API.
"""

import json
import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv

from rag.pipeline import retrieve, query_knowledge

load_dotenv()

logger = logging.getLogger(__name__)

REPO_ROOT = Path(os.getenv("REPO_ROOT", Path(__file__).parent.parent))
RTL_DIR   = REPO_ROOT / "rtl" / "generated"
LOG_FILE  = REPO_ROOT / "results" / "generation_log.jsonl"

MODEL        = "claude-sonnet-4-6"
TEMPERATURE  = 0.05
MAX_TOKENS   = 6000


# ── Hardware contract (injected into every prompt) ─────────────────────────────

GLOBAL_CONTRACT = """
RV32I 5-Stage Pipeline Hardware Specification
==============================================

PIPELINE: 5-stage in-order RV32I: IF → ID → EX → MEM → WB
CLOCK: always @(posedge clk) if (rst) ... synchronous active-high reset
NON-BLOCKING: always use <= in clocked blocks, = in combinational

OPCODE CONSTANTS:
  RTYPE=7'b0110011  ITYPE=7'b0010011  LOAD=7'b0000011
  STORE=7'b0100011  BRANCH=7'b1100011 JAL=7'b1101111
  JALR=7'b1100111   LUI=7'b0110111    AUIPC=7'b0010111
  SYSTEM=7'b1110011 FENCE=7'b0001111

ALU_OP[3:0]: 0000=ADD 0001=SUB 0010=AND 0011=OR 0100=XOR
             0101=SLT 0110=SLTU 0111=SLL 1000=SRL 1001=SRA

WB_SEL[1:0]: 00=ALU 01=MEM 10=PC+4 11=CSR

PIPELINE REGISTER CONTRACT:
  IF/ID:  pc[31:0], instr[31:0]
  ID/EX:  pc, rs1_data, rs2_data, rs1_addr[4:0], rs2_addr[4:0],
          rd_addr[4:0], imm, alu_op[3:0], alu_src, mem_write, mem_read,
          wb_sel[1:0], reg_write, branch, jump, branch_funct3[2:0],
          is_auipc, pc_plus4[31:0]
  EX/MEM: alu_result, rs2_data, rd_addr, branch_target, branch_taken,
          mem_write, mem_read, wb_sel[1:0], reg_write, pc_plus4[31:0]
  MEM/WB: alu_result, load_data, rd_addr, reg_write, wb_sel[1:0], pc_plus4

MEM/WB register CRITICAL: alu_result, load_data, rd_addr, reg_write,
wb_sel[1:0], pc_plus4 MUST ALL update in the SAME always block.
Never register wb_sel or pc_plus4 separately from the data signals.

CRITICAL RULES:
1. ALU operand A = PC for AUIPC/JAL/BRANCH, rs1 otherwise
2. Branch type = funct3 directly, NOT alu_op bits
3. Pipeline rs1_addr/rs2_addr as separate 5-bit wires (not [4:0] of data)
4. Flush using branch_taken_ex (direct EX output), NOT registered signal
5. wb_sel travels inside pipeline register WITH its instruction
6. pc_plus4 pipelined all the way to MEM/WB for JAL writeback
7. Unified memory array (single reg[31:0] mem[0:65535]) for fence.i
8. CSR stub: mhartid=0, silent writes, wb_sel=2'b11
"""


# ── Module generation specifications ──────────────────────────────────────────

MODULE_SPECS: dict[str, str] = {
    "alu": """\
Generate a purely combinational Verilog module `alu` for RV32I.
Ports: input [31:0] a, b; input [3:0] alu_op; output reg [31:0] result; output zero.
Operations (per ALU_OP encoding in contract):
  ADD=0000, SUB=0001, AND=0010, OR=0011, XOR=0100,
  SLT=0101 ($signed comparison), SLTU=0110 (unsigned), SLL=0111, SRL=1000, SRA=1001.
Shift amount: b[4:0] only. Use $signed() for SLT and SRA. zero = (result == 0).
No clock needed. Single always@(*) block with default result=0.""",

    "regfile": """\
Generate a Verilog register file module `regfile` with 32 x 32-bit registers.
Ports: input clk; input [4:0] rs1, rs2, rd; input [31:0] wdata; input we;
       output [31:0] rdata1, rdata2.
Register x0 always reads as zero. Write is synchronous on posedge clk.
Gate write enable: only write when (we && rd != 5'd0).
Reads are combinational (wire assignments or always@(*)).
Async read: assign rdata1 = (rs1 == 0) ? 0 : regs[rs1];""",

    "decoder": """\
Generate a purely combinational instruction decoder module `decoder` for all 11 RV32I opcodes.
Ports: input [31:0] inst;
       output [4:0] rs1, rs2, rd;
       output [31:0] imm;
       output [3:0] alu_op;
       output alu_src;        // 0=rs2, 1=imm for ALU operand B
       output mem_read, mem_write;
       output [1:0] mem_size; // 00=byte 01=half 10=word
       output reg_write;
       output [1:0] wb_sel;   // 00=alu 01=mem 10=pc+4 11=csr
       output branch, jump;   // branch=BRANCH opcode, jump=JAL/JALR
       output is_auipc;       // AUIPC: ALU A must be PC
       output [2:0] branch_funct3; // inst[14:12] for branch comparator
Use a single always@(*) with defaults first, then case(inst[6:0]).
Handle all immediates (I/S/B/U/J types) with correct sign extension.
Handle all 11 opcodes: RTYPE, ITYPE, LOAD, STORE, BRANCH, JAL, JALR, LUI, AUIPC, SYSTEM, FENCE.""",

    "branch_unit": """\
Generate a combinational Verilog module `branch_unit` for branch and jump resolution.
Ports: input [31:0] pc, rs1, rs2, imm;
       input [2:0] funct3;   // branch type directly from decoder (NOT from alu_op)
       input is_branch;      // instruction is a conditional branch
       input is_jal;         // instruction is JAL
       input is_jalr;        // instruction is JALR
       output [31:0] branch_target;
       output branch_taken.
branch_target: BRANCH = pc + imm; JAL = pc + imm; JALR = (rs1 + imm) & ~32'h1.
branch_taken: only asserted for conditional branches when condition is met.
  funct3 comparison: BEQ=3'b000($eq), BNE=3'b001($ne), BLT=3'b100($signed<),
                     BGE=3'b101($signed>=), BLTU=3'b110(unsigned<), BGEU=3'b111(unsigned>=).
For JAL/JALR: branch_taken is always 1 when is_jal or is_jalr.
Use $signed() for BLT/BGE comparisons.""",

    "lsu": """\
Generate a Verilog load/store unit module `lsu` for RV32I memory access.
Ports: input mem_read, mem_write;
       input [1:0] mem_size;  // 00=byte 01=halfword 10=word
       input mem_signed;      // 1=sign-extend loads (LB/LH), 0=zero-extend (LBU/LHU)
       input [31:0] addr, wdata;
       input [31:0] mem_rdata;  // raw word from memory array
       output reg [31:0] rdata; // sign/zero extended load result
       output [31:0] mem_addr;  // word-aligned address to memory
       output [31:0] mem_wdata; // formatted write data
       output [3:0]  mem_be;    // byte enables for write
mem_addr = {addr[31:2], 2'b00} (word-aligned).
Byte lane: addr[1:0] selects byte within word.
Load: extract correct bytes from mem_rdata using addr[1:0], apply sign/zero extension.
Store: replicate wdata byte/half into correct lane, set mem_be accordingly.""",

    "csr_unit": """\
Generate a minimal CSR unit module `csr_unit` for RV32I simulation.
Ports: input clk, rst;
       input csr_we;           // write enable
       input [11:0] csr_addr;  // CSR address
       input [31:0] wdata;     // write data
       input [2:0] funct3;     // CSRRW/CSRRS/CSRRC
       output reg [31:0] rdata; // read data
       output ecall;           // ECALL detected
Implement these CSRs: mstatus(0x300), mtvec(0x305), mepc(0x341), mcause(0x342).
mhartid (0xF14): always returns 0, writes ignored.
All other CSR reads return 32'h0. All writes silently accepted.
ecall output: asserted for one cycle when SYSTEM opcode with funct3=3'b000 and rs1/rd=0.
Use synchronous reset. wb_sel=2'b11 for CSR instructions.""",

    "hazard_unit": """\
Generate a combinational hazard and forwarding unit module `hazard_unit`.
Ports:
  input  [4:0] id_ex_rs1, id_ex_rs2,        // source regs in EX stage (ADDRESSES)
  input  [4:0] ex_mem_rd, mem_wb_rd,         // dest regs in MEM/WB stages
  input        ex_mem_reg_write, mem_wb_reg_write,
  input        id_ex_mem_read,               // load-use hazard detection
  input  [4:0] if_id_rs1, if_id_rs2,        // source regs in ID stage
  input  [4:0] id_ex_rd,                     // EX stage destination register
  input        branch_taken_ex,              // DIRECT from EX (NOT registered)
  output reg   pc_write,                     // 0=stall PC
  output reg   if_id_write,                  // 0=stall IF/ID register
  output reg   id_ex_flush,                  // flush ID/EX (load-use bubble)
  output reg   if_id_flush,                  // flush IF/ID (branch taken)
  output reg [1:0] forward_a, forward_b      // 00=regfile 01=EX/MEM 10=MEM/WB
Forwarding priority: EX hazard > MEM hazard. Never forward from rd==0.
Load-use stall: id_ex_mem_read && id_ex_rd!=0 && (id_ex_rd==if_id_rs1 || id_ex_rd==if_id_rs2).
Branch flush: flush IF/ID and ID/EX on branch_taken_ex.""",

    "pipeline_regs": """\
Generate a Verilog module `pipeline_regs` containing all 4 pipeline registers for a 5-stage RV32I pipeline.
All resets are synchronous active-high.
Stall: hold current value (no update). Flush: set to NOP/zero.

IF/ID register: pc[31:0], instr[31:0]. Flush inserts NOP: instr <= 32'h00000013.
  Controls: stall_if_id (hold), flush_if_id (NOP).

ID/EX register: all fields from PIPELINE REGISTER CONTRACT ID/EX section.
  Controls: stall_id_ex (hold), flush_id_ex (zero all control signals).
  On flush: clear mem_read, mem_write, reg_write, branch, jump, is_auipc; keep data fields.

EX/MEM register: all fields from PIPELINE REGISTER CONTRACT EX/MEM section.
  Controls: flush_ex_mem.

MEM/WB register: alu_result, load_data, rd_addr, reg_write, wb_sel[1:0], pc_plus4.
  CRITICAL: ALL MEM/WB fields MUST update in the SAME always @(posedge clk) block.
  Never split wb_sel or pc_plus4 into a separate always block.

Use flat port list (no structs/interfaces for Verilator compatibility).
All pipeline register input/output port names must follow the pattern:
  if_* for IF/ID inputs, id_* for ID/EX inputs, ex_* for EX/MEM inputs, mem_* for MEM/WB inputs.""",

    "top": """\
Generate the top-level integration module `top` for a 5-stage RV32I processor.
Ports: input clk, rst. (No other external ports needed for simulation.)

Instantiate: alu, regfile, decoder, branch_unit, lsu, csr_unit, hazard_unit, pipeline_regs.

Memory: reg [31:0] mem [0:65535]; (word-addressed, unified instruction+data)
Initialize: initial $readmemh("mem_init.hex", mem);

PC register (exact priority order):
  always @(posedge clk) begin
    if (rst)                              pc <= 32'h0;
    else if (branch_taken_ex)            pc <= branch_target_ex;   // branch/JAL/JALR
    else if (id_ex_jump && !load_stall)  pc <= jump_target;
    else if (load_stall)                 pc <= pc;                 // stall
    else                                 pc <= pc + 4;
  end

Fetch: instr_fetch = mem[pc >> 2]; (register into IF/ID on next cycle)
Data memory: synchronous write, combinational read (use lsu outputs for byte enables).

ALU operand A mux: alu_a = (ex_is_auipc | ex_branch | ex_jump) ? ex_pc : forwarded_rs1;
Writeback mux: uses mem_wb_wb_sel: 00=alu_result 01=load_data 10=pc_plus4 11=csr_rdata.

Forwarding mux: apply forward_a/forward_b selectors to choose between
  regfile output, EX/MEM alu_result, MEM/WB writeback value.

Simulation display (required for test pass detection):
  always @(posedge clk) if (!rst) $display("PC=%08h INSTR=%08h", if_id_pc, if_id_instr);

Wire all submodules. Use descriptive wire names matching the pipeline register contract.""",
}


# ── Errors and logging ─────────────────────────────────────────────────────────

class LintFailureError(RuntimeError):
    def __init__(self, module_name: str, errors: list[str], attempts: int):
        self.module_name = module_name
        self.errors = errors
        self.attempts = attempts
        super().__init__(
            f"Module '{module_name}' failed lint after {attempts} attempts. "
            f"Last errors:\n" + "\n".join(errors[:10])
        )


def _log_attempt(
    module_name: str,
    attempt: int,
    lint_errors: list[str],
    token_count: int,
    success: bool,
) -> None:
    """Append JSON line to results/generation_log.jsonl."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "module_name": module_name,
        "attempt": attempt,
        "success": success,
        "lint_error_count": len(lint_errors),
        "lint_errors": lint_errors[:20],
        "token_count": token_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ── Verilog extraction ─────────────────────────────────────────────────────────

def _extract_verilog(response_text: str) -> str:
    """
    Extract Verilog code from an LLM response.
    Tries ```verilog ... ``` first, then ``` ... ```, then searches for 'module' keyword.
    """
    # Try ```verilog ... ```
    m = re.search(r"```verilog\s*(.*?)```", response_text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # Try ``` ... ```
    m = re.search(r"```\s*(.*?)```", response_text, re.DOTALL)
    if m:
        code = m.group(1).strip()
        if "module" in code:
            return code

    # Fall back: find 'module' keyword and take everything from there
    idx = response_text.find("module ")
    if idx != -1:
        return response_text[idx:].strip()

    raise ValueError("No Verilog code block found in LLM response")


# ── Core generation ────────────────────────────────────────────────────────────

def _format_rtl_context(rtl_docs: list[dict]) -> str:
    """Format RTL context documents for inclusion in prompt."""
    if not rtl_docs:
        return "No RTL reference context available."
    parts = []
    for i, doc in enumerate(rtl_docs, 1):
        meta = doc.get("metadata", {})
        source = meta.get("source", "unknown")
        module_name = meta.get("module_name", "unknown")
        parts.append(f"--- Reference {i}: {module_name} (from {source}) ---\n{doc['document']}")
    return "\n\n".join(parts)


def _format_knowledge_context(knowledge_docs: list[dict]) -> str:
    """Format knowledge context for inclusion in prompt."""
    if not knowledge_docs:
        return "No knowledge context available."
    parts = []
    for doc in knowledge_docs:
        meta = doc.get("metadata", {})
        title = meta.get("title", "")
        parts.append(f"[{title}]\n{doc['document']}")
    return "\n\n".join(parts)


def generate_module(
    module_name: str,
    spec: str,
    rtl_context: list[dict],
    knowledge_context: list[dict],
) -> tuple[str, int]:
    """
    Call claude-sonnet-4-6 to generate a Verilog module.
    Returns (verilog_string, total_token_count).
    """
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    rtl_ctx_text = _format_rtl_context(rtl_context)
    know_ctx_text = _format_knowledge_context(knowledge_context)

    user_prompt = f"""\
Generate the Verilog module: {module_name}

SPECIFICATION:
{spec}

REFERENCE RTL (use for interface and implementation patterns):
{rtl_ctx_text}

RELEVANT BUG PATTERNS AND LESSONS (avoid these mistakes):
{know_ctx_text}

Requirements:
- Return ONLY the complete Verilog module code in a ```verilog code block.
- No explanations before or after the code block.
- The module must be self-contained and pass Verilator lint.
- Use localparams for all opcode/alu_op constants (no `define).
- Follow ALL rules in the hardware contract exactly.
"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=GLOBAL_CONTRACT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    response_text = response.content[0].text
    token_count = response.usage.input_tokens + response.usage.output_tokens

    verilog = _extract_verilog(response_text)
    return verilog, token_count


def lint_check(filepath: Path, all_files: list[Path]) -> list[str]:
    """
    Run Verilator lint-only on filepath plus all_files for cross-module resolution.
    For non-top modules, suppress unconnected port warnings.
    Returns list of error/warning lines. Empty list = clean.
    """
    module_name = filepath.stem

    # Order: all prior accepted files first, then the current file
    other_files = [str(f) for f in all_files if f != filepath and f.exists()]
    cmd = [
        "verilator",
        "--lint-only",
        "-Wall",
        "--language", "1800-2012",
        f"--top-module", module_name,
        "-Wno-fatal",
    ]

    # Suppress unconnected warnings for intermediate modules (not top)
    if module_name != "top":
        cmd += ["-Wno-PINCONNECTEMPTY", "-Wno-UNDRIVEN", "-Wno-UNUSED"]

    cmd += other_files + [str(filepath)]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout + result.stderr
        error_lines = [
            line for line in output.splitlines()
            if "%Error" in line or "%Warning" in line
        ]
        return error_lines
    except FileNotFoundError:
        logger.warning("verilator not found in PATH. Skipping lint check.")
        return []
    except subprocess.TimeoutExpired:
        return ["%Error: verilator lint timed out"]


def fix_with_feedback(
    module_name: str,
    verilog: str,
    errors: list[str],
    spec: str,
) -> tuple[str, int]:
    """
    Feed broken Verilog + Verilator error output back to LLM for correction.
    Returns (fixed_verilog, token_count).
    """
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    error_text = "\n".join(errors)
    fix_prompt = f"""\
The Verilog module `{module_name}` failed Verilator lint with these errors:

VERILATOR ERRORS:
{error_text}

ORIGINAL SPECIFICATION:
{spec}

BROKEN CODE:
```verilog
{verilog}
```

Fix ALL lint errors while:
1. Preserving the exact module interface (port names and widths).
2. Following all rules in the hardware contract.
3. Not changing correct logic — only fix what Verilator complained about.

Return ONLY the corrected complete Verilog module in a ```verilog code block.
"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=GLOBAL_CONTRACT,
        messages=[{"role": "user", "content": fix_prompt}],
    )

    response_text = response.content[0].text
    token_count = response.usage.input_tokens + response.usage.output_tokens
    verilog = _extract_verilog(response_text)
    return verilog, token_count


# ── Main generation loop ───────────────────────────────────────────────────────

def generate_with_lint_fix(
    module_name: str,
    component: str,
    all_files: list[Path],
    max_iterations: int = 5,
    spec: Optional[str] = None,
) -> tuple[str, Path]:
    """
    Full generation loop with lint-fix feedback:
    1. Retrieve RTL context and knowledge context.
    2. Generate module via LLM.
    3. Save to rtl/generated/{module_name}.v
    4. Lint check.
    5. If errors: fix_with_feedback → overwrite file → repeat lint.
    6. Return (final_verilog, filepath) on success.
    7. Raise LintFailureError if still failing after max_iterations.

    Logs every attempt to results/generation_log.jsonl.
    """
    if spec is None:
        spec = MODULE_SPECS.get(module_name, f"Generate Verilog module {module_name} for RV32I pipeline.")

    RTL_DIR.mkdir(parents=True, exist_ok=True)
    filepath = RTL_DIR / f"{module_name}.v"

    logger.info("Generating module: %s (component=%s)", module_name, component)

    # Retrieve context
    rtl_context = retrieve(component, spec)
    knowledge_context = query_knowledge(spec)
    logger.debug("Retrieved %d RTL docs, %d knowledge docs", len(rtl_context), len(knowledge_context))

    # Initial generation
    verilog, tokens = generate_module(module_name, spec, rtl_context, knowledge_context)
    filepath.write_text(verilog)
    logger.info("Generated %s (%d tokens)", module_name, tokens)

    last_errors: list[str] = []
    for attempt in range(1, max_iterations + 1):
        errors = lint_check(filepath, all_files)
        success = len(errors) == 0

        _log_attempt(
            module_name=module_name,
            attempt=attempt,
            lint_errors=errors,
            token_count=tokens,
            success=success,
        )

        if success:
            logger.info("[OK] %s lint PASS (attempt %d)", module_name, attempt)
            return verilog, filepath

        last_errors = errors
        logger.info("  %s attempt %d: %d lint issues — fixing...", module_name, attempt, len(errors))
        for e in errors[:5]:
            logger.debug("    %s", e)

        if attempt < max_iterations:
            verilog, tokens = fix_with_feedback(module_name, verilog, errors, spec)
            filepath.write_text(verilog)

    raise LintFailureError(module_name, last_errors, max_iterations)
