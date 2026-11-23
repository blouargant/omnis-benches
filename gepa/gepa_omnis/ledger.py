"""Dollar ledger of a run (append-only JSONL, so a resumed run keeps its spend)."""
import json
import threading
import time
from pathlib import Path


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._total = 0.0
        if self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._total += float(json.loads(line)["usd"])

    def add(self, usd, kind):
        with self._lock:
            self._total += float(usd)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": round(time.time(), 1), "usd": round(float(usd), 6),
                                    "kind": kind}) + "\n")

    def spent(self):
        with self._lock:
            return self._total

    def by_kind(self):
        out = {}
        if self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    d = json.loads(line)
                    out[d["kind"]] = out.get(d["kind"], 0.0) + d["usd"]
        return out


class DollarStopper:
    """GEPA stop condition: true once the ledger reaches the ceiling."""

    def __init__(self, ledger, ceiling):
        self.ledger, self.ceiling = ledger, float(ceiling)

    def __call__(self, gepa_state):
        return self.ledger.spent() >= self.ceiling
