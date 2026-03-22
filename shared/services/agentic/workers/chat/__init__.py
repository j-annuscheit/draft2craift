"""Chat workers.

The chat workflow stays intentionally small: classify, retrieve, draft, gate,
and emit. Each worker module documents the exact state and tool contract.
"""
