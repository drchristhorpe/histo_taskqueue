#!/usr/bin/env python3
"""Build the slim MHC class I allele registry used by the pMHC panel.

The IMGT/HLA locus dumps that histo.fyi ships (``hla_a.json`` etc.) are large
(~16 MB total) and carry far more than the app needs — every subtype, multiple
sequence variants, G-domain sequences, and so on. This script distils each
protein-level allele group down to the fields the task queue actually uses:

    { "name", "locus", "heavy_chain", "pocket_pseudosequence" }

and writes them, sorted by name, to ``histo_taskqueue/resources/alleles/registry.json``.

Usage:
    python scripts/build_allele_registry.py SRC_DIR [-o OUT.json]

``SRC_DIR`` holds the raw locus files (``hla_a.json``, ``hla_b.json``,
``hla_c.json`` — any ``hla_*.json`` is picked up). Re-run whenever a new IMGT
release is dropped in.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "histo_taskqueue" / "resources" / "alleles" / "registry.json"


def distil_locus_file(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[dict] = []
    for group_key, group in data.items():
        if not isinstance(group, dict):
            continue
        heavy = (group.get("canonical_sequence") or "").strip()
        if not heavy:
            continue
        canonical = group.get("canonical_allele") or {}
        name = (canonical.get("protein_allele_name") or "").strip()
        locus = (canonical.get("locus") or "").strip()
        if not name:
            # Fall back to the group key, e.g. hla_a_02_01 -> HLA-A*02:01
            name = _name_from_key(group_key)
        out.append(
            {
                "name": name,
                "locus": locus or _locus_from_key(group_key),
                "heavy_chain": heavy,
                "pocket_pseudosequence": (group.get("pocket_pseudosequence") or "").strip(),
            }
        )
    return out


def _name_from_key(key: str) -> str:
    parts = key.split("_")  # ["hla", "a", "02", "01"]
    if len(parts) >= 4 and parts[0] == "hla":
        return f"HLA-{parts[1].upper()}*{parts[2]}:{parts[3]}"
    return key.upper()


def _locus_from_key(key: str) -> str:
    parts = key.split("_")
    return parts[1].upper() if len(parts) >= 2 else ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("src_dir", type=Path, help="directory of raw hla_*.json files")
    parser.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    files = sorted(args.src_dir.glob("hla_*.json"))
    if not files:
        raise SystemExit(f"No hla_*.json files found in {args.src_dir}")

    alleles: list[dict] = []
    for f in files:
        distilled = distil_locus_file(f)
        alleles.extend(distilled)
        print(f"{f.name}: {len(distilled)} alleles")

    # De-duplicate by name (keep first), then sort.
    seen: set[str] = set()
    unique = []
    for a in alleles:
        if a["name"] in seen:
            continue
        seen.add(a["name"])
        unique.append(a)
    unique.sort(key=lambda a: a["name"])

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(unique, separators=(",", ":")) + "\n", encoding="utf-8")
    size_mb = args.out.stat().st_size / 1_048_576
    print(f"Wrote {len(unique)} alleles to {args.out} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
