"""Embeddings checks (opt-in: only runs with --embeddings).

Omnis's semantic recall (soft-skills, precedents, code, docs, registries) needs
an embeddings endpoint returning fixed-length vectors. Point --model at the
embedding model id when running this category.
"""

from core import check, Result, PASS, FAIL, WARN


@check("Embeddings endpoint", category="embeddings", critical=True,
       why="Omnis semantic recall requires POST /embeddings to return a vector for the configured embed model.")
def embeddings_basic(client):
    code, obj = client.post_json("/embeddings", {"model": client.model, "input": "hello world"})
    if code != 200:
        return Result(FAIL, "/embeddings returned %s" % code, data={"body": str(obj)[:400]})
    try:
        vec = obj["data"][0]["embedding"]
        dim = len(vec)
    except Exception as e:
        return Result(FAIL, "unexpected embeddings response: %s" % e, data={"body": str(obj)[:300]})
    return Result(PASS, "embeddings OK, dim=%d" % dim, data={"dim": dim})


@check("Embeddings: custom dimension", category="embeddings", critical=False,
       why="Matryoshka models (qwen3, text-embedding-3-*) can be truncated via `dimensions`; "
           "Omnis uses this to keep the index small.")
def embeddings_dimensions(client):
    code, obj = client.post_json("/embeddings", {"model": client.model, "input": "hello", "dimensions": 256})
    if code != 200:
        return Result(WARN, "endpoint rejected `dimensions` (status=%s)" % code, data={"body": str(obj)[:200]})
    try:
        dim = len(obj["data"][0]["embedding"])
    except Exception as e:
        return Result(WARN, "unexpected response: %s" % e)
    if dim == 256:
        return Result(PASS, "dimensions honored (got 256-d vector)")
    return Result(WARN, "dimensions=256 requested but got %d-d vector (not a Matryoshka model)" % dim)
