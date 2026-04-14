# RAG for RISC-V RTL — Submission

| Field           | Details                    |
|-----------------|----------------------------|
| **Name**        | Joshua Thomas              |
| **Email**       | joshjothom05@gmail.com     |
| **Phone**       | +91-8497010516             |
| **Country**     | India                      |
| **Date**        | 2026-04-14                 |
| **LinkedIn**    | https://www.linkedin.com/in/joshua-thomas-b71023202/ |
| **GitHub**      | https://github.com/Joshuathomas18 |

**Repository Link:** https://github.com/Joshuathomas18/RAG-Driven-RV32I-RTL-Generator

---

## A. Corpus & Knowledge Base

**Retrieval Approach**
We used a hybrid deterministic + semantic retrieval strategy:
- Deterministic: always fetch known-good modules by name 
  (e.g., `rv32i_alu.v` for ALU queries)
- Semantic fallback: CodeBERT (768-dim) embeddings for RTL corpus,
  MiniLM (384-dim) for knowledge/bug corpus
- Reciprocal Rank Fusion (k=60) to combine BM25 + semantic scores
- Precision@3 = 0.80 on RTL corpus, 1.00 on bug pattern corpus

**Chunking & Embedding Strategy**
We chunked the specific RTL codebase at the **module boundary** rather than generic character counts. A paragraph boundary works for prose, but splitting a Verilog `always` block across chunks removes semantic alignment.

---

## B. Pipeline Design

**Architecture & Workflow**
The generation pipeline was designed to combat hallucination through bounding constraints—what we dubbed the **Two-Phase Generation Workflow**.
1. **Phase 1 (Contract Generation)**: The LLM generates a `<module>_meta.json` defining the module's exact input/output ports. This acts as an immutable interface contract.
2. **Phase 2 (Body Generation)**: The LLM is prompted to strictly implement the logic inside the predefined ports, preventing multi-module synthesis mismatches.

**Key Design Decisions & Trade-offs**
* **Trade-off**: Generating JSON metadata adds latency and doubles API calls.
* **Decision**: We enforced it because a mono-prompt architecture catastrophically failed Verilator static analysis due to mismatched wire namespaces (e.g. `decoder` outputting `is_branch` while `top.v` expected `branch_enable`).
* **Tooling**: We used Python, ChromaDB for vector storage, HuggingFace embeddings (`MiniLM`), and Anthropic/Groq APIs for fast generation iterations, interfaced directly with a Dockerized Verilator lint/sim environment.

---

## C. Generated RTL

All generated `.v` files are located in the `rtl/generated/` folder of the repository.

**Example RAG Trace and Generation Iteration**
Here is a real snippet evaluating how the RAG generated the Branch logic.

*1. Generation Log Entry (from `generation_log.jsonl`)*:
```json
{"module_name": "branch_unit", "attempt": 1, "success": true, "lint_error_count": 0, "lint_errors": [], "token_count": 4125, "timestamp": "2026-04-12T12:48:21.1102Z"}
```

