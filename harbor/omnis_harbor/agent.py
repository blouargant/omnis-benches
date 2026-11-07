"""omnis as a Harbor installed agent (Harbor imports this module; it is the one
place in omnis-benches that depends on a third-party package — Harbor itself).

Usage (see ../README.md):

    harbor run -p <task dir> \
        -a omnis_harbor.agent:OmnisAgent --ak variant=full \
        -m openai/<model> ...

What it does, per trial:

* install  — builds (once, cached on the host) a static omnis CLI from a pinned
  omnis git ref + a bench *system config layer* (make_sysconf.py), uploads both
  into the sandbox under /installed-agent/.
* run      — ``omnis -d < instruction`` (one-shot CLI, prompt on stdin so an
  instruction starting with "-" is never parsed as a flag; stdin is then at EOF,
  so an ``ask_user`` the agent raises is answered "cancelled" rather than
  hanging). Env: OMNIS_SYSTEM_CONFIG_DIR (never OMNIS_CONFIG_PATH),
  OMNIS_HOME under /logs/agent (logs come back to the host),
  OMNIS_NON_INTERACTIVE=1, OMNIS_START_SQUAD=coding, curator + update check off.
* post-run — tokens and cost from omnis's own event log (usage.py).
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import threading
import tomllib
from pathlib import Path
from typing import Literal, override

from pydantic import Field

from harbor.agents.capabilities import AgentCapabilities
from harbor.agents.installed.base import BaseInstalledAgent, with_prompt_template
from harbor.agents.model_connection import ModelConnectionSpec
from harbor.agents.options import InstalledAgentOptions
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext, ModelUsage

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import make_sysconf  # noqa: E402
from omnis_harbor import usage  # noqa: E402

REMOTE = "/installed-agent/omnis-bench"
CACHE = Path(os.environ.get("OMNIS_HARBOR_CACHE", Path.home() / ".cache/omnis-benches/harbor"))
_build_lock = threading.Lock()


class OmnisOptions(InstalledAgentOptions):
    variant: Literal["full", "lean", "full-noreview"] = Field(default="full", description="full = shipped Coding squad; full-noreview = full without the reviewer; lean = coder alone, fs+tests.")
    omnis_ref: str = Field(default="HEAD", description="omnis git ref to build.")
    omnis_repo: str = Field(default=str(ROOT.parent.parent / "omnis"), description="Path to the omnis checkout (read-only: git archive).")
    in_price: float = Field(default=0.0, description="$ per M input tokens.")
    out_price: float = Field(default=0.0, description="$ per M output tokens.")
    cache_price: float | None = Field(default=None, description="$ per M cached input tokens (default: input price).")
    context_length: int = Field(default=200000)
    max_output_tokens: int = Field(default=32000)
    tiered: bool = Field(default=False, description="Keep the shipped model tiers (production) instead of one model for every agent; cost priced per agent.")
    shape: str = Field(default="", description="squad-bench/shapes.json arm applied as a user-layer overlay (empty = shipped shape).")


def _run(cmd: list[str], **kw) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw).stdout


def prepare(opts: OmnisOptions, model: str) -> tuple[Path, Path, str]:
    """Host side: (omnis binary, sysconf dir, version). Cached by inputs."""
    with _build_lock:
        env = {**os.environ, "OMNIS_REPO": opts.omnis_repo, "OMNIS_REF": opts.omnis_ref,
               "OMNIS_HARBOR_CACHE": str(CACHE)}
        build_dir = Path(_run([str(ROOT / "build-omnis.sh")], env=env).strip().splitlines()[-1])
        version = (build_dir / "VERSION").read_text().strip()
        models = None if opts.tiered else make_sysconf.bench_models(
            model, context_length=opts.context_length, max_output_tokens=opts.max_output_tokens,
            in_price=opts.in_price, out_price=opts.out_price, cache_price=opts.cache_price)
        key = hashlib.sha256(json.dumps([version, opts.variant, models, opts.tiered, opts.shape],
                                        sort_keys=True).encode()
                             + (ROOT / "make_sysconf.py").read_bytes()
                             + (ROOT.parent / "squad-bench" / "shapes.json").read_bytes()).hexdigest()[:12]
        sysconf = CACHE / f"sysconf-{opts.variant}{'-' + opts.shape if opts.shape else ''}-{key}"
        if not (sysconf / "BENCH_VARIANT").exists():
            make_sysconf.build(build_dir / "src.tar", sysconf, opts.variant, models, shape=opts.shape)
        return build_dir / "omnis", sysconf, version


class OmnisAgent(BaseInstalledAgent):
    capabilities = AgentCapabilities()
    MODEL_CONNECTION = ModelConnectionSpec(passthrough=True)
    options_model = OmnisOptions
    options: OmnisOptions

    @staticmethod
    @override
    def name() -> str:
        return "omnis"

    @property
    def _model_id(self) -> str:
        m = self.model_name or ""
        return m.split("/", 1)[1] if "/" in m else m

    @override
    def get_version_command(self) -> str | None:
        return f"{REMOTE}/omnis version"

    @override
    def parse_version(self, stdout: str) -> str:
        return stdout.strip().splitlines()[-1].strip()

    @override
    async def install(self, environment: BaseEnvironment) -> None:
        binary, sysconf, version = prepare(self.options, self._model_id)
        self._omnis_version = version
        self._sysconf = sysconf
        await self.exec_as_root(environment, command=f"mkdir -p {REMOTE}")
        await environment.upload_file(binary, f"{REMOTE}/omnis")
        await environment.upload_dir(sysconf, f"{REMOTE}/sysconf")
        await self.exec_as_root(
            environment,
            command=f"chmod -R a+rX {REMOTE} && chmod 755 {REMOTE}/omnis && {REMOTE}/omnis version",
        )

    def _env(self) -> dict[str, str]:
        access = self.model_connection
        if not access.configured_base_url or not access.api_key:
            raise ValueError("omnis needs OPENAI_BASE_URL and OPENAI_API_KEY (model connection)")
        return {
            "OPENAI_BASE_URL": access.configured_base_url,
            "OPENAI_API_KEY": access.api_key,
            "OMNIS_SYSTEM_CONFIG_DIR": f"{REMOTE}/sysconf",
            "OMNIS_HOME": "/logs/agent/omnis-home",
            "OMNIS_AGENTSKILLS_DIR": "",
            "OMNIS_NON_INTERACTIVE": "1",
            "OMNIS_START_SQUAD": "coding",
            "OMNIS_CURATOR_ENABLED": "false",
            "OMNIS_UPDATE_CHECK": "false",
            **self._time_limit_env(),
        }

    def _time_limit_env(self) -> dict[str, str]:
        """Tell omnis the task's agent time limit (omnis turn_budget max_seconds).

        The agent is killed at the task's ``[agent] timeout_sec``; omnis then tells
        its agents how much time is left once half is spent, so they stop starting
        work that cannot finish (4 of 9 full trials hit the limit in the
        2026-11-07 smokes). Read from the trial's config.json → task.toml, with a
        60 s margin for startup and the final answer. Absent/unreadable ⇒ no limit.
        """
        try:
            trial = json.loads((self.logs_dir.parent / "config.json").read_text())
            task = tomllib.loads((Path(trial["task"]["path"]) / "task.toml").read_text())
            limit = float(task["agent"]["timeout_sec"])
        except (OSError, KeyError, ValueError, TypeError, tomllib.TOMLDecodeError):
            return {}
        secs = int(limit) - 60
        return {"OMNIS_TURN_MAX_SECONDS": str(secs)} if secs > 0 else {}

    @override
    @with_prompt_template
    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        local = self.logs_dir / "instruction.md"
        local.write_text(instruction)
        await environment.upload_file(local, f"{REMOTE}/instruction.md")
        await self.exec_as_root(environment, command=f"chmod a+r {REMOTE}/instruction.md")
        await self.exec_as_agent(
            environment,
            command=(
                "mkdir -p /logs/agent/omnis-home; "
                + make_sysconf.overlay_seed_cmd(f"{REMOTE}/sysconf", "/logs/agent/omnis-home") + "; "
                f"{REMOTE}/omnis -d < {REMOTE}/instruction.md "
                "> /logs/agent/omnis.txt 2> /logs/agent/omnis.stderr; "
                "rc=$?; echo \"omnis exit $rc\" >> /logs/agent/omnis.stderr; exit $rc"
            ),
            env=self._env(),
        )

    @override
    def populate_context_post_run(self, context: AgentContext) -> None:
        u = usage.parse_dir(self.logs_dir / "omnis-home")
        t = u["total"]
        o = self.options
        if o.tiered:
            prices = usage.agent_prices(self._sysconf)
            usd = usage.cost_by_agent(u["agents"], prices, prices.get("coder", (o.in_price, o.out_price, o.cache_price)))
        else:
            usd = usage.cost(t, o.in_price, o.out_price, o.cache_price)
        context.n_input_tokens = t["prompt"]
        context.n_cache_tokens = t["cached"]
        context.n_output_tokens = t["output"]
        context.cost_usd = usd
        context.model_usage = {self._model_id: ModelUsage(
            n_input_tokens=t["prompt"], n_cache_tokens=t["cached"],
            n_output_tokens=t["output"], cost_usd=usd)}
        context.metadata = {
            "harness": "omnis", "variant": o.variant, "tiered": o.tiered, "shape": o.shape,
            "omnis_version": getattr(self, "_omnis_version", None),
            "model_calls": t["calls"], "tool_calls": u["tool_calls"],
            "agents": u["agents"],
        }
        (self.logs_dir / "omnis-usage.json").write_text(json.dumps(
            {**u, "cost_usd": usd, "variant": o.variant}, indent=2))
