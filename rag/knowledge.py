"""
Knowledge base: bug patterns, debug lessons, and Angelo architectural patterns.
Embedded with MiniLM and stored in ChromaDB collection 'knowledge_corpus'.
"""

import os
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import chromadb
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

logger = logging.getLogger(__name__)

REPO_ROOT = Path(os.getenv("REPO_ROOT", Path(__file__).parent.parent))
CHROMA_PATH = REPO_ROOT / "data" / "chromadb"
MINILM_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

os.environ.setdefault("HF_HOME", str(REPO_ROOT / "data" / "model_cache"))


@dataclass
class KnowledgeEntry:
    id: str
    category: Literal["bug_pattern", "debug_lesson", "angelo_pattern"]
    title: str
    text: str


# ── Bug Patterns (15) ──────────────────────────────────────────────────────────

BUG_PATTERNS: list[KnowledgeEntry] = [
    KnowledgeEntry(
        id="bp_blocking_assign",
        category="bug_pattern",
        title="Blocking assignments in clocked always blocks",
        text=(
            "CRITICAL: Always use non-blocking assignments (<= ) in always @(posedge clk) blocks. "
            "Blocking (=) assignments cause race conditions and incorrect pipeline register behavior. "
            "Rule: clocked blocks use <=, combinational always@(*) blocks use =."
        ),
    ),
    KnowledgeEntry(
        id="bp_sign_extend",
        category="bug_pattern",
        title="Sign extension errors in load instructions",
        text=(
            "LB and LH load instructions require sign extension: LB sign-extends 8-bit to 32-bit, "
            "LH sign-extends 16-bit to 32-bit. Use $signed() cast or explicit sign-bit replication. "
            "LBU and LHU are zero-extended (no sign extension). "
            "Example: LB: {{24{mem_byte[7]}}, mem_byte}. LBU: {24'b0, mem_byte}."
        ),
    ),
    KnowledgeEntry(
        id="bp_x0_write",
        category="bug_pattern",
        title="Register x0 must always read as zero",
        text=(
            "Register x0 (register address 5'b00000) is hardwired to zero. "
            "Gate the register file write enable: we_actual = we && (rd_addr != 5'd0). "
            "Never write to x0. Reads of x0 must always return 32'b0. "
            "This is critical for forwarding — never forward from x0 writes."
        ),
    ),
    KnowledgeEntry(
        id="bp_branch_flush",
        category="bug_pattern",
        title="Branch flush timing — two instructions must be squashed",
        text=(
            "When a branch resolves as taken in EX stage at cycle N: "
            "the instruction fetched at PC_branch+4 (now in IF/ID) and "
            "the instruction fetched at PC_branch+8 (now in ID/EX) are wrong. "
            "Both must be flushed at cycle N+1 by replacing IF/ID and ID/EX with NOPs (0x00000013). "
            "Flush signal: flush_if_id = branch_taken_ex (direct from EX, NOT registered)."
        ),
    ),
    KnowledgeEntry(
        id="bp_shift_amt",
        category="bug_pattern",
        title="Shift amount must be masked to 5 bits",
        text=(
            "RV32I: shift amount is only the lower 5 bits. "
            "For register shifts (SLL, SRL, SRA): shamt = rs2[4:0]. "
            "For immediate shifts (SLLI, SRLI, SRAI): shamt = inst[24:20]. "
            "Never use the full 32-bit rs2 value as shift amount — this causes wrong results."
        ),
    ),
    KnowledgeEntry(
        id="bp_slt_signed",
        category="bug_pattern",
        title="SLT uses signed comparison, SLTU uses unsigned",
        text=(
            "SLT (Set Less Than): result = ($signed(rs1) < $signed(rs2)) ? 1 : 0. "
            "SLTU (Set Less Than Unsigned): result = (rs1 < rs2) ? 1 : 0. "
            "These MUST use different comparison paths. "
            "Mixing them causes test failures on negative numbers."
        ),
    ),
    KnowledgeEntry(
        id="bp_imm_encoding",
        category="bug_pattern",
        title="RV32I immediate encoding — B-type and J-type are scrambled",
        text=(
            "B-type (branch): imm = {inst[31], inst[7], inst[30:25], inst[11:8], 1'b0} "
            "sign-extended to 32 bits. "
            "J-type (JAL): imm = {inst[31], inst[19:12], inst[20], inst[30:21], 1'b0} "
            "sign-extended to 32 bits. "
            "U-type (LUI/AUIPC): imm = {inst[31:12], 12'b0}. "
            "I-type: imm = {inst[31:20]} sign-extended. "
            "S-type: imm = {inst[31:25], inst[11:7]} sign-extended."
        ),
    ),
    KnowledgeEntry(
        id="bp_forward_stale",
        category="bug_pattern",
        title="Data forwarding: EX hazard must take priority over MEM hazard",
        text=(
            "Forward EX/MEM.ALUResult when: EX/MEM.RegWrite AND EX/MEM.rd == ID/EX.rs1 AND EX/MEM.rd != 0. "
            "Forward MEM/WB result when: MEM/WB.RegWrite AND MEM/WB.rd == ID/EX.rs1 AND MEM/WB.rd != 0 "
            "AND NOT (EX/MEM.RegWrite AND EX/MEM.rd == ID/EX.rs1). "
            "EX hazard always takes priority over MEM hazard for the same register."
        ),
    ),
    KnowledgeEntry(
        id="bp_load_hazard",
        category="bug_pattern",
        title="Load-use hazard requires a one-cycle pipeline stall",
        text=(
            "When ID/EX.MemRead AND (ID/EX.rd == IF/ID.rs1 OR ID/EX.rd == IF/ID.rs2) AND ID/EX.rd != 0: "
            "stall the pipeline for one cycle. "
            "Assert: PCWrite=0 (hold PC), IF_IDWrite=0 (hold IF/ID register), "
            "insert bubble into ID/EX (clear all control signals). "
            "This allows the load to complete before the dependent instruction reads the value."
        ),
    ),
    KnowledgeEntry(
        id="bp_pc_reset",
        category="bug_pattern",
        title="PC must initialize to 0x00000000 on synchronous reset",
        text=(
            "PC initializes to 32'h0 on synchronous active-high reset. "
            "Ensure the reset path drives: always @(posedge clk) if (rst) pc <= 32'h0; "
            "Do not use asynchronous reset unless specifically required. "
            "The first instruction fetched after reset is at address 0."
        ),
    ),
    KnowledgeEntry(
        id="bp_mem_align",
        category="bug_pattern",
        title="Memory alignment: word accesses must be 4-byte aligned",
        text=(
            "RV32I requires naturally aligned memory accesses. "
            "Word (LW/SW): address[1:0] must be 2'b00. "
            "Halfword (LH/SH): address[0] must be 1'b0. "
            "Byte (LB/SB): any address. "
            "For basic ISA tests, misaligned accesses can be ignored (they won't occur). "
            "The byte enable for store: SW=4'b1111, SH=4'b0011 or 4'b1100, SB=4'b0001/0010/0100/1000."
        ),
    ),
    KnowledgeEntry(
        id="bp_auipc",
        category="bug_pattern",
        title="AUIPC: ALU input A must be the instruction's PC",
        text=(
            "AUIPC (Add Upper Immediate to PC): rd = PC + imm_u. "
            "The PC fed to the ALU must be the PC of the AUIPC instruction itself (from IF/ID pipeline reg), "
            "NOT the current fetch PC, and NOT rs1. "
            "Pass the instruction PC through pipeline registers and mux it as ALU operand A "
            "when is_auipc is asserted."
        ),
    ),
    KnowledgeEntry(
        id="bp_jal_jalr",
        category="bug_pattern",
        title="JAL/JALR must write PC+4 to rd, NOT alu_result",
        text=(
            "JAL writes PC+4 to rd (return address). JALR writes PC+4 to rd. "
            "ALU computes the branch target (PC+imm or rs1+imm), NOT the return address. "
            "Use a dedicated pc_plus4 path: register PC+4 through all pipeline stages to WB. "
            "wb_sel=2'b10 selects pc_plus4 for writeback. "
            "JALR target: (rs1_data + imm_i) & ~32'h1 (clear LSB)."
        ),
    ),
    KnowledgeEntry(
        id="bp_csr_addr",
        category="bug_pattern",
        title="CSR address decode for riscv-tests",
        text=(
            "riscv-tests use these CSRs: mhartid=0x314 (returns 0), mtvec=0x305, "
            "mepc=0x341, mcause=0x342, mstatus=0x300. "
            "CSRR (CSRRS with rs1=x0): read CSR, write 0. "
            "CSRW (CSRRW): write rs1 to CSR, return old value. "
            "For simulation: mhartid always returns 0. All other reads return 0 unless written. "
            "Unimplemented CSRs must NOT trap — silently return 0."
        ),
    ),
    KnowledgeEntry(
        id="bp_endian",
        category="bug_pattern",
        title="RV32I is little-endian — byte 0 is least significant",
        text=(
            "RV32I is little-endian. When storing 0xAABBCCDD to address 0x00: "
            "mem[0x00]=0xDD (LSB), mem[0x01]=0xCC, mem[0x02]=0xBB, mem[0x03]=0xAA (MSB). "
            "When using a word-addressed memory array (reg[31:0] mem[N]): "
            "load byte from addr: mem[addr>>2][8*(addr&3) +: 8]. "
            "Store byte to addr: mem[addr>>2][8*(addr&3) +: 8] = wdata[7:0]."
        ),
    ),
]


