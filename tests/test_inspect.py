"""Tests for POST /inspect: static audit of candidate paths."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def net(p0, p1, via_limit=0, name=None):
    d = {"pads": [p0, p1], "via_limit": via_limit}
    if name is not None:
        d["name"] = name
    return d


def inspect(body: dict):
    r = client.post("/inspect", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def rules(resp, rule: str):
    return [v for v in resp["violations"] if v["rule"] == rule]


def cells_of(v):
    return [(c["x"], c["y"], c["layer"]) for c in v["cells"]]


# ------------------------------- legal paths --------------------------------

def test_inspect_legal_straight_path():
    body = {
        "width": 5, "height": 5,
        "nets": [net({"x": 0, "y": 0, "layer": 0},
                     {"x": 4, "y": 0, "layer": 0})],
        "paths": [[{"x": x, "y": 0, "layer": 0} for x in range(5)]],
    }
    resp = inspect(body)
    assert resp == {"legal": True, "violations": []}


def test_inspect_legal_with_via_and_detour():
    body = {
        "width": 4, "height": 4,
        "blocked": [{"x": 2, "y": 0, "layer": 0}],
        "nets": [net({"x": 0, "y": 0, "layer": 0},
                     {"x": 3, "y": 0, "layer": 0}, via_limit=2)],
        "paths": [[
            {"x": 0, "y": 0, "layer": 0},
            {"x": 1, "y": 0, "layer": 0},
            {"x": 1, "y": 0, "layer": 1},
            {"x": 2, "y": 0, "layer": 1},
            {"x": 3, "y": 0, "layer": 1},
            {"x": 3, "y": 0, "layer": 0},
        ]],
    }
    assert inspect(body)["legal"] is True


def test_inspect_legal_two_nets_diagonal_gap():
    body = {
        "width": 5, "height": 4,
        "nets": [
            net({"x": 0, "y": 0, "layer": 0}, {"x": 4, "y": 0, "layer": 0}),
            net({"x": 0, "y": 2, "layer": 0}, {"x": 4, "y": 2, "layer": 0}),
        ],
        "paths": [
            [{"x": x, "y": 0, "layer": 0} for x in range(5)],
            [{"x": x, "y": 2, "layer": 0} for x in range(5)],
        ],
    }
    assert inspect(body)["legal"] is True


def test_inspect_accepts_solver_output():
    # whatever /route returns for a legal board must pass /inspect
    board = {
        "width": 8, "height": 8,
        "blocked": [{"x": 3, "y": y, "layer": 0} for y in range(8)],
        "nets": [
            net({"x": 0, "y": 3, "layer": 0}, {"x": 7, "y": 3, "layer": 0}, 2),
            net({"x": 0, "y": 5, "layer": 1}, {"x": 7, "y": 5, "layer": 1}, 0),
        ],
    }
    r = client.post("/route", json=board)
    solved = r.json()
    assert solved["status"] in ("optimal", "feasible")
    body = dict(board)
    body["paths"] = [n["path"] for n in solved["nets"]]
    assert inspect(body)["legal"] is True


# ----------------------------- single-net rules -----------------------------

def test_empty_path_reports_endpoint_violations():
    body = {
        "width": 3, "height": 3,
        "nets": [net({"x": 0, "y": 0, "layer": 0},
                     {"x": 2, "y": 2, "layer": 0})],
        "paths": [[]],
    }
    resp = inspect(body)
    ep = rules(resp, "ENDPOINT_MISMATCH")
    assert len(ep) == 2
    assert [cells_of(v) for v in ep] == [
        [(0, 0, 0)], [(2, 2, 0)],
    ]
    assert all(v["steps"] == [[]] for v in ep)


def test_wrong_endpoints_report_each_pad():
    body = {
        "width": 4, "height": 4,
        "nets": [net({"x": 0, "y": 0, "layer": 0},
                     {"x": 3, "y": 3, "layer": 0})],
        "paths": [[
            {"x": 1, "y": 0, "layer": 0},
            {"x": 3, "y": 0, "layer": 0},
            {"x": 2, "y": 3, "layer": 0},
        ]],
    }
    resp = inspect(body)
    ep = rules(resp, "ENDPOINT_MISMATCH")
    assert [cells_of(v) for v in ep] == [[(0, 0, 0)], [(3, 3, 0)]]
    # plus the jump violations, audit continues
    assert len(rules(resp, "NON_ORTHOGONAL_STEP")) == 2


def test_out_of_bounds_and_illegal_layer_are_200_violations():
    body = {
        "width": 3, "height": 3,
        "nets": [net({"x": 0, "y": 0, "layer": 0},
                     {"x": 2, "y": 2, "layer": 0})],
        "paths": [[
            {"x": 0, "y": 0, "layer": 0},
            {"x": 3, "y": 0, "layer": 0},   # x out of bounds
            {"x": -1, "y": 0, "layer": 0},  # negative x
            {"x": 0, "y": 9, "layer": 0},   # y out of bounds
            {"x": 0, "y": 0, "layer": 2},   # illegal layer
            {"x": 0, "y": 0, "layer": -1},  # illegal layer, also duplicate? no
            {"x": 2, "y": 2, "layer": 0},
        ]],
    }
    resp = inspect(body)
    oob = rules(resp, "CELL_OUT_OF_BOUNDS")
    assert {cells_of(v)[0] for v in oob} == {
        (3, 0, 0), (-1, 0, 0), (0, 9, 0),
    }
    assert [v["steps"] for v in oob] == [[[1]], [[2]], [[3]]]
    ill = rules(resp, "ILLEGAL_LAYER")
    assert {cells_of(v)[0] for v in ill} == {(0, 0, 2), (0, 0, -1)}


def test_blocked_cell_reports_steps():
    body = {
        "width": 3, "height": 3,
        "blocked": [{"x": 1, "y": 1, "layer": 0}],
        "nets": [net({"x": 0, "y": 1, "layer": 0},
                     {"x": 2, "y": 1, "layer": 0})],
        "paths": [[
            {"x": 0, "y": 1, "layer": 0},
            {"x": 1, "y": 1, "layer": 0},
            {"x": 2, "y": 1, "layer": 0},
        ]],
    }
    blk = rules(inspect(body), "BLOCKED_CELL")
    assert len(blk) == 1
    assert cells_of(blk[0]) == [(1, 1, 0)]
    assert blk[0]["steps"] == [[1]]


def test_duplicate_cell_keeps_all_steps():
    body = {
        "width": 4, "height": 3,
        "nets": [net({"x": 0, "y": 0, "layer": 0},
                     {"x": 0, "y": 2, "layer": 0})],
        "paths": [[
            {"x": 0, "y": 0, "layer": 0},
            {"x": 1, "y": 0, "layer": 0},
            {"x": 1, "y": 1, "layer": 0},
            {"x": 0, "y": 1, "layer": 0},
            {"x": 1, "y": 1, "layer": 0},  # revisit of step 2
            {"x": 1, "y": 2, "layer": 0},
            {"x": 0, "y": 2, "layer": 0},
        ]],
    }
    resp = inspect(body)
    dup = rules(resp, "DUPLICATE_CELL")
    assert len(dup) == 1
    assert cells_of(dup[0]) == [(1, 1, 0)]
    assert dup[0]["steps"] == [[2, 4]]


def test_non_orthogonal_step_rules():
    body = {
        "width": 5, "height": 5,
        "nets": [net({"x": 0, "y": 0, "layer": 0},
                     {"x": 4, "y": 4, "layer": 0})],
        "paths": [[
            {"x": 0, "y": 0, "layer": 0},
            {"x": 2, "y": 0, "layer": 0},  # distance 2
            {"x": 3, "y": 1, "layer": 0},  # diagonal
            {"x": 3, "y": 2, "layer": 0},  # unit move, legal
            {"x": 4, "y": 4, "layer": 0},  # jump
        ]],
    }
    resp = inspect(body)
    bad = rules(resp, "NON_ORTHOGONAL_STEP")
    assert [v["steps"] for v in bad] == [[[0, 1]], [[1, 2]], [[3, 4]]]
    assert [cells_of(v) for v in bad] == [
        [(0, 0, 0), (2, 0, 0)],
        [(2, 0, 0), (3, 1, 0)],
        [(3, 2, 0), (4, 4, 0)],
    ]


def test_layer_change_must_keep_coordinate():
    body = {
        "width": 4, "height": 4,
        "nets": [net({"x": 0, "y": 0, "layer": 0},
                     {"x": 3, "y": 3, "layer": 0}, via_limit=5)],
        "paths": [[
            {"x": 0, "y": 0, "layer": 0},
            {"x": 1, "y": 0, "layer": 0},
            {"x": 1, "y": 0, "layer": 1},  # in-place via, legal
            {"x": 2, "y": 1, "layer": 0},  # offset layer change
            {"x": 3, "y": 3, "layer": 0},
        ]],
    }
    resp = inspect(body)
    offs = rules(resp, "LAYER_CHANGE_OFFSET")
    assert len(offs) == 1
    assert offs[0]["steps"] == [[2, 3]]
    assert cells_of(offs[0]) == [(1, 0, 1), (2, 1, 0)]
    # in-place change is not a NON_ORTHOGONAL_STEP (it's a via)
    non_orth = rules(resp, "NON_ORTHOGONAL_STEP")
    assert [v["steps"] for v in non_orth] == [[[3, 4]]]


def test_via_limit_counts_coordinates_on_both_layers():
    body = {
        "width": 4, "height": 4,
        "nets": [net({"x": 0, "y": 0, "layer": 0},
                     {"x": 0, "y": 3, "layer": 0}, via_limit=1)],
        "paths": [[
            {"x": 0, "y": 0, "layer": 0},
            {"x": 0, "y": 0, "layer": 1},  # via #1 at (0,0)
            {"x": 1, "y": 0, "layer": 1},
            {"x": 1, "y": 0, "layer": 0},  # via #2 at (1,0)
            {"x": 1, "y": 1, "layer": 0},
            {"x": 1, "y": 1, "layer": 1},  # via #3 at (1,1)
            {"x": 0, "y": 1, "layer": 1},
            {"x": 0, "y": 1, "layer": 0},  # via #4 at (0,1)
            {"x": 0, "y": 2, "layer": 0},
            {"x": 0, "y": 3, "layer": 0},
        ]],
    }
    resp = inspect(body)
    vl = rules(resp, "VIA_LIMIT")
    assert len(vl) == 1
    v = vl[0]
    assert v["nets"] == [0]
    assert v["via_count"] == 4
    assert v["via_limit"] == 1
    # every layer cell of every via is listed, steps reference all of them
    assert cells_of(v) == [
        (0, 0, 0), (0, 0, 1),
        (0, 1, 0), (0, 1, 1),
        (1, 0, 0), (1, 0, 1),
        (1, 1, 0), (1, 1, 1),
    ]
    assert v["steps"] == [[0, 1, 2, 3, 4, 5, 6, 7]]


def test_one_net_error_does_not_stop_other_checks_and_nets():
    # net 0 is broken in many ways; net 1 is clean and must still be audited
    body = {
        "width": 4, "height": 4,
        "blocked": [{"x": 1, "y": 1, "layer": 0}],
        "nets": [
            net({"x": 0, "y": 0, "layer": 0}, {"x": 3, "y": 3, "layer": 0}),
            net({"x": 0, "y": 3, "layer": 0}, {"x": 3, "y": 3, "layer": 1}, 1),
        ],
        "paths": [
            [{"x": 9, "y": 9, "layer": 7}],
            [
                {"x": 0, "y": 3, "layer": 0},
                {"x": 1, "y": 3, "layer": 0},
                {"x": 1, "y": 3, "layer": 1},
                {"x": 2, "y": 3, "layer": 1},
                {"x": 3, "y": 3, "layer": 1},
            ],
        ],
    }
    resp = inspect(body)
    for rule in ("ENDPOINT_MISMATCH", "CELL_OUT_OF_BOUNDS", "ILLEGAL_LAYER"):
        assert rules(resp, rule)
    # net 1: fully legal -> no violations carry net index 1
    assert all(1 not in v["nets"] for v in resp["violations"])


# ------------------------------ cross-net rules -----------------------------

def test_adjacency_independent_of_net_order_and_direction():
    # two parallel straight traces one cell apart: the conflicts must be
    # reported whichever net has the smaller index and whichever side
    # (right/below) it runs on -- the old +x/+y scan filtered by net order
    # and silently returned legal=true for these boards
    parallel_nets = [
        net({"x": 0, "y": 0, "layer": 0}, {"x": 2, "y": 0, "layer": 0}),
        net({"x": 0, "y": 1, "layer": 0}, {"x": 2, "y": 1, "layer": 0}),
    ]
    horizontal_paths = [
        [{"x": x, "y": 0, "layer": 0} for x in range(3)],
        [{"x": x, "y": 1, "layer": 0} for x in range(3)],
    ]
    vertical_nets = [
        net({"x": 0, "y": 0, "layer": 0}, {"x": 0, "y": 2, "layer": 0}),
        net({"x": 1, "y": 0, "layer": 0}, {"x": 1, "y": 2, "layer": 0}),
    ]
    vertical_paths = [
        [{"x": 0, "y": y, "layer": 0} for y in range(3)],
        [{"x": 1, "y": y, "layer": 0} for y in range(3)],
    ]
    for nets, paths in (
        (parallel_nets, horizontal_paths),
        (parallel_nets[::-1], horizontal_paths[::-1]),  # low net below
        (vertical_nets, vertical_paths),
        (vertical_nets[::-1], vertical_paths[::-1]),    # low net to the right
    ):
        body = {"width": 3, "height": 3, "nets": nets, "paths": paths}
        resp = inspect(body)
        assert resp["legal"] is False, body
        adj = rules(resp, "CROSS_NET_ADJACENT")
        assert len(adj) == 3
        assert all(v["nets"] == [0, 1] for v in adj)


def test_several_net_pairs_on_same_edge_reported_separately():
    # edge (1,0,0)-(1,1,0): net 0 and net 2 both occupy the top endpoint
    # (they coincide with each other there), net 1 the bottom one.  Each
    # cross-net pair facing across the edge is its own violation; two nets
    # that merely share one endpoint never get an adjacency entry.
    p = {"x": 1, "y": 0, "layer": 0}
    body = {
        "width": 5, "height": 3,
        "nets": [
            net({"x": 0, "y": 0, "layer": 0}, {"x": 2, "y": 0, "layer": 0}),
            net({"x": 0, "y": 2, "layer": 0}, {"x": 2, "y": 2, "layer": 0}),
            net({"x": 4, "y": 0, "layer": 0}, {"x": 1, "y": 0, "layer": 0}),
        ],
        "paths": [
            [{"x": 0, "y": 0, "layer": 0}, dict(p),
             {"x": 2, "y": 0, "layer": 0}],
            [{"x": 0, "y": 2, "layer": 0},
             {"x": 1, "y": 1, "layer": 0},
             {"x": 2, "y": 2, "layer": 0}],
            [{"x": 4, "y": 0, "layer": 0},
             {"x": 3, "y": 0, "layer": 0}, dict(p)],
        ],
    }
    resp = inspect(body)
    edge = [(1, 0, 0), (1, 1, 0)]
    # on THIS edge both net pairs facing across it are reported separately,
    # one per net pair, while nets 0 and 2 (which only share the top
    # endpoint) do not claim the edge as an adjacency
    on_edge = {
        tuple(v["nets"]): v["steps"]
        for v in rules(resp, "CROSS_NET_ADJACENT")
        if cells_of(v) == edge
    }
    assert sorted(on_edge) == [(0, 1), (1, 2)]
    assert on_edge[(0, 1)] == [[1], [1]]
    assert on_edge[(1, 2)] == [[1], [2]]
    # nets 0/2 extending along the row next to the shared cell still face
    # each other across the row edges (different cells, different nets)
    row_pairs = sorted(
        tuple(v["nets"]) for v in rules(resp, "CROSS_NET_ADJACENT")
    )
    assert (0, 2) in row_pairs
    assert all(
        cells_of(v) != edge
        for v in rules(resp, "CROSS_NET_ADJACENT") if v["nets"] == [0, 2]
    )
    # the same-endpoint coincidence is its own rule, one pair only
    assert sorted(tuple(v["nets"])
                  for v in rules(resp, "CROSS_NET_COINCIDE")) == [(0, 2)]


def test_adjacency_keeps_every_step_of_repeated_visits():
    # net 0 occupies (1,1,0) twice (steps 1 and 4); net 1 sits on (1,2,0)
    # at steps 1 and 4.  Every visiting step number is kept per net.
    body = {
        "width": 4, "height": 4,
        "nets": [
            net({"x": 0, "y": 1, "layer": 0}, {"x": 3, "y": 1, "layer": 0}),
            net({"x": 0, "y": 3, "layer": 0}, {"x": 2, "y": 3, "layer": 0}),
        ],
        "paths": [
            [
                {"x": 0, "y": 1, "layer": 0},
                {"x": 1, "y": 1, "layer": 0},
                {"x": 2, "y": 0, "layer": 0},
                {"x": 2, "y": 1, "layer": 0},
                {"x": 1, "y": 1, "layer": 0},  # revisit step 1
                {"x": 3, "y": 1, "layer": 0},
            ],
            [
                {"x": 0, "y": 3, "layer": 0},
                {"x": 1, "y": 2, "layer": 0},
                {"x": 2, "y": 2, "layer": 0},
                {"x": 2, "y": 3, "layer": 0},
            ],
        ],
    }
    resp = inspect(body)
    adj = rules(resp, "CROSS_NET_ADJACENT")
    by_edge = {tuple(cells_of(v)): v["steps"] for v in adj}
    assert by_edge[((1, 1, 0), (1, 2, 0))] == [[1, 4], [1]]
    assert by_edge[((2, 1, 0), (2, 2, 0))] == [[3], [2]]


def test_cross_net_coincide_and_adjacent():
    body = {
        "width": 4, "height": 5,
        "nets": [
            net({"x": 0, "y": 1, "layer": 0}, {"x": 3, "y": 1, "layer": 0}),
            net({"x": 0, "y": 3, "layer": 0}, {"x": 3, "y": 3, "layer": 0}),
        ],
        "paths": [
            [{"x": x, "y": 1, "layer": 0} for x in range(4)],
            [
                {"x": 0, "y": 3, "layer": 0},  # distance 2 from net 0
                {"x": 1, "y": 1, "layer": 0},  # coincide with net 0 step 1
                {"x": 2, "y": 2, "layer": 0},  # adjacent to net 0 at (2,1)
                {"x": 3, "y": 2, "layer": 0},  # adjacent to net 0 at (3,1)
                {"x": 3, "y": 3, "layer": 0},  # distance 2 from net 0
            ],
        ],
    }
    resp = inspect(body)
    coin = rules(resp, "CROSS_NET_COINCIDE")
    assert len(coin) == 1
    assert coin[0]["nets"] == [0, 1]
    assert coin[0]["steps"] == [[1], [1]]
    assert cells_of(coin[0]) == [(1, 1, 0), (1, 1, 0)]
    adj = rules(resp, "CROSS_NET_ADJACENT")
    edges = sorted(cells_of(v) for v in adj)
    # the edge (1,1)-(2,1) is detected regardless of which net sits on
    # which side: net 1 coincides with net 0 at (1,1) while net 0 keeps
    # running right to (2,1)
    assert edges == [
        [(0, 1, 0), (1, 1, 0)],
        [(1, 1, 0), (2, 1, 0)],
        [(2, 1, 0), (2, 2, 0)],
        [(3, 1, 0), (3, 2, 0)],
    ]
    assert all(v["nets"] == [0, 1] for v in adj)
    by_edge = {tuple(cells_of(v)): v["steps"] for v in adj}
    assert by_edge[((0, 1, 0), (1, 1, 0))] == [[0, 1], [1]]
    assert by_edge[((1, 1, 0), (2, 1, 0))] == [[1, 2], [1]]
    assert by_edge[((2, 1, 0), (2, 2, 0))] == [[2], [2]]
    assert by_edge[((3, 1, 0), (3, 2, 0))] == [[3], [3]]


def test_three_nets_same_cell_report_three_pairs():
    p = {"x": 1, "y": 1, "layer": 0}
    body = {
        "width": 3, "height": 3,
        "blocked": [dict(p)],  # blocked cells still take part
        "nets": [
            net({"x": 0, "y": 0, "layer": 0}, {"x": 0, "y": 2, "layer": 0}),
            net({"x": 2, "y": 0, "layer": 0}, {"x": 2, "y": 2, "layer": 0}),
            net({"x": 1, "y": 0, "layer": 1}, {"x": 1, "y": 2, "layer": 1}),
        ],
        "paths": [
            [{"x": 0, "y": 0, "layer": 0}, dict(p),
             {"x": 0, "y": 2, "layer": 0}],
            [{"x": 2, "y": 0, "layer": 0}, dict(p),
             {"x": 2, "y": 2, "layer": 0}],
            [{"x": 1, "y": 0, "layer": 1},
             {"x": 1, "y": 1, "layer": 1},
             {"x": 1, "y": 2, "layer": 1}],
        ],
    }
    resp = inspect(body)
    coin = rules(resp, "CROSS_NET_COINCIDE")
    assert sorted(v["nets"] for v in coin) == [[0, 1]]
    # the third net is on layer 1: only orthogonal same-layer comparisons
    assert not any(v["nets"] == [0, 2] or v["nets"] == [1, 2] for v in coin)
    # both layer-0 nets blocked, layer-1 net not
    blk = sorted((v["nets"][0], cells_of(v)[0])
                 for v in rules(resp, "BLOCKED_CELL"))
    assert blk == [(0, (1, 1, 0)), (1, (1, 1, 0))]


def test_three_nets_same_cell_same_layer_three_pairs():
    p = {"x": 1, "y": 1, "layer": 0}
    body = {
        "width": 3, "height": 3,
        "nets": [
            net({"x": 0, "y": 0, "layer": 0}, {"x": 2, "y": 0, "layer": 0}),
            net({"x": 0, "y": 2, "layer": 0}, {"x": 2, "y": 2, "layer": 0}),
            net({"x": 0, "y": 1, "layer": 0}, {"x": 2, "y": 1, "layer": 0}),
        ],
        "paths": [
            [{"x": 0, "y": 0, "layer": 0}, dict(p),
             {"x": 2, "y": 0, "layer": 0}],
            [{"x": 0, "y": 2, "layer": 0}, dict(p),
             {"x": 2, "y": 2, "layer": 0}],
            [{"x": 0, "y": 1, "layer": 0}, dict(p),
             {"x": 2, "y": 1, "layer": 0}],
        ],
    }
    coin = rules(inspect(body), "CROSS_NET_COINCIDE")
    assert sorted(v["nets"] for v in coin) == [[0, 1], [0, 2], [1, 2]]


def test_mirror_conflict_dedup_but_distinct_pairs_kept():
    # net 0 and net 1 share cell C via various visits: one coincide entry;
    # net 2 also visits C: two more pairs; repeats keep every step
    c0 = {"x": 1, "y": 1, "layer": 0}
    body = {
        "width": 4, "height": 4,
        "nets": [
            net({"x": 0, "y": 0, "layer": 0}, {"x": 3, "y": 0, "layer": 0}),
            net({"x": 0, "y": 2, "layer": 0}, {"x": 3, "y": 2, "layer": 0}),
            net({"x": 0, "y": 3, "layer": 0}, {"x": 3, "y": 3, "layer": 0}),
        ],
        "paths": [
            [{"x": 0, "y": 0, "layer": 0}, dict(c0),
             {"x": 2, "y": 1, "layer": 0}, dict(c0),
             {"x": 3, "y": 0, "layer": 0}],
            [{"x": 0, "y": 2, "layer": 0}, dict(c0),
             {"x": 3, "y": 2, "layer": 0}],
            [{"x": 0, "y": 3, "layer": 0},
             {"x": 1, "y": 2, "layer": 0}, dict(c0),
             {"x": 3, "y": 3, "layer": 0}],
        ],
    }
    resp = inspect(body)
    coin = {tuple(v["nets"]): v for v in rules(resp, "CROSS_NET_COINCIDE")}
    assert set(coin) == {(0, 1), (0, 2), (1, 2)}
    assert coin[(0, 1)]["steps"] == [[1, 3], [1]]
    assert coin[(0, 2)]["steps"] == [[1, 3], [2]]
    assert coin[(1, 2)]["steps"] == [[1], [2]]


def test_cross_net_ignores_out_of_bounds_and_illegal_layers():
    body = {
        "width": 3, "height": 3,
        "nets": [
            net({"x": 0, "y": 0, "layer": 0}, {"x": 2, "y": 2, "layer": 0}),
            net({"x": 2, "y": 0, "layer": 0}, {"x": 0, "y": 2, "layer": 0}),
        ],
        "paths": [
            [
                {"x": 0, "y": 0, "layer": 0},
                {"x": 1, "y": 0, "layer": 5},  # illegal layer, ignored cross
                {"x": 9, "y": 0, "layer": 0},  # out of bounds, ignored cross
                {"x": 2, "y": 2, "layer": 0},
            ],
            [
                {"x": 2, "y": 0, "layer": 0},
                {"x": 1, "y": 0, "layer": 5},  # same illegal cell: still no
                {"x": 9, "y": 0, "layer": 0},  # same OOB cell: no cross rule
                {"x": 0, "y": 2, "layer": 0},
            ],
        ],
    }
    resp = inspect(body)
    assert not rules(resp, "CROSS_NET_COINCIDE")
    assert not rules(resp, "CROSS_NET_ADJACENT")
    # the cells are still flagged on their own merits
    assert len(rules(resp, "ILLEGAL_LAYER")) == 2
    assert len(rules(resp, "CELL_OUT_OF_BOUNDS")) == 2


def test_different_layers_never_conflict():
    # same coordinates on different layers: no coincide, no adjacency
    body = {
        "width": 3, "height": 3,
        "nets": [
            net({"x": 0, "y": 1, "layer": 0}, {"x": 2, "y": 1, "layer": 0}),
            net({"x": 0, "y": 1, "layer": 1}, {"x": 2, "y": 1, "layer": 1}),
        ],
        "paths": [
            [{"x": x, "y": 1, "layer": 0} for x in range(3)],
            [{"x": x, "y": 1, "layer": 1} for x in range(3)],
        ],
    }
    resp = inspect(body)
    assert resp["legal"] is True


# ------------------------------- ordering -----------------------------------

def test_violations_sorted_by_net_step_rule():
    body = {
        "width": 6, "height": 3,
        "nets": [
            net({"x": 0, "y": 0, "layer": 0}, {"x": 5, "y": 0, "layer": 0}),
            net({"x": 0, "y": 2, "layer": 0}, {"x": 5, "y": 2, "layer": 0}),
        ],
        "paths": [
            # jump at the start (step pair 1-2) and blocked later
            [
                {"x": 0, "y": 0, "layer": 0},
                {"x": 2, "y": 0, "layer": 0},
                {"x": 3, "y": 1, "layer": 0},
                {"x": 4, "y": 1, "layer": 0},
                {"x": 5, "y": 0, "layer": 0},
            ],
            [
                {"x": 0, "y": 2, "layer": 0},
                {"x": 4, "y": 1, "layer": 0},  # coincide with net0 step3
                {"x": 5, "y": 2, "layer": 0},
            ],
        ],
    }
    resp = inspect(body)
    keys = [
        (v["nets"][0],
         v["nets"][1] if len(v["nets"]) > 1 else -1,
         tuple(s for idxs in v["steps"] for s in idxs),
         v["rule"])
        for v in resp["violations"]
    ]
    assert keys == sorted(keys)
    # first item is net 0's earliest single-net violation; cross-net items
    # on pair (0, 1) still sort before net 1's own single-net items
    rules_only = [v["rule"] for v in resp["violations"]]
    assert rules_only[0] == "NON_ORTHOGONAL_STEP"
    ordered = [(v["rule"], v["nets"]) for v in resp["violations"]]
    assert ordered.index(("CROSS_NET_COINCIDE", [0, 1])) < ordered.index(
        ("NON_ORTHOGONAL_STEP", [1])
    )


# --------------------------------- 422 --------------------------------------

def inspect_422(body):
    return client.post("/inspect", json=body).status_code == 422


def good_body(**over):
    body = {
        "width": 3, "height": 3,
        "nets": [net({"x": 0, "y": 0, "layer": 0},
                     {"x": 2, "y": 2, "layer": 0})],
        "paths": [[
            {"x": 0, "y": 0, "layer": 0},
            {"x": 2, "y": 2, "layer": 0},
        ]],
    }
    body.update(over)
    return body


def test_422_missing_paths_field():
    assert inspect_422({"width": 3, "height": 3, "nets": good_body()["nets"]})


@pytest.mark.parametrize("npaths", [[], [[] , []]])
def test_422_path_count_mismatch(npaths):
    body = good_body(paths=npaths)
    assert inspect_422(body)


def test_422_too_many_paths():
    nets = [
        net({"x": 0, "y": i, "layer": 0}, {"x": 1, "y": i, "layer": 0})
        for i in range(2)
    ]
    body = {"width": 3, "height": 3, "nets": nets,
            "paths": [[{"x": 0, "y": 0, "layer": 0}]] * 3}
    assert inspect_422(body)


@pytest.mark.parametrize("bad", [
    [{"x": 0.5, "y": 0, "layer": 0}],
    [{"x": 1.0, "y": 0, "layer": 0}],     # integral float still rejected
    [{"x": "1", "y": 0, "layer": 0}],
    [{"x": True, "y": 0, "layer": 0}],   # bool is not an int here
    [{"x": None, "y": 0, "layer": 0}],
    [{"x": 0, "y": 0.0, "layer": 0}],
    [{"x": 0, "y": 0, "layer": 0.0}],
])
def test_422_non_integer_coordinates(bad):
    body = good_body(paths=[bad + [{"x": 2, "y": 2, "layer": 0}]])
    assert inspect_422(body)


def test_422_path_longer_than_total_board_cells():
    limit = 2 * 3 * 3
    body = good_body(paths=[
        [{"x": 0, "y": 0, "layer": 0} for _ in range(limit + 1)]
    ])
    assert inspect_422(body)


def test_path_equal_to_total_board_cells_is_accepted():
    limit = 2 * 3 * 3
    body = good_body(paths=[
        [{"x": i % 18, "y": 0, "layer": 0} for i in range(limit)]
    ])
    # accepted for inspection (it will of course report duplicates etc.)
    r = client.post("/inspect", json=body)
    assert r.status_code == 200


def test_422_board_validation_still_applies():
    # pad on a blocked cell is a board-level 422, not a reported violation
    body = good_body(blocked=[{"x": 0, "y": 0, "layer": 0}])
    assert inspect_422(body)
    body = good_body(width=1)
    assert inspect_422(body)


def test_422_missing_required_fields():
    assert inspect_422({"width": 3, "height": 3})
    assert inspect_422({"nets": [], "paths": []})
    r = client.post("/inspect", json=good_body(paths=[[
        {"x": 0, "y": 0}, {"x": 2, "y": 2, "layer": 0}
    ]]))
    assert r.status_code == 422


# ------------------------ /route stays unchanged ----------------------------

def test_route_still_works_as_before():
    r = client.get("/health")
    assert r.json() == {"status": "ok"}
    body = {
        "width": 3, "height": 3,
        "nets": [net({"x": 1, "y": 1, "layer": 0},
                     {"x": 1, "y": 1, "layer": 1}, via_limit=1)],
    }
    r = client.post("/route", json=body)
    assert r.status_code == 200
    resp = r.json()
    assert resp["status"] == "optimal"
    assert resp["total_vias"] == 1
    assert set(resp) == {
        "status", "solve_time_seconds", "total_vias",
        "total_moves", "nets",
    }
