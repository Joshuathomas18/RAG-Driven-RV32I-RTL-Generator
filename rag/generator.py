"""
LLM-based Verilog generator with Verilator lint-fix feedback loop.
Uses OpenRouter OpenAI-compatible chat completions API.
"""

import json
import logging
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from rag.pipeline import retrieve, query_knowledge
from rag.validator import validate
from rag.corpus import DEFINES_CONTEXT

load_dotenv()

logger = logging.getLogger(__name__)

REPO_ROOT = Path(os.getenv("REPO_ROOT", Path(__file__).parent.parent))
RTL_DIR   = REPO_ROOT / "rtl" / "generated"
LOG_FILE  = REPO_ROOT / "results" / "generation_log.jsonl"

MODEL        = "llama-3.3-70b-versatile"
TEMPERATURE  = 0.05
MAX_TOKENS   = 6000

DOCKER_ID = "ab09dec6aa83"  # Target container for Verilator
DOCKER_APP_DIR = "/app"


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

CRITICAL SIMULATION LESSONS (MUST FOLLOW):
=========================================

1. MEMORY SIZE: Use reg [31:0] mem [0:65535]; (65536 words = 256KB)
   Access: mem[addr[17:2]] for word-aligned access. Never smaller arrays.

2. ALU OPERAND A: For AUIPC/JAL/BRANCH, operand A = PC, not rs1.
   Code: alu_in_a = id_ex_is_auipc ? id_ex_pc : id_ex_rs1_data;

3. BRANCH FUNCT3: branch_unit receives instr[14:12] directly as branch_funct3.
   Never derive from alu_op bits. branch_funct3 = instr[14:12].

4. FORWARDING REGISTERS: hazard_unit inputs are rs1_addr[4:0], rs2_addr[4:0]
   (register ADDRESSES). Never use rs1_data[4:0] (would be wrong bits).

5. BRANCH FLUSH TIMING: Use branch_taken_ex (combinational from EX stage).
   Never use ex_mem_branch_taken (registered, 1 cycle late).

6. JAL WRITEBACK: JAL writes PC+4 to rd. Pipeline pc_plus4 through ALL stages.
   wb_sel=2'b10 selects pc_plus4 in MEM/WB stage.

7. WB_SEL TIMING: wb_sel travels in SAME pipeline register as its data.
   Pipeline chain: id_ex_wb_sel -> ex_mem_wb_sel -> mem_wb_wb_sel.
   Never register wb_sel or pc_plus4 in separate always blocks or skip stages.

8. CSR MHARTID: Always return 32'h0 for mhartid (0xF14). Core crashes otherwise.

9. LSU MEM_OP: LSU receives funct3[2:0] for load/store size (NOT hardcoded).
   Pipeline ex_mem_funct3 through EX/MEM register. Connect to LSU mem_op.

10. MEMORY INITIALIZATION: $readmemh("mem_init.hex", mem); in top.v
    File contains 65536 lines of 8-hex-digit words (NOPs by default).

11. PASS DETECTION: Include $display("PC=%08h INSTR=%08h", if_id_pc, if_id_instr);
    Required for test pass detection (JAL-self-loop at stable PC).

12. REGISTER ADDRESSES: Pipeline rs1_addr/rs2_addr as separate [4:0] wires.
    Distinct from rs1_data/rs2_data [31:0]. Hazard unit uses addresses.
