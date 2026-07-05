# Kubernetes squad model-tier bench

Sweeps model tiers on the Kubernetes squad's **`k8s_editor`** and **`k8s_cleaner`**
sub-agents to answer "how cheap a model can these run on without losing accuracy?"

Tasks: [`tasks-kubernetes.json`](tasks-kubernetes.json) — 6 read/plan/verdict tasks
(Helm-vs-kubectl **ownership detection** ×2, the **"don't break future helm
upgrades"** safety guard, a **change-plan**, **cleanup identification** by the
`omnis.dev/ephemeral=true` label, and **suspect classification**). They are
*read/plan only* — see "Why it's cluster-safe" below.

## Prerequisites

- A reachable Kubernetes cluster with `kubectl` **and** `helm`.
- A running `omnis-server` whose config you control (a throwaway instance is
  cleanest — see below), with model credentials in the environment.

## 1. Cluster fixtures (ground truth)

```bash
NS=omnis-bench
kubectl create ns $NS

# a) a real Helm release  -> Helm-managed ground truth
cat > /tmp/bench-chart/Chart.yaml <<'Y'
apiVersion: v2
name: bench-app
version: 0.1.0
Y
mkdir -p /tmp/bench-chart/templates
cat > /tmp/bench-chart/values.yaml <<'Y'
replicaCount: 1
image: registry.k8s.io/pause:3.10
Y
cat > /tmp/bench-chart/templates/deployment.yaml <<'Y'
apiVersion: apps/v1
kind: Deployment
metadata: { name: bench-app }
spec:
  replicas: {{ .Values.replicaCount }}
  selector: { matchLabels: { app: bench-app } }
  template:
    metadata: { labels: { app: bench-app } }
    spec:
      containers: [ { name: app, image: {{ .Values.image }}, imagePullPolicy: IfNotPresent } ]
Y
helm install bench-app /tmp/bench-chart -n $NS

# b) a plain kubectl deployment (client-side apply) -> kubectl-managed ground truth
kubectl apply -n $NS -f - <<'Y'
apiVersion: apps/v1
kind: Deployment
metadata: { name: web, namespace: omnis-bench, labels: { app: web } }
spec:
  replicas: 1
  selector: { matchLabels: { app: web } }
  template:
    metadata: { labels: { app: web } }
    spec:
      containers: [ { name: app, image: registry.k8s.io/pause:3.10, imagePullPolicy: IfNotPresent } ]
Y

# c) ephemeral leftovers: one labeled pod + one labeled cm + one UNLABELED suspect
kubectl run debug-probe -n $NS --image=registry.k8s.io/pause:3.10 --restart=Never \
  --labels=omnis.dev/ephemeral=true,omnis.dev/created-by=k8s_investigator
kubectl create cm debug-cm -n $NS --from-literal=note=temp
kubectl label cm debug-cm -n $NS omnis.dev/ephemeral=true omnis.dev/created-by=k8s_investigator
kubectl run tmp-debug-shell -n $NS --image=busybox --restart=Never -- sleep 7200
```

Teardown afterwards: `helm uninstall bench-app -n omnis-bench && kubectl delete ns omnis-bench`.

## 2. Isolate the agent under test — leaderless solo squads

Bench each sub-agent as a **leaderless single-member squad** so the exact model
you set runs directly (no leader to absorb the work or mix costs), and it's
guaranteed to be exercised. Add to the server's `agents.json`:

```json
{ "name": "editor-solo",  "leader": "none", "members": ["k8s_editor"] },
{ "name": "cleaner-solo", "leader": "none", "members": ["k8s_cleaner"] }
```

This is a *conservative* test: in production a premium leader briefs and oversees
these sub-agents, so the real accuracy bar is even lower than what a solo squad
measures.

## 3. Make it cluster-safe (read/plan only)

`bench.py` **never answers `ask_user`**, so any tool call that raises a permission
prompt would hang to the deadline — and, conversely, **no mutation can ever
execute** (the bench can't approve it). Lean into that: in the server's
`permissions.json`, **hard-deny cluster mutations** and **broadly allow reads** so
runs never hang and the cluster can't be changed:

```jsonc
"deny": [
  { "regex": "\\bkubectl\\b[^|;&]*\\b(apply|delete|patch|edit|scale|rollout|replace|create|run|debug|exec|set|annotate|label|cordon|drain|taint|attach|expose|cp|port-forward)\\b", "tools": ["Bash"] },
  { "regex": "\\bhelm\\s+(install|upgrade|uninstall|delete|rollback)\\b", "tools": ["Bash"] }
],
"allow": [ "Bash(kubectl *)", "Bash(helm *)", "Bash(*)", "Write(*)", "Edit(*)", "revert(*)" ]
```

Precedence is deny → ask → allow, so mutations are blocked (no prompt, no
execution) while reads/writes flow. The tasks all say "do NOT apply / do NOT
delete", so correct behaviour is a plan/verdict in the final answer.

## 4. Sweep the model tiers

**Gotcha:** `OMNIS_CONFIG_DIRS` redirects config *files* but **not** the agent
registry — a per-agent `model_ref` edit in a custom config dir is ignored (the
registry resolves from `.agents` → `$HOME/.omnis` → `/etc/omnis`). Drive the tier
with the hot-reloadable **single-model override** in `models.json` instead:

```bash
for tier in premium high hosted balanced simple; do
  # set override in the server's models.json:
  #   "override_model_ref": "<tier>", "override_model_enabled": true
  curl -s -X POST http://127.0.0.1:8091/api/config/reload
  python3 squad-bench/bench.py --server http://127.0.0.1:8091 \
    --tasks squad-bench/tasks-kubernetes.json --suite --deadline 260 \
    --json >> results.jsonl
done
```

**Always verify the recorded per-tier price actually changed** (each record's
`models` block carries the in/out `$/M`) before trusting the numbers — a silent
no-op swap makes every tier look identical.

## Result (ChapsVision gateway, 2026-07)

All five tiers were **correct on all six tasks** — the editor/cleaner instructions
+ skills carry the behaviour; model tier only affects verbosity and latency, not
correctness. Suite cost: premium $1.57, high $0.27, balanced/simple ~$0.10,
**hosted $0.011** (~140× cheaper than premium, same accuracy). Extra latency on
`hosted` was slower endpoint throughput + a few more read commands, **not** more
reasoning turns. Conclusion: run `k8s_editor` and `k8s_cleaner` on **`hosted`**
(or `balanced` if latency matters more than cost).
