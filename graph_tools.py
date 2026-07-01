"""
graph_tools.py
基于 NetworkX 图遍历的研究空白挖掘工具。

与 gap_agent.py 中的 SQL 工具互补：
- SQL 工具擅长：聚合统计（计数、均值、分组）
- 图遍历工具擅长：结构关系、传播路径、社区结构、中心性

五个工具：
  graph_entity_pagerank        — 实体影响力（PageRank vs 论文数对比）
  graph_structural_holes       — 结构洞：连接不同研究社群的桥梁实体
  graph_community_gaps         — 社区检测：孤立研究簇之间的跨界空白
  graph_disease_method_reach   — 多跳可达性：疾病可通过2跳到达但未直连的方法
  graph_citation_pagerank      — 引用网络 PageRank vs 原始引用数的偏差

所有工具都返回 {"description": str, "data": list[dict]} 格式，
与 gap_agent.py 中其他工具保持一致。
"""
from __future__ import annotations

import functools
import math
from typing import Any

import networkx as nx
import config

# ─────────────────────────────────────────────────────────────────────────────
# 缓存图实例（避免每次工具调用都重建图）
# ─────────────────────────────────────────────────────────────────────────────

_FULL_GRAPH: nx.MultiDiGraph | None = None
_ENTITY_COOC_GRAPH: nx.Graph | None = None


def _get_full_graph() -> nx.MultiDiGraph:
    """懒加载完整知识图谱（包含引用边）。"""
    global _FULL_GRAPH
    if _FULL_GRAPH is None:
        from graph.kg_builder import KGBuilder
        builder = KGBuilder()
        _FULL_GRAPH = builder.build(include_authors=False, include_citations=True)
    return _FULL_GRAPH


def _get_entity_cooc_graph() -> nx.Graph:
    """
    构建实体共现无向图：
    若两个实体（Disease/Method/Task/Tissue/Dataset/Metric）出现在同一篇论文中，
    则它们之间有一条边，边权为共现论文数。
    用于社区检测和中心性分析。
    """
    global _ENTITY_COOC_GRAPH
    if _ENTITY_COOC_GRAPH is not None:
        return _ENTITY_COOC_GRAPH

    from utils.db import get_conn

    ENTITY_TYPES = {"Disease", "Method", "Task", "Tissue", "Dataset", "Metric"}

    with get_conn() as conn:
        rows = conn.execute("""
            SELECT r.source_pmid, e.id AS eid, e.name, e.type
            FROM relations r
            JOIN entities e ON r.object_id = e.id
            WHERE e.type IN ('Disease','Method','Task','Tissue','Dataset','Metric')
        """).fetchall()

    # paper_id → list of (eid, name, type)
    paper_entities: dict[str, list[tuple[int, str, str]]] = {}
    for row in rows:
        pmid = row["source_pmid"]
        paper_entities.setdefault(pmid, []).append(
            (row["eid"], row["name"], row["type"])
        )

    G = nx.Graph()

    # Add nodes
    seen: dict[int, tuple[str, str]] = {}
    for ents in paper_entities.values():
        for eid, name, etype in ents:
            if eid not in seen:
                seen[eid] = (name, etype)
                G.add_node(eid, name=name, entity_type=etype)

    # Add co-occurrence edges
    for pmid, ents in paper_entities.items():
        for i in range(len(ents)):
            for j in range(i + 1, len(ents)):
                a, b = ents[i][0], ents[j][0]
                if G.has_edge(a, b):
                    G[a][b]["weight"] += 1
                else:
                    G.add_edge(a, b, weight=1, papers=[])

    _ENTITY_COOC_GRAPH = G
    return G


def invalidate_cache() -> None:
    """清除缓存图（数据库更新后调用）。"""
    global _FULL_GRAPH, _ENTITY_COOC_GRAPH
    _FULL_GRAPH = None
    _ENTITY_COOC_GRAPH = None