""" + f"\n\nDEFINED ENUMS:\n{DEFINES_CONTEXT}\n"



# ── Simulation Validation Functions ───────────────────────────────────────────

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
Ports: input [31:0] instr;
       output [4:0] rs1, rs2, rd;
       output [31:0] imm;
       output [3:0] alu_op;
       output alu_src;        // 0=rs2, 1=imm for ALU operand B
       output mem_read, mem_write;
       output [1:0] mem_size; // 00=byte 01=halfword 10=word (funct3[1:0])
       output reg_write;
       output [1:0] wb_sel;   // 00=alu 01=mem 10=pc+4 11=csr
       output branch, jump;   // branch=BRANCH opcode, jump=JAL/JALR
       output is_auipc;       // AUIPC: ALU A must be PC
       output [2:0] branch_funct3; // instr[14:12] for branch comparator
       output [2:0] funct3;   // instr[14:12] for load/store operations (LSU mem_op)
       output csr_en;         // SYSTEM opcode detected
       output [11:0] csr_addr;// instr[31:20] for CSR operations
       output [2:0] csr_op;   // instr[14:12] for CSR operations
       output [31:0] csr_wdata; // CSR write data (rs1 or immediate)
Use a single always@(*) with defaults first, then case(instr[6:0]).
Handle all immediates (I/S/B/U/J types) with correct sign extension.
Handle all 11 opcodes: RTYPE, ITYPE, LOAD, STORE, BRANCH, JAL, JALR, LUI, AUIPC, SYSTEM, FENCE.
CRITICAL: Output funct3 = instr[14:12] for LSU mem_op (load/store size control).
CRITICAL: Output branch_funct3 = instr[14:12] for branch resolution.""",

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
       input [2:0] mem_op;    // funct3 from instruction: 000=LB/SB 001=LH/SH 010=LW/SW 100=LBU 101=LHU
       input [31:0] addr, wdata;
       input [31:0] mem_rdata;  // raw word from memory array
       output reg [31:0] rdata; // sign/zero extended load result
       output [31:0] mem_addr;  // word-aligned address to memory
       output [31:0] mem_wdata; // formatted write data
       output [3:0]  mem_be;    // byte enables for write
