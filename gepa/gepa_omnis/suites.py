"""Which squad-bench task files evaluate which agent (gepa/suites.json)."""
import json
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SUITES_FILE = HERE / "suites.json"
BENCH_DIR = HERE.parent / "squad-bench"
SPLITS = ("train", "val", "heldout")


class MissingSuites(Exception):
    def __init__(self, agents, what="a suite"):
        self.agents = sorted(agents)
        super().__init__(f"no {what} for: {', '.join(self.agents)} — add it to {SUITES_FILE.name}")


@dataclass
class Item:
    agent: str
    task_file: str
    task_id: str
    task: dict = field(repr=False)


def _table():
    return json.loads(Path(SUITES_FILE).read_text(encoding="utf-8"))


def load(agents, heldout_ok_missing=()):
    """The suite entries of `agents`; refuses a missing entry or held-out set."""
    tbl = _table()
    missing = [a for a in agents if a not in tbl]
    if missing:
        raise MissingSuites(missing)
    no_heldout = [a for a in agents if not tbl[a].get("heldout") and a not in heldout_ok_missing]
    if no_heldout:
        raise MissingSuites(no_heldout, "held-out suite")
    return {a: tbl[a] for a in agents}


def items(agents, split):
    if split not in SPLITS:
        raise ValueError(split)
    tbl, out = _table(), []
    for agent in sorted(agents):
        for f in tbl[agent].get(split, []):
            data = json.loads((Path(BENCH_DIR) / f).read_text(encoding="utf-8"))
            out += [Item(agent, f, t["id"], t) for t in data["tasks"]]
    return out


def fake_agents(agents):
    tbl = _table()
    return sorted({f for a in agents for f in tbl[a].get("fake", [])})
