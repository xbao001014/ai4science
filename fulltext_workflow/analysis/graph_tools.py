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
from analysis.focus_filter import focus_pmid_in_clause, focus_sql_clause, normalize_focus
from db.schema import get_conn

_ENTITY_COOC_CACHE: dict[str, nx.Graph] = {}
_PAGERANK_CACHE: dict[str, dict] = {}
_ENTITY_TYPES = {"Disease", "Method", "Task", "Tissue", "Dataset", "Metric", "Modality"}
_REACH_RESULTS_CACHE: dict[tuple[Any, ...], dict] = {}
_REACH_PAPER_SAMPLE: int = config.GRAPH_REACH_PAPER_SAMPLE
_TYPE_SQL = "('Disease','Method','Task','Tissue','Dataset','Metric','Modality')"


def _graph_cache_key(focus: str | None) -> str:
    return (normalize_focus(focus) or "").lower()


def _get_entity_cooc_graph(focus: str | None = None) -> nx.Graph:
    """Build entity co-occurrence graph; optional focus seeds papers via disease/title."""
    key = _graph_cache_key(focus)
    cached = _ENTITY_COOC_CACHE.get(key)
    if cached is not None:
        return cached

    focus_n = normalize_focus(focus)
    pmid_clause = focus_pmid_in_clause("r.source_pmid", focus_n) if focus_n else ""
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT r.source_pmid, e.id AS eid, e.name, e.type
            FROM relations r
            JOIN entities e ON r.object_id = e.id
            WHERE e.type IN {_TYPE_SQL}
            {pmid_clause}
            """
        ).fetchall()

    paper_entities: dict[str, list[tuple[int, str, str]]] = {}
    seen_per_paper: dict[str, set[int]] = {}
    max_per = max(5, config.GRAPH_MAX_ENTITIES_PER_PAPER)
    for row in rows:
        pmid = row["source_pmid"]
        eid = row["eid"]
        seen = seen_per_paper.setdefault(pmid, set())
        if eid in seen:
            continue
        ents = paper_entities.setdefault(pmid, [])
        if len(ents) >= max_per:
            continue
        seen.add(eid)
        ents.append((eid, row["name"], row["type"]))

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

    _ENTITY_COOC_CACHE[key] = G
    return G


def invalidate_cache() -> None:
    global _REACH_RESULTS_CACHE
    _ENTITY_COOC_CACHE.clear()
    _PAGERANK_CACHE.clear()
    _REACH_RESULTS_CACHE.clear()


def _top_disease_rows(conn, *, top_diseases: int, focus: str | None) -> list:
    if focus:
        fc = focus_sql_clause("e.name", focus)
        rows = conn.execute(
            f"""
            SELECT e.id, e.name, COUNT(DISTINCT r.source_pmid) AS paper_cnt
            FROM entities e
            JOIN relations r ON r.object_id = e.id
            WHERE e.type = 'Disease' {fc}
            GROUP BY e.id
            ORDER BY paper_cnt DESC
            LIMIT ?
            """,
            (top_diseases,),
        ).fetchall()
        if rows:
            return rows

        like = f"%{focus.strip()}%"
        method_ids = [
            row["id"]
            for row in conn.execute(
                """
                SELECT id FROM entities
                WHERE type = 'Method' AND LOWER(name) LIKE LOWER(?)
                LIMIT 8
                """,
                (like,),
            ).fetchall()
        ]
        if method_ids:
            mph = ",".join("?" * len(method_ids))
            rows = conn.execute(
                f"""
                SELECT ed.id, ed.name, COUNT(DISTINCT rd.source_pmid) AS paper_cnt
                FROM relations rm
                JOIN relations rd ON rd.source_pmid = rm.source_pmid
                JOIN entities ed ON ed.id = rd.object_id AND ed.type = 'Disease'
                WHERE rm.object_id IN ({mph})
                GROUP BY ed.id
                ORDER BY paper_cnt DESC
                LIMIT ?
                """,
                [*method_ids, top_diseases],
            ).fetchall()
            if rows:
                return rows

    return conn.execute(
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


def _reach_one_disease(
    conn,
    disease_id: int,
    *,
    sample: int,
    max_hops: int,
) -> tuple[list, list]:
    pmid_rows = conn.execute(
        """
        SELECT DISTINCT source_pmid AS pmid
        FROM relations
        WHERE object_id = ?
        LIMIT ?
        """,
        (disease_id, sample),
    ).fetchall()
    pmids = [row["pmid"] for row in pmid_rows]
    if not pmids:
        return [], []

    ph = ",".join("?" * len(pmids))
    direct_rows = conn.execute(
        f"""
        SELECT em.id AS method_id, em.name AS method_name,
               COUNT(DISTINCT rm.source_pmid) AS paper_cnt
        FROM relations rm
        JOIN entities em ON em.id = rm.object_id AND em.type = 'Method'
        WHERE rm.source_pmid IN ({ph})
        GROUP BY em.id
        """,
        pmids,
    ).fetchall()

    if max_hops < 2:
        return direct_rows, []

    bridge_rows = conn.execute(
        f"""
        SELECT r.object_id AS bridge_id, COUNT(*) AS freq
        FROM relations r
        JOIN entities e ON e.id = r.object_id
        WHERE r.source_pmid IN ({ph}) AND e.type != 'Method'
        GROUP BY r.object_id
        ORDER BY freq DESC
        LIMIT 40
        """,
        pmids,
    ).fetchall()
    bridge_ids = [row["bridge_id"] for row in bridge_rows]
    if not bridge_ids:
        return direct_rows, []

    bph = ",".join("?" * len(bridge_ids))
    other_papers = conn.execute(
        f"""
        SELECT DISTINCT r.source_pmid AS pmid
        FROM relations r
        WHERE r.object_id IN ({bph})
          AND r.source_pmid NOT IN ({ph})
        LIMIT 120
        """,
        [*bridge_ids, *pmids],
    ).fetchall()
    other_pmids = [row["pmid"] for row in other_papers]
    if not other_pmids:
        return direct_rows, []

    oph = ",".join("?" * len(other_pmids))
    direct_ids = {row["method_id"] for row in direct_rows}
    gap_rows = conn.execute(
        f"""
        SELECT em.id AS method_id, em.name AS method_name,
               COUNT(DISTINCT rm.source_pmid) AS paper_cnt
        FROM relations rm
        JOIN entities em ON em.id = rm.object_id AND em.type = 'Method'
        WHERE rm.source_pmid IN ({oph})
        GROUP BY em.id
        ORDER BY paper_cnt DESC
        LIMIT 40
        """,
        other_pmids,
    ).fetchall()
    return direct_rows, [
        row for row in gap_rows if row["method_id"] not in direct_ids
    ]


def _sql_disease_method_reach(
    *,
    focus: str | None,
    max_hops: int,
    top_diseases: int,
) -> dict:
    sample = max(10, _REACH_PAPER_SAMPLE)
    focus_lower = focus.lower() if focus else None

    def _method_matches(name: str) -> bool:
        return not focus_lower or focus_lower in name.lower()

    with get_conn() as conn:
        disease_rows = _top_disease_rows(
            conn, top_diseases=top_diseases, focus=focus
        )
        if not disease_rows:
            return {
                "description": "No diseases found for reachability analysis",
                "data": [],
            }

    results = []
    for d_row in disease_rows:
        with get_conn() as conn:
            direct_rows, gap_rows = _reach_one_disease(
                conn,
                d_row["id"],
                sample=sample,
                max_hops=max_hops,
            )

        direct_methods = {row["method_id"] for row in direct_rows}
        gap_list = [
            {"method": row["method_name"], "method_paper_cnt": row["paper_cnt"]}
            for row in gap_rows
            if row["method_id"] not in direct_methods
            and _method_matches(row["method_name"])
        ][:8]

        direct_list = sorted(
            [
                row["method_name"]
                for row in direct_rows
                if _method_matches(row["method_name"])
            ],
            key=lambda name: next(
                (row["paper_cnt"] for row in direct_rows if row["method_name"] == name),
                0,
            ),
            reverse=True,
        )[:6]

        if focus_lower and focus_lower not in d_row["name"].lower():
            if not gap_list and not direct_list:
                continue

        results.append({
            "disease": d_row["name"],
            "disease_paper_cnt": d_row["paper_cnt"],
            "direct_methods": direct_list,
            "direct_method_cnt": len(direct_methods),
            "gap_method_cnt": len(gap_list),
            "top_gap_methods": gap_list,
        })

    results.sort(key=lambda x: x["gap_method_cnt"], reverse=True)
    return {
        "description": (
            "Disease-method multi-hop reachability (sampled papers per disease). "
            "top_gap_methods = 2-hop reachable but not directly studied."
        ),
        "data": results,
    }


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


def _get_pagerank(focus: str | None = None) -> dict:
    key = _graph_cache_key(focus)
    cached = _PAGERANK_CACHE.get(key)
    if cached is not None:
        return cached
    G = _get_entity_cooc_graph(focus)
    pr = _compute_pagerank(G)
    _PAGERANK_CACHE[key] = pr
    return pr


def tool_graph_entity_pagerank(
    entity_type: str = "Method",
    focus: str | None = None,
    top_n: int | None = None,
) -> dict:
    if top_n is None:
        top_n = config.GRAPH_TOP_N
    focus_n = normalize_focus(focus)
    G = _get_entity_cooc_graph(focus_n)
    if G.number_of_nodes() == 0:
        return {"description": "Entity co-occurrence graph is empty", "data": []}

    pr = _get_pagerank(focus_n)

    pmid_clause = focus_pmid_in_clause("r.source_pmid", focus_n) if focus_n else ""
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT e.id, e.name, e.type, COUNT(DISTINCT r.source_pmid) AS paper_cnt
            FROM entities e
            JOIN relations r ON r.object_id = e.id
            WHERE e.type = ?
            {pmid_clause}
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
    scope = f"focus={focus_n!r}" if focus_n else "full corpus"
    return {
        "description": (
            f"{entity_type} PageRank vs paper count ({scope}). "
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
    focus_n = normalize_focus(focus)
    G = _get_entity_cooc_graph(focus_n)
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
    scope = f"focus={focus_n!r}" if focus_n else "full corpus"
    return {
        "description": (
            f"Community detection ({scope}) found {len(communities)} communities. "
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

    cache_key = (focus or "", max_hops, top_diseases)
    cached = _REACH_RESULTS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    result = _sql_disease_method_reach(
        focus=focus,
        max_hops=max_hops,
        top_diseases=top_diseases,
    )
    _REACH_RESULTS_CACHE[cache_key] = result
    return result


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
                "focus seeds papers by disease/title (not entity-name substring). "
                "High pr_paper_ratio = under-studied but structurally important entity."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["Disease", "Method", "Task", "Dataset", "Modality"],
                    },
                    "focus": {
                        "type": "string",
                        "description": "Disease/topic seed for paper subset",
                    },
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
                "focus seeds papers by disease/title. "
                "High isolation_score = research island = cross-community gap."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "min_community_size": {"type": "integer"},
                    "top_n": {"type": "integer"},
                    "focus": {
                        "type": "string",
                        "description": "Disease/topic seed for paper subset",
                    },
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
