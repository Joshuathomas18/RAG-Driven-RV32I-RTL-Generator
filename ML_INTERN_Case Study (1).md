# Machine Learning Intern — RAG for Hardware Design Generation

> **** Complete the case study below and email your submission to **Careers@fermions.co**  
> Subject line: `ML Intern Application — <Your Full Name>`

# Case Study

### RAG-Driven RTL Generation for a Simple In-Order RISC-V Processor

## Overview

Large language models can write code — but writing **correct, synthesizable RTL** for a processor is a fundamentally harder problem than writing application software. A single off-by-one in a pipeline stage, a missing stall condition, or a wrong register file read port can cause silent functional failures that are invisible without simulation.

Read our article — **[Software Optimization vs. Silicon: Why AI Coding Assistants Fall Short in Hardware Design](https://www.linkedin.com/pulse/software-optimization-vs-silicon-why-ai-coding-assistants-wr5ie/)** — for context on exactly why this problem is interesting and unsolved. Your case study is a direct attempt to push the boundary it describes.

**Your task:** Design and implement a **RAG (Retrieval-Augmented Generation) pipeline** that generates correct Verilog RTL for a simple in-order RISC-V processor, then simulate and benchmark the result.

---

## Objective

We want to evaluate your ability to:

1. **Build a working RAG pipeline** — retrieval, chunking, embedding, generation — applied to a hardware design domain.
2. **Think critically about correctness** — RTL generation is not a vibe check. You need to verify the output works.
3. **Evaluate systematically** — use simulation and standard benchmarks to measure how well your pipeline performs.
4. **Understand the domain well enough** — you don't need to be an RTL engineer, but you need to understand what you're generating and why it might be wrong.

---

## The Target Design

You are generating RTL for a **simple in-order RV32I processor** — a 32-bit RISC-V core implementing the base integer instruction set. This is the smallest complete RISC-V ISA: 47 instructions covering arithmetic, loads/stores, branches, and jumps. No floating point, no compressed instructions, no privileged mode required.

A minimal in-order implementation has the following canonical stages:

```
Fetch → Decode → Execute → Memory → Writeback
```

Key components to generate:

| Component | Description |
|---|---|
| **Program Counter (PC)** | Holds current instruction address, updates on branch/jump or sequential increment |
| **Instruction Fetch** | Reads instruction from memory at PC |
| **Decoder** | Decodes opcode, funct3, rs1, rs2, rd, and immediate fields |
| **Register File** | 32 × 32-bit general-purpose registers (x0 hardwired to 0) |
| **ALU** | Performs ADD, SUB, AND, OR, XOR, SLT, shifts |
| **Branch Unit** | Evaluates BEQ, BNE, BLT, BGE, BLTU, BGEU conditions |
| **Load/Store Unit** | Handles LW, LH, LB, SW, SH, SB with byte-enable logic |
| **Control Hazard Handling** | Pipeline flush or stall on taken branches |

> You are **not** expected to implement caches, out-of-order execution, branch prediction, or privilege modes. Focus on a correct, functional RV32I core.

---

## Instructions

### Step 1 — Build Your Knowledge Base

Construct the corpus your RAG system will retrieve from. Think carefully about what information is actually useful for generating correct RTL. Your corpus should include at least some of the following:

- **The RISC-V RV32I specification** — instruction encodings, semantics, register conventions. The official unprivileged ISA spec is available at [riscv.org](https://riscv.org/technical/specifications/).
- **Reference RTL implementations** — open-source RISC-V cores (e.g., [PicoRV32](https://github.com/YosysHQ/picorv32), [SERV](https://github.com/olofk/serv), [ibex](https://github.com/lowRISC/ibex)) are excellent sources of correct RTL patterns.
- **Verilog design patterns** — FSM templates, pipeline register patterns, synchronous reset conventions, valid/ready handshake patterns.
- **Common RTL bugs and fixes** — documentation of known pitfalls (blocking vs non-blocking assignments, sensitivity list errors, signed/unsigned mismatches).

Document your corpus construction choices — what you included, how you chunked it, and why.

### Step 2 — Design the RAG Pipeline

Design your retrieval and generation pipeline. Address the following:

- **Chunking strategy** — how do you split RTL and spec documents? What granularity works best for hardware? (Hint: a Verilog module boundary is semantically very different from a paragraph boundary in prose.)
- **Embedding model** — what embedding model did you use or evaluate? Did you consider any code-specific or hardware-specific embeddings?
- **Retrieval strategy** — dense retrieval, sparse (BM25), hybrid? How many chunks do you retrieve per query?
- **Re-ranking** — did you apply any re-ranking step? What was the impact?
- **Generation prompt** — how do you structure the prompt? What context do you pass, and in what order?
- **Post-processing** — do you extract/clean the generated Verilog before passing it to simulation?

### Step 3 — Generate RTL

Use your pipeline to generate Verilog for the target components. You can approach this **component by component** (generate and verify each module individually) or **holistically** (prompt for a full processor and iterate).

Be explicit about:
- What prompts you used (include them in your submission)
- What the pipeline retrieved for each prompt
- How many iterations it took to get a simulatable result

### Step 4 — Simulate with Verilator

Use [Verilator](https://www.veripool.org/verilator/) to simulate and verify the generated RTL.

**Functional verification:**
- Run the [riscv-tests](https://github.com/riscv-software-src/riscv-tests) ISA test suite (`rv32ui` tests) against your core. Each test passes or fails — report the pass rate.
- A fully correct RV32I core should pass all `rv32ui-p-*` tests.

**Setup guidance:**
```bash
# Compile generated Verilog with Verilator
verilator --binary -j 0 -Wall top.v --exe sim_main.cpp

# Run a specific ISA test
./obj_dir/Vtop +load=rv32ui-p-add.hex
```

Document which tests pass, which fail, and your analysis of why specific failures occur.

### Step 5 — Benchmark

Run at least one standard benchmark on your simulated core and report the results:

| Benchmark | What It Measures |
|---|---|
| **[riscv-tests](https://github.com/riscv-software-src/riscv-tests)** (ISA tests) | Functional correctness — required |
| **[Dhrystone](https://github.com/riscv-software-src/riscv-tests/tree/master/benchmarks)** | Integer performance, included in riscv-tests benchmarks |
| **[CoreMark](https://github.com/riscv-boom/riscv-coremark)** | Industry-standard embedded CPU benchmark — optional but impressive |

Report your results as:
- ISA test pass rate (e.g., `42/47 rv32ui tests passing`)
- Dhrystone score in DMIPS or iterations/second (if achieved)
- Any other metrics you find meaningful (simulation cycles per instruction, etc.)

---

## What to Submit

A single Markdown file covering:

#### A. Corpus & Knowledge Base
- What sources did you use?
- How did you chunk and embed them?
- What retrieval approach did you use, and why?

#### B. Pipeline Design
- Architecture diagram or description of your RAG pipeline
- Key design decisions and trade-offs
- Tools and models used (LLM, embedding model, vector store, etc.)

#### C. Generated RTL
- Include your final generated Verilog (or link to a public repo)
- Show 2–3 example prompt → retrieval → generation traces to illustrate how the pipeline works

#### D. Simulation Results
- Verilator setup and testbench approach
- ISA test pass/fail table
- Benchmark results

#### E. Failure Analysis
- Where did your pipeline generate incorrect RTL?
- What were the most common failure modes?
- How did you debug and fix them — through better retrieval, better prompting, or manual correction?

#### F. Reflection
- What was the hardest part of this problem?
- What would you do differently with more time?
- What does this tell you about the limits of RAG for hardware generation?

---

## Submission Format

Submit a single **Markdown file** (`.md`) named:

```
submission_<your-first-name>_<your-last-name>.md
```

Your submission must begin with the following header:

```markdown
# RAG for RISC-V RTL — Submission

| Field           | Details                    |
|-----------------|----------------------------|
| **Name**        | <Your Full Name>           |
| **Email**       | <Your Email Address>       |
| **Phone**       | <Your Phone Number>        |
| **Country**     | <Your Country>             |
| **Date**        | <Submission Date>          |
| **LinkedIn**    | <LinkedIn Profile URL>     |
| **GitHub**      | <GitHub Profile URL>       |
```

Also link to a **public GitHub repository** containing your code, generated RTL, testbench, and simulation scripts.

**Email your completed submission to: [careers@fermions.co](mailto:careers@fermions.co)**  
Subject line: `ML Intern Application — <Your Full Name>`

---

## Evaluation Criteria

| Criteria | Weight |
|---|---|
| RAG pipeline design — quality, reasoning, and iteration | 30% |
| Correctness of generated RTL (ISA test pass rate) | 25% |
| Depth of failure analysis and debugging | 20% |
| Clarity of write-up and reproducibility of results | 15% |
| Benchmark results and reflection | 10% |

---

## Guidelines

- There is **no time limit**, but a strong submission can be done in **1–1.5 weekends**.
- You may use any LLM (GPT-4, Claude, Mistral, Llama, etc.) and any RAG framework (LangChain, LlamaIndex, custom, etc.).
- The generated RTL **must be simulated** — submissions without Verilator results will not be evaluated.
- You may manually fix generated RTL **but you must clearly document every manual change** and explain why the pipeline failed to produce it correctly. Undisclosed manual fixes are disqualifying.
- You are not expected to achieve 100% ISA test coverage — we care far more about your analysis of what works and what doesn't than a perfect score.
- Submissions must be in **`.md` (Markdown) format**. Other formats will not be reviewed.

---

> ⚠️ **Before submitting, re-read the [Evaluation Criteria](#evaluation-criteria) and [Guidelines](#guidelines) above to make sure your submission is complete.**
>
> 📩 **Send your submission to [careers@fermions.co](mailto:careers@fermions.co)**

*Good luck. We look forward to reading your work.*
