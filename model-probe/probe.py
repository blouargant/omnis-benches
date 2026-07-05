#!/usr/bin/env python3
"""
Omnis model-probe — verify that an OpenAI-compatible endpoint + model supports
the features Omnis actually uses, with real requests against the live endpoint.

    python3 probe.py --base-url https://api.scaleway.ai/v1 --model glm-5.2 --key "$KEY"

Reads credentials from flags first, then these env vars as fallback:
    base-url : OMNIS_PROBE_BASE_URL | OPENAI_BASE_URL | SCALEWAY_API_BASE_URL
    key      : OMNIS_PROBE_API_KEY  | OPENAI_API_KEY  | SCALEWAY_API_KEY
    model    : OMNIS_PROBE_MODEL    | OMNIS_MODEL

See CLAUDE.md for how to add checks.
"""

import argparse
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core            # noqa: E402
import checks          # noqa: E402  (importing the package registers every check)

# Categories that only run when explicitly requested (they need a specific model
# kind, e.g. an embedding or vision model).
OPT_IN_CATEGORIES = {"embeddings", "vision"}

# Display order for categories in the report. Unknown categories sort last.
CATEGORY_ORDER = ["chat", "tools", "params", "caching", "reasoning", "meta", "vision", "embeddings"]

_COLORS = {core.PASS: "32", core.FAIL: "31", core.WARN: "33",
           core.INFO: "36", core.SKIP: "90", core.ERROR: "35"}


def colorize(status, text, enable):
    if not enable:
        return text
    return "\033[%sm%s\033[0m" % (_COLORS.get(status, "0"), text)


def env_first(*names):
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None


def parse_args(argv):
    p = argparse.ArgumentParser(description="Probe an OpenAI-compatible model for Omnis feature support.")
    p.add_argument("-u", "--base-url", help="endpoint base URL incl. version path, e.g. https://api.scaleway.ai/v1")
    p.add_argument("-m", "--model", help="model id to test")
    p.add_argument("-k", "--key", help="API key (Bearer token)")
    p.add_argument("--header", action="append", default=[], metavar="K:V", help="extra request header (repeatable)")
    p.add_argument("--timeout", type=float, default=120, help="per-request timeout seconds (default 120)")
    p.add_argument("--only", help="comma-separated categories to run (default: all non-opt-in)")
    p.add_argument("--skip", help="comma-separated categories to skip")
    p.add_argument("--embeddings", action="store_true", help="run the embeddings checks (point --model at an embed model)")
    p.add_argument("--vision", action="store_true", help="run the vision checks (point --model at a vision model)")
    p.add_argument("--list", action="store_true", help="list registered checks and exit")
    p.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of a report")
    p.add_argument("--verbose", "-v", action="store_true", help="show the 'why' and data for each check")
    p.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    return p.parse_args(argv)


def selected_checks(args):
    enabled_optin = set()
    if args.embeddings:
        enabled_optin.add("embeddings")
    if args.vision:
        enabled_optin.add("vision")
    only = {c.strip() for c in args.only.split(",")} if args.only else None
    skip = {c.strip() for c in args.skip.split(",")} if args.skip else set()

    out = []
    for c in core.all_checks():
        if c.category in OPT_IN_CATEGORIES and c.category not in enabled_optin:
            continue
        if only is not None and c.category not in only:
            continue
        if c.category in skip:
            continue
        out.append(c)
    # stable order: by category rank then registration order
    out.sort(key=lambda c: (CATEGORY_ORDER.index(c.category) if c.category in CATEGORY_ORDER else len(CATEGORY_ORDER),))
    return out


def run_check(client, chk):
    try:
        res = chk.fn(client)
    except Exception as e:
        return [core.Result(core.ERROR, "check raised: %s" % e, data={"traceback": traceback.format_exc()})]
    if isinstance(res, core.Result):
        return [res]
    if isinstance(res, list):
        return res
    return [core.Result(core.ERROR, "check returned %r (expected Result)" % type(res))]


def main(argv):
    args = parse_args(argv)
    color = (not args.no_color) and sys.stdout.isatty()

    if args.list:
        for c in sorted(core.all_checks(), key=lambda c: (c.category, c.name)):
            tag = "critical" if c.critical else "info"
            optin = " [opt-in]" if c.category in OPT_IN_CATEGORIES else ""
            print("  [%-10s] %-34s (%s)%s" % (c.category, c.name, tag, optin))
            if c.why:
                print("                 %s" % c.why)
        return 0

    base_url = args.base_url or env_first("OMNIS_PROBE_BASE_URL", "OPENAI_BASE_URL", "SCALEWAY_API_BASE_URL")
    model = args.model or env_first("OMNIS_PROBE_MODEL", "OMNIS_MODEL")
    key = args.key or env_first("OMNIS_PROBE_API_KEY", "OPENAI_API_KEY", "SCALEWAY_API_KEY") or ""
    if not base_url or not model:
        print("error: --base-url and --model are required (or set the env fallbacks). See --help.", file=sys.stderr)
        return 2

    extra_headers = {}
    for h in args.header:
        if ":" in h:
            k, v = h.split(":", 1)
            extra_headers[k.strip()] = v.strip()

    client = core.Client(base_url, model, key, timeout=args.timeout, headers=extra_headers)
    chks = selected_checks(args)

    rows = []  # (check, [results])
    for chk in chks:
        rows.append((chk, run_check(client, chk)))

    if args.json:
        return emit_json(base_url, model, rows)
    return emit_report(base_url, model, rows, color, args.verbose)


def emit_json(base_url, model, rows):
    out = {"base_url": base_url, "model": model, "checks": []}
    crit_fail = False
    for chk, results in rows:
        for r in results:
            out["checks"].append({
                "name": chk.name, "category": chk.category, "critical": chk.critical,
                "why": chk.why, "status": r.status, "summary": r.summary, "data": r.data,
            })
            if chk.critical and r.status in (core.FAIL, core.ERROR):
                crit_fail = True
    print(json.dumps(out, indent=2, default=str))
    return 1 if crit_fail else 0


def emit_report(base_url, model, rows, color, verbose):
    print()
    print("  Omnis model-probe")
    print("  endpoint : %s" % base_url)
    print("  model    : %s" % model)
    print("  %s" % ("-" * 64))

    counts = {s: 0 for s in core.ALL_STATUSES}
    crit_fail = False
    last_cat = None
    for chk, results in rows:
        if chk.category != last_cat:
            print("\n  %s" % chk.category.upper())
            last_cat = chk.category
        for r in results:
            counts[r.status] += 1
            if chk.critical and r.status in (core.FAIL, core.ERROR):
                crit_fail = True
            tag = colorize(r.status, "%-5s" % r.status, color)
            star = "*" if chk.critical else " "
            print("    %s %s %-34s %s" % (tag, star, chk.name, r.summary))
            if verbose:
                if chk.why:
                    print("            why: %s" % chk.why)
                if r.data:
                    blob = json.dumps(r.data, default=str)
                    if len(blob) > 400:
                        blob = blob[:400] + " ..."
                    print("            data: %s" % blob)

    print("\n  %s" % ("-" * 64))
    summary = "  %s  %s  %s  %s  %s" % (
        colorize(core.PASS, "%d pass" % counts[core.PASS], color),
        colorize(core.FAIL, "%d fail" % counts[core.FAIL], color),
        colorize(core.WARN, "%d warn" % counts[core.WARN], color),
        colorize(core.INFO, "%d info" % counts[core.INFO], color),
        colorize(core.ERROR, "%d error" % counts[core.ERROR], color) if counts[core.ERROR] else "",
    )
    print(summary)
    verdict = "FEATURES BROKEN — see critical (*) failures above" if crit_fail else "all critical features OK"
    print("  %s\n" % colorize(core.FAIL if crit_fail else core.PASS, verdict, color))
    return 1 if crit_fail else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