# ── Debug Lessons (7) ──────────────────────────────────────────────────────────

DEBUG_LESSONS: list[KnowledgeEntry] = [
    KnowledgeEntry(
        id="dl_branch_flush_timing",
        category="debug_lesson",
        title="Branch flush must use branch_taken_ex (direct EX output), NOT registered",
        text=(
            "LESSON LEARNED: EX stage detects branch_taken at clock N. "
            "flush_if_id and flush_id_ex must use the COMBINATIONAL branch_taken_ex signal "
            "directly from the EX computation, NOT the registered ex_mem_branch_taken. "
            "Using the registered version delays the flush by one cycle, causing a wrong instruction "
            "to commit. Wire: assign flush_if_id = branch_taken_ex; assign flush_id_ex = branch_taken_ex;"
        ),
    ),
    KnowledgeEntry(
        id="dl_branch_type_encoding",
        category="debug_lesson",
        title="Branch unit needs funct3 directly from decoder, NOT alu_op bits",
        text=(
            "LESSON LEARNED: Branch comparison type (BEQ/BNE/BLT/BGE/BLTU/BGEU) is encoded in "
            "inst[14:12] (funct3). Pass branch_funct3[2:0] through the pipeline registers to the "
            "branch unit. Do NOT derive it from alu_op[2:0] — the ALU op encoding is different. "
            "BEQ=3'b000, BNE=3'b001, BLT=3'b100, BGE=3'b101, BLTU=3'b110, BGEU=3'b111."
        ),
    ),
    KnowledgeEntry(
        id="dl_forwarding_address",
        category="debug_lesson",
        title="Hazard unit needs 5-bit register ADDRESSES, not [4:0] of 32-bit data values",
        text=(
            "LESSON LEARNED: The forwarding/hazard unit compares register ADDRESS fields (5-bit). "
            "Pipeline registers must carry rs1_addr[4:0] and rs2_addr[4:0] as separate fields, "
            "NOT derived from the bottom bits of rs1_data or rs2_data (which are 32-bit data values). "
            "Always declare explicit address ports: id_ex_rs1[4:0], id_ex_rs2[4:0], etc."
        ),
    ),
    KnowledgeEntry(
        id="dl_auipc_alu_input",
        category="debug_lesson",
        title="AUIPC/JAL/BRANCH: ALU operand A must be PC, not rs1",
        text=(
            "LESSON LEARNED: For AUIPC, JAL, and BRANCH instructions, ALU operand A must be "
            "the instruction's own PC (from the ID/EX pipeline register's pc field). "
            "For all other instructions (ITYPE, RTYPE, LOAD, STORE, JALR), ALU operand A is rs1_data. "
            "Use is_auipc OR is_branch OR is_jal to select: "
            "alu_a = (is_auipc | is_branch | is_jal) ? ex_pc : forward_rs1_data;"
        ),
    ),
    KnowledgeEntry(
        id="dl_jal_writeback",
        category="debug_lesson",
        title="JAL writes PC+4 to rd — pipeline pc_plus4 separately through all stages",
        text=(
            "LESSON LEARNED: JAL/JALR writeback value is PC+4 (return address), NOT alu_result. "
            "Compute pc_plus4 = pc + 4 in the IF stage and pipeline it through "
            "IF/ID → ID/EX → EX/MEM → MEM/WB registers alongside the instruction. "
            "wb_sel=2'b10 selects pc_plus4 at writeback. "
            "Never try to reconstruct PC+4 in the WB stage — by then the PC has moved on."
        ),
    ),
    KnowledgeEntry(
        id="dl_wb_sel_timing",
        category="debug_lesson",
        title="wb_sel must travel inside pipeline registers WITH its instruction",
        text=(
            "LESSON LEARNED: The wb_sel[1:0] control signal must be registered through "
            "EX/MEM and MEM/WB pipeline registers as part of the same always block as the data. "
            "Never latch wb_sel separately or derive it in the WB stage from the current instruction. "
            "By the time an instruction reaches WB, the ID stage has moved 3 instructions forward. "
            "MEM/WB register must update wb_sel, pc_plus4, alu_result, and load_data ALL TOGETHER."
        ),
    ),
    KnowledgeEntry(
        id="dl_csr_support",
        category="debug_lesson",
        title="riscv-tests require mhartid=0 and silent CSR writes",
        text=(
            "LESSON LEARNED: riscv-tests startup code reads mhartid (csrr a0, mhartid, addr=0x314). "
            "If mhartid != 0, the test spins forever or branches to wrong path. "
            "Implement a minimal CSR stub: mhartid always returns 0. "
            "All unimplemented CSR writes must be silently ignored (no trap). "
            "ECALL: treat as NOP for simulation — the test pass/fail is detected by the JAL-self-loop. "
            "CSR wb_sel=2'b11 for CSRR/CSRW instructions."
        ),
    ),
]
SIMULATION_LESSONS: list[KnowledgeEntry] = [
    KnowledgeEntry(
        id="sim_001",
        category="debug_lesson",
        title="ELF to hex conversion must use byte-reversed verilog output",
        text=(
            "LESSON LEARNED: riscv64-unknown-elf-objcopy must output verilog format with byte reversal. "
            "Parse @address markers and remap addresses to 0x00000000. "
            "The final mem_init.hex must contain 65536 32-bit words in little-endian word order."
        ),
    ),
    KnowledgeEntry(
        id="sim_002",
        category="debug_lesson",
        title="program.hex must be colocated with the sim binary or use absolute path",
        text=(
            "LESSON LEARNED: Verilator simulation runs from sim/obj_dir/, so relative $readmemh paths must resolve there. "
            "The test harness must write mem_init.hex where the sim binary can open it before running."
        ),
    ),
    KnowledgeEntry(
        id="sim_003",
        category="debug_lesson",
        title="Memory must be 65536 words, not 4096",
        text=(
            "LESSON LEARNED: riscv-tests require 256KB of unified memory. "
            "Use reg [31:0] mem [0:65535] and address with pc[17:2]. "
            "Smaller memories lead to illegal 0x00000000 fetches and wrong branch behavior."
        ),
    ),
    KnowledgeEntry(
        id="sim_004",
        category="debug_lesson",
        title="CSR mhartid must return 0 at startup",
        text=(
            "LESSON LEARNED: riscv-tests startup reads mhartid and expects zero. "
            "Implement a CSR stub that returns 32'h0 for CSR address 12'hF14."
        ),
    ),
    KnowledgeEntry(
        id="sim_005",
        category="debug_lesson",
        title="Branch flush must use branch_taken_ex, not registered signal",
        text=(
            "LESSON LEARNED: flush_if_id and flush_id_ex must be driven by branch_taken_ex directly. "
            "Using the registered ex_mem_branch_taken delays flush by one cycle and corrupts the next instruction."
        ),
    ),
    KnowledgeEntry(
        id="sim_006",
        category="debug_lesson",
        title="Branch unit must use funct3, not alu_op bits",
        text=(
            "LESSON LEARNED: branch condition is encoded in inst[14:12]. "
            "Do not derive branch type from alu_op bits, because ALU encoding differs."
        ),
    ),
    KnowledgeEntry(
        id="sim_007",
        category="debug_lesson",
        title="Forwarding unit must compare register addresses, not data bits",
        text=(
            "LESSON LEARNED: hazard detection must use 5-bit rs1/rs2 register addresses. "
            "Never compare lower bits of rs1_data or rs2_data."
        ),
    ),
    KnowledgeEntry(
        id="sim_008",
        category="debug_lesson",
        title="AUIPC must use PC as ALU operand A",
        text=(
            "LESSON LEARNED: AUIPC computes PC + immediate, so ALU operand A must be the current PC. "
            "Use id_ex_pc when is_auipc is asserted."
        ),
    ),
    KnowledgeEntry(
        id="sim_009",
        category="debug_lesson",
        title="JAL writeback must use pipelined PC+4",
        text=(
            "LESSON LEARNED: JAL writes return address PC+4, not ALU result. "
            "Pipeline pc_plus4 through all stages and select it with wb_sel=2'b10 in MEM/WB."
        ),
    ),
    KnowledgeEntry(
        id="sim_010",
        category="debug_lesson",
        title="wb_sel must travel with its data in the same pipeline register",
        text=(
            "LESSON LEARNED: wb_sel and pc_plus4 must update in the same always block as the rest of MEM/WB data. "
            "Separating wb_sel into a different register causes writeback to use stale select signals."
        ),
    ),
    KnowledgeEntry(
        id="sim_011",
        category="debug_lesson",
        title="Pass detection requires $display PC/INSTR output",
        text=(
            "LESSON LEARNED: test harness detects pass by parsing PC and instruction values from $display output. "
            "Include $display(\"PC=%08h INSTR=%08h\", if_id_pc, if_id_instr) in top.v."
        ),
    ),
    KnowledgeEntry(
        id="sim_012",
        category="debug_lesson",
        title="LSU mem_op must be routed from pipelined funct3, not hardcoded value",
        text=(
            "LESSON LEARNED: load/store size control comes from instruction funct3. "
            "Pipeline ex_mem_funct3 through EX/MEM and connect it to the LSU mem_op port."
        ),
    ),
]

