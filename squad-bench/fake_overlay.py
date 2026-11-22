#!/usr/bin/env python3
"""Config overlay that points omnis sub-agents at fake_subagents.py.

The overlay is a directory for an omnis user layer ($OMNIS_HOME; `OVERLAY=` of
setup-ab.sh, with MODEL=tiered): `models.json` declares a `fake` provider and
one model `fake-<agent>` per faked agent, and each faked agent's `agent.json`
takes it as `model_ref`. The single-model override is switched off, since it
would put the fakes back on a real model. With --leader and --leader-model the
named leaders are moved to that catalogue model.

  fake_overlay.py --sys <dir holding registry/agents> --fake a,b,c --port N
                  [--leader AGENT[,AGENT] --leader-model REF] --out <dir>
"""
import argparse
import json
from pathlib import Path

PREFIX = "fake-"


def build_overlay(sys_dir, fake, port, out, leader=None, leader_model=None):
    sys_dir, out = Path(sys_dir), Path(out)
    fake = list(fake)
    leaders = [leader] if isinstance(leader, str) else list(leader or [])
    if not fake:
        raise SystemExit("no agent to fake")
    if bool(leaders) != bool(leader_model):
        raise SystemExit("--leader and --leader-model go together")
    for name in leaders:
        if name in fake:
            raise SystemExit(f"{name!r} cannot be both a leader and a faked agent")
    for name in fake + leaders:
        if not (sys_dir / "registry" / "agents" / name).is_dir():
            raise SystemExit(f"no agent {name!r} under {sys_dir}/registry/agents")

    def write(path, obj):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, indent=1))

    write(out / "models.json", {
        "providers": {"fake": {"kind": "openai_compat",
                               "base_url": f"http://127.0.0.1:{port}/v1", "api_key": "x"}},
        "models": {PREFIX + a: {"provider_ref": "fake", "model": PREFIX + a, "context_length": 200000,
                                "input_token_price_per_million": 0, "output_token_price_per_million": 0}
                   for a in fake},
        "override_model_enabled": False})
    for a in fake:
        write(out / "registry" / "agents" / a / "agent.json", {"model_ref": PREFIX + a})
    for name in leaders:
        write(out / "registry" / "agents" / name / "agent.json", {"model_ref": leader_model})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sys", required=True, type=Path)
    ap.add_argument("--fake", required=True, help="comma-separated agent names")
    ap.add_argument("--port", required=True, type=int)
    ap.add_argument("--leader", help="comma-separated leader names to move to --leader-model")
    ap.add_argument("--leader-model")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    print(build_overlay(a.sys, [n for n in a.fake.split(",") if n], a.port, a.out,
                        [n for n in (a.leader or "").split(",") if n], a.leader_model))


if __name__ == "__main__":
    main()
