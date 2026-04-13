"""
RTL corpus ingestion: clone PicoRV32, Ibex, and Angelo RISC-V repos,
extract Verilog modules, embed with CodeBERT, store in ChromaDB.

Task 1: RISC-V ISA spec ingestion (_ingest_riscv_spec).
Task 2: AI-generated chunk summaries (_generate_chunk_summary).
"""

import json
import logging
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import chromadb
import torch
from tqdm import tqdm
from transformers import AutoTokenizer, AutoModel

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(os.getenv("REPO_ROOT", Path(__file__).parent.parent))
RTL_SOURCES = REPO_ROOT / "data" / "rtl_sources"
CHROMA_PATH = REPO_ROOT / "data" / "chromadb"
CHUNK_SUMMARIES_CACHE = REPO_ROOT / "data" / "chunk_summaries.json"

os.environ.setdefault("HF_HOME", str(REPO_ROOT / "data" / "model_cache"))

# ── Repo config ────────────────────────────────────────────────────────────────
REPOS: dict[str, str] = {
    "picorv32": "https://github.com/YosysHQ/picorv32.git",
    "ibex":     "https://github.com/lowRISC/ibex.git",
    "angelo":   "https://github.com/AngeloJacobo/RISC-V.git",
}

WHITELIST: dict[str, list[str]] = {
    "picorv32": ["picorv32.v"],
    "ibex": [
        "rtl/ibex_alu.sv",
        "rtl/ibex_decoder.sv",
        "rtl/ibex_register_file_ff.sv",
        "rtl/ibex_load_store_unit.sv",
        "rtl/ibex_ex_block.sv",
    ],
    "angelo": [
        "rtl/rv32i_header.vh",
        "rtl/rv32i_alu.v",
        "rtl/rv32i_forwarding.v",
        "rtl/rv32i_decoder.v",
        "rtl/rv32i_writeback.v",
        "rtl/rv32i_basereg.v",
        "rtl/rv32i_memoryaccess.v",
    ],
}

HINTS: dict[str, str] = {
    "ibex_alu":                "alu",
    "ibex_ex_block":           "alu",
    "ibex_decoder":            "decoder",
    "ibex_register_file_ff":   "regfile",
    "ibex_load_store_unit":    "lsu",
    "picorv32":                "full_core",
    "rv32i_alu":               "alu",
    "rv32i_decoder":           "decoder",
    "rv32i_forwarding":        "hazard",
    "rv32i_basereg":           "regfile",
    "rv32i_memoryaccess":      "lsu",
    "rv32i_writeback":         "writeback",
}

CHARS_PER_TOKEN = 4
MAX_EMBED_CHARS = 512 * CHARS_PER_TOKEN
MAX_SIG_CHARS   = 150 * CHARS_PER_TOKEN

CODEBERT_MODEL = "microsoft/codebert-base"


class CorpusUnavailableError(RuntimeError):
    """Raised when zero RTL source files could be processed."""


