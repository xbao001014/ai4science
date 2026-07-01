"""
Graph traversal gap tools for the full-text workflow.

Three tools (no citation PageRank — fulltext DB lacks citations table):
  graph_entity_pagerank       — PageRank vs paper count on entity co-occurrence graph
  graph_community_gaps        — Community detection / isolated research clusters
  graph_disease_method_reach  — 2-hop disease-method reachability gaps
"""
from __future__ import annotations

from typing import Any

import networkx as nx

import config
from db.schema import get_conn

_ENTITY_COOC_GRAPH: nx.Graph | None = None
_ENTITY_TYPES = {"Disease", "Method", "Task", "Tissue", "Dataset", "Metric", "Modality"}


def _get_entity_cooc_graph() -> nx.Graph:
    global _ENTITY_COOC_GRAPH
    if _ENTITY_COOC_GRAPH is not None:
        return _ENTITY_COOC_GRAPH

    with get_conn() as conn:
        rows = conn.execute("""
            SELECT r.source_pmid, e.id AS eid, e.name, e.type
            FROM relations r
            JOIN entities e ON r.object_id = e.id
            WHERE e.type IN ('Disease','Method','Task','Tissue','Dataset','Metric','Modality')
        """).fetchall()

    paper_entities: dict[str, list[tuple[int, str, str]]] = {}
    for row in rows:
        pmid = row["source_pmid"]
        paper_entities.setdefault(pmid, []).append(
            (row["eid"], row["name"], row["type"])
        )

    G = nx.Graph()
    for ents in paper_entities.values():
        for eid, name, etype in ents:
            if eid not in G:
                G.add_node(eid, name=name, entity_type=etype)

    for ents in paper_entities.values():
        for i in range(len(ents)):
            for j in range(i + 1, len(ents)):
                a, b = ents[i][0], ents[j][0]
                if G.has_edge(a, b):
                    G[a][b]["weight"] += 1
                else:
                    G.add_edge(a, b, weight=1)

    _ENTITY_COOC_GRAPH = G
    return G


def invalidate_cache() -> None:
    global _ENTITY_COOC_GRAPH
    _ENTITY_COOC_GRAPH = None


def _compute_pagerank(G: nx.Graph, alpha: float = 0.85, max_iter: int = 100) -> dict:
    try:
        return nx.pagerank(G, alpha=alpha, weight="weight")
    except (ModuleNotFoundError, ImportError, AttributeError):
        pass

    nodes = list(G.nodes())
    if not nodes:
        return {}
    n = len(nodes)
    out_weight: dict[Any, float] = {}
    for node in nodes:
        w = sum(d.get("weight", 1) for _, _, d in G.edges(node, data=True))
        out_weight[node] = w if w > 0 else 0.0

    pr = {node: 1.0 / n for node in nodes}
    for _ in range(max_iter):
        dangling = sum(pr[node] for node in nodes if out_weight[node] == 0.0)
        new_pr: dict[Any, float] = {}
        for node in nodes:
            incoming = 0.0
            for nbr in G.neighbors(node):
                ow = out_weight[nbr]
                if ow > 0:
                    incoming += pr[nbr] * G[node][nbr].get("weight", 1) / ow
            new_pr[node] = (1 - alpha) / n + alpha * (incoming + dangling / n)
        diff = sum(abs(new_pr[node] - pr[node]) for node in nodes)
        pr = new_pr
        if diff < 1e-6:
            break
    return pr


