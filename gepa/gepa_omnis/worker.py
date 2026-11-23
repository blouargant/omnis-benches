"""A bench worker: one omnis-server (setup-ab.sh) and one fake_subagents.py.

The fake server holds one scenario at a time, so a worker runs its tasks one
after the other; parallelism comes from several workers on distinct ports.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import components

BENCHES = Path(__file__).resolve().parent.parent.parent
SQUAD_BENCH = BENCHES / "squad-bench"
TOKEN = "bench"


class ReloadError(Exception):
    """The candidate did not become the running config: never score it."""


def _http(method, url, body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


class Worker:
    def __init__(self, index, workdir, omnis_ref, leader_model, leaders, fake,
                 omnis_src, bench_cmd=None, port_base=18900):
        self.index, self.workdir, self.omnis_ref = index, Path(workdir), omnis_ref
        self.leader_model, self.leaders, self.fake = leader_model, list(leaders), list(fake)
        self.omnis_src = Path(omnis_src)
        self.bench_cmd = bench_cmd or [sys.executable, str(SQUAD_BENCH / "bench.py")]
        self.port, self.fake_port = port_base + 2 * index, port_base + 2 * index + 1
        self.label = f"w{index}"
        self.arm = self.workdir / self.label
        self.home, self.base = self.arm / "home", self.arm / "base"
        self.url = f"http://127.0.0.1:{self.port}"
        self.fake_url = f"http://127.0.0.1:{self.fake_port}"
        self.generation = 0
        self._fake_proc = None

    # -- lifecycle ---------------------------------------------------------------
    def build_base(self):
        """The overlay every candidate is written on top of. Without fakes (the
        real-squad held-out tasks) it only moves the leaders to the run's model."""
        import shutil
        if self.base.exists():
            shutil.rmtree(self.base)
        if self.fake:
            if str(SQUAD_BENCH) not in sys.path:
                sys.path.insert(0, str(SQUAD_BENCH))
            import fake_overlay
            fake_overlay.build_overlay(self.omnis_src, self.fake, self.fake_port, self.base,
                                       self.leaders, self.leader_model)
            return
        self.base.mkdir(parents=True)
        (self.base / "models.json").write_text(json.dumps({"override_model_enabled": False}))
        for name in self.leaders:
            p = self.base / "registry" / "agents" / name / "agent.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"model_ref": self.leader_model}))

    def start(self):
        self.arm.mkdir(parents=True, exist_ok=True)
        if self.fake:
            with open(self.arm / "fake.log", "a") as log:
                self._fake_proc = subprocess.Popen(
                    [sys.executable, str(SQUAD_BENCH / "fake_subagents.py"), str(self.fake_port)],
                    stdout=log, stderr=subprocess.STDOUT)
        self.build_base()
        env = dict(os.environ, MODEL="tiered", OVERLAY=str(self.base),
                   OMNIS_SRC=str(self.omnis_src))
        subprocess.run(["bash", str(SQUAD_BENCH / "setup-ab.sh"), str(self.workdir), self.label,
                        self.omnis_ref, str(self.port)], env=env, check=True,
                       stdout=subprocess.DEVNULL)
        deadline = time.time() + 120
        while time.time() < deadline:
            try:
                code, _ = _http("GET", self.url + "/api/squads", timeout=5)
                if code == 200:
                    break
            except OSError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError(f"{self.label}: omnis-server did not come up on {self.url}")
        self.generation = _http("GET", self.url + "/api/config/status")[1].get("generation", 0)

    def stop(self):
        subprocess.run(["bash", str(SQUAD_BENCH / "setup-ab.sh"), str(self.workdir), self.label,
                        "stop"], check=False)
        if self._fake_proc:
            self._fake_proc.terminate()
            self._fake_proc.wait(timeout=10)
            self._fake_proc = None

    def restart_model(self, leader_model):
        self.stop()
        self.leader_model = leader_model
        self.start()

    # -- candidates and runs -------------------------------------------------------
    def apply(self, candidate):
        components.apply_candidate(self.home, self.base, candidate, omnis_src=self.omnis_src)
        code, body = _http("POST", self.url + "/api/config/reload", {})
        if code != 200:
            raise ReloadError(f"{self.label}: reload refused ({code}): {body.get('error', body)}")
        gen = body.get("generation", 0)
        if gen <= self.generation:
            raise ReloadError(f"{self.label}: reload kept generation {gen} (was {self.generation})")
        code, parsed = _http("GET", self.url + "/api/config/parsed/agent")
        if code != 200:
            raise ReloadError(f"{self.label}: reading the config after reload failed ({code})")
        warnings = parsed.get("warnings") or []
        if warnings:
            raise ReloadError(f"{self.label}: config warnings after reload: {'; '.join(warnings)}")
        served = {a.get("name"): a for a in (parsed.get("data") or {}).get("agents") or []
                  if isinstance(a, dict)}
        for name, text in candidate.items():
            kind, target = components.parse(name)
            if kind not in ("instruction", "turn_reminder"):
                continue        # skills are not served by this route
            got = (served.get(target) or {}).get(kind) or ""
            if got.strip() != text.strip():
                raise ReloadError(f"{self.label}: {name} is not the text the server runs")
        self.generation = gen
        return gen

    def run(self, item, repeat):
        cmd = self.bench_cmd + ["--server", self.url, "--token", TOKEN,
                                "--tasks", str(SQUAD_BENCH / item.task_file), "--task", item.task_id,
                                "--repeat", str(repeat), "--nonce", "--json"]
        if "fake" in item.task:
            cmd += ["--fake", self.fake_url]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=repeat * 600,
                             cwd=str(BENCHES))
        recs = []
        for line in out.stdout.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    recs.append(json.loads(line))
                except ValueError:
                    pass
        if not recs:
            raise RuntimeError(f"{self.label}: bench produced no record for {item.task_id}: "
                               f"{out.stderr.strip()[-500:]}")
        return recs
