"""Build NetworkX KG from full-text workflow database."""
from __future__ import annotations

import json
import os
from typing import Optional

import networkx as nx

import config
from db.schema import get_conn

NODE_COLORS: dict[str, str] = {
    "Paper": "#4A90D9",
    "Journal": "#7B68EE",
    "Disease": "#E05C5C",
    "Method": "#F0A500",
    "Task": "#00BCD4",
    "Tissue": "#FF80AB",
    "Dataset": "#80CBC4",
    "Metric": "#FFCC80",
    "Modality": "#9C27B0",
    "Limitation": "#795548",
}

STUDY_TYPE_COLORS: dict[str, str] = {
    "ai_algorithm": "#1565C0",
    "clinical_study": "#2E7D32",
    "review": "#6A1B9A",
    "meta_analysis": "#AD1457",
    "dataset_benchmark": "#E65100",
    "foundation_model": "#00695C",
    "multimodal": "#F57F17",
    "other": "#546E7A",
}


class KGBuilder:
    def __init__(self) -> None:
        self.G: nx.MultiDiGraph = nx.MultiDiGraph()

    @staticmethod
    def _paper_node_id(paper_id: int) -> str:
        return f"Paper_{paper_id}"

    @staticmethod
    def _journal_node_id(journal_id: int) -> str:
        return f"Journal_{journal_id}"

    @staticmethod
    def _entity_node_id(entity_id: int, entity_type: str) -> str:
        return f"{entity_type}_{entity_id}"

    def build(self) -> nx.MultiDiGraph:
        print("[KG] Loading data from SQLite...")
        with get_conn() as conn:
            papers = [dict(r) for r in conn.execute("SELECT * FROM papers").fetchall()]
            journals = [dict(r) for r in conn.execute("SELECT * FROM journals").fetchall()]
            entities = [dict(r) for r in conn.execute("SELECT * FROM entities").fetchall()]
            relations = [dict(r) for r in conn.execute("SELECT * FROM relations").fetchall()]

        journal_id_map: dict[int, str] = {}
        for j in journals:
            nid = self._journal_node_id(j["id"])
            journal_id_map[j["id"]] = nid
            self.G.add_node(
                nid,
                label=j["name"] or "",
                node_type="Journal",
                color=NODE_COLORS["Journal"],
            )

        paper_id_map: dict[int, str] = {}
        for p in papers:
            nid = self._paper_node_id(p["id"])
            paper_id_map[p["id"]] = nid
            study_type = p.get("study_type") or "other"
            title = p.get("title") or ""
            label = title[:80] + "..." if len(title) > 80 else title
            self.G.add_node(
                nid,
                label=label,
                node_type="Paper",
                color=STUDY_TYPE_COLORS.get(study_type, NODE_COLORS["Paper"]),
                pmid=p.get("pmid") or "",
                year=p.get("year"),
                study_type=study_type,
                full_text_status=p.get("full_text_status") or "pending",
                pmc_id=p.get("pmc_id") or "",
            )
            if p.get("journal_id") and p["journal_id"] in journal_id_map:
                self.G.add_edge(
                    nid,
                    journal_id_map[p["journal_id"]],
                    relation="PUBLISHED_IN",
                )

        entity_id_map: dict[int, str] = {}
        for e in entities:
            nid = self._entity_node_id(e["id"], e["type"])
            entity_id_map[e["id"]] = nid
            self.G.add_node(
                nid,
                label=e["name"],
                node_type=e["type"],
                color=NODE_COLORS.get(e["type"], "#AAAAAA"),
            )

        for rel in relations:
            if rel["subject_type"] == "Paper":
                subj_nid = paper_id_map.get(rel["subject_id"])
            else:
                subj_nid = entity_id_map.get(rel["subject_id"])
            obj_nid = entity_id_map.get(rel["object_id"])

            if subj_nid and obj_nid and subj_nid in self.G and obj_nid in self.G:
                self.G.add_edge(
                    subj_nid,
                    obj_nid,
                    relation=rel["relation"],
                    source_pmid=rel.get("source_pmid") or "",
                    metric_value=rel.get("metric_value") or "",
                    confidence=rel.get("confidence") or 1.0,
                    evidence_section=rel.get("evidence_section") or "",
                    evidence_quote=rel.get("evidence_quote") or "",
                    extraction_granularity=rel.get("extraction_granularity") or "abstract",
                    polarity=rel.get("polarity") or "asserted",
                )

        print(
            f"[KG] Graph built: {self.G.number_of_nodes()} nodes, "
            f"{self.G.number_of_edges()} edges."
        )
        return self.G

    def export_gexf(self, path: Optional[str] = None) -> str:
        path = path or os.path.join(config.OUTPUT_DIR, "kg_fulltext.gexf")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        G_export = self.G.copy()
        for _, data in G_export.nodes(data=True):
            for k, v in list(data.items()):
                if v is None:
                    data[k] = ""
                elif isinstance(v, (list, dict)):
                    data[k] = json.dumps(v)
        for _, _, data in G_export.edges(data=True):
            for k, v in list(data.items()):
                if v is None:
                    data[k] = ""
        nx.write_gexf(G_export, path)
        print(f"[KG] Exported GEXF to {path}")
        return path

    def export_stats_csv(self, path: Optional[str] = None) -> str:
        path = path or os.path.join(config.OUTPUT_DIR, "kg_stats.csv")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        from collections import Counter

        node_types = Counter(d.get("node_type", "?") for _, d in self.G.nodes(data=True))
        edge_rels = Counter(d.get("relation", "?") for _, _, d in self.G.edges(data=True))
        gran = Counter(
            d.get("extraction_granularity", "?") for _, _, d in self.G.edges(data=True)
        )

        lines = ["metric,value"]
        for t, c in sorted(node_types.items()):
            lines.append(f"node_{t},{c}")
        for r, c in sorted(edge_rels.items()):
            lines.append(f"edge_{r},{c}")
        for g, c in sorted(gran.items()):
            lines.append(f"granularity_{g},{c}")

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"[KG] Exported stats to {path}")
        return path