def tool_graph_entity_pagerank(
    entity_type: str = "Method",
    focus: str | None = None,
    top_n: int | None = None,
) -> dict:
    if top_n is None:
        top_n = config.GRAPH_TOP_N
    G = _get_entity_cooc_graph()
    if G.number_of_nodes() == 0:
        return {"description": "Entity co-occurrence graph is empty", "data": []}

    pr = _compute_pagerank(G)

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT e.id, e.name, e.type, COUNT(DISTINCT r.source_pmid) AS paper_cnt
            FROM entities e
            JOIN relations r ON r.object_id = e.id
            WHERE e.type = ?
            GROUP BY e.id
            """,
            (entity_type,),
        ).fetchall()

    paper_cnt_map = {row["id"]: row["paper_cnt"] for row in rows}

    candidates = []
    for eid in G.nodes():
        node = G.nodes[eid]
        if node.get("entity_type") != entity_type:
            continue
        name = node.get("name", "")
        if focus and focus.lower() not in name.lower():
            continue
        pc = paper_cnt_map.get(eid, 0)
        pg = pr.get(eid, 0.0)
        candidates.append({
            "entity": name,
            "entity_type": entity_type,
            "paper_cnt": pc,
            "pagerank": round(pg * 1e4, 4),
            "pr_paper_ratio": round((pg * 1e4) / max(pc, 1), 4),
        })

    candidates.sort(key=lambda x: x["pr_paper_ratio"], reverse=True)
    return {
        "description": (
            f"{entity_type} PageRank vs paper count. "
            "High pr_paper_ratio = structurally important but under-studied."
        ),
        "data": candidates[:top_n],
    }


def tool_graph_community_gaps(
    min_community_size: int = 5,
    top_n: int | None = None,
    focus: str | None = None,
) -> dict:
    if top_n is None:
        top_n = config.GRAPH_TOP_N
    G = _get_entity_cooc_graph()
    if G.number_of_nodes() < 10:
        return {"description": "Too few nodes for community detection", "data": []}

    communities = list(nx.algorithms.community.label_propagation_communities(G))
    communities = [c for c in communities if len(c) >= min_community_size]
    communities.sort(key=len, reverse=True)

    node_community: dict[int, int] = {}
    for ci, comm in enumerate(communities):
        for eid in comm:
            node_community[eid] = ci

    cross_edges: dict[tuple[int, int], int] = {}
    for u, v, data in G.edges(data=True):
        cu = node_community.get(u, -1)
        cv = node_community.get(v, -1)
        if cu != cv and cu >= 0 and cv >= 0:
            key = (min(cu, cv), max(cu, cv))
            cross_edges[key] = cross_edges.get(key, 0) + data.get("weight", 1)

    community_summaries = []
    for ci, comm in enumerate(communities[:top_n]):
        deg = G.degree(list(comm), weight="weight")
        top_nodes = sorted(deg, key=lambda x: x[1], reverse=True)[:5]
        representatives = [
            G.nodes[eid].get("name", str(eid))
            for eid, _ in top_nodes
            if eid in G.nodes
        ]
        if focus:
            representatives = [r for r in representatives if focus.lower() in r.lower()]
            if not representatives:
                continue

        type_counts: dict[str, int] = {}
        for eid in comm:
            if eid in G.nodes:
                t = G.nodes[eid].get("entity_type", "Unknown")
                type_counts[t] = type_counts.get(t, 0) + 1

        total_cross = sum(
            w for (ca, cb), w in cross_edges.items() if ca == ci or cb == ci
        )
        community_summaries.append({
            "community_id": ci,
            "size": len(comm),
            "type_dist": type_counts,
            "representatives": representatives,
            "cross_community_edges": total_cross,
            "isolation_score": round(len(comm) / max(total_cross, 1), 3),
        })

    community_summaries.sort(key=lambda x: x["isolation_score"], reverse=True)
    return {
        "description": (
            f"Community detection found {len(communities)} communities. "
            "High isolation_score = research island = cross-community opportunity."
        ),
        "data": community_summaries[:top_n],
        "total_communities": len(communities),
        "total_cross_edges": len(cross_edges),
    }


def tool_graph_disease_method_reach(
    focus: str | None = None,
    max_hops: int = 2,
    top_diseases: int | None = None,
) -> dict:
    if top_diseases is None:
        top_diseases = config.GRAPH_TOP_N
    G = _get_entity_cooc_graph()

    with get_conn() as conn:
        disease_rows = conn.execute(
            """
            SELECT e.id, e.name, COUNT(DISTINCT r.source_pmid) AS paper_cnt
            FROM entities e
            JOIN relations r ON r.object_id = e.id
            WHERE e.type = 'Disease'
            GROUP BY e.id
            ORDER BY paper_cnt DESC
            LIMIT ?
            """,
            (top_diseases,),
        ).fetchall()
        method_rows = conn.execute(
            """
            SELECT e.id, e.name, COUNT(DISTINCT r.source_pmid) AS paper_cnt
            FROM entities e
            JOIN relations r ON r.object_id = e.id
            WHERE e.type = 'Method'
            GROUP BY e.id
            """
        ).fetchall()

    method_set = {row["id"] for row in method_rows}
    method_paper_cnt = {row["id"]: row["paper_cnt"] for row in method_rows}
    method_name = {row["id"]: row["name"] for row in method_rows}

    results = []
    for d_row in disease_rows:
        did = d_row["id"]
        dname = d_row["name"]
        if focus and focus.lower() not in dname.lower():
            continue
        if did not in G:
            continue

        direct_methods = {nbr for nbr in G.neighbors(did) if nbr in method_set}

        two_hop_methods: set[int] = set()
        if max_hops >= 2:
            for mid_node in G.neighbors(did):
                if mid_node in method_set:
                    continue
                for nbr2 in G.neighbors(mid_node):
                    if nbr2 in method_set and nbr2 not in direct_methods:
                        two_hop_methods.add(nbr2)

        gap_methods = two_hop_methods - direct_methods
        gap_list = sorted(
            [
                {"method": method_name[m], "method_paper_cnt": method_paper_cnt[m]}
                for m in gap_methods
                if m in method_name
            ],
            key=lambda x: x["method_paper_cnt"],
            reverse=True,
        )[:8]

        direct_list = sorted(
            [method_name[m] for m in direct_methods if m in method_name],
            key=lambda m: method_paper_cnt.get(
                next((k for k, v in method_name.items() if v == m), -1), 0
            ),
            reverse=True,
        )[:6]

        results.append({
            "disease": dname,
            "disease_paper_cnt": d_row["paper_cnt"],
            "direct_methods": direct_list,
            "direct_method_cnt": len(direct_methods),
            "gap_method_cnt": len(gap_methods),
            "top_gap_methods": gap_list,
        })

    results.sort(key=lambda x: x["gap_method_cnt"], reverse=True)
    return {
        "description": (
            "Disease-method multi-hop reachability. "
            "top_gap_methods = 2-hop reachable but not directly studied."
        ),
        "data": results,
    }


GRAPH_TOOLS: dict[str, Any] = {
    "graph_entity_pagerank": tool_graph_entity_pagerank,
    "graph_community_gaps": tool_graph_community_gaps,
    "graph_disease_method_reach": tool_graph_disease_method_reach,
}

GRAPH_TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "graph_entity_pagerank",
            "description": (
                "PageRank on entity co-occurrence graph vs paper count. "
                "High pr_paper_ratio = under-studied but structurally important entity."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["Disease", "Method", "Task", "Dataset", "Modality"],
                    },
                    "focus": {"type": "string"},
                    "top_n": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "graph_community_gaps",
            "description": (
                "Community detection on entity co-occurrence graph. "
                "High isolation_score = research island = cross-community gap."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "min_community_size": {"type": "integer"},
                    "top_n": {"type": "integer"},
                    "focus": {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "graph_disease_method_reach",
            "description": (
                "2-hop disease-method reachability. "
                "Methods reachable in 2 hops but not directly linked = transferable gap."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string"},
                    "max_hops": {"type": "integer"},
                    "top_diseases": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
]

GAP_TOOLS: dict[str, Any] = {}
GAP_TOOL_SCHEMAS: list[dict] = []


def init_gap_registry() -> None:
    """Populate merged GAP_TOOLS after module load."""
    from analysis.gap_tools import SQL_TOOLS, TOOL_SCHEMAS

    GAP_TOOLS.clear()
    GAP_TOOLS.update({**SQL_TOOLS, **GRAPH_TOOLS})
    GAP_TOOL_SCHEMAS.clear()
    GAP_TOOL_SCHEMAS.extend(TOOL_SCHEMAS + GRAPH_TOOL_SCHEMAS)