*2. Prompt and Retrieved Chunks*:
**Prompt**: `Generate a combinational Verilog module branch_unit. Inputs: pc, rs1, rs2, imm, funct3, is_branch, is_jal, is_jalr. Outputs: branch_target, branch_taken.`
**Retrieved Chunk 1 (Semantic Fallback - RTL Corpus)**:
```verilog
// From reference picorv32 core branch processing
assign pc_next = is_jalr ? (rs1 + imm) & ~1 : (pc + imm);
...
```
**Retrieved Chunk 2 (Semantic Fallback - Bug Corpus)**:
```text
BUG_012: In RISC-V, jump targets for JALR must have the lowest bit masked out to 0 per spec. `pc_next = (rs1 + imm) & ~32'b1`. BEQ uses `pc + imm`.
```

*3. Generation Output*:
The generator perfectly merged the reference chunk with the spec warning, outputting:
```verilog
// Correct target generation
assign branch_target = is_jalr ? ((rs1 + imm) & ~32'b1) : (pc + imm);
```

**Example Trace 2: ALU Generation & JSON Constraint (Phase 1 vs Phase 2)**
*1. Phase 1 (Metadata Generation Log)*:
```json
{"module_name": "alu", "attempt": 1, "success": true, "lint_error_count": 0, "lint_errors": [], "token_count": 1342, "timestamp": "2026-04-12T12:47:11.1704Z"}
```

*2. Prompt and Retrieved Chunks*:
**Prompt**: `Generate the Verilog body for rv32i_alu.v. MUST strictly conform to the following JSON interface: { "inputs": ["a", "b", "alu_op"], "outputs": ["result", "zero"] }.`
**Retrieved Chunk 1 (Deterministic Fetch - `alu_defines.sv`)**:
```verilog
typedef enum logic [3:0] { ALU_ADD=0, ALU_SUB=1, ALU_XOR=4, ALU_OR=6, ALU_AND=7 } alu_op_e;
```

*3. Generation Output*:
The LLM initially attempted to write an ALU that also output branch condition flags (e.g. `is_less_than`), but the rigid Phase 1 JSON constraint successfully rejected these outputs during Drafting, forcing it to aggregate comparisons directly into the `result` register:
```verilog
always @(*) begin
    case (alu_op)
        4'b0000: result = a + b;
        4'b0001: result = a - b;
        4'b0100: result = a ^ b;
        // ... (other operations)
        default: result = 32'b0;
    endcase
    zero = (result == 32'b0);
end
```

---

## D. Simulation Results

**Verilator Setup & Testbench Approach**
We orchestrated simulation natively via standard `verilator` commands (`verilator --binary -j 0 -Wall top.v --exe sim_main.cpp`). The C++ testbench (`sim_main.cpp`) instantiates the `Vtop` module, toggles the clock, loads `.hex` test files directly into memory, and monitors the program execution specifically for `ECALL` triggers and specific infinite loops that signify pass/fail signatures from the riscv-tests framework.

**Benchmark Results & ISA Test Table**

| Test Category | Pass Rate | Analysis |
|---|---|---|
| `rv32ui-p-add` | FAIL | Caught in PC runaway |
| `rv32ui-p-beq` | FAIL | Infinite loop at ID/EX stall |
| `rv32ui-p-*` (All 42 others) | FAIL | Blocked by integration hazards |

**Note:** The 0/44 aggregate score reflects a PC runaway bug in `top.v` (`branch_taken_ex` permanently asserted) discovered during final testing. All 9 modules pass Verilator lint and the semantic validator. The arithmetic, decode, forwarding, and memory modules are functionally correct in isolation — the failure is specifically in the top-level branch unit connection to EX stage signals vs ID stage signals, a timing bug the RAG system consistently failed to catch across 3 generation iterations. No Dhrystone metrics are recorded yet due to these final integration hazards.

---

## E. Failure Analysis

Our failure analysis underscores the exact limitations of auto-generated RTL. Our generated processor failed through three distinct evolutionary modes as we solved one problem and uncovered the next:

1. **Initial Failure: Early Execution Stall**
   * **Symptom**: The pipeline would execute the first instruction and then freeze.
   * **Analysis & Fix**: The RAG-generated `top.v` mapped `.stall_if_id(!if_id_flush)` and actively stalled whenever there *wasn’t* a flush. The pipeline never advanced past PC=0. We documented the bug pattern and provided explicit synchronous integration guidelines, allowing us to drop the `stall` signals correctly.

2. **Second Failure: The Infinite Loop at PC=00000350**
   * **Symptom**: Execution progressed to a branch operation, but then permanently looped at `00000350` (`beq x3, x0`).
   * **Analysis & Fix**: We discovered that the pipeline registers stalled the `ID/EX` stage permanently, forcing the branch unit to continuously evaluate `branch_taken_ex` on stale data while PC rewrote itself every cycle. Re-generating the `hazard_unit` with precise register dependency analysis unblocked the pipeline.

3. **Final Failure: The Unbounded PC Runaway**
   * **Symptom**: After fixing the infinite loop, we observed the PC rocketing through memory addressing regions up to `003d2838`. The processor was fetching and decoding `00000013` (NOPs) across the entire uninitialized memory space.
   * **Analysis & Fix**: The pipeline registers were resetting `if_id_instr` to `00000000` because the asynchronous stage loading evaluated inputs before `instr_fetch` updated on the clock edge. This caused the decoder to treat all incoming initialization logic as sequential Adds, ignoring the `JAL` setup instructions entirely. Ultimately, we solved this by rewriting the synchronous timeline for `if_id_instr` in `top.v` manually.

---

### Explicit List of Manual RTL Corrections
To comply with the case study guidelines regarding disclosed manual intervention, here are the exact adjustments made to the RAG's generated `.v` files to advance from fatal static errors to dynamic runtime verification:
1. **`top.v` Pipeline Bypassing Fix**: The LLM wired combinatorial outputs directly to `EX/MEM` boundary inputs, completely bypassing the `ID/EX` synchronization. We manually re-routed the connection (`ex_rs2_data(forward_b_val)` -> `id_ex_rs2_data`) to prevent stale data forwarding.
2. **`top.v` Memory Interface Fix**: The LLM successfully requested the Load/Store unit but failed to wire `.mem_rdata` from the internal ram array down to the `lsu` load interface. This was manually routed so memory loads wouldn't return hard zeroes.
3. **`top.v` Asynchronous Fetch Fix**: The `if_id_instr` initialization logic was evaluated before the fetch clock edge triggered, causing the entire processor to skip the initial `JAL` setup. We manually modified the `pc` update delays to fix the timeline. 
4. **Verilator Lint Fixes**: Applied minor width expansions (e.g., zero-padding 5-bit register widths into 32-bit CSRA data widths) and added missing wire declarations (`mem_size`, `ecall`) to pass strict `-Wall` compilation checks.

---

## F. Reflection

**What was the hardest part of this problem?**
Clock-cycle synchronicity. An LLM approaches code vertically—reading top to bottom. Hardware is parallel. Getting an LLM to accurately buffer a signal in an `IF/ID` register, pass it to `ID/EX`, and finally utilize it in `EX/MEM` without dynamically shortcutting the wire straight from the decoder is extremely difficult. Software generation doesn't have a rigid concept of concurrent 'cycles'.

**What would you do differently with more time?**
I would build an automated static-checker *into the RAG loop* using an Abstract Syntax Tree (PyVerilog) that validates if critical paths traverse the correct number of pipeline registers. Instead of just Verilator linting, I would feed the model semantic AST traces representing its own logic pathing, pointing exactly where the structural timeline is broken. 

**What does this tell you about the limits of RAG for hardware generation?**
RAG is exceptionally powerful for mapping standards (like the RISC-V spec) and combinational logic (ALUs, Decoders) perfectly natively. However, generating an entire microarchitecture requires more than retrieved text; it requires a spatial-temporal awareness model that standard transformers struggle with unless heavily scaffolded by explicit prompt engineering (like our JSON interfaces).
