#!/usr/bin/env python3
"""Build the omnis *system config layer* used inside a Harbor sandbox.

omnis embeds no defaults: it reads its config + agent/skill registry from a
3-layer chain (.agents → $OMNIS_HOME → system). In the sandbox we ship ONE
directory and point ``OMNIS_SYSTEM_CONFIG_DIR`` at it (never
``OMNIS_CONFIG_PATH``, which bypasses the layer merge — see omnis CLAUDE.md).

The tree is the shipped omnis config (``config/`` + ``registry/`` +
``softskills/`` from the pinned omnis source tarball) with a small, explicit
set of bench overrides:

* ``models.json``  — one provider whose base_url / api_key are env-var NAMES
  (``OPENAI_BASE_URL`` / ``OPENAI_API_KEY``, resolved at runtime from the agent
  env — no secret is ever written to disk), every catalogue tier re-pointed at
  the bench model, and the single-model override switched on so every agent
  (leader and sub-agents) runs on that one model, as the leaderboard requires.
* ``permissions.json`` — ``bypassPermissions`` (no human in the loop).
* ``agents.json`` — ``start_squad: coding``, routing off (``router_squad:
  none``), no per-turn spend ceiling, curator/reflector disabled.
* ``hooks.json`` — removed: its only entry is the Kubernetes change guard
  (``fail_closed``, needs python3 on every Bash call) — irrelevant to coding
  tasks and it would block every Bash call in an image without python3.
* variant ``full-noreview`` — ``full`` minus the ``reviewer``: it is dropped
  from the Coding squad's members and its paragraph is cut from the coder's
  instruction (so the coder never calls a tool that is not mounted). Everything
  else is identical, so ``full`` vs ``full-noreview`` isolates the reviewer.
* variant ``lean`` — the Coding squad becomes leaderless with ``coder`` alone,
  tools ``fs`` + ``tests`` only, and an instruction stripped of the team /
  LSP / ast-grep sections (those tools are not mounted).

Stdlib only. Pure function ``build(...)`` is unit-tested.
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import tarfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "squad-bench"))
import shape_overlay  # noqa: E402

VARIANTS = ("full", "lean", "full-noreview")

# Catalogue tiers the shipped agents reference via model_ref. All are aliased
# to the bench model so no agent can resolve to an unreachable endpoint even
# if the override were ever ignored.
_TIERS = ("premium", "high", "balanced", "simple", "hosted", "imagegen")

LEAN_INSTRUCTION = """\
You are **Coder**, a software-engineering agent. You work directly in the
user's project, in its working directory, with a shell and file tools.

## Operating principles

- **Understand before you change.** Look at the relevant code first (`Grep`,
  `Glob`, `Read` the spans you need). Don't re-read a file you already read and
  haven't changed.
- **Verify everything you change.** An edit is not done until the build/tests
  pass. Never claim something works without checking.
- **Make the smallest change that fully solves the task.** Match the
  surrounding code's style. Don't reformat unrelated code or add features that
  weren't asked for.

## The edit → verify loop

1. Locate and understand the target (`Grep` / `Glob` / `Read`, or `Bash`).
2. Edit with `Edit` (one surgical change), `MultiEdit` (several changes at
   once) or `Write` (new/replaced file).
3. Run `run_tests` (auto-detects the framework; pass `scope` to run just what
   you touched) or the project's own command via `Bash`.
4. Only report done once the relevant checks pass — and say plainly what you
   verified and what you did not.

