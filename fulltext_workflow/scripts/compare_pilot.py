"""Compare pilot before/after CSV snapshots."""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    before = list(csv.DictReader((ROOT / "output" / "pilot_before.csv").open(encoding="utf-8")))
    after_path = ROOT / "output" / "pilot_after.csv"
    if not after_path.exists():
        print("missing after snapshot")
        return
    after = list(csv.DictReader(after_path.open(encoding="utf-8")))
    ba = {r["pmid"]: r for r in before}
    aa = {r["pmid"]: r for r in after}

    print("PMID | before ds/lim/plat | after ds/lim/supLim/bind/plat/status")
    print("-" * 100)
    for pmid in ba:
        b, a = ba[pmid], aa[pmid]
        print(
            f"{pmid} | {b['n_active_ds']}/{b['n_active_lim']}/plat={b['platform_hit']} | "
            f"{a['n_active_ds']}/{a['n_active_lim']}/supLim={a['n_super_lim']}/"
            f"bind={a['n_bindings']}/plat={a['platform_hit']}/{a['reconcile_status']}"
        )

    def s(rows: list[dict], k: str) -> int:
        return sum(int(r[k]) for r in rows)

    print("\nTOTALS")
    print(f"  active_ds: {s(before,'n_active_ds')} -> {s(after,'n_active_ds')}")
    print(f"  active_lim: {s(before,'n_active_lim')} -> {s(after,'n_active_lim')}")
    print(f"  super_lim: {s(before,'n_super_lim')} -> {s(after,'n_super_lim')}")
    print(f"  bindings: {s(before,'n_bindings')} -> {s(after,'n_bindings')}")
    print(f"  platform_hit_papers: {s(before,'platform_hit')} -> {s(after,'platform_hit')}")

    print("\nBEFORE platform names:")
    for r in before:
        if r.get("platform_names"):
            print(f"  {r['pmid']}: {r['platform_names']}")
    print("AFTER platform names:")
    for r in after:
        if r.get("platform_names"):
            print(f"  {r['pmid']}: {r['platform_names']}")
        elif int(r["platform_hit"]):
            print(f"  {r['pmid']}: (hit but empty names?)")

    print("\nAFTER public_active (sample):")
    for r in after:
        print(f"  {r['pmid']}: {r.get('public_active','')[:140]}")

    print("\nAFTER active_limitations (sample first 3):")
    for r in after[:3]:
        print(f"  {r['pmid']}: {r.get('active_limitations','')[:160]}")


if __name__ == "__main__":
    main()
