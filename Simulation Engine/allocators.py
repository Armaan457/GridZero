"""allocators.py - the three sharing policies. Pure functions: (pool, needs) -> {node: kWh}."""
EPS = 1e-9


def static_alloc(pool, needs):
    """STATIC: equal share to every needy node, capped at its need; leftovers re-split (water-filling)."""
    got = {n: 0.0 for n in needs}
    active = {n for n, v in needs.items() if v > EPS}
    while pool > EPS and active:
        share = pool / len(active)
        for n in list(active):
            give = min(share, needs[n] - got[n])
            got[n] += give
            pool -= give
            if needs[n] - got[n] <= EPS:
                active.discard(n)
    return got


def dynamic_alloc(pool, needs, policy="smallest_first"):
    """DYNAMIC: strict priority queue.
    smallest_first -> serve nodes whose need can be FULLY met first (max # of homes satisfied)
    largest_first  -> serve the neediest node first"""
    order = sorted(needs, key=needs.get, reverse=(policy == "largest_first"))
    got = {}
    for n in order:
        got[n] = min(needs[n], pool)
        pool -= got[n]
    return got


def hybrid_alloc(pool, needs, beta=0.5, policy="smallest_first"):
    """HYBRID: phase 1 = base equal share from beta*pool; phase 2 = priority queue on what is left."""
    base = static_alloc(pool * beta, needs)
    leftover_pool = pool - sum(base.values())
    residual = {n: needs[n] - base[n] for n in needs}
    extra = dynamic_alloc(leftover_pool, residual, policy)
    return {n: base[n] + extra[n] for n in needs}


MODES = {"static": static_alloc, "dynamic": dynamic_alloc, "hybrid": hybrid_alloc}
