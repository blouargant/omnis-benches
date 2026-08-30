#!/usr/bin/env python3
"""Apply / verify / revert an omnis config variant over the HTTP API.

Why over the API and not by editing files: OMNIS_CONFIG_PATH is exported in the
developer shell profile and bypasses OMNIS_SYSTEM_CONFIG_DIR, so file edits are
easy to apply to the wrong layer. It is also what makes time-interleaved
campaigns possible — switching variants must be one call, not a manual step.

omnis's CLAUDE.md documents that a config PUT can silently drop keys it does not
round-trip, so every apply is verified and every revert is checked against the
pre-campaign snapshot.

Live-shape note (confirmed against a running omnis-server — see Task 5's Step 1
probe): `GET /api/config/parsed/<section>` does NOT hand back the config
object directly. It wraps it in an envelope: `{"name": <section>, "data":
<config>, "mtime": <string>}`. `PUT /api/config/parsed/<section>` expects the
matching envelope back — a body shaped `{"data": <config>}` (server/config.go
binds `Data any` + an optional `MTime *time.Time`; `mtime` is only enforced
for optimistic concurrency when present, so it is deliberately omitted here —
this module does two separate writes, apply then revert, against one snapshot
that ages between them, and re-sending a stale mtime would 409).

`find_agent` / `apply_patch` operate on the UNWRAPPED `<config>` dict (i.e.
the `data` field), so they stay simple, directly unit-testable against plain
dicts, and agnostic of the transport envelope. `Switcher` is what owns the
envelope: `self.baseline[section]` is always the unwrapped config.
"""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench import api  # noqa: E402  (stdlib-only HTTP helper, already in this dir)

SECTIONS = ("agent",)


def find_agent(cfg, name):
    """Locate an agent entry regardless of the container shape (list or dict).

    `cfg` is the unwrapped section config (the `data` field of a
    `GET /api/config/parsed/<section>` response), not the transport envelope.
    """
    ags = (cfg or {}).get("agents")
    if isinstance(ags, dict):
        return ags.get(name)
    if isinstance(ags, list):
        for a in ags:
            if isinstance(a, dict) and a.get("name") == name:
                return a
    return None


def apply_patch(cfg, patch):
    """Return a NEW config with `patch` applied. Never mutates `cfg`.

    patch = {"agent": n, "key": k, "value": v}          -> set
          | {"agent": n, "remove_from": k, "value": v}  -> drop from a list
    """
    out = copy.deepcopy(cfg)
    a = find_agent(out, patch["agent"])
    if a is None:
        raise KeyError(f"agent {patch['agent']!r} not found in config")
    if "remove_from" in patch:
        cur = a.get(patch["remove_from"]) or []
        a[patch["remove_from"]] = [x for x in cur if x != patch["value"]]
    else:
        a[patch["key"]] = patch["value"]
    return out


def load_variants(path):
    with open(path) as f:
        return {v["id"]: v for v in json.load(f)["variants"]}


class Switcher:
    """Applies variants to a running server, and can always get back to V0.

    Owns the `GET`/`PUT /api/config/parsed/<section>` envelope
    (`{"data": ..., "mtime": ...}`) so `find_agent` and `apply_patch` can work
    on plain config dicts. `self.baseline[section]` is always the unwrapped
    `data` value.
    """

    def __init__(self, base, token):
        self.base, self.token = base, token
        self.baseline = None

    def _get(self, section):
        return api("GET", self.base, f"/api/config/parsed/{section}", self.token)["data"]

    def snapshot(self):
        self.baseline = {s: self._get(s) for s in SECTIONS}
        return self.baseline

    def _put(self, section, cfg):
        api("PUT", self.base, f"/api/config/parsed/{section}", self.token, {"data": cfg})

    def _reload(self):
        api("POST", self.base, "/api/config/reload", self.token, {})

    def apply(self, variant):
        """Apply a variant from the SNAPSHOT, never from current state, so
        variants never stack."""
        if self.baseline is None:
            self.snapshot()
        for section in SECTIONS:
            cfg = copy.deepcopy(self.baseline[section])
            touched = False
            for p in variant.get("patches", []):
                if p.get("section", "agent") != section:
                    continue
                cfg = apply_patch(cfg, p)
                touched = True
            if touched:
                self._put(section, cfg)
        self._reload()

    def verify(self, variant):
        """Read the live config back and confirm each patch actually landed.
        Returns a list of human-readable mismatches (empty == verified)."""
        bad = []
        for section in SECTIONS:
            live = self._get(section)
            for p in variant.get("patches", []):
                if p.get("section", "agent") != section:
                    continue
                a = find_agent(live, p["agent"]) or {}
                if "remove_from" in p:
                    if p["value"] in (a.get(p["remove_from"]) or []):
                        bad.append(f"{p['agent']}.{p['remove_from']} still has {p['value']!r}")
                elif a.get(p["key"]) != p["value"]:
                    bad.append(f"{p['agent']}.{p['key']} is {a.get(p['key'])!r},"
                               f" expected {p['value']!r}")
        return bad

    def revert(self):
        """Restore the snapshot and confirm it round-tripped."""
        if self.baseline is None:
            return []
        for section in SECTIONS:
            self._put(section, self.baseline[section])
        self._reload()
        bad = []
        for section in SECTIONS:
            live = self._get(section)
            if live != self.baseline[section]:
                bad.append(f"section {section} did not round-trip on revert")
        return bad
