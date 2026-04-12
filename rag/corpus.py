"""
RTL corpus ingestion: clone PicoRV32, Ibex, and Angelo RISC-V repos,
extract Verilog modules, embed with CodeBERT, store in ChromaDB.
"""

import os
import re
import logging
import subprocess
from pathlib import Path
from typing import Optional

import chromadb
import torch
from tqdm import tqdm
from transformers import AutoTokenizer, AutoModel

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(os.getenv("REPO_ROOT", Path(__file__).parent.parent))
RTL_SOURCES = REPO_ROOT / "data" / "rtl_sources"
CHROMA_PATH = REPO_ROOT / "data" / "chromadb"

# Point HuggingFace cache into repo-local directory
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

# ── Tokenization constants (approximate: 4 chars ≈ 1 token) ──────────────────
CHARS_PER_TOKEN = 4
MAX_EMBED_CHARS = 512 * CHARS_PER_TOKEN   # 2048 chars
MAX_SIG_CHARS   = 150 * CHARS_PER_TOKEN   # 600 chars

CODEBERT_MODEL = "microsoft/codebert-base"


class CorpusUnavailableError(RuntimeError):
    """Raised when zero RTL source files could be processed."""


# ── Repo cloning ───────────────────────────────────────────────────────────────

def clone_repos(timeout: int = 120) -> dict[str, bool]:
    """
    Git clone each repo into data/rtl_sources/ if not already present.
    Returns dict mapping repo_name -> success boolean.
    Failures are logged as warnings, not raised.
    """
    RTL_SOURCES.mkdir(parents=True, exist_ok=True)
    results: dict[str, bool] = {}

    for name, url in REPOS.items():
        dest = RTL_SOURCES / name
        if dest.exists() and (dest / ".git").exists():
            logger.info("Repo %s already cloned at %s", name, dest)
            results[name] = True
            continue
        logger.info("Cloning %s from %s ...", name, url)
        try:
            subprocess.run(
                ["git", "clone", "--depth=1", url, str(dest)],
                check=True,
                capture_output=True,
                timeout=timeout,
            )
            logger.info("Cloned %s successfully", name)
            results[name] = True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
            logger.warning("Failed to clone %s: %s", name, e)
            results[name] = False

    return results


# ── Text processing ────────────────────────────────────────────────────────────

def strip_copyright(text: str) -> str:
    """
    Remove leading copyright comment blocks (/* ... */ or consecutive // lines).
    Returns text starting from the first non-comment, non-blank line.
    """
    # Remove /* ... */ block comments at start
    text = re.sub(r"^\s*/\*.*?\*/\s*", "", text, flags=re.DOTALL)
    # Remove leading // comment lines
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
    """
    Regex-extract all `module ... endmodule` blocks from Verilog/SV text.
    Handles `endmodule : label` variant from SystemVerilog.
    Returns list of module text strings. Empty list if none found.
    """
    pattern = re.compile(
        r"\bmodule\b.*?\bendmodule\b(?:\s*:\s*\w+)?",
        re.DOTALL,
    )
    return pattern.findall(text)


def _find_largest_block(text: str) -> str:
    """
    Find the largest case/if block in Verilog text (proxy for decode table).
    Returns the block text, or empty string if none found.
    """
    # Find all case and if blocks (greedy for the biggest span)
    candidates: list[str] = []
    for pat in [r"case\s*\(.*?endcase", r"if\s*\(.*?(?=\s*(?:always|assign|module|endmodule|$))"]:
        for m in re.finditer(pat, text, re.DOTALL):
            candidates.append(m.group(0))
    if not candidates:
        return ""
    return max(candidates, key=len)


def make_embed_window(module_text: str) -> str:
    """
    Produce a <=512-token embedding window:
    1. Strip copyright from module_text.
    2. Extract module signature (up to MAX_SIG_CHARS).
    3. Find the largest case/if block in the body.
    4. Concatenate signature + truncation marker + largest_block.
    5. Truncate total to MAX_EMBED_CHARS characters.
    """
    cleaned = strip_copyright(module_text)

    # Extract module signature: everything up to the first ; or )
    sig_end = max(
        cleaned.find(");"),
        cleaned.find(");", cleaned.find("module")),
    )
    if sig_end == -1:
        sig_end = len(cleaned)
    sig_end = min(sig_end + 2, MAX_SIG_CHARS)
    signature = cleaned[:sig_end]

    body = cleaned[sig_end:]
    largest_block = _find_largest_block(body)

    if largest_block:
        window = signature + "\n// ...[BODY TRUNCATED]...\n" + largest_block
    else:
        window = cleaned

    return window[:MAX_EMBED_CHARS]