# ── Task 1: RISC-V ISA Spec chunks ────────────────────────────────────────────
# Authoritative RV32I encoding tables from RISC-V ISA Manual Vol. I
RISCV_ISA_SPEC_CHUNKS: list[dict] = [
    {
        "id": "riscv_spec::formats",
        "title": "RV32I Instruction Formats",
        "component_hint": "decoder",
        "text": """\
RV32I INSTRUCTION FORMATS (RISC-V ISA Manual Vol. I, Chapter 2)
================================================================
All RV32I instructions are 32 bits wide, word-aligned.

R-type: funct7[31:25] | rs2[24:20] | rs1[19:15] | funct3[14:12] | rd[11:7] | opcode[6:0]
  Used by: ADD SUB SLL SLT SLTU XOR SRL SRA OR AND

I-type: imm[31:20] | rs1[19:15] | funct3[14:12] | rd[11:7] | opcode[6:0]
  imm sign-extended from bit 31. Used by: ADDI SLTI SLTIU XORI ORI ANDI SLLI SRLI SRAI JALR LB LH LW LBU LHU
  Shift immediates: shamt=inst[24:20], funct7=inst[31:25]

S-type: imm[11:5]=[31:25] | rs2[24:20] | rs1[19:15] | funct3[14:12] | imm[4:0]=[11:7] | opcode[6:0]
  imm = {inst[31:25], inst[11:7]}, sign-extended. Used by: SB SH SW

B-type: imm[12]=[31] | imm[10:5]=[30:25] | rs2[24:20] | rs1[19:15] | funct3[14:12] | imm[4:1]=[11:8] | imm[11]=[7] | opcode[6:0]
  imm = {inst[31], inst[7], inst[30:25], inst[11:8], 1'b0}, sign-extended (multiples of 2)
  Used by: BEQ BNE BLT BGE BLTU BGEU

U-type: imm[31:12]=[31:12] | rd[11:7] | opcode[6:0]
  imm = {inst[31:12], 12'b0}. Used by: LUI AUIPC

J-type: imm[20]=[31] | imm[10:1]=[30:21] | imm[11]=[20] | imm[19:12]=[19:12] | rd[11:7] | opcode[6:0]
  imm = {inst[31], inst[19:12], inst[20], inst[30:21], 1'b0}, sign-extended (multiples of 2)
  Used by: JAL
""",
    },
    {
        "id": "riscv_spec::opcodes",
        "title": "RV32I Opcode Map",
        "component_hint": "decoder",
        "text": """\
RV32I OPCODE MAP (inst[6:0])
============================
7'b0110011 = OP      (R-type): ADD SUB SLL SLT SLTU XOR SRL SRA OR AND
7'b0010011 = OP-IMM  (I-type): ADDI SLTI SLTIU XORI ORI ANDI SLLI SRLI SRAI
7'b0000011 = LOAD    (I-type): LB LH LW LBU LHU
7'b0100011 = STORE   (S-type): SB SH SW
7'b1100011 = BRANCH  (B-type): BEQ BNE BLT BGE BLTU BGEU
7'b1101111 = JAL     (J-type): JAL
7'b1100111 = JALR    (I-type): JALR  funct3=3'b000
7'b0110111 = LUI     (U-type): LUI
7'b0010111 = AUIPC   (U-type): AUIPC
7'b1110011 = SYSTEM  (I-type): ECALL EBREAK CSRRW CSRRS CSRRC CSRRWI CSRRSI CSRRCI
7'b0001111 = MISC-MEM(I-type): FENCE FENCE.I
""",
    },
    {
        "id": "riscv_spec::alu_ops",
        "title": "RV32I ALU Operation funct3/funct7 Encoding",
        "component_hint": "alu",
        "text": """\
RV32I ALU OPERATIONS — funct3 and funct7 encoding
===================================================
OP (7'b0110011) R-type:
  ADD:  funct7=7'b0000000  funct3=3'b000   rd = rs1 + rs2
  SUB:  funct7=7'b0100000  funct3=3'b000   rd = rs1 - rs2
  SLL:  funct7=7'b0000000  funct3=3'b001   rd = rs1 << rs2[4:0]
  SLT:  funct7=7'b0000000  funct3=3'b010   rd = ($signed(rs1) < $signed(rs2)) ? 1 : 0
  SLTU: funct7=7'b0000000  funct3=3'b011   rd = (rs1 < rs2) ? 1 : 0
  XOR:  funct7=7'b0000000  funct3=3'b100   rd = rs1 ^ rs2
  SRL:  funct7=7'b0000000  funct3=3'b101   rd = rs1 >> rs2[4:0]
  SRA:  funct7=7'b0100000  funct3=3'b101   rd = $signed(rs1) >>> rs2[4:0]
  OR:   funct7=7'b0000000  funct3=3'b110   rd = rs1 | rs2
  AND:  funct7=7'b0000000  funct3=3'b111   rd = rs1 & rs2

OP-IMM (7'b0010011) I-type (imm = inst[31:20] sign-extended):
  ADDI:  funct3=3'b000  SLTI:3'b010  SLTIU:3'b011  XORI:3'b100  ORI:3'b110  ANDI:3'b111
  SLLI:  funct3=3'b001  funct7=7'b0000000  shamt=inst[24:20]
  SRLI:  funct3=3'b101  funct7=7'b0000000  shamt=inst[24:20]
  SRAI:  funct3=3'b101  funct7=7'b0100000  shamt=inst[24:20]
""",
    },
    {
        "id": "riscv_spec::branch",
        "title": "RV32I Branch/Jump Instructions",
        "component_hint": "alu",
        "text": """\
RV32I BRANCH AND JUMP INSTRUCTIONS
===================================
BRANCH (7'b1100011) B-type:
  BEQ:3'b000  BNE:3'b001  BLT:3'b100  BGE:3'b101  BLTU:3'b110  BGEU:3'b111
  BLT/BGE use $signed comparison; BLTU/BGEU unsigned
  Target = PC + B-imm (sign-extended, multiple of 2)

JAL (7'b1101111) J-type:
  rd = PC + 4 (return address)
  PC = PC + J-imm (sign-extended, multiple of 2)

JALR (7'b1100111) I-type: funct3=3'b000
  rd = PC + 4; PC = (rs1 + I-imm) & ~32'h1

LUI (7'b0110111): rd = {inst[31:12], 12'b0}
AUIPC (7'b0010111): rd = PC + {inst[31:12], 12'b0}
""",
    },
    {
        "id": "riscv_spec::memory",
        "title": "RV32I Memory/Load/Store Instructions",
        "component_hint": "lsu",
        "text": """\
RV32I MEMORY ACCESS INSTRUCTIONS
==================================
LOAD (7'b0000011) I-type — effective address = rs1 + imm:
  LB:3'b000 sign-extend byte   LH:3'b001 sign-extend half   LW:3'b010 word
  LBU:3'b100 zero-extend byte  LHU:3'b101 zero-extend half

STORE (7'b0100011) S-type — effective address = rs1 + S-imm:
  SB:3'b000  SH:3'b001  SW:3'b010

RV32I is little-endian. funct3[1:0]=size(00=byte,01=half,10=word) funct3[2]=zero-extend
Byte enables for word-addressed store:
  SW: mem_be=4'b1111
  SH: mem_be = addr[1] ? 4'b1100 : 4'b0011
  SB: mem_be = 4'b0001 << addr[1:0]
""",
    },
    {
        "id": "riscv_spec::csr",
        "title": "RV32I System/CSR Instructions",
        "component_hint": "full_core",
        "text": """\
RV32I SYSTEM AND CSR INSTRUCTIONS
===================================
SYSTEM (7'b1110011):
  ECALL:  funct3=3'b000 rs1=0 rd=0 imm=0
  EBREAK: funct3=3'b000 rs1=0 rd=0 imm=1

Zicsr: CSR address = inst[31:20]
  CSRRW:3'b001  CSRRS:3'b010  CSRRC:3'b011
  CSRRWI:3'b101 CSRRSI:3'b110 CSRRCI:3'b111

Key CSR addresses for riscv-tests:
  mstatus=12'h300  mtvec=12'h305  mepc=12'h341  mcause=12'h342
  mhartid=12'hF14  (MUST return 32'h0; never trap on write)
""",
    },
]


