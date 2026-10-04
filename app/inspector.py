"""Static rule checker for candidate paths (POST /inspect).

Unlike :func:`app.solver.solve_board`, this module never solves anything:
it takes one ordered candidate path per net and reports *every* routing
violation it can find.  One bad net does not stop the audit of the other
nets or of the remaining rules.

Rules (see README)::

    ENDPOINT_MISMATCH      first/last step is not pads[0]/pads[1]
    CELL_OUT_OF_BOUNDS     step coordinate outside the board
    ILLEGAL_LAYER          step layer is not 0/1
    BLOCKED_CELL           step lands on a blocked cell
    DUPLICATE_CELL         one net occupies one (x, y, layer) twice
    NON_ORTHOGONAL_STEP    same-layer consecutive steps are not an
                           orthogonal unit move
    LAYER_CHANGE_OFFSET    a layer change between consecutive steps does
                           not keep the same (x, y) coordinate
    VIA_LIMIT              more vias (coordinates occupied on both layers)
                           than the net's via_limit
    CROSS_NET_COINCIDE     two nets occupy the same cell on one layer
    CROSS_NET_ADJACENT     two nets occupy orthogonally adjacent cells on
                           the same layer

Illegal layers and out-of-bounds coordinates are *violations*, never
rejected requests (HTTP 422 is reserved for malformed input).  Cross-net
rules only compare in-bounds cells on legal layers; blocked cells still
take part in the comparison.

Cross-net adjacency is direction independent: every undirected
orthogonal edge of the board is enumerated exactly once and each
*unordered* net pair that faces the other net across that edge produces
exactly one violation, regardless of which net has the smaller index or
which side of the edge it occupies.  Relying on "only report when the
left/upper net has the smaller index" silently missed conflicts whenever
a low-numbered net was routed to the right of or below a higher-numbered
net.
"""
from __future__ import annotations

from collections import defaultdict

from .schemas import (
    InspectRequest,
    InspectResponse,
    InspectViolation,
    ViolationCell,
)

RULE_ENDPOINT = "ENDPOINT_MISMATCH"
RULE_OUT_OF_BOUNDS = "CELL_OUT_OF_BOUNDS"
RULE_ILLEGAL_LAYER = "ILLEGAL_LAYER"
RULE_BLOCKED = "BLOCKED_CELL"
RULE_DUPLICATE = "DUPLICATE_CELL"
RULE_NON_ORTHOGONAL = "NON_ORTHOGONAL_STEP"
RULE_LAYER_CHANGE_OFFSET = "LAYER_CHANGE_OFFSET"
RULE_VIA_LIMIT = "VIA_LIMIT"
RULE_CROSS_COINCIDE = "CROSS_NET_COINCIDE"
RULE_CROSS_ADJACENT = "CROSS_NET_ADJACENT"


def _vcell(cell: tuple[int, int, int]) -> ViolationCell:
    return ViolationCell(x=cell[0], y=cell[1], layer=cell[2])