# ── Angelo Patterns (6) ────────────────────────────────────────────────────────

ANGELO_PATTERNS: list[KnowledgeEntry] = [
    KnowledgeEntry(
        id="ap_alu_operand",
        category="angelo_pattern",
        title="ALU operand selection: PC for AUIPC/JAL/BRANCH, rs1 for others",
        text=(
            "Angelo's design: separate alu_a_sel and alu_b_sel control signals. "
            "alu_a = rs1_data or PC (selected by opcode). "
            "alu_b = rs2_data or immediate (selected by alu_src). "
            "Forward into the mux inputs, not after — this keeps forwarding logic clean. "
            "Opcodes requiring PC as operand A: AUIPC (0010111), JAL (1101111), BRANCH (1100011)."
        ),
    ),
    KnowledgeEntry(
        id="ap_header_constants",
        category="angelo_pattern",
        title="Use named constants for all opcodes and ALU ops in a localparams block",
        text=(
            "Angelo defines all opcodes, funct3, funct7 constants. For Verilator compatibility, "
            "use localparams inside each module instead of `define (avoids include-path issues). "
            "Example: localparam RTYPE=7'b0110011, ITYPE=7'b0010011, LOAD=7'b0000011, etc. "
            "This makes the decode logic readable and prevents magic number bugs."
        ),
    ),
    KnowledgeEntry(
        id="ap_forwarding_arch",
        category="angelo_pattern",
        title="Forwarding unit: compare addresses, return forwarded values directly",
        text=(
            "Angelo's forwarding unit takes current rs1_addr, rs2_addr and compares against "
            "EX/MEM.rd and MEM/WB.rd (register ADDRESSES, not data). "
            "Returns 2-bit forward_a and forward_b selectors: "
            "2'b00 = use register file output, 2'b01 = forward from EX/MEM, 2'b10 = forward from MEM/WB. "
            "The pipeline stage then uses these to mux the correct value into the ALU. "
            "Always check rd != 0 and reg_write before forwarding."
        ),
    ),
    KnowledgeEntry(
        id="ap_pipeline_control",
        category="angelo_pattern",
        title="Use per-stage stall and flush one-hot signals",
        text=(
            "Angelo uses separate stall and flush signals per pipeline stage. "
            "Stall: stall_if_id=1 holds PC and IF/ID register (PCWrite=0, IF_IDWrite=0). "
            "stall_id_ex=1 inserts a bubble (NOP) into ID/EX. "
            "Flush: flush_if_id=1 zeroes the IF/ID instruction field to NOP (0x00000013). "
            "flush_id_ex=1 zeroes all ID/EX control signals. "
            "Stall has priority over flush for the same register."
        ),
    ),
    KnowledgeEntry(
        id="ap_memory_unified",
        category="angelo_pattern",
        title="Unified memory array for fence.i — single reg[31:0] mem[0:65535]",
        text=(
            "For fence.i (instruction-cache fence) to work correctly, instruction and data memory "
            "must be the same array. Use: reg [31:0] mem [0:65535] (word-addressed). "
            "Initialize with $readmemh. Instruction fetch: mem[pc>>2]. "
            "Data read/write: mem[addr>>2] with byte-enable masking. "
            "This is required for riscv-tests fence_i test to pass."
        ),
    ),
    KnowledgeEntry(
        id="ap_ecall_handling",
        category="angelo_pattern",
        title="ECALL: treat as NOP; pass detection is JAL-self-loop (0x0000006f)",
        text=(
            "For riscv-tests simulation: ECALL (opcode=7'h73, funct3=3'b000) should be treated as NOP. "
            "Test pass/fail is not detected via ECALL — instead, a passing test jumps to "
            "a JAL instruction that loops to itself (0x0000006f at some address). "
            "Detect PASS by observing the same PC producing instruction 0x0000006f for >100 cycles. "
            "ECALL trapping or crashing will prevent the test from reaching the pass loop."
        ),
    ),
]


