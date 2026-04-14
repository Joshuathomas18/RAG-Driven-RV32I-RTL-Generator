# Generative RTL Pipeline: Failure Analysis & Evolution Journey

This document chronicles the diagnostic journey of building our internal RAG-driven RV32I RTL Generator. The overarching objective was to leverage AI for autonomous hardware generation. Rather than just brute-forcing prompts, we built an evolving RAG pipeline. Below is a detailed breakdown of the failure modes encountered, our architectural interventions, and the impact of each iteration.

## Phase 1: The Initial Baseline & Structural Chaos

### Early Failure Modes
Initially, we used a standard retrieval pipeline with simple prompts for Verilog generation. The failures were primarily structural and syntactic:
1. **Module Interface Mismatches**: The model would generate a `decoder.v` that output variable `is_branch`, and a `top.v` that tried to wire it as `branch_enable`. This caused immediate Verilator compilation failures.
2. **Procedural Assignment Errors (`PROCASSWIRE`)**: The model fundamentally confused `wand`, `wire`, and `reg` types inside `always` blocks, trying to procedurally assign signals defined as wires.
3. **Black-box Instantiations**: The top-level module often hallucinated submodules (like `lsu` or `csr`) that hadn't actually been generated, or forgot to propagate critical clock (`clk`) and reset (`rst`) signals.

**Analysis**: The monolithic generation task over-saturated the model's context window. Attempting to track the internal state of 6 different Verilog files simultaneously led to catastrophic semantic drift.

---

## Phase 2: Bounding Hallucination with The "JSON Contract" Idea

To solve the structural chaos, we intervened by splitting the generation into a **Two-Phase Generation Workflow**.
Before generating any Verilog body, the pipeline first generates a `*_meta.json` file defining the absolute input/output ports for the module. Once approved, this JSON serves as an immutable contract.

### What Changed?
* We injected `json` generation steps into our workflow (e.g., `decoder_meta.json`).
* `top.v` generation became strictly constrained to instantiate other modules based *only* on these validated JSON contracts.

### Impact
* **Syntax Errors Eliminated**: Verilator linting errors dropped by over 80%. `PROCASSWIRE` errors were squashed because the JSON explicitly forced the model to categorize `reg` vs `wire` outputs.
* **Stable Integration**: Instantiations perfectly matched across the boundaries. The pipeline now successfully advanced past static analysis and began actually compiling binary simulators.

---

## Phase 3: The Knowledge Gap & Reference Repository Dataset

Despite clean syntax, the processor suffered from massive functional failures. The compiled pipeline either got stuck in infinite stall loops or suffered from "PC Runaway" (fetching invalid memory regions until it crashed). 

### Functional Failure Modes
1. **Instruction Decoding Hallucination**: The model guessed how to map RISC-V opcodes, failing to account for nuances in immediate extractions (e.g., B-type vs J-type instruction slicing).
2. **Forwarding Logic Errors**: The control path for the 5-stage pipeline lacked true data forwarding. Data hazards immediately caused execution to diverge on branches.

### The Intervention: Introducing specialized datasets
We actively enriched the vector database with a highly curated **reference RISC-V repository codebase**. We ingested exact working examples of pipelined RISC-V cores.

### Impact
* **Smarter CodeBERT Retrievals**: When the model was tasked with generating `branch_unit.v`, the RAG pipeline surfaced the exact implementation patterns from the reference dataset. 
* **Accurate Bit-Slicing**: The immediate decoders were suddenly mathematically perfect natively.
* **Architectural Cohesiveness**: The LLM understood pipeline hazard detection naturally, producing standard 2-bit multiplexing forwarding paths (e.g., `forward_a = 2'b10`).

---

## Phase 4: Current State & The Final Mile

With the JSON contracts bounding the structure and the new datasets providing domain intuition, our pipeline is now achieving successful top-to-bottom compiles of a pipelined processor. 

However, functional ISA validation (running actual programs like `rv32ui-p-add`) currently scores 0/44. The system is fundamentally executing instructions and calculating jumps, but we are running into micro-architectural data-path edge cases.

### Remaining Hurdles to be Tackled

1. **Pipeline Register Bypassing**:
   * **The Bug**: We observed that the `pipeline_regs` occasionally bypassed stages, wiring `ID` outputs directly into `EX_MEM` inputs, preventing operations like `STORE` from getting the correct register values. 
   * **Future RAG Fix**: We need to inject stronger pipeline layout constraints in the RAG prompt, explicitly enforcing synchronous stage boundaries.

2. **Dangling Memory Interfaces**:
   * **The Bug**: The generation sometimes forgets to physically instance the data memory interaction (`mem[addr] <= wdata`). The `lsu` gets created but the data is unmapped in `top.v`. 
   * **Future RAG Fix**: Add a specialized "integration checklist" that the LLM must validate against the Reference Repository before finalizing `top.v`.

3. **Control Signal Glitches**:
   * **The Bug**: Specific operations like `LUI` allow uninitialized `rs1` bits to propagate forward, causing rogue ALU additions.
   * **Future RAG Fix**: Enhance the RAG with a "Micro-architectural Edge-Case" knowledge bank that queries for common RISC-V pitfalls (like LUI/AUIPC source isolation) prior to generation.

## Conclusion

Breaking down the generation task via **JSON Meta-contracts** stabilized the structure, while **High-Quality Context Injection (Reference Repos)** provided the functional intelligence. The remaining gap involves building in targeted sub-routines that analyze and correct synchronous pipelines — transitioning our system from "syntactically correct generation" to "verifiable behavioral generation".