If a request is ambiguous, state your assumption and proceed.
"""


def _load(p: Path) -> dict:
    return json.loads(p.read_text())


def _dump(p: Path, obj: dict) -> None:
    p.write_text(json.dumps(obj, indent=2) + "\n")


def bench_models(model: str, *, context_length: int, max_output_tokens: int,
                 in_price: float, out_price: float, cache_price: float | None,
                 prompt_cache: bool | None = None) -> dict:
    entry: dict = {
        "provider_ref": "bench",
        "model": model,
        "context_length": context_length,
        "max_output_tokens": max_output_tokens,
        "input_token_price_per_million": in_price,
        "output_token_price_per_million": out_price,
    }
    if cache_price is not None:
        entry["cached_input_token_price_per_million"] = cache_price
    if prompt_cache is not None:
        entry["prompt_cache"] = prompt_cache
    models = {t: dict(entry) for t in _TIERS}
    models["bench"] = dict(entry)
    return {
        "providers": {"bench": {"kind": "openai_compat",
                                "base_url": "OPENAI_BASE_URL",
                                "api_key": "OPENAI_API_KEY"}},
        "models": models,
        "embed_model_ref": "",
        "eval_model_ref": "bench",
        "override_model_ref": "bench",
        "override_model_enabled": True,
    }


def tiered_models(shipped: dict) -> dict:
    """The shipped catalogue, unchanged tiers and prices (production tiering),
    with every provider reading the gateway from the env and no override."""
    m = json.loads(json.dumps(shipped))
    for prov in (m.get("providers") or {}).values():
        prov["base_url"], prov["api_key"] = "OPENAI_BASE_URL", "OPENAI_API_KEY"
    m["override_model_enabled"], m["override_model_ref"], m["embed_model_ref"] = False, "", ""
    return m


def overlay_seed_cmd(sysconf: str, home: str) -> str:
    """Shell that copies a squad-shape overlay into the omnis user layer."""
    return f"if [ -d {sysconf}/overlay ]; then cp -r {sysconf}/overlay/. {home}/; fi"


def patch_agents(agents: dict, variant: str) -> dict:
    a = json.loads(json.dumps(agents))
    a["agents"] = [n for n in a["agents"] if n not in ("curator", "reflector")]
    a["router_squad"] = "none"
    a["start_squad"] = "coding"
    a["turn_budget"] = {"max_tool_calls": 0, "max_tokens": 0}
    coding = [s for s in a["squads"] if s["name"].lower() == "coding"]
    if not coding:
        raise SystemExit("no Coding squad in the shipped agents.json")
    if variant == "full-noreview":
        coding[0]["members"] = [m for m in coding[0].get("members", []) if m != "reviewer"]
    if variant == "lean":
        coding[0]["leader"] = "none"
        coding[0]["members"] = ["coder"]
    return a


def strip_reviewer(instruction: str) -> str:
    """Cut the coder instruction's ``- **Reviewer** (`reviewer`)`` bullet (up to
    the next top-level bullet). Refuses when it is missing: a variant that
    silently kept the paragraph would no longer isolate the reviewer."""
    lines = instruction.splitlines(keepends=True)
    start = next((i for i, l in enumerate(lines) if l.startswith("- **Reviewer** (`reviewer`)")), None)
    if start is None:
        raise SystemExit("full-noreview: no Reviewer bullet in the coder instruction (instruction changed?)")
    end = start + 1
    while end < len(lines) and lines[end].startswith("  "):  # the bullet's indented continuation
        end += 1
    return "".join(lines[:start] + lines[end:])


def build(src_tar: Path, out: Path, variant: str, models: dict | None, shape: str = "") -> Path:
    """models None = production tiering (tiered_models of the shipped catalogue).
    shape = a squad-bench/shapes.json arm, written to <out>/overlay/."""
    if variant not in VARIANTS:
        raise ValueError(f"variant must be one of {VARIANTS}")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    with tarfile.open(src_tar) as tf:
        for m in tf.getmembers():
            top = m.name.split("/", 1)[0]
            if top not in ("config", "registry", "softskills"):
                continue
            if m.issym() or m.islnk() or ".." in Path(m.name).parts:
                continue
            rel = Path(m.name)
            if top == "config":
                rel = Path(*rel.parts[1:]) if len(rel.parts) > 1 else Path(".")
            dest = out / rel
            if m.isdir():
                dest.mkdir(parents=True, exist_ok=True)
            elif m.isfile():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(tf.extractfile(m).read())
                dest.chmod(m.mode & 0o755 | 0o644)

    (out / "hooks.json").unlink(missing_ok=True)
    if models is None:
        models = tiered_models(_load(out / "models.json"))
    _dump(out / "models.json", models)
    _dump(out / "permissions.json", {"permissions": {
        "defaultMode": "bypassPermissions", "deny": [], "ask": [], "allow": []}})
    _dump(out / "agents.json", patch_agents(_load(out / "agents.json"), variant))

    if variant == "lean":
        coder = out / "registry" / "agents" / "coder"
        cfg = _load(coder / "agent.json")
        cfg["tools"] = ["fs", "tests"]
        cfg["skills"] = []
        cfg.pop("subagents", None)
        cfg["leader"] = False
        _dump(coder / "agent.json", cfg)
        (coder / "instruction.md").write_text(LEAN_INSTRUCTION)
    if variant == "full-noreview":
        instr = out / "registry" / "agents" / "coder" / "instruction.md"
        instr.write_text(strip_reviewer(instr.read_text()))
    if shape:
        shape_overlay.build_overlay(out, shape_overlay.load_arm(shape), out / "overlay")
    (out / "BENCH_VARIANT").write_text(variant + "\n")
    return out


def tar_dir(d: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        tf.add(d, arcname="sysconf")
    return buf.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", required=True, type=Path, help="omnis src.tar (from build-omnis.sh)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--variant", choices=VARIANTS, default="full")
    ap.add_argument("--model", required=True)
    ap.add_argument("--context-length", type=int, default=200000)
    ap.add_argument("--max-output-tokens", type=int, default=32000)
    ap.add_argument("--in-price", type=float, default=0.0)
    ap.add_argument("--out-price", type=float, default=0.0)
    ap.add_argument("--cache-price", type=float, default=None)
    args = ap.parse_args()
    models = bench_models(args.model, context_length=args.context_length,
                          max_output_tokens=args.max_output_tokens,
                          in_price=args.in_price, out_price=args.out_price,
                          cache_price=args.cache_price)
    print(build(args.src, args.out, args.variant, models))


if __name__ == "__main__":
    main()