def _ingest_riscv_spec(
    collection: chromadb.Collection,
    model,
    tokenizer,
) -> int:
    """Embed and store RISC-V ISA spec encoding tables. Returns chunks added."""
    try:
        existing = collection.get(where={"source": {"$eq": "riscv_spec"}})
        if existing["ids"]:
            logger.info("RISC-V spec already in corpus (%d chunks), skipping.", len(existing["ids"]))
            return 0
    except Exception:
        pass

    logger.info("Ingesting RISC-V ISA spec (%d chunks) ...", len(RISCV_ISA_SPEC_CHUNKS))
    documents = [c["text"] for c in RISCV_ISA_SPEC_CHUNKS]
    ids = [c["id"] for c in RISCV_ISA_SPEC_CHUNKS]
    metadatas = [
        {
            "source": "riscv_spec",
            "filename": "riscv-isa-manual/rv32i",
            "module_name": c["title"],
            "component_hint": c["component_hint"],
        }
        for c in RISCV_ISA_SPEC_CHUNKS
    ]
    embeddings = _codebert_embed(documents, model, tokenizer)
    collection.add(documents=documents, embeddings=embeddings, ids=ids, metadatas=metadatas)
    logger.info("RISC-V spec: %d chunks stored.", len(RISCV_ISA_SPEC_CHUNKS))
    return len(RISCV_ISA_SPEC_CHUNKS)


# ── Task 2: AI-generated chunk summaries ──────────────────────────────────────