def inspect_board(req: InspectRequest) -> InspectResponse:
    w, h = req.width, req.height
    blocked = {(c.x, c.y, c.layer) for c in req.blocked}
    paths = [
        [(c.x, c.y, c.layer) for c in path]
        for path in req.paths
    ]

    violations: list[InspectViolation] = []

    # cell -> {net index: step indices (in path order) at which the net
    # occupies it}; only in-bounds, legal-layer cells participate in the
    # cross-net rules, blocked cells included.
    occupied: dict[tuple[int, int, int], dict[int, list[int]]] = defaultdict(dict)

    for k, (net, path) in enumerate(zip(req.nets, paths)):
        src = (net.pads[0].x, net.pads[0].y, net.pads[0].layer)
        dst = (net.pads[1].x, net.pads[1].y, net.pads[1].layer)

        # ---- endpoints (an empty path matches neither pad) -------------
        if not path or path[0] != src:
            violations.append(
                InspectViolation(
                    rule=RULE_ENDPOINT,
                    nets=[k],
                    steps=[[]],
                    cells=[_vcell(src)],
                )
            )
        if not path or path[-1] != dst:
            violations.append(
                InspectViolation(
                    rule=RULE_ENDPOINT,
                    nets=[k],
                    steps=[[]],
                    cells=[_vcell(dst)],
                )
            )

        # ---- per-cell rules: bounds, layer, blocked, duplicate ---------
        seen: dict[tuple[int, int, int], list[int]] = defaultdict(list)
        # layers used at each in-bounds coordinate, with their step indices
        layers_at: dict[tuple[int, int], dict[int, list[int]]] = defaultdict(
            lambda: {0: [], 1: []}
        )
        for i, cell in enumerate(path):
            x, y, layer = cell
            in_bounds = 0 <= x < w and 0 <= y < h
            legal_layer = layer in (0, 1)
            if not in_bounds:
                violations.append(
                    InspectViolation(
                        rule=RULE_OUT_OF_BOUNDS,
                        nets=[k],
                        steps=[[i]],
                        cells=[_vcell(cell)],
                    )
                )
            if not legal_layer:
                violations.append(
                    InspectViolation(
                        rule=RULE_ILLEGAL_LAYER,
                        nets=[k],
                        steps=[[i]],
                        cells=[_vcell(cell)],
                    )
                )
            if in_bounds and legal_layer:
                if cell in blocked:
                    violations.append(
                        InspectViolation(
                            rule=RULE_BLOCKED,
                            nets=[k],
                            steps=[[i]],
                            cells=[_vcell(cell)],
                        )
                    )
                occupied[cell].setdefault(k, []).append(i)
                layers_at[(x, y)][layer].append(i)
            seen[cell].append(i)

        for cell, idxs in seen.items():
            if len(idxs) > 1:  # repeated visit: keep every step number
                violations.append(
                    InspectViolation(
                        rule=RULE_DUPLICATE,
                        nets=[k],
                        steps=[sorted(idxs)],
                        cells=[_vcell(cell)],
                    )
                )

        # ---- per-step rules --------------------------------------------
        for i, (a, b) in enumerate(zip(path, path[1:])):
            if a[2] == b[2]:
                if abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
                    violations.append(
                        InspectViolation(
                            rule=RULE_NON_ORTHOGONAL,
                            nets=[k],
                            steps=[[i, i + 1]],
                            cells=[_vcell(a), _vcell(b)],
                        )
                    )
            elif a[:2] != b[:2]:
                violations.append(
                    InspectViolation(
                        rule=RULE_LAYER_CHANGE_OFFSET,
                        nets=[k],
                        steps=[[i, i + 1]],
                        cells=[_vcell(a), _vcell(b)],
                    )
                )

        # ---- vias: a via is a coordinate occupied on BOTH layers -------
        via_coords = [
            xy
            for xy, layers in layers_at.items()
            if layers[0] and layers[1]
        ]
        n_vias = len(via_coords)
        if n_vias > net.via_limit:
            via_steps = sorted(
                i
                for xy in via_coords
                for layer in (0, 1)
                for i in layers_at[xy][layer]
            )
            via_cells = [
                _vcell((x, y, layer))
                for (x, y) in sorted(via_coords)
                for layer in (0, 1)
            ]
            violations.append(
                InspectViolation(
                    rule=RULE_VIA_LIMIT,
                    nets=[k],
                    steps=[via_steps],
                    cells=via_cells,
                    via_count=n_vias,
                    via_limit=net.via_limit,
                )
            )

    # ---- cross-net rules (in-bounds legal-layer cells only) -------------
    # Each undirected orthogonal edge is enumerated exactly once by looking
    # only at the +x/+y neighbour (a pair A|B is never re-examined as B|A),
    # making the audit independent of the direction the nets were routed in.
    for cell, at in occupied.items():
        nets_at = sorted(at)
        # coincidence: every pair of distinct nets sharing the cell
        # (three nets on one cell reports three pairs)
        for a in range(len(nets_at)):
            for b in range(a + 1, len(nets_at)):
                i, j = nets_at[a], nets_at[b]
                violations.append(
                    InspectViolation(
                        rule=RULE_CROSS_COINCIDE,
                        nets=[i, j],
                        steps=[sorted(at[i]), sorted(at[j])],
                        cells=[_vcell(cell), _vcell(cell)],
                    )
                )
        # adjacency on this undirected edge: collect which nets occupy which
        # of the two endpoints, then report, once per edge, every net pair
        # that faces the other net across the edge.  Net order (i < j)
        # decides the reporting order but never whether a pair is reported,
        # so a low-numbered net routed to the right of/below a higher one is
        # caught just the same.
        x, y, layer = cell
        for dx, dy in ((1, 0), (0, 1)):
            nb = (x + dx, y + dy, layer)
            at_nb = occupied.get(nb)
            if not at_nb:
                continue
            net_ids = sorted(set(at) | set(at_nb))
            first, second = sorted((cell, nb))
            for a in range(len(net_ids)):
                for b in range(a + 1, len(net_ids)):
                    i, j = net_ids[a], net_ids[b]
                    # each net must actually sit on an endpoint: the pair
                    # faces across the edge iff one occupies an endpoint the
                    # other does not (in either orientation).  Two nets that
                    # merely coincide at a single endpoint are handled by
                    # CROSS_NET_COINCIDE, not here.
                    i_left, i_right = i in at, i in at_nb
                    j_left, j_right = j in at, j in at_nb
                    if not (
                        (i_left and j_right) or (j_left and i_right)
                    ):
                        continue
                    # keep every visit of each net on this edge, including
                    # repeated visits of one endpoint or a net occupying
                    # both ends of the edge
                    isteps = sorted(
                        list(at.get(i, ())) + list(at_nb.get(i, ()))
                    )
                    jsteps = sorted(
                        list(at.get(j, ())) + list(at_nb.get(j, ()))
                    )
                    violations.append(
                        InspectViolation(
                            rule=RULE_CROSS_ADJACENT,
                            nets=[i, j],
                            steps=[isteps, jsteps],
                            cells=[_vcell(first), _vcell(second)],
                        )
                    )

    violations.sort(key=_sort_key)
    return InspectResponse(legal=not violations, violations=violations)


def _sort_key(v: InspectViolation) -> tuple:
    # net order, then step numbers, then rule code; cross-net items follow
    # single-net items on the same first net
    nets = v.nets
    return (
        nets[0],
        nets[1] if len(nets) > 1 else -1,
        tuple(sorted(s for idxs in v.steps for s in idxs)),
        v.rule,
    )
