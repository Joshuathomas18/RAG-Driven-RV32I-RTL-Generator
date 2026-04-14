# Pipeline RV32I Reference Corpus Integration

This plan implements the final architectural enhancements for the RAG-driven RTL generator, focusing on integrating the `pietroglyph/pipelined-rv32i` reference corpus and enforcing strict hardware contracts for the `top.v` assembly layout.

## Proposed Changes

---

### Corpus Ingestion Core (rag/corpus.py)

#### [MODIFY] rag/corpus.py
1. **Repository Settings**: Add the new pipeline target to the `REPOS` dictionary:
   ```python
   "pietroglyph": "https://github.com/pietroglyph/pipelined-rv32i.git",
   ```
2. **Whitelist Additions**: Add specific architecture files to `WHITELIST`:
   ```python
   "pietroglyph": [
       "hdl/rv32i_pipelined_core.sv",
       "hdl/alu_behavioural.sv",
       "hdl/register_file.sv",
       "hdl/rv32i_defines.sv",
   ]
   ```
3. **Definition Extraction Function**: Introduce `extract_defines` to parse the `rv32i_defines.sv` files for enumerated definitions (opcodes, operations). This establishes the structured typing environment.
   ```python
   def extract_defines(path) -> str:
       # Regex to capture enum blocks from the referenced SV file.
   ```
4. **Export DEFINES Context**: Export `DEFINES_CONTEXT` at the module level. We will use a fallback (empty string) dynamically if the underlying repository hasn't been cloned yet upon first module import.

---

### Generation Pipeline and Contracts (rag/generator.py)

#### [MODIFY] rag/generator.py
1. **Contract Enrichment**: Import `DEFINES_CONTEXT` from `rag.corpus` and append it to our baseline `GLOBAL_CONTRACT` environment variable or dynamically inject it where the contract string is built up.
2. **Deterministic Port Extraction**: Introduce `extract_ports(verilog)` using pure Python Regular Expressions over the generated code. Replace the prior sequence evaluating the interface via the LLM API to save generation overhead and guarantee determinability.
   ```python
   def extract_ports(verilog: str) -> dict: ...
   ```
3. **Meta Generation Drop**: During `generate_with_lint_fix()`, directly dump `extract_ports(current_verilog)` logic out to `{module}_meta.json`. 
4. **Top Level Assembly Hook**: During `generate_top_v`, the orchestrator explicitly collects all eight `_meta.json` dependency graphs. They are subsequently surfaced into a distinct "EXACT PORT CONTRACTS" prompt section, establishing definitive guardrails against I/O hallucination.

## User Review Required

> [!WARNING]
> Due to the transition from LLM-generated port metadata to Regex-based extraction, are there any exotic SystemVerilog port declarations (e.g. interfaces, arrays, structs) we need to explicitly support in `extract_ports`? The standard regex logic handles pure widths (`[31:0]`) normally but may struggle if it discovers unpacked layouts.

## Verification Plan

### Automated Tests
- Trigger a build/verilator pipeline against the revised environment: `python scripts/run_pipeline.py`.
- Verify the generated `top.v` modules contain deterministic sub-module connections mapped specifically from `{module}_meta.json`.