# ── Accessor ───────────────────────────────────────────────────────────────────

def get_all_entries() -> list[KnowledgeEntry]:
    """Return flat list of all knowledge entries."""
    return BUG_PATTERNS + DEBUG_LESSONS + SIMULATION_LESSONS + ANGELO_PATTERNS


# ── Build knowledge base ───────────────────────────────────────────────────────

def build_knowledge_base(force_rebuild: bool = False) -> chromadb.Collection:
    """
    Embed all 28 knowledge entries with MiniLM and store in 'knowledge_corpus'.
    If force_rebuild=False and collection already has documents, skip rebuild.
    Returns the ChromaDB collection.
    """
    CHROMA_PATH.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    collection = client.get_or_create_collection(
        "knowledge_corpus",
        metadata={"hnsw:space": "cosine"},
    )

    entries = get_all_entries()

    if not force_rebuild and collection.count() >= len(entries):
        logger.info("knowledge_corpus already has %d documents, skipping rebuild.", collection.count())
        return collection

    logger.info("Loading MiniLM model (%s) ...", MINILM_MODEL)
    model = SentenceTransformer(MINILM_MODEL)

    documents = [e.text for e in entries]
    ids = [e.id for e in entries]
    metadatas = [{"category": e.category, "title": e.title} for e in entries]

    logger.info("Embedding %d knowledge entries ...", len(documents))
    embeddings = model.encode(documents, show_progress_bar=True, convert_to_numpy=True).tolist()

    # Clear existing if rebuild
    if force_rebuild and collection.count() > 0:
        existing = collection.get()
        if existing["ids"]:
            collection.delete(ids=existing["ids"])

    collection.add(
        documents=documents,
        embeddings=embeddings,
        ids=ids,
        metadatas=metadatas,
    )

    logger.info("knowledge_corpus built: %d entries stored.", collection.count())
    return collection
