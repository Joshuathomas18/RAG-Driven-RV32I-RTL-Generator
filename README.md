# RAG-Driven RV32I RTL Generator

A RAG (Retrieval-Augmented Generation) pipeline that generates correct Verilog RTL for a 5-stage in-order RV32I processor, verifies every file with Verilator lint (automated fix loop), simulates with Verilator, and validates against 42 riscv-tests.

```text
                 ┌──────────────────────────────────────────────────┐
                 │                RETRIEVAL PIPELINE                │
  Corpus         │                                                  │
                 │ ┌──────────────┐     ┌────────────────┐          │
 pipelined-rv32i ──►  rtl_corpus  ├────►│  RRF (k=60)    │          │
 (Golden Repo)   │ │  (CodeBERT)  │     │  BM25 + Dense  │          │
                 │ └──────────────┘     └───────┬────────┘          │
                 │                              │                   │
                 │ ┌──────────────┐     ┌───────▼────────┐          │
  Bug Patterns  ───►  knowledge_  │     │ Cross-Encoder  │◄── query │
  ISA Spec       │ │  corpus      ├────►│  Re-Ranker     │          │
                 │ │  (MiniLM)    │     │  (ms-marco)    │          │
                 │ └──────────────┘     └───────┬────────┘          │
                 └──────────────────────────────┼───────────────────┘
                                                │ context
                                                ▼
                 ┌──────────────────────────────────────────────────┐
                 │           TWO-PHASE LLM GENERATOR                │
                 │                                                  │
                 │  ┌────────────────┐         ┌─────────────────┐  │
                 │  │    Phase 1     │ strict  │     Phase 2     │  │
                 │  │ JSON Interface ├────────►│  Verilog Body   │  │
                 │  │ Contract Gen   │ bounds  │  Generation     │  │
                 │  └────────────────┘         └───────┬─────────┘  │
                 └─────────────────────────────────────┼────────────┘
                                                       │ .v files
                                                       ▼
                 ┌──────────────────────────────────────────────────┐
                 │             VERIFICATION & SIMULATION            │
                 │                                                  │
                 │  ┌────────────────┐         ┌─────────────────┐  │
                 │  │ Verilator Lint │ syntax  │  Verilator Sim  │  │
                 │  │ Automated Fix  ├────────►│  C++ Testbench  │  │
                 │  │ Loop (Max 5)   │ passed  │  Detect JAL-loop│  │
                 │  └────────────────┘         └─────────────────┘  │
                 └──────────────────────────────────────────────────┘
```

## Prerequisites

```bash
# Verilator
sudo apt install verilator

# RISC-V toolchain
sudo apt install gcc-riscv64-unknown-elf binutils-riscv64-unknown-elf

# Python 3.11+
python3 --version
```

## Quick Start

```bash
git clone <this-repo>
cd RAG-Driven-RV32I-RTL-Generator
pip install -r requirements.txt
cp .env.example .env
# Edit .env — set OPENROUTER_API_KEY
python scripts/run_pipeline.py
```

## Module Descriptions

| Module | Purpose |
|--------|---------|
| `rag/corpus.py` | Clone PicoRV32/Ibex/Angelo repos, extract Verilog modules, embed with CodeBERT, store in ChromaDB |
| `rag/knowledge.py` | Embed 28 bug patterns + debug lessons + Angelo patterns with MiniLM |
| `rag/pipeline.py` | Hybrid retrieval: deterministic by module name + BM25+semantic fallback + Cross-Encoder re-ranking |
| `rag/generator.py` | Two-Phase LLM generation via OpenRouter: Phase 1 (JSON Interface) -> Phase 2 (Verilog Body) + Verilator lint-fix loop |
| `scripts/run_pipeline.py` | Main entry: build corpus → generate 9 modules → compile → test |
| `sim/sim_main.cpp` | Verilator C++ testbench (reset 10 cycles, run 500k cycles) |
| `sim/run_tests.py` | Run all 42 rv32ui-p-* riscv-tests, detect PASS via JAL-self-loop |

## Running Tests

```bash
# After generating RTL:
pytest tests/test_lint.py -v

# Run ISA tests standalone:
python sim/run_tests.py

# Skip corpus/knowledge rebuild (use existing ChromaDB):
python scripts/run_pipeline.py --skip-corpus --skip-knowledge

# Generate only specific modules:
python scripts/run_pipeline.py --modules alu,regfile,decoder
```

## Results

After a full run:
- `results/generation_log.jsonl` — per-attempt generation log (module, attempt, errors, tokens)
- `results/isa_results.md` — pass/fail table for all 42 ISA tests

## Troubleshooting

**Verilator not found:** `sudo apt install verilator`

**RISC-V toolchain not found:** `sudo apt install gcc-riscv64-unknown-elf`

**riscv-tests not found:** Script will auto-clone from GitHub into `data/riscv-tests/`. Pre-built ELFs are included in the repo.

**ChromaDB errors:** Delete `data/chromadb/` and re-run to rebuild from scratch.

**HuggingFace model download slow:** Models cache to `data/model_cache/` (set via `HF_HOME`). First run downloads ~500MB (CodeBERT) + ~90MB (MiniLM).

**OPENROUTER_API_KEY not set:** Copy `.env.example` to `.env` and set your OpenRouter key.
