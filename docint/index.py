"""Embed passages and write them to Qdrant. Every stored version stays in the index with a `status`
(current / superseded / simulated) so retrieval can hide old revisions and still explain them."""
import uuid

from qdrant_client import models

from docint import chunking, config, store
from docint.fetch import load_inventory

META = ("passage_id", "doc_id", "version", "title", "url", "doc_type", "revision", "published", "date_note", "host", "provenance", "status",
        "location", "page", "chunk_type", "sha256")


def _points(passages, vectors):
    return [models.PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_URL, p["passage_id"])), vector=v,
                               payload={"page_content": p["text"], **{k: p[k] for k in META}})
            for p, v in zip(passages, vectors)]


def all_passages(inv=None):
    inv = inv or load_inventory()
    out = []
    for d in inv["documents"]:
        for v in d["versions"]:
            out += chunking.passages_for(d, v, config.ROOT)
    return out


def index_all():
    """Rebuild the collection from every stored version (idempotent)."""
    ps = all_passages()
    c = store.client()
    if not ps:
        if c.collection_exists(config.COLLECTION):
            c.delete_collection(config.COLLECTION)
        return 0
    vecs = store.embeddings().embed_documents([p["embed_text"] for p in ps])
    if c.collection_exists(config.COLLECTION):
        c.delete_collection(config.COLLECTION)
    c.create_collection(config.COLLECTION, vectors_config=models.VectorParams(size=len(vecs[0]), distance=models.Distance.COSINE))
    c.upsert(config.COLLECTION, _points(ps, vecs))
    ensure_indexes()
    return len(ps)


def ensure_collection():
    """Create the (empty) collection when the first document arrives, then make sure the filter indexes exist."""
    c = store.client()
    if not c.collection_exists(config.COLLECTION):
        c.create_collection(config.COLLECTION, vectors_config=models.VectorParams(size=config.EMBED_DIM, distance=models.Distance.COSINE))
    ensure_indexes()


def ensure_indexes():
    """Filters by document, status and version need payload indexes in Qdrant (creating one that exists is harmless)."""
    c = store.client()
    for f, kind in (("doc_id", models.PayloadSchemaType.KEYWORD), ("status", models.PayloadSchemaType.KEYWORD),
                    ("version", models.PayloadSchemaType.INTEGER)):
        c.create_payload_index(config.COLLECTION, f, kind)


def add_version(doc, version):
    """Index one new version (used by reindex)."""
    ps = chunking.passages_for(doc, version, config.ROOT)
    vecs = store.embeddings().embed_documents([p["embed_text"] for p in ps])
    store.client().upsert(config.COLLECTION, _points(ps, vecs))
    return len(ps)


def set_status(doc_id, version, status):
    c = store.client()
    c.set_payload(config.COLLECTION, payload={"status": status},
                  points=models.Filter(must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id)),
                                             models.FieldCondition(key="version", match=models.MatchValue(value=version))]))
