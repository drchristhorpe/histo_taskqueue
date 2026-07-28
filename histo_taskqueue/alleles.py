"""A registry of MHC class I alleles (heavy-chain sequences) for the pMHC panel.

Alleles are loaded from a JSON file — the slim registry built by
``scripts/build_allele_registry.py`` from the IMGT/HLA locus dumps:

```json
[
  { "name": "HLA-A*02:01", "locus": "A",
    "heavy_chain": "GSHSMRYFFT…", "pocket_pseudosequence": "YFAMY…" }
]
```

Only ``name`` and ``heavy_chain`` are required (``locus`` and
``pocket_pseudosequence`` are optional metadata). The default human
β2-microglobulin sequence is loaded from ``human_b2m.json`` sitting next to the
registry, falling back to a built-in constant.

The bundled registry ships ~9,700 alleles, so the pMHC page never renders them
all — it queries :meth:`AlleleRegistry.search` through a small autocomplete API.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

RESOURCES_DIR = Path(__file__).parent / "resources" / "alleles"
DEFAULT_REGISTRY_PATH = RESOURCES_DIR / "registry.json"
DEFAULT_B2M_PATH = RESOURCES_DIR / "human_b2m.json"

#: Mature human β2-microglobulin — fallback if no b2m file is present.
FALLBACK_B2M = (
    "IQRTPKIQVYSRHPAENGKSNFLNCYVSGFHPSDIEVDLLKNGERIEKVEHSDLSFSKDW"
    "SFYLLYYTEFTPTEKDEYACRVNHVTLSQPKIVKWDRDM"
)


@dataclass(frozen=True)
class Allele:
    name: str
    heavy_chain: str
    locus: str = ""
    pocket_pseudosequence: str = ""


class AlleleRegistry:
    """In-memory registry of MHC class I alleles, loaded from JSON.

    ``path`` may point at a registry file directly, or at a directory containing
    ``registry.json`` (and optionally ``human_b2m.json``). A missing file yields
    an empty registry — the pMHC panel then falls back to pasted sequences.
    """

    def __init__(self, path: str | Path | None = None):
        base = Path(path) if path else DEFAULT_REGISTRY_PATH
        if base.is_dir():
            self.path = base / "registry.json"
            self._b2m_path = base / "human_b2m.json"
        else:
            self.path = base
            self._b2m_path = base.parent / "human_b2m.json"
        self._alleles: dict[str, Allele] = {}
        self._sorted: list[Allele] = []
        self.default_b2m = FALLBACK_B2M
        self.reload()

    def reload(self) -> None:
        self._alleles = {}
        self._load_b2m()
        if not self.path.exists():
            self._sorted = []
            return
        raw = json.loads(self.path.read_text(encoding="utf-8") or "[]")
        for item in raw:
            name = (item.get("name") or "").strip()
            heavy = (item.get("heavy_chain") or "").strip()
            if not name or not heavy:
                continue
            self._alleles[name] = Allele(
                name=name,
                heavy_chain=heavy,
                locus=(item.get("locus") or "").strip(),
                pocket_pseudosequence=(item.get("pocket_pseudosequence") or "").strip(),
            )
        self._sorted = sorted(self._alleles.values(), key=lambda a: a.name)

    def _load_b2m(self) -> None:
        if self._b2m_path.exists():
            try:
                data = json.loads(self._b2m_path.read_text(encoding="utf-8"))
                seq = (data.get("canonical_sequence") or "").strip()
                if seq:
                    self.default_b2m = seq
                    return
            except (json.JSONDecodeError, AttributeError):
                pass
        self.default_b2m = FALLBACK_B2M

    def get(self, name: str) -> Allele | None:
        return self._alleles.get((name or "").strip())

    def list(self) -> list[Allele]:
        return list(self._sorted)

    def search(self, query: str, limit: int = 20) -> list[Allele]:
        """Case-insensitive substring match on the allele name.

        Results prefer a prefix match, then any substring, and are capped at
        ``limit``. An empty query returns the first ``limit`` alleles.
        """
        q = (query or "").strip().upper()
        if not q:
            return self._sorted[:limit]
        prefix: list[Allele] = []
        contains: list[Allele] = []
        for a in self._sorted:
            upper = a.name.upper()
            if upper.startswith(q):
                prefix.append(a)
            elif q in upper:
                contains.append(a)
            if len(prefix) >= limit:
                break
        return (prefix + contains)[:limit]

    def __len__(self) -> int:
        return len(self._alleles)