def _load_summary_cache() -> dict[str, str]:
    if CHUNK_SUMMARIES_CACHE.exists():
        try:
            return json.loads(CHUNK_SUMMARIES_CACHE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_summary_cache(cache: dict[str, str]) -> None:
    CHUNK_SUMMARIES_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CHUNK_SUMMARIES_CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _call_llm_for_summary(module_text: str) -> str:
    """Call LLM for a 1-sentence description of a Verilog module. Returns '' on failure."""
    if os.environ.get("OPENROUTER_API_KEY"):
        url = "https://openrouter.ai/api/v1/chat/completions"
        model = os.environ.get("OPENROUTER_MODEL", "gpt-4o-mini")
        auth = os.environ["OPENROUTER_API_KEY"]
    elif os.environ.get("GROQ_API_KEY"):
        url = "https://api.groq.com/openai/v1/chat/completions"
        model = "llama-3.3-70b-versatile"
        auth = os.environ["GROQ_API_KEY"]
    else:
        return ""

    prompt = (
        "In one sentence, describe the exact role of this Verilog module "
        "in a RISC-V 5-stage pipeline. Be specific:\n\n" + module_text[:800]
    )
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 80,
        "temperature": 0.0,
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={
                "Authorization": f"Bearer {auth}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/google-deepmind/antigravity", # Optional
                "X-Title": "Antigravity RTL Generator",                         # Optional
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.debug("Summary LLM call failed: %s", e)
        return ""


def _generate_chunk_summary(module_text: str, cache_key: str, cache: dict[str, str]) -> str:
    """Return cached or newly-generated summary. Updates cache in-place."""
    if cache_key in cache:
        return cache[cache_key]
    summary = _call_llm_for_summary(module_text)
    if summary:
        cache[cache_key] = summary
    return summary


# ── Repo cloning ───────────────────────────────────────────────────────────────

def clone_repos(timeout: int = 120) -> dict[str, bool]:
    RTL_SOURCES.mkdir(parents=True, exist_ok=True)
    results: dict[str, bool] = {}
    for name, url in REPOS.items():
        dest = RTL_SOURCES / name
        if dest.exists() and (dest / ".git").exists():
            logger.info("Repo %s already cloned.", name)
            results[name] = True
            continue
        logger.info("Cloning %s ...", name)
        try:
            subprocess.run(
                ["git", "clone", "--depth=1", url, str(dest)],
                check=True, capture_output=True, timeout=timeout,
            )
            results[name] = True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
            logger.warning("Failed to clone %s: %s", name, e)
            results[name] = False
    return results


# ── Text processing ────────────────────────────────────────────────────────────

def strip_copyright(text: str) -> str:
    text = re.sub(r"^\s*/\*.*?\*/\s*", "", text, flags=re.DOTALL)
    lines = text.splitlines(keepends=True)
    start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("//") or stripped == "":
            start = i + 1
        else:
            break
    return "".join(lines[start:])


def extract_modules(text: str) -> list[str]:
    pattern = re.compile(r"\bmodule\b.*?\bendmodule\b(?:\s*:\s*\w+)?", re.DOTALL)
    return pattern.findall(text)


def _find_largest_block(text: str) -> str:
    candidates: list[str] = []
    for pat in [r"case\s*\(.*?endcase", r"if\s*\(.*?(?=\s*(?:always|assign|module|endmodule|$))"]:
        for m in re.finditer(pat, text, re.DOTALL):
            candidates.append(m.group(0))
    if not candidates:
        return ""
    return max(candidates, key=len)


def make_embed_window(module_text: str, summary: str = "") -> str:
    """
    Build <=512-token embedding window.
    Task 2: Prepends '// ROLE: {summary}' when summary is provided.
    """
    prefix = f"// ROLE: {summary}\n" if summary else ""
    cleaned = strip_copyright(module_text)
    sig_end = max(cleaned.find(");"), cleaned.find(");", cleaned.find("module")))
    if sig_end == -1:
        sig_end = len(cleaned)
    sig_end = min(sig_end + 2, MAX_SIG_CHARS)
    signature = cleaned[:sig_end]
    body = cleaned[sig_end:]
    largest_block = _find_largest_block(body)
    window = signature + "\n// ...[BODY TRUNCATED]...\n" + largest_block if largest_block else cleaned
    return (prefix + window)[:MAX_EMBED_CHARS]


# ── CodeBERT embedding ─────────────────────────────────────────────────────────

def _mean_pool(last_hidden_state: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    mask_expanded = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    sum_hidden = torch.sum(last_hidden_state * mask_expanded, dim=1)
    sum_mask = torch.clamp(mask_expanded.sum(dim=1), min=1e-9)
    return sum_hidden / sum_mask


def _codebert_embed(texts: list[str], model, tokenizer, batch_size: int = 8) -> list[list[float]]:
    all_embeddings: list[list[float]] = []
    device = next(model.parameters()).device
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        encoded = tokenizer(batch, padding=True, truncation=True, max_length=512, return_tensors="pt").to(device)
        with torch.no_grad():
            outputs = model(**encoded)
        embeddings = _mean_pool(outputs.last_hidden_state, encoded["attention_mask"])
        all_embeddings.extend(embeddings.cpu().tolist())
    return all_embeddings


# ── Main corpus build ──────────────────────────────────────────────────────────

def build_corpus(force_rebuild: bool = False) -> chromadb.Collection:
    """
    Build (or reuse) the RTL corpus in ChromaDB.
    Task 1: Ingest RISC-V ISA spec encoding tables.
    Task 2: Generate AI summaries for each module chunk, cache to disk.
    """
    CHROMA_PATH.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    collection = client.get_or_create_collection("rtl_corpus", metadata={"hnsw:space": "cosine"})

    if not force_rebuild and collection.count() > 0:
        logger.info("rtl_corpus already has %d documents, skipping rebuild.", collection.count())
        return collection

    clone_results = clone_repos()

    logger.info("Loading CodeBERT model (%s) ...", CODEBERT_MODEL)
    tokenizer = AutoTokenizer.from_pretrained(CODEBERT_MODEL)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = AutoModel.from_pretrained(CODEBERT_MODEL).to(device).eval()
    logger.info("CodeBERT loaded on %s", device)

    if force_rebuild and collection.count() > 0:
        existing = collection.get()
        if existing["ids"]:
            collection.delete(ids=existing["ids"])

    # Task 1: Ingest RISC-V ISA spec
    _ingest_riscv_spec(collection, model, tokenizer)

    # Task 2: Load summary cache
    summary_cache = _load_summary_cache()
    cache_dirty = False

    documents: list[str] = []
    ids: list[str] = []
    metadatas: list[dict] = []

    for repo_name, file_list in WHITELIST.items():
        if not clone_results.get(repo_name, False):
            logger.warning("Skipping %s (clone failed)", repo_name)
            continue
        repo_dir = RTL_SOURCES / repo_name
        for rel_path in file_list:
            full_path = repo_dir / rel_path
            if not full_path.exists():
                logger.warning("File not found: %s", full_path)
                continue
            source_text = full_path.read_text(errors="replace")
            modules = extract_modules(source_text)

            if not modules:
                stem = full_path.stem
                cache_key = f"{repo_name}::{stem}::0"
                summary = _generate_chunk_summary(source_text[:800], cache_key, summary_cache)
                if summary:
                    cache_dirty = True
                documents.append(make_embed_window(source_text, summary=summary))
                ids.append(cache_key)
                metadatas.append({
                    "source": repo_name, "filename": rel_path,
                    "module_name": stem, "component_hint": HINTS.get(stem, "unknown"),
                })
                continue

            for idx, mod_text in enumerate(modules):
                m = re.search(r"\bmodule\s+(\w+)", mod_text)
                module_name = m.group(1) if m else full_path.stem
                doc_id = f"{repo_name}::{full_path.stem}::{idx}"
                summary = _generate_chunk_summary(mod_text, doc_id, summary_cache)
                if summary:
                    cache_dirty = True
                documents.append(make_embed_window(mod_text, summary=summary))
                ids.append(doc_id)
                metadatas.append({
                    "source": repo_name, "filename": rel_path,
                    "module_name": module_name,
                    "component_hint": HINTS.get(module_name, HINTS.get(full_path.stem, "unknown")),
                })

    if cache_dirty:
        _save_summary_cache(summary_cache)
        logger.info("Chunk summaries cached to %s", CHUNK_SUMMARIES_CACHE)

    if not documents:
        raise CorpusUnavailableError("No RTL source files were processed.")

    logger.info("Embedding %d RTL document windows with CodeBERT ...", len(documents))
    embeddings = _codebert_embed(documents, model, tokenizer)

    BATCH = 100
    for i in tqdm(range(0, len(documents), BATCH), desc="Storing corpus"):
        collection.add(
            documents=documents[i : i + BATCH],
            embeddings=embeddings[i : i + BATCH],
            ids=ids[i : i + BATCH],
            metadatas=metadatas[i : i + BATCH],
        )

    logger.info("rtl_corpus built: %d documents stored.", collection.count())
    return collection
