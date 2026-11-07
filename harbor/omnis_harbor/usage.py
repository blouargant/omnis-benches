"""Token / cost accounting from an omnis event log (stdlib only).

omnis run with ``-d`` writes ``$OMNIS_HOME/logs/agent_events_<ts>.log`` as
JSONL; every model call (leader AND sub-agents — the events callback is
attached to every agent) produces one ``after_model`` record whose
``payload.response.UsageMetadata`` carries ``promptTokenCount`` (includes the
cached part, OpenAI convention), ``cachedContentTokenCount`` and
``candidatesTokenCount``.

Billing is cache-aware, same rule as squad-bench's ``note_model``: the uncached
remainder pays the input price, cached tokens pay the cache-read price (input
price when none is known), output pays the output price.

This is HARNESS-reported usage. The Harness Leaderboard meters outside the
harness (a proxy in the sandbox); see the README's limits section.
"""
from __future__ import annotations

import json
from pathlib import Path


def _um(resp: dict) -> dict:
    return resp.get("UsageMetadata") or resp.get("usageMetadata") or {}


def parse_events(lines) -> dict:
    """Fold after_model records into totals + a per-agent breakdown."""
    per: dict[str, dict] = {}
    tools = 0
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        ev = rec.get("event")
        p = rec.get("payload") or {}
        if not isinstance(p, dict):
            continue
        if ev == "before_tool":
            tools += 1
            continue
        if ev != "after_model":
            continue
        resp = p.get("response") or {}
        if resp.get("Partial") or resp.get("partial"):
            continue
        um = _um(resp)
        if not um and isinstance(p.get("usage"), dict):
            u = p["usage"]
            um = {"promptTokenCount": u.get("prompt_tokens", 0),
                  "candidatesTokenCount": u.get("candidates_tokens", 0)}
        if not um:
            continue
        a = per.setdefault(p.get("agent") or "?", {"calls": 0, "prompt": 0, "cached": 0, "output": 0})
        a["calls"] += 1
        a["prompt"] += int(um.get("promptTokenCount") or 0)
        a["cached"] += int(um.get("cachedContentTokenCount") or 0)
        a["output"] += int(um.get("candidatesTokenCount") or 0)
    tot = {"calls": 0, "prompt": 0, "cached": 0, "output": 0}
    for a in per.values():
        for k in tot:
            tot[k] += a[k]
    return {"total": tot, "agents": per, "tool_calls": tools}


def cost(t: dict, in_price: float, out_price: float, cache_price: float | None) -> float:
    """USD for one tally; prices are $ per million tokens."""
    cp = in_price if cache_price is None else cache_price
    cached = min(t["cached"], t["prompt"])
    return ((t["prompt"] - cached) * in_price + cached * cp + t["output"] * out_price) / 1e6


def agent_prices(sysconf: Path) -> dict:
    """agent -> (in, out, cache) $/M from a sysconf's models.json and agent
    model_refs. An agent without model_ref inherits its squad leader's model;
    an enabled single-model override prices every agent at that model."""
    sysconf = Path(sysconf)
    cat = json.loads((sysconf / "models.json").read_text())
    models = cat.get("models") or {}

    def tup(ref):
        m = models.get(ref) or {}
        return (float(m.get("input_token_price_per_million") or 0),
                float(m.get("output_token_price_per_million") or 0),
                m.get("cached_input_token_price_per_million"))

    refs = {}
    for f in (sysconf / "registry" / "agents").glob("*/agent.json"):
        a = json.loads(f.read_text())
        refs[a.get("name") or f.parent.name] = a.get("model_ref") or ""
    leader_of = {}
    for sq in (json.loads((sysconf / "agents.json").read_text()).get("squads") or []):
        for m in sq.get("members") or []:
            leader_of.setdefault(m, sq.get("leader") or "")
    out = {}
    for name, ref in refs.items():
        if cat.get("override_model_enabled") and cat.get("override_model_ref"):
            ref = cat["override_model_ref"]
        elif not ref:
            ref = refs.get(leader_of.get(name, ""), "")
        out[name] = tup(ref)
    return out


def cost_by_agent(agents: dict, prices: dict, default: tuple) -> float:
    """Sum of each agent's tally at its own model's price (default for unknown)."""
    return sum(cost(t, *prices.get(a, default)) for a, t in agents.items())


def parse_dir(home: Path) -> dict:
    logs = sorted((home / "logs").glob("agent_events_*.log")) if home.exists() else []
    lines: list[str] = []
    for f in logs:
        lines.extend(f.read_text(errors="replace").splitlines())
    out = parse_events(lines)
    out["event_logs"] = [str(f) for f in logs]
    return out