# ─────────────────────────────────────────────────────────────────────────────
# 工具 1：实体 PageRank vs 论文数对比
# ─────────────────────────────────────────────────────────────────────────────

def tool_graph_entity_pagerank(
    entity_type: str = "Method",
    focus: str | None = None,
    top_n: int | None = None,
) -> dict:
    if top_n is None:
        top_n = config.GRAPH_TOP_N
    """
    在实体共现图上计算 PageRank，与原始论文数对比。

    识别两类研究空白：
    - PageRank 高但论文数少：在图结构上影响力大（被高影响实体包围），
      但实际研究产出少 → 被忽视的重要实体
    - 论文数多但 PageRank 低：论文孤立（与其他研究主流断开），
      可能是低影响力的重复研究

    Args:
        entity_type: 实体类型，Disease/Method/Task/Dataset，默认 Method
        focus: 可选关键词过滤实体名称
        top_n: 返回条数
    """
    G = _get_entity_cooc_graph()
    if G.number_of_nodes() == 0:
        return {"description": "实体共现图为空", "data": []}

    # 计算带权重的 PageRank
    pr = nx.pagerank(G, alpha=0.85, weight="weight")

    # 从 DB 获取各实体的论文数
    from utils.db import get_conn
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT e.id, e.name, e.type, COUNT(DISTINCT r.source_pmid) AS paper_cnt
            FROM entities e
            JOIN relations r ON r.object_id = e.id
            WHERE e.type = ?
            GROUP BY e.id
        """, (entity_type,)).fetchall()

    paper_cnt_map = {row["id"]: row["paper_cnt"] for row in rows}
    name_map = {row["id"]: row["name"] for row in rows}

    # 只保留指定类型、可选 focus 过滤
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
            "entity":     name,
            "entity_type": entity_type,
            "paper_cnt":  pc,
            "pagerank":   round(pg * 1e4, 4),   # 放大便于阅读
            "pr_paper_ratio": round((pg * 1e4) / max(pc, 1), 4),  # 高→被低产出研究者忽视
        })

    # 按 pr_paper_ratio 降序（PageRank高但论文少 = 最值得关注的空白）
    candidates.sort(key=lambda x: x["pr_paper_ratio"], reverse=True)
    data = candidates[:top_n]

    return {
        "description": (
            f"{entity_type}实体PageRank vs 论文数分析。"
            "pr_paper_ratio高→图结构影响力大但研究产出少（被忽视的重要方向）；"
            "pr_paper_ratio低→论文多但与主流研究断联（重复低效研究）。"
        ),
        "data": data,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 工具 2：结构洞检测
# ─────────────────────────────────────────────────────────────────────────────

def tool_graph_structural_holes(
    focus: str | None = None,
    top_n: int | None = None,
) -> dict:
    if top_n is None:
        top_n = config.GRAPH_TOP_N
    """
    在实体共现图上计算 Betweenness Centrality（介数中心性）。

    介数中心性高的实体是连接不同研究社群的"桥梁"或"结构洞"。
    若这类实体论文数少，说明它虽然在知识图谱结构上连接了多个研究方向，
    但本身作为研究主题被严重忽视 → 研究突破口。

    返回：介数中心性 × 论文数的综合排名，聚焦于高介数低论文数的实体。
    """
    G = _get_entity_cooc_graph()
    if G.number_of_nodes() == 0:
        return {"description": "实体共现图为空", "data": []}

    # 对大图使用近似算法（k 采样）
    k = min(300, G.number_of_nodes())
    bc = nx.betweenness_centrality(G, k=k, weight="weight", normalized=True)

    from utils.db import get_conn
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT e.id, e.name, e.type, COUNT(DISTINCT r.source_pmid) AS paper_cnt
            FROM entities e
            JOIN relations r ON r.object_id = e.id
            WHERE e.type IN ('Disease','Method','Task')
            GROUP BY e.id
        """).fetchall()
    paper_cnt_map = {row["id"]: row["paper_cnt"] for row in rows}

    results = []
    for eid in G.nodes():
        node = G.nodes[eid]
        etype = node.get("entity_type", "")
        if etype not in ("Disease", "Method", "Task"):
            continue
        name = node.get("name", "")
        if focus and focus.lower() not in name.lower():
            continue
        btw = bc.get(eid, 0.0)
        pc  = paper_cnt_map.get(eid, 0)
        if btw < 1e-6:
            continue
        # 桥梁价值 = betweenness / log(paper_cnt+2)  → 高介数、低论文数 = 最大价值
        bridge_score = btw / math.log(pc + 2)
        results.append({
            "entity":          name,
            "entity_type":     etype,
            "paper_cnt":       pc,
            "betweenness":     round(btw * 1e4, 4),
            "bridge_score":    round(bridge_score * 1e4, 4),
            "interpretation":  "高介数低论文 → 研究空白桥梁" if (btw > 1e-4 and pc < 20) else "主流节点",
        })

    results.sort(key=lambda x: x["bridge_score"], reverse=True)
    return {
        "description": (
            "实体结构洞分析（介数中心性 / log(论文数)）。"
            "bridge_score高 = 连接多个研究社群但自身研究少 = 跨领域研究突破口。"
        ),
        "data": results[:top_n],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 工具 3：社区检测与跨社区空白
# ─────────────────────────────────────────────────────────────────────────────

def tool_graph_community_gaps(
    min_community_size: int = 5,
    top_n: int | None = None,
    focus: str | None = None,  # accepted but unused (community detection is global)
) -> dict:
    if top_n is None:
        top_n = config.GRAPH_TOP_N
    """
    在实体共现图上运行 Greedy Modularity 社区检测。

    将知识图谱中的实体自动聚类为若干研究社群（每个社群 = 相互高度共现的实体集合）。
    分析：
    1. 各社群的规模、主导实体类型、代表性实体
    2. 跨社群边的稀疏程度（社群间连边少 = 研究孤岛）
    3. 仅出现在单一社群的实体（孤立，研究交叉机会）
    """
    G = _get_entity_cooc_graph()
    if G.number_of_nodes() < 10:
        return {"description": "图节点数过少，无法进行社区检测", "data": []}

    # Label Propagation communities（O(n+m)，比 Greedy Modularity 快数倍）
    communities = list(
        nx.algorithms.community.label_propagation_communities(G)
    )
    communities = [c for c in communities if len(c) >= min_community_size]
    communities.sort(key=len, reverse=True)

    # 为每个节点记录所属社区
    node_community: dict[int, int] = {}
    for ci, comm in enumerate(communities):
        for eid in comm:
            node_community[eid] = ci

    # 统计跨社区边
    cross_edges: dict[tuple[int, int], int] = {}
    for u, v, data in G.edges(data=True):
        cu = node_community.get(u, -1)
        cv = node_community.get(v, -1)
        if cu != cv and cu >= 0 and cv >= 0:
            key = (min(cu, cv), max(cu, cv))
            cross_edges[key] = cross_edges.get(key, 0) + data.get("weight", 1)

    # 构建社区摘要
    community_summaries = []
    for ci, comm in enumerate(communities[:top_n]):
        nodes_data = [(eid, G.nodes[eid]) for eid in comm if eid in G.nodes]
        # 按度数取 top5 代表实体
        deg = G.degree(list(comm), weight="weight")
        top_nodes = sorted(deg, key=lambda x: x[1], reverse=True)[:5]
        representatives = [
            G.nodes[eid].get("name", str(eid)) for eid, _ in top_nodes
            if eid in G.nodes
        ]
        # 统计实体类型分布
        type_counts: dict[str, int] = {}
        for eid, nd in nodes_data:
            t = nd.get("entity_type", "Unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

        # 与其他社区的连接强度（越小 = 越孤立）
        total_cross = sum(w for (ca, cb), w in cross_edges.items() if ca == ci or cb == ci)

        community_summaries.append({
            "community_id":   ci,
            "size":           len(comm),
            "type_dist":      type_counts,
            "representatives": representatives,
            "cross_community_edges": total_cross,
            "isolation_score": round(len(comm) / max(total_cross, 1), 3),  # 高 = 孤立
        })

    community_summaries.sort(key=lambda x: x["isolation_score"], reverse=True)

    return {
        "description": (
            f"实体共现图社区检测（Greedy Modularity），发现 {len(communities)} 个社区。"
            "isolation_score高 = 研究孤岛（社区内部高度自洽但与其他社区极少连接）= 跨社区研究突破口。"
        ),
        "data": community_summaries[:top_n],
        "total_communities": len(communities),
        "total_cross_edges": len(cross_edges),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 工具 4：疾病-方法多跳可达性分析
# ─────────────────────────────────────────────────────────────────────────────

def tool_graph_disease_method_reach(
    focus: str | None = None,
    max_hops: int = 2,
    top_diseases: int | None = None,
) -> dict:
    if top_diseases is None:
        top_diseases = config.GRAPH_TOP_N
    """
    对每个疾病，分析：
    - 1-hop 直连的方法（已有直接研究）
    - 2-hop 可达的方法（通过共同任务/组织/数据集间接关联，但尚无直接研究）
    
    2-hop 可达但 1-hop 不可达的方法 = "潜在可迁移方法" = 有研究依据但未被探索的应用空白。

    使用实体共现图进行遍历。
    """
    G = _get_entity_cooc_graph()

    from utils.db import get_conn
    with get_conn() as conn:
        # 获取疾病节点
        disease_rows = conn.execute("""
            SELECT e.id, e.name, COUNT(DISTINCT r.source_pmid) AS paper_cnt
            FROM entities e
            JOIN relations r ON r.object_id = e.id
            WHERE e.type = 'Disease'
            GROUP BY e.id
            ORDER BY paper_cnt DESC
            LIMIT ?
        """, (top_diseases,)).fetchall()

        # 获取所有方法实体 id
        method_rows = conn.execute("""
            SELECT e.id, e.name, COUNT(DISTINCT r.source_pmid) AS paper_cnt
            FROM entities e
            JOIN relations r ON r.object_id = e.id
            WHERE e.type = 'Method'
            GROUP BY e.id
        """).fetchall()

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

        # 1-hop 直连的方法节点
        direct_methods = {
            nbr for nbr in G.neighbors(did)
            if nbr in method_set
        }

        # 2-hop 可达方法（通过中间节点）
        if max_hops >= 2:
            two_hop_methods = set()
            for mid_node in G.neighbors(did):
                if mid_node in method_set:
                    continue  # 跳过已直连方法
                for nbr2 in G.neighbors(mid_node):
                    if nbr2 in method_set and nbr2 not in direct_methods:
                        two_hop_methods.add(nbr2)
        else:
            two_hop_methods = set()

        # 潜在空白 = 2-hop 可达但未直连
        gap_methods = two_hop_methods - direct_methods

        # 优先选高论文数的方法（在领域内已成熟）
        gap_list = sorted(
            [{"method": method_name[m], "method_paper_cnt": method_paper_cnt[m]}
             for m in gap_methods if m in method_name],
            key=lambda x: x["method_paper_cnt"],
            reverse=True
        )[:8]

        direct_list = sorted(
            [method_name[m] for m in direct_methods if m in method_name],
            key=lambda m: method_paper_cnt.get(
                next((k for k, v in method_name.items() if v == m), -1), 0
            ),
            reverse=True
        )[:6]

        results.append({
            "disease":           dname,
            "disease_paper_cnt": d_row["paper_cnt"],
            "direct_methods":    direct_list,
            "direct_method_cnt": len(direct_methods),
            "gap_method_cnt":    len(gap_methods),
            "top_gap_methods":   gap_list,
        })

    results.sort(key=lambda x: x["gap_method_cnt"], reverse=True)

    return {
        "description": (
            "疾病-方法多跳可达性分析。"
            "top_gap_methods = 在知识图谱中与该疾病2跳可达（通过共同任务/组织/数据集），"
            "但尚无直接研究论文的方法 → 有理论依据但未被探索的研究空白。"
        ),
        "data": results,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 工具 5：引用网络 PageRank vs 原始引用数偏差分析
# ─────────────────────────────────────────────────────────────────────────────

def tool_graph_citation_pagerank(
    focus: str | None = None,
    top_n: int | None = None,
    min_year: int = 2018,
) -> dict:
    if top_n is None:
        top_n = config.GRAPH_TOP_N
    """
    在论文引用网络上计算 PageRank（引用重要性 = 被重要论文引用）。

    对比 PageRank 与原始引用数，识别两类论文：
    1. PageRank 高但引用数低：被高影响力论文引用，但总引用少。
       → "隐性影响力"论文，值得关注的低曝光前沿工作
    2. 引用数高但 PageRank 低：被大量不重要论文引用（引用来源质量低）。
       → 可能是教科书式综述或方法论文，不一定是研究前沿

    Args:
        focus: 可选关键词（过滤论文标题或实体名）
        top_n: 返回条数
        min_year: 只分析该年份之后的论文（避免旧论文 PageRank 天然高）
    """
    G_full = _get_full_graph()

    # 提取引用子图（只保留 CITES 边）
    cite_edges = [
        (u, v) for u, v, d in G_full.edges(data=True)
        if d.get("relation") == "CITES"
    ]
    G_cite = nx.DiGraph()
    G_cite.add_edges_from(cite_edges)

    if G_cite.number_of_nodes() < 5:
        return {"description": "引用子图节点数过少，无法计算 PageRank", "data": []}

    pr = nx.pagerank(G_cite, alpha=0.85)

    from utils.db import get_conn
    focus_sql = ""
    if focus:
        focus_sql = f"""
        AND (LOWER(p.title) LIKE LOWER('%{focus}%')
             OR p.pmid IN (
                 SELECT DISTINCT r.source_pmid FROM relations r
                 JOIN entities e ON r.object_id=e.id
                 WHERE LOWER(e.name) LIKE LOWER('%{focus}%')
             ))"""

    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT p.id, p.pmid, p.title, p.year, p.citation_count,
                   p.study_type, p.journal_name
            FROM papers p
            WHERE p.year >= {min_year}
              AND p.citation_count IS NOT NULL {focus_sql}
        """).fetchall()

    # 构建 node_id → paper info 映射
    paper_nid_map = {}
    for nid, nd in G_full.nodes(data=True):
        if nd.get("node_type") == "Paper":
            pmid = nd.get("pmid", "")
            if pmid:
                paper_nid_map[pmid] = (nid, nd)

    results = []
    max_pr = max(pr.values()) if pr else 1.0
    for row in rows:
        pmid = row["pmid"] or ""
        if not pmid or pmid not in paper_nid_map:
            continue
        nid, nd = paper_nid_map[pmid]
        pg = pr.get(nid, 0.0)
        raw_cite = row["citation_count"] or 0
        # 归一化 PageRank（0~100 分）
        pr_score = round(pg / max_pr * 100, 2)
        # 偏差：PageRank 高但引用数少 → hidden_gem > 0
        hidden_gem = round(pr_score - math.log1p(raw_cite) * 5, 2)
        results.append({
            "title":       (row["title"] or "")[:80],
            "year":        row["year"],
            "citation_count": raw_cite,
            "pr_score":    pr_score,
            "hidden_gem_score": hidden_gem,
            "study_type":  row["study_type"] or "",
            "journal":     row["journal_name"] or "",
            "interpretation": (
                "隐性影响力（低引用但被重要论文引用）" if hidden_gem > 5
                else "主流引用（引用来源质量高）" if pr_score > 30
                else "普通"
            ),
        })

    # 按 hidden_gem_score 降序（找被忽视的有影响力论文）
    results.sort(key=lambda x: x["hidden_gem_score"], reverse=True)
    return {
        "description": (
            "引用网络 PageRank 分析（2020年后论文）。"
            "hidden_gem_score高 → 被高影响力论文引用但自身引用数少（隐性影响力，值得关注）；"
            "pr_score高 → 在引用网络中真正居于枢纽地位。"
        ),
        "data": results[:top_n],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 工具注册表（供 gap_agent.py 导入）
# ─────────────────────────────────────────────────────────────────────────────

GRAPH_TOOLS: dict[str, Any] = {
    "graph_entity_pagerank":       tool_graph_entity_pagerank,
    "graph_structural_holes":      tool_graph_structural_holes,
    "graph_community_gaps":        tool_graph_community_gaps,
    "graph_disease_method_reach":  tool_graph_disease_method_reach,
    "graph_citation_pagerank":     tool_graph_citation_pagerank,
}

GRAPH_TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "graph_entity_pagerank",
            "description": (
                "在实体共现图上计算 PageRank，与论文数对比。"
                "发现 pr_paper_ratio 高的实体（图结构影响力大但论文少）= 被忽视的重要方向。"
                "适合用于分析哪些 Method/Disease/Task 在知识图谱拓扑上处于核心位置但研究不足。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": "实体类型：Disease / Method / Task / Dataset，默认 Method",
                        "enum": ["Disease", "Method", "Task", "Dataset"],
                    },
                    "focus": {
                        "type": "string",
                        "description": "可选关键词，过滤实体名称（如 'transformer'）",
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "返回条数，默认 25",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "graph_structural_holes",
            "description": (
                "计算实体共现图的介数中心性（Betweenness Centrality），识别连接不同研究社群的桥梁实体。"
                "bridge_score高（介数高、论文少）= 跨领域研究突破口：该实体连接了多个研究方向但本身被忽视。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {
                        "type": "string",
                        "description": "可选关键词过滤",
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "返回条数，默认 20",
                    },
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
                "对实体共现图进行 Greedy Modularity 社区检测，识别孤立研究社群（研究孤岛）。"
                "isolation_score高的社区与其他社区连接极少 = 研究孤岛，跨越孤岛的研究是创新机会。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "min_community_size": {
                        "type": "integer",
                        "description": "最小社区规模，默认 5",
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "返回社区数，默认 15",
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
                "分析疾病与方法的多跳可达性。"
                "2-hop 可达但 1-hop 未直连的方法 = '潜在可迁移方法'——在图结构上有关联但尚无直接研究。"
                "用于发现有依据的跨领域方法迁移机会。可配合 focus 过滤特定疾病。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {
                        "type": "string",
                        "description": "可选疾病关键词过滤（如 'gastric'）",
                    },
                    "max_hops": {
                        "type": "integer",
                        "description": "最大跳数，默认 2",
                    },
                    "top_diseases": {
                        "type": "integer",
                        "description": "分析的疾病数量，默认 15",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "graph_citation_pagerank",
            "description": (
                "在引用网络上计算论文 PageRank（2020年后），与原始引用数对比。"
                "hidden_gem_score高 = 被高影响力论文引用但自身引用数少（隐性影响力论文）= 值得关注的低曝光前沿。"
                "配合 focus 关键词可聚焦特定疾病/方法领域。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {
                        "type": "string",
                        "description": "可选关键词，过滤论文标题或关联实体",
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "返回条数，默认 20",
                    },
                    "min_year": {
                        "type": "integer",
                        "description": "最早年份，默认 2020",
                    },
                },
                "required": [],
            },
        },
    },
]
