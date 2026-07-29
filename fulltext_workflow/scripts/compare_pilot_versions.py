"""Compare original before, v1 after (buggy), and after_fix."""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> dict[str, dict]:
    path = ROOT / "output" / name
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    return {r["pmid"]: r for r in rows}


def s(rows: dict[str, dict], k: str) -> int:
    return sum(int(r[k]) for r in rows.values())


def main() -> None:
    before = load("pilot_before.csv")
    v1 = load("pilot_after_v1.csv")
    fix = load("pilot_after.csv")
    print("PMID | orig ds/lim/plat | v1 ds/lim/supL/bind/plat | fix ds/lim/supL/bind/plat/status")
    print("-" * 110)
    for pmid in before:
        b, a, f = before[pmid], v1[pmid], fix[pmid]
        print(
            f"{pmid} | {b['n_active_ds']}/{b['n_active_lim']}/p={b['platform_hit']} | "
            f"{a['n_active_ds']}/{a['n_active_lim']}/sL={a['n_super_lim']}/b={a['n_bindings']}/p={a['platform_hit']} | "
            f"{f['n_active_ds']}/{f['n_active_lim']}/sL={f['n_super_lim']}/b={f['n_bindings']}/p={f['platform_hit']}/{f['reconcile_status']}"
        )
    print("\nTOTALS (orig -> v1 -> fix)")
    for label, rows in [("orig", before), ("v1", v1), ("fix", fix)]:
        print(
            f"  {label}: ds={s(rows,'n_active_ds')} lim={s(rows,'n_active_lim')} "
            f"supLim={s(rows,'n_super_lim')} bind={s(rows,'n_bindings')} "
            f"platPapers={s(rows,'platform_hit')}"
        )
    print("\nZero-active-lim papers (should shrink after fix):")
    for pmid, f in fix.items():
        v = v1[pmid]
        if int(v["n_active_lim"]) == 0 or int(f["n_active_lim"]) == 0:
            print(f"  {pmid}: v1_lim={v['n_active_lim']} fix_lim={f['n_active_lim']}")
    print("\nZero-active-ds papers:")
    for pmid, f in fix.items():
        v = v1[pmid]
        if int(v["n_active_ds"]) == 0 or int(f["n_active_ds"]) == 0:
            print(
                f"  {pmid}: v1_ds={v['n_active_ds']} fix_ds={f['n_active_ds']} "
                f"public={f.get('public_active','')[:80]}"
            )


if __name__ == "__main__":
    main()
