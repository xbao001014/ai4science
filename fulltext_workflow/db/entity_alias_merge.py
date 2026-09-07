"""Conservative backfill for exact curated Method/Disease aliases."""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from db.schema import get_conn
from extractor.entity_normalize import normalize_entity_name


def _aliases(value: Any) -> set[str]:
    if not value:
        return set()
    try:
        parsed = json.loads(str(value))
        if isinstance(parsed, list):
            return {str(item).strip().lower() for item in parsed if str(item).strip()}
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return {item.strip().lower() for item in str(value).split(",") if item.strip()}


def merge_known_entity_aliases(*, apply: bool = False) -> dict[str, Any]:
    """Plan or apply exact curated alias merges.

    Broad/fuzzy disease focus resolution is deliberately excluded. Relations
    and binding foreign-key-like columns are rewired transactionally before an
    alias entity is removed.
    """
    with get_conn() as conn:
        rows = [dict(row) for row in conn.execute(
            """
            SELECT e.*,
                   (SELECT COUNT(*) FROM relations r
                    WHERE (r.object_type=e.type AND r.object_id=e.id)
                       OR (r.subject_type=e.type AND r.subject_id=e.id)) AS relation_count
            FROM entities e
            WHERE e.type IN ('Method', 'Disease')
            ORDER BY e.type, e.name
            """
        ).fetchall()]
        groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            canonical = normalize_entity_name(str(row["name"]), str(row["type"]))
            groups[(str(row["type"]), canonical)].append(row)

        plans: list[dict[str, Any]] = []
        for (entity_type, canonical), members in groups.items():
            if len(members) == 1 and members[0]["name"] == canonical:
                continue
            target = next((row for row in members if row["name"] == canonical), None)
            if target is None:
                target = sorted(
                    members,
                    key=lambda row: (-int(row["relation_count"] or 0), int(row["id"])),
                )[0]
            aliases = set()
            for member in members:
                aliases.update(_aliases(member.get("aliases")))
                if member["name"] != canonical:
                    aliases.add(str(member["name"]))
            alias_rows = [row for row in members if row["id"] != target["id"]]
            plans.append({
                "type": entity_type,
                "canonical": canonical,
                "target_id": int(target["id"]),
                "alias_ids": [int(row["id"]) for row in alias_rows],
                "aliases": sorted(aliases),
                "relations_rewired": sum(int(row["relation_count"] or 0) for row in alias_rows),
            })

        if apply:
            for plan in plans:
                target_id = int(plan["target_id"])
                entity_type = str(plan["type"])
                for alias_id in plan["alias_ids"]:
                    conn.execute(
                        "UPDATE relations SET object_id=? WHERE object_type=? AND object_id=?",
                        (target_id, entity_type, alias_id),
                    )
                    conn.execute(
                        "UPDATE relations SET subject_id=? WHERE subject_type=? AND subject_id=?",
                        (target_id, entity_type, alias_id),
                    )
                    binding_column = (
                        "method_entity_id" if entity_type == "Method" else "disease_entity_id"
                    )
                    conn.execute(
                        f"UPDATE paper_entity_bindings SET {binding_column}=? "
                        f"WHERE {binding_column}=?",
                        (target_id, alias_id),
                    )
                    conn.execute("DELETE FROM entities WHERE id=?", (alias_id,))
                conn.execute(
                    "UPDATE entities SET name=?, aliases=? WHERE id=?",
                    (
                        plan["canonical"],
                        json.dumps(plan["aliases"], ensure_ascii=False) or None,
                        target_id,
                    ),
                )
            # Rewiring can make binding rows identical. Keep the earliest row;
            # relation rows remain separate because each can own distinct evidence.
            conn.execute(
                """
                DELETE FROM paper_entity_bindings
                WHERE id IN (
                    SELECT newer.id
                    FROM paper_entity_bindings newer
                    JOIN paper_entity_bindings older ON older.id < newer.id
                     AND older.source_pmid = newer.source_pmid
                     AND COALESCE(older.method_entity_id, -1) = COALESCE(newer.method_entity_id, -1)
                     AND COALESCE(older.disease_entity_id, -1) = COALESCE(newer.disease_entity_id, -1)
                     AND COALESCE(older.dataset_entity_id, -1) = COALESCE(newer.dataset_entity_id, -1)
                )
                """
            )

    return {
        "applied": bool(apply),
        "group_count": len(plans),
        "alias_entity_count": sum(len(plan["alias_ids"]) for plan in plans),
        "relations_rewired": sum(int(plan["relations_rewired"]) for plan in plans),
        "groups": plans,
    }
