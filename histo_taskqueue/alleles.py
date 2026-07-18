"""A small registry of MHC class I alleles (heavy-chain sequences).

The registry is loaded from a JSON file — a list of objects:

```json
[
  {
    "name": "HLA-A*02:01",
    "heavy_chain": "GSHSMRYFFTSVSRPGRGEPRFIAVGYVDDTQFVRFDSDAASQRMEPRAPWIEQEGPEYWD...",
    "b2m": "IQRTPKIQVYSRHPAENGKSNFLNCYVSGFHPSDIEVDLLKNGERIEKVEHSDLSFSKDW...",
    "notes": "optional free text"
  }
]
```

Only ``name`` and ``heavy_chain`` are required. ``b2m`` is optional — when
omitted, the pMHC builder falls back to the default human β2-microglobulin
sequence. The bundled file ships empty; point ``HTQ_ALLELES_PATH`` at your own
file (or replace the bundled ``resources/alleles.json``) to populate it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ALLELES_PATH = Path(__file__).parent / "resources" / "alleles.json"


@dataclass(frozen=True)
class Allele:
    name: str
    heavy_chain: str
    b2m: str | None = None
    notes: str = ""


class AlleleRegistry:
    """In-memory registry loaded from a JSON file (missing file ⇒ empty)."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else DEFAULT_ALLELES_PATH
        self._alleles: dict[str, Allele] = {}
        self.reload()

    def reload(self) -> None:
        self._alleles = {}
        if not self.path.exists():
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
                b2m=(item.get("b2m") or None),
                notes=item.get("notes", ""),
            )

    def list(self) -> list[Allele]:
        return sorted(self._alleles.values(), key=lambda a: a.name)

    def get(self, name: str) -> Allele | None:
        return self._alleles.get((name or "").strip())

    def __len__(self) -> int:
        return len(self._alleles)
