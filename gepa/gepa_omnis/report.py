"""Run report (Markdown) and the patch against the omnis checkout."""
import difflib
import json
from pathlib import Path

from . import components


def _file_texts(omnis_src, name, text):
    """(relative path, current file text, file text with `text` applied)."""
    kind, target = components.parse(name)
    if kind == "instruction":
        rel = f"registry/agents/{target}/instruction.md"
        old = (Path(omnis_src) / rel).read_text(encoding="utf-8")
        return rel, old, text
    if kind == "turn_reminder":
        rel = f"registry/agents/{target}/agent.json"
        old = (Path(omnis_src) / rel).read_text(encoding="utf-8")
        aj = json.loads(old)
        aj["turn_reminder"] = text
        return rel, old, json.dumps(aj, indent=2, ensure_ascii=False) + "\n"
    if kind == "skill":
        rel = f"registry/skills/{target}/SKILL.md"
        old = (Path(omnis_src) / rel).read_text(encoding="utf-8")
        return rel, old, components.split_front_matter(old)[0] + text
    raise NotImplementedError(name)


def patch(omnis_src, seeds, best):
    out = []
    for name in sorted(best):
        if best[name] == seeds.get(name):
            continue
        rel, old, new = _file_texts(omnis_src, name, best[name])
        out += difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                    f"a/{rel}", f"b/{rel}")
    return "".join(out)


def _text_diff(a, b):
    return "".join(difflib.unified_diff(a.splitlines(keepends=True), b.splitlines(keepends=True),
                                        "seed", "best"))


def write(reports_dir, name, date, config, seeds, best, frontier, decision, spend, patch_text):
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"gepa-{name}-{date}.md"
    L = [f"# GEPA run `{name}` — {date}", "",
         f"Components: {', '.join(config['components'])}. Models: {', '.join(config['models'])} "
         f"(search on {config['models'][0]}).", "",
         f"Spend: ${sum(spend.values()):.2f} (" +
         ", ".join(f"{k} ${v:.2f}" for k, v in sorted(spend.items())) + ").", "",
         "## Held-out verdict", "",
         f"Adopt: **{'yes' if decision['adopt'] else 'no'}** — no (agent, model) below the "
         "baseline's 90 % interval and at least one above it.", "",
         "| agent | model | baseline | 90 % interval | candidate | verdict |",
         "|---|---|---|---|---|---|"]
    for r in decision["rows"]:
        L.append(f"| {r['agent']} | {r['model']} | {r['base_mean']} | "
                 f"{r['base_lo']}–{r['base_hi']} | {r['cand_mean']} | {r['verdict']} |")
    L += ["", "## Validation scores of the candidates", "", "| candidate | val score |", "|---|---|"]
    L += [f"| {i} | {s:.3f} |" for i, s in frontier]
    L += ["", "## Best texts against the seed", ""]
    for comp in sorted(best):
        L += [f"### {comp}", ""]
        d = _text_diff(seeds.get(comp, ""), best[comp])
        L += ["```diff", d.rstrip() or "(unchanged)", "```", ""]
    L += ["## Patch", "", "Apply by hand after review (never automatic):", "",
          "```diff", patch_text.rstrip() or "(no change)", "```", ""]
    path.write_text("\n".join(L), encoding="utf-8")
    return path
