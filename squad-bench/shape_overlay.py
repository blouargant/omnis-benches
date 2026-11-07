#!/usr/bin/env python3
"""Turn a squad-shape arm (shapes.json) into an omnis config overlay.

The overlay is a directory meant to be copied into an omnis user layer
($OMNIS_HOME): ``agents.json`` with the squad's reduced ``members`` (omnis
merges squads by name and replaces ``members``), and, for the leader,
``registry/agents/<leader>/instruction.md`` (a note naming the removed members,
then the shipped instruction) plus ``agent.json`` when tools are added.
A reference arm (nothing dropped or added) produces an empty overlay.

  shape_overlay.py --sys <omnis config dir with registry/> --arm <name> --out <dir>
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

NOTE = ("In this configuration the following team members are not available: {names}. "
        "Wherever this prompt or a skill tells you to delegate to them, do that part yourself "
        "with your own tools, or skip a review step that only they perform.")
WEB_NOTE = " You hold the web search and fetch tools yourself."


def load_arm(name: str) -> dict:
    arms = json.loads((HERE / "shapes.json").read_text())
    if name not in arms:
        raise SystemExit(f"unknown arm {name!r}; known: {', '.join(sorted(arms))}")
    return arms[name]


def build_overlay(sys_dir: Path, arm: dict, out: Path) -> Path:
    sys_dir, out = Path(sys_dir), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    drop, add = list(arm.get("drop") or []), list(arm.get("add_tools") or [])
    if not drop and not add:
        return out
    squads = json.loads((sys_dir / "agents.json").read_text()).get("squads") or []
    squad = next((s for s in squads if s["name"].lower() == arm["squad"].lower()), None)
    if squad is None:
        raise SystemExit(f"no squad {arm['squad']!r} in {sys_dir}/agents.json")
    members = squad.get("members") or []
    missing = [m for m in drop if m not in members]
    if missing:
        raise SystemExit(f"squad {squad['name']} has no member(s) {missing}")
    (out / "agents.json").write_text(json.dumps(
        {"squads": [{"name": squad["name"], "members": [m for m in members if m not in drop]}]}, indent=1))

    leader = arm["leader"]
    src = sys_dir / "registry" / "agents" / leader
    dst = out / "registry" / "agents" / leader
    dst.mkdir(parents=True, exist_ok=True)
    note = NOTE.format(names=", ".join(drop)) if drop else ""
    if add:
        note = (note + WEB_NOTE).strip()
        cfg = json.loads((src / "agent.json").read_text())
        tools = list(cfg.get("tools") or [])
        cfg["tools"] = tools + [t for t in add if t not in tools]
        (dst / "agent.json").write_text(json.dumps(cfg, indent=1))
    (dst / "instruction.md").write_text(note + "\n\n" + (src / "instruction.md").read_text())
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sys", required=True, type=Path)
    ap.add_argument("--arm", required=True)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    print(build_overlay(a.sys, load_arm(a.arm), a.out))


if __name__ == "__main__":
    main()
