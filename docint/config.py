"""Single place for tunables. Only secrets/endpoints come from .env."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
VERSIONS = DATA / "versions"
INVENTORY = DATA / "inventory.json"
REVIEW_QUEUE = DATA / "review_queue.json"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
QDRANT_URL = os.getenv("QDRANT_URL") or None
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None

COLLECTION = "c16qs_docs"
CHAT_MODEL = "gpt-5.5"
CHAT_REASONING = "none"
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
TOP_K = 8             # passages shown to the model
CANDIDATES = 20       # per retriever before fusion
RRF_K = 60
MIN_COSINE = 0.30     # a passage below this is not evidence
OUT_OF_SCOPE_BELOW = 0.35