# ── CodeBERT embedding ─────────────────────────────────────────────────────────

def _mean_pool(last_hidden_state: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    """Mean pool last_hidden_state over non-padding tokens."""
    mask_expanded = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    sum_hidden = torch.sum(last_hidden_state * mask_expanded, dim=1)
    sum_mask = torch.clamp(mask_expanded.sum(dim=1), min=1e-9)
    return sum_hidden / sum_mask


def _codebert_embed(
    texts: list[str],
    model: AutoModel,
    tokenizer: AutoTokenizer,
    batch_size: int = 8,
) -> list[list[float]]:
    """
    Produce mean-pooled CodeBERT embeddings for a list of texts.
    Uses last_hidden_state mean pooling (NOT pooler_output / CLS token).
    Returns list of 768-dim float vectors.
    """
    all_embeddings: list[list[float]] = []
    device = next(model.parameters()).device

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        encoded = tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        ).to(device)
        with torch.no_grad():
            outputs = model(**encoded)
        embeddings = _mean_pool(outputs.last_hidden_state, encoded["attention_mask"])
        all_embeddings.extend(embeddings.cpu().tolist())

    return all_embeddings


# ── Main corpus build ──────────────────────────────────────────────────────────

def build_corpus(force_rebuild: bool = False) -> chromadb.Collection:
    """
    Build (or reuse) the RTL corpus in ChromaDB.

    Steps:
    1. clone_repos() — log per-repo success/failure.
    2. Load CodeBERT (microsoft/codebert-base).
    3. For each repo+whitelist file: read → extract_modules() → make_embed_window().
    4. Batch embed with _codebert_embed().
    5. Store in ChromaDB PersistentClient collection 'rtl_corpus' with cosine similarity.
       Metadata: source, filename, module_name, component_hint.
    6. If zero files processed, raise CorpusUnavailableError.

    If force_rebuild=False and collection already has documents, skip rebuild.
    Returns the ChromaDB collection.
    """
    CHROMA_PATH.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    collection = client.get_or_create_collection(
        "rtl_corpus",
        metadata={"hnsw:space": "cosine"},
    )

    if not force_rebuild and collection.count() > 0:
        logger.info("rtl_corpus already has %d documents, skipping rebuild.", collection.count())
        return collection

    # Clone repos
    clone_results = clone_repos()

    # Load CodeBERT
    logger.info("Loading CodeBERT model (%s) ...", CODEBERT_MODEL)
    tokenizer = AutoTokenizer.from_pretrained(CODEBERT_MODEL)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = AutoModel.from_pretrained(CODEBERT_MODEL).to(device).eval()
    logger.info("CodeBERT loaded on %s", device)

    # Collect documents
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
                # Header file or no module blocks — embed the whole file
                logger.debug("No module blocks in %s, embedding full file", rel_path)
                window = strip_copyright(source_text)[:MAX_EMBED_CHARS]
                stem = full_path.stem
                doc_id = f"{repo_name}::{stem}::0"
                documents.append(window)
                ids.append(doc_id)
                metadatas.append({
                    "source": repo_name,
                    "filename": rel_path,
                    "module_name": stem,
                    "component_hint": HINTS.get(stem, "unknown"),
                })
                continue

            for idx, mod_text in enumerate(modules):
                window = make_embed_window(mod_text)
                # Extract declared module name
                m = re.search(r"\bmodule\s+(\w+)", mod_text)
                module_name = m.group(1) if m else full_path.stem
                doc_id = f"{repo_name}::{full_path.stem}::{idx}"
                documents.append(window)
                ids.append(doc_id)
                metadatas.append({
                    "source": repo_name,
                    "filename": rel_path,
                    "module_name": module_name,
                    "component_hint": HINTS.get(module_name, HINTS.get(full_path.stem, "unknown")),
                })

    if not documents:
        raise CorpusUnavailableError(
            "No RTL source files were processed. Check network connectivity and repo availability."
        )

    logger.info("Embedding %d RTL document windows with CodeBERT ...", len(documents))
    embeddings = _codebert_embed(documents, model, tokenizer)

    # Clear and re-add (force_rebuild path)
    if force_rebuild and collection.count() > 0:
        existing = collection.get()
        if existing["ids"]:
            collection.delete(ids=existing["ids"])

    # Add in batches (ChromaDB has a default batch limit)
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