CRITICAL: mem_op determines operation size - NOT hardcoded!
mem_addr = {addr[31:2], 2'b00} (word-aligned).
Byte lane: addr[1:0] selects byte within word.
Load: extract correct bytes from mem_rdata using addr[1:0] and mem_op, apply sign/zero extension.
Store: replicate wdata byte/half into correct lane, set mem_be accordingly.
mem_op[1:0]: 00=byte 01=halfword 10=word
mem_op[2]: 0=sign-extend loads 1=zero-extend loads (LBU/LHU only)
Store: replicate wdata byte/half into correct lane, set mem_be accordingly.
""",

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

EX/MEM register: all fields from PIPELINE REGISTER CONTRACT EX/MEM section PLUS ex_funct3[2:0].
  CRITICAL: Include ex_mem_funct3 for LSU mem_op control.
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

Memory: reg [31:0] mem [0:65535]; (word-addressed, unified instruction+data, 256KB)
Initialize: initial $readmemh("mem_init.hex", mem);

PC register (exact priority order):
  always @(posedge clk) begin
    if (rst)                              pc <= 32'h0;
    else if (branch_taken_ex)            pc <= branch_target_ex;   // branch/JAL/JALR
    else if (id_ex_jump && !load_stall)  pc <= jump_target;
    else if (load_stall)                 pc <= pc;                 // stall
    else                                 pc <= pc + 4;
  end

Fetch: instr_fetch = mem[pc[17:2]]; (word-aligned access to 256KB memory)
Data memory: synchronous write, combinational read (use lsu outputs for byte enables).

CRITICAL ALU operand A mux: alu_a = id_ex_is_auipc ? id_ex_pc : id_ex_rs1_data;
CRITICAL LSU mem_op: .mem_op(ex_mem_funct3)  // NOT hardcoded 3'b010!

Writeback mux: uses mem_wb_wb_sel: 00=alu_result 01=load_data 10=pc_plus4 11=csr_rdata.

Forwarding mux: apply forward_a/forward_b selectors to choose between
  regfile output, EX/MEM alu_result, MEM/WB writeback value.

CRITICAL: Pipeline ex_mem_funct3 through EX/MEM register for LSU mem_op control.

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
    semantic_errors: list[str],
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
        "semantic_error_count": len(semantic_errors),
        "lint_errors": lint_errors[:20],
        "semantic_errors": semantic_errors[:20],
        "token_count": token_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _normalize_verilog_text(verilog: str) -> str:
    """Ensure every generated Verilog file ends with a single newline."""
    return verilog.rstrip("\r\n") + "\n"


def _call_groq_api(system: str, messages: list[dict], model: str) -> tuple[str, int]:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
        ] + messages,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "python-groq-client/1.0",
    }
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(request, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            payload = exc.read().decode("utf-8")
        except Exception:
            payload = ""
        raise RuntimeError(
            f"Groq API request failed: {exc.code} {exc.reason}. Response body: {payload}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Groq API request failed: {exc.reason}") from exc

    choices = body.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        message = first.get("message", {})
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            token_count = body.get("usage", {}).get("total_tokens", 0)
            return message["content"], token_count

    raise RuntimeError(f"Unexpected Groq API response format: {body}")


def _call_openrouter_api(system: str, messages: list[dict], model: str) -> tuple[str, int]:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    url = "https://openrouter.ai/api/v1/chat/completions"
    payload = {
        "model": os.environ.get("OPENROUTER_MODEL", "gpt-4o-mini"),
        "messages": [
            {"role": "system", "content": system},
        ] + messages,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "HTTP-Referer": "https://github.com/google-deepmind/antigravity",
        "X-Title": "Antigravity RTL Generator",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(request, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            payload = exc.read().decode("utf-8")
        except Exception:
            payload = ""
        raise RuntimeError(
            f"OpenRouter API request failed: {exc.code} {exc.reason}. Response body: {payload}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenRouter API request failed: {exc.reason}") from exc

    choices = body.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        message = first.get("message", {})
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            token_count = body.get("usage", {}).get("total_tokens", 0)
            return message["content"], token_count

    raise RuntimeError(f"Unexpected OpenRouter API response format: {body}")


def _call_llm(system: str, messages: list[dict], model: str) -> tuple[str, int]:
    if os.environ.get("OPENROUTER_API_KEY"):
        return _call_openrouter_api(system, messages, model)
    raise RuntimeError("OPENROUTER_API_KEY not set. OpenRouter is required for generation.")


# ── Extraction Utils ───────────────────────────────────────────────────────────

def _extract_verilog(response_text: str) -> str:
    """
    Extract Verilog code from an LLM response.
    Tries ```verilog ... ``` first, then ``` ... ```, then searches for 'module' keyword.
    """
    m = re.search(r"```verilog\s*(.*?)```", response_text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()

    m = re.search(r"```\s*(.*?)```", response_text, re.DOTALL)
    if m:
        code = m.group(1).strip()
        if "module" in code:
            return code

    idx = response_text.find("module ")
    if idx != -1:
        return response_text[idx:].strip()

    raise ValueError("No Verilog code block found in LLM response")


def _extract_json(response_text: str) -> dict:
    """Extract a JSON block from an LLM response."""
    m = re.search(r"```json\s*(.*?)```", response_text, re.DOTALL | re.IGNORECASE)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try raw JSON finding
    m = re.search(r"\{.*\}", response_text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0).strip())
        except json.JSONDecodeError:
            pass

    return {}


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
    Call Groq to generate a Verilog module.
    Returns (verilog_string, total_token_count).
    """

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

    response_text, token_count = _call_llm(
        system=GLOBAL_CONTRACT,
        messages=[{"role": "user", "content": user_prompt}],
        model=MODEL,
    )

    verilog = _extract_verilog(response_text)
    return verilog, token_count


def generate_module_v(
    module_name: str,
    spec: str,
    header: str,
    rtl_context: list[dict],
    knowledge_context: list[dict],
) -> tuple[str, int]:
    """Phase 3: Generate full module body (Verilog only)."""
    rtl_ctx_text = _format_rtl_context(rtl_context)
    know_ctx_text = _format_knowledge_context(knowledge_context)

    user_prompt = f"""\
Generate the full Verilog module: {module_name}
Using this EXACT header signature:
{header}

SPECIFICATION:
{spec}

REFERENCE RTL (from RAG corpus):
{rtl_ctx_text}

RELEVANT BUG PATTERNS:
{know_ctx_text}

Requirements:
1. Return ONLY the complete Verilog code in a ```verilog block.
2. Use the exact ports provided in the header.
3. Follow ALL rules in the hardware contract.
"""
    response_text, tokens = _call_llm(
        system=GLOBAL_CONTRACT,
        messages=[{"role": "user", "content": user_prompt}],
        model=MODEL,
    )
    verilog = _extract_verilog(response_text)
    return verilog, tokens


def _extract_module_name(verilog: str) -> str:
    m = re.search(r'\bmodule\s+(\w+)', verilog)
    return m.group(1) if m else "unknown"

def extract_ports(verilog: str) -> dict:
    pattern = r'(input|output)\s+(?:wire\s+|reg\s+)?(?:\[([^\]]+)\]\s+)?(\w+)'
    ports = []
    for m in re.finditer(pattern, verilog):
        direction, width, name = m.group(1), m.group(2), m.group(3)
        # skip keywords that match pattern accidentally
        if name in ('wire','reg','logic','signed','unsigned'): continue
        ports.append({
            "direction": direction,
            "width": f"[{width}]" if width else "1",
            "name": name
        })
    return {"module": _extract_module_name(verilog), "ports": ports}


def _generate_header(module_name: str, spec: str) -> tuple[str, int]:
    """Phase 1: Generate only the Verilog module header."""
    prompt = f"""\
Generate ONLY the Verilog module header (module name + complete port declarations) for: {module_name}
Ending with ');'. DO NOT generate any internal logic or 'endmodule'.

SPECIFICATION:
{spec}

Requirements:
- Return ONLY the header code in a ```verilog block.
- Follow the hardware contract for port names and types.
"""
    response_text, tokens = _call_llm(
        system=GLOBAL_CONTRACT,
        messages=[{"role": "user", "content": prompt}],
        model=MODEL,
    )
    header = _extract_verilog(response_text)
    # Ensure it ends at );
    idx = header.find(");")
    if idx != -1:
        header = header[:idx+2]
    return header, tokens


def lint_check(filepath: Path, all_files: list[Path]) -> list[str]:
    """
    Run Verilator lint-only inside the Docker container.
    1. Sync all involved files into the container.
    2. Execute verilator via docker exec.
    """
    module_name = filepath.stem
    
    # Sync current file + all dependencies to the container
    files_to_sync = [filepath] + all_files
    for f in files_to_sync:
        if f.exists():
            dest = f"{DOCKER_ID}:{DOCKER_APP_DIR}/rtl/generated/{f.name}"
            subprocess.run(["docker", "cp", str(f), dest], capture_output=True)

    # Build the command string for docker exec
    verilator_cmd = [
        "verilator",
        "--lint-only",
        "-Wall",
        "--language", "1800-2012",
        "--top-module", module_name,
        "-Wno-fatal",
    ]
    
    if module_name != "top":
        verilator_cmd += ["-Wno-PINCONNECTEMPTY", "-Wno-UNDRIVEN", "-Wno-UNUSED"]

    # Files inside the container
    v_files_in_container = [f"{DOCKER_APP_DIR}/rtl/generated/{f.name}" for f in files_to_sync if f.exists()]
    
    full_cmd = ["docker", "exec", "-w", f"{DOCKER_APP_DIR}/sim", DOCKER_ID] + verilator_cmd + v_files_in_container

    try:
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout + result.stderr
        error_lines = [
            line for line in output.splitlines()
            if "%Error" in line or "%Warning" in line
        ]
        return error_lines
    except subprocess.TimeoutExpired:
        return ["%Error: docker verilator lint timed out"]
    except Exception as e:
        return [f"%Error: Docker lint execution failed: {e}"]


# ── Main generation loop ───────────────────────────────────────────────────────

def generate_with_lint_fix(
    module_name: str,
    component: str,
    all_files: list[Path],
    max_iterations: int = 3,
    spec: Optional[str] = None,
) -> tuple[str, Path]:
    """Full generation loop: Header -> RAG -> Verilog -> Lint Loop -> JSON."""
    if spec is None:
        spec = MODULE_SPECS.get(module_name, f"Generate Verilog module {module_name} for RV32I pipeline.")

    RTL_DIR.mkdir(parents=True, exist_ok=True)
    filepath = RTL_DIR / f"{module_name}.v"
    meta_path = RTL_DIR / f"{module_name}_meta.json"

    # 1. Header generation (to ground the retrieval)
    logger.info("[%s] Phase 1: Header generation...", module_name)
    header, _ = _generate_header(module_name, spec)
    
    # 2. Retrieval
    logger.info("[%s] Phase 2: RAG retrieval...", module_name)
    retrieval_query = f"Module {module_name} with ports: {header}"
    rtl_context = retrieve(component, retrieval_query)
    knowledge_context = query_knowledge(spec)
    
    # 3. Verilog generation
    logger.info("[%s] Phase 3: Verilog body generation...", module_name)
    verilog, _ = generate_module_v(
        module_name, spec, header, rtl_context, knowledge_context
    )
    
    filepath.write_text(_normalize_verilog_text(verilog), encoding="utf-8")

    # 4. Lint Loop
    current_verilog = verilog
    for attempt in range(1, max_iterations + 1):
        lint_errors = lint_check(filepath, all_files)
        semantic_errors = validate(current_verilog, module_name)
        all_errors = lint_errors + semantic_errors

        if not all_errors:
            logger.info("[OK] %s passed linting", module_name)
            break

        if attempt < max_iterations:
            logger.info("[%s] Lint failure (attempt %d), retrying fix...", module_name, attempt)
            current_verilog = fix_with_feedback(module_name, current_verilog, all_errors)
            filepath.write_text(_normalize_verilog_text(current_verilog))
            time.sleep(10)
    else:
        # Failed all attempts
        raise LintFailureError(module_name, all_errors, max_iterations)

    # 5. Final JSON Metadata generation (ONLY after lint pass)
    logger.info("[%s] Phase 5: Generating metadata JSON...", module_name)
    contract = extract_ports(current_verilog)
    meta_path.write_text(json.dumps(contract, indent=2), encoding="utf-8")
    
    return current_verilog, filepath


def _build_port_contracts(rtl_dir: Path) -> str:
    """Load all _meta.json files and format as port contracts."""
    contracts = []
    for meta_file in sorted(rtl_dir.glob("*_meta.json")):
        meta = json.loads(meta_file.read_text())
        module = meta["module"]
        ports = meta["ports"]
        port_lines = "\n".join(
            f"  {p['direction']} {p['width']} {p['name']}"
            for p in ports
        )
        contracts.append(f"// {module}\n{port_lines}")
    return "=== EXACT PORT CONTRACTS ===\n" + "\n\n".join(contracts)

def generate_top_v(
    specs: str,
    all_json_contracts: str,
    rtl_context: list[dict],
    knowledge_context: list[dict],
) -> tuple[str, int]:
    """Special generation for top.v using all sub-module JSONs."""
    
    # Overwrite the passed all_json_contracts with the newly constructed deterministic one
    all_json_contracts = _build_port_contracts(RTL_DIR)
    
    rtl_ctx_text = _format_rtl_context(rtl_context)
    know_ctx_text = _format_knowledge_context(knowledge_context)

    prompt = f"""\
Generate the top-level RV32I integration module `top.v`.

USE THESE SUB-MODULE INTERFACE CONTRACTS FOR ALL WIRING:
{all_json_contracts}

SPECIFICATION:
{specs}

REFERENCE RTL (from RAG corpus):
{rtl_ctx_text}

KNOWLEDGE CONTEXT:
{know_ctx_text}

Requirements:
1. Wire all modules exactly as defined in the JSON contracts.
2. Return ONLY the complete Verilog code in a ```verilog block.
3. Follow ALL rules in the hardware contract.
"""
    resp, tokens = _call_llm(GLOBAL_CONTRACT, [{"role": "user", "content": prompt}], MODEL)
    return _extract_verilog(resp), tokens


def fix_with_feedback(module_name: str, verilog: str, errors: list[str]) -> str:
    error_str = "\n".join(errors[:15])
    system = (
        "You are fixing Verilog-2001 lint errors. "
        "Output ONLY the complete corrected Verilog module. "
        "No markdown fences, no explanation. "
        "Start with 'module' and end with 'endmodule'.\n\n"
        "COMMON FIXES:\n"
        "- WIDTHEXPAND on comparison: use 'result = (a<b) ? 32'd1 : 32'd0' not just '(a<b)'\n"
        "- PROCASSWIRE: change 'output wire' to 'output reg' for signals assigned in always blocks\n"
        "- CASEINCOMPLETE: add 'default: ;' to every case statement\n"
        "- Incomplete literals: write '4'b0000' not '4'b', '32'h0' not '32'h'\n"
        "- PINMISSING: use exact port names from submodule declarations\n"
    )
    prompt = (
        f"Fix all Verilator lint errors in this Verilog module '{module_name}'.\n\n"
        f"LINT ERRORS:\n{error_str}\n\n"
        f"CURRENT CODE:\n{verilog}\n\n"
        f"Output the complete corrected module only."
    )
    fixed, _ = _call_llm(system, [{"role": "user", "content": prompt}], MODEL)
    # extract verilog
    m = re.search(r'\bmodule\b.*?\bendmodule\b', fixed, re.DOTALL)
    return m.group(0).strip() if m else fixed.strip()
