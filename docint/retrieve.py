"""Dense, keyword (BM25) and hybrid (reciprocal-rank fusion) retrieval over the indexed passages."""
import re
from collections import defaultdict

import numpy as np
from qdrant_client import models
from rank_bm25 import BM25Okapi

from docint import config, store

_TOK = re.compile(r"[a-z0-9]+")
_P = {}


def tokens(text):
    return [t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t for t in _TOK.findall(text.lower())]


def _load(collection=None):
    """Every passage (all versions) once per collection, for BM25; filtering happens at query time."""
    collection = collection or config.COLLECTION
    if collection not in _P:
        c, docs, off = store.client(), [], None
        while True:
            pts, off = c.scroll(collection, limit=256, offset=off, with_payload=True, with_vectors=False)
            docs += [dict(p.payload, text=p.payload["page_content"]) for p in pts]
            if off is None:
                break
        docs.sort(key=lambda d: d["passage_id"])
        _P[collection] = (docs, BM25Okapi([tokens(d["title"] + " " + d["location"] + " " + d["text"]) for d in docs]) if docs else None)
    return _P[collection]


def reset_cache(collection=None):
    if collection:
        _P.pop(collection, None)
    else:
        _P.clear()


def _statuses(include):
    return set(include)


def _match(p, scope):
    return all(p.get(k) == v for k, v in scope.items())


def retrieve(question, mode="hybrid", k=config.TOP_K, include=("current",), collection=None, scopes=None, min_cosine=None):
    """-> (passages with dense_rank / keyword_rank / score fields, best cosine).
    `scopes` = list of {field: value} dicts; a passage is eligible if it matches any of them (e.g. one document version, or
    the website references). Without scopes, eligibility is by status."""
    collection = collection or config.COLLECTION
    docs, bm25 = _load(collection)
    if not docs:
        return [], 0.0
    vec = store.embeddings().embed_query(question)
    if scopes:
        flt = models.Filter(should=[models.Filter(must=[models.FieldCondition(key=f, match=models.MatchValue(value=v)) for f, v in sc.items()]) for sc in scopes])
        eligible = lambda d: any(_match(d, sc) for sc in scopes)
    else:
        ok = set(include)
        flt = models.Filter(must=[models.FieldCondition(key="status", match=models.MatchAny(any=list(ok)))])
        eligible = lambda d: d["status"] in ok
    dense = store.client().query_points(collection, query=vec, limit=config.CANDIDATES, query_filter=flt, with_payload=True).points
    dense_ids = [p.payload["passage_id"] for p in dense]
    cos = {p.payload["passage_id"]: float(p.score) for p in dense}
    sc = bm25.get_scores(tokens(question))
    kw = [(docs[i]["passage_id"], float(sc[i])) for i in np.argsort(-sc) if sc[i] > 0 and eligible(docs[i])][:config.CANDIDATES]
    kw_ids = [i for i, _ in kw]
    rank_d = {i: r + 1 for r, i in enumerate(dense_ids)}
    rank_k = {i: r + 1 for r, i in enumerate(kw_ids)}
    fused = defaultdict(float)
    if mode in ("dense", "hybrid"):
        for i, r in rank_d.items():
            fused[i] += 1 / (config.RRF_K + r)
    if mode in ("keyword", "hybrid"):
        for i, r in rank_k.items():
            fused[i] += 1 / (config.RRF_K + r)
    by_id = {d["passage_id"]: d for d in docs}
    out = []
    for i in sorted(fused, key=lambda x: -fused[x])[:k]:
        out.append(dict(by_id[i], dense_rank=rank_d.get(i), keyword_rank=rank_k.get(i), score=round(fused[i], 4),
                        cosine=round(cos[i], 3) if i in cos else None))
    return out, (max(cos.values()) if cos else 0.0)
