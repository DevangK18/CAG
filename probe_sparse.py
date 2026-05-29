"""Probe sparse vector vocab sync between index and query."""
from src.rag_pipeline.qdrant_service import QdrantService
from src.rag_pipeline.retrieval_service import SparseQueryEncoder
from qdrant_client.http.models import SparseVector

qs = QdrantService()
client = qs.client

# 1) Look at a few indexed sparse vectors
print("=== Sample indexed sparse vectors ===")
points, _ = client.scroll(qs.child_collection, limit=3, with_vectors=True, with_payload=True)
for p in points:
    sv = p.vector.get("sparse")
    if sv:
        top = sorted(zip(sv.indices, sv.values), key=lambda x: -x[1])[:8]
        print(f"\n  chunk_id={p.payload.get('chunk_id')}")
        print(f"    content[:120]: {p.payload.get('content','')[:120]}")
        print(f"    top sparse (idx,wt): {top}")

# 2) Encode a query and run a pure-sparse search
print("\n=== Pure-sparse search for distinctive term ===")
enc = SparseQueryEncoder()
q = "NHAI toll collection revenue loss"
qv = enc.encode(q)
print(f"Query: {q!r}")
print(f"  query top sparse: {sorted(zip(qv['indices'], qv['values']), key=lambda x: -x[1])[:8]}")
print(f"  query encoder vocab size after 1 query: {len(enc._vocab)}")

res = client.query_points(
    collection_name=qs.child_collection,
    query=SparseVector(indices=qv["indices"], values=qv["values"]),
    using="sparse",
    limit=5,
)
print(f"\n  Pure-sparse top-5 results:")
for h in res.points:
    print(f"    score={h.score:.4f}  {h.payload.get('content','')[:120]}")

# 3) Vocab overlap between query and a sample of the index
print("\n=== Vocab overlap check ===")
points, _ = client.scroll(qs.child_collection, limit=200, with_vectors=True)
idx_set = set()
for p in points:
    sv = p.vector.get("sparse")
    if sv:
        idx_set.update(sv.indices)
q_set = set(qv["indices"])
print(f"  Indexed indices (200 chunks): {len(idx_set)}")
print(f"  Query indices: {len(q_set)}")
print(f"  Overlap: {len(q_set & idx_set)}")