#!/usr/bin/env python3
"""Mesure le taux de hit du cache de prefixe d'un endpoint OpenAI-compatible.

Accompagne reports/deepseek-prompt-cache-2026-09-15.md — voir §6 pour la methode.
Stdlib uniquement. Prend ses identifiants dans le .env racine :
    set -a; . ./.env; set +a
    python3 reports/deepseek-prompt-cache-2026-09-15-probe.py --rail direct -n 40

Points de methode que ce script applique (et qu'une mesure a la main rate) :
  - prefixe UNIQUE par execution (nonce) => depart reellement a froid ;
  - >= 20 appels avant d'annoncer un taux (a 6 appels le resultat va de 0% a 100%) ;
  - publie la SEQUENCE, pas seulement le pourcentage ;
  - corrobore par x-envoy-upstream-service-time, independant de cached_tokens.
"""
import argparse, json, os, time, urllib.request, uuid

def build_prefix(run_id, sections=400):
    return "".join(
        f"Doc {run_id} sect {i}: the widget subsystem coordinates frobnication across "
        f"shards, retries on contention, and emits telemetry per batch. "
        for i in range(sections))

def call(base, key, model, prefix, tag, timeout=300):
    body = {"model": model, "max_tokens": 8, "messages": [
        {"role": "system", "content": prefix},
        {"role": "user", "content": f"{tag}: reply with one word."}]}
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    t0 = time.time()
    resp = urllib.request.urlopen(req, timeout=timeout)
    hdr, d = dict(resp.headers), json.load(resp)
    det = d["usage"].get("prompt_tokens_details") or {}
    return {"cached": det.get("cached_tokens") or 0,
            "prompt": d["usage"]["prompt_tokens"],
            "upstream_ms": int(hdr.get("x-envoy-upstream-service-time", -1)),
            "wall_ms": int((time.time() - t0) * 1000)}

def report(rows, window=10):
    hits = [r for r in rows if r["cached"] > 0]
    miss = [r for r in rows if r["cached"] == 0]
    seq = "".join("H" if r["cached"] > 0 else "." for r in rows)
    print(f"\n  hits {len(hits)}/{len(rows)} ({len(hits)/len(rows):.0%})   seq={seq}")
    for s in range(0, len(rows) - window + 1, window):
        w = rows[s:s + window]
        print(f"    appels {s:3d}-{s+window-1:3d}: {sum(1 for r in w if r['cached']>0)}/{window}")
    for name, rs in (("HIT ", hits), ("MISS", miss)):
        if rs:
            v = sorted(r["upstream_ms"] for r in rs)
            print(f"    upstream {name}: min={v[0]}ms med={v[len(v)//2]}ms max={v[-1]}ms")
    print("\n    Un plateau (fenetres stables) = best-effort, PAS une montee en chauffe.")
    print("    Si un MISS est aussi rapide qu'un HIT, suspecter la telemetrie, pas le cache.")

def main():
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rail", choices=["direct", "gateway"], default="direct")
    ap.add_argument("--model")
    ap.add_argument("-n", "--calls", type=int, default=40)
    ap.add_argument("--sections", type=int, default=400, help="taille du prefixe")
    a = ap.parse_args()
    if a.rail == "direct":
        base, key = os.environ["SCALEWAY_API_BASE_URL"], os.environ["SCALEWAY_API_KEY"]
        model = a.model or "deepseek-v4-flash-0731"
    else:
        base, key = os.environ["OPENAI_BASE_URL"], os.environ["OPENAI_API_KEY"]
        model = a.model or "deepseek-v4-flash-scaleway"
    run_id = uuid.uuid4().hex[:8]
    prefix = build_prefix(run_id, a.sections)
    print(f"rail={a.rail} model={model} calls={a.calls} run={run_id}")
    rows = []
    for i in range(a.calls):
        rows.append(call(base, key, model, prefix, f"q{i}"))
        print(f"  {i:3d} cached={rows[-1]['cached']:6} upstream={rows[-1]['upstream_ms']:6}ms", flush=True)
    report(rows)

if __name__ == "__main__":
    main()
