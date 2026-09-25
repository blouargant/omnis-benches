# tokopt bench — omnis `token_optimization` (Bash output filters)

Results and conclusions: [`reports/token-optimization-2026-09-25.md`](../reports/token-optimization-2026-09-25.md).
The feature was **removed** from omnis afterwards, so the TO/TL variants only
mean something against an omnis build that still has `config/filters`.

```bash
OMNIS_REPO=../omnis squad-bench/setup-tokopt.sh /tmp/tokopt
export TOKOPT_DIR=/tmp/tokopt
kubectl config use-context kubernetes-admin@kubernetes   # an explicit --context triggers an ask rule
python3 squad-bench/campaign.py --tasks squad-bench/tasks-tokopt.json \
    --variants-file squad-bench/variants-tokopt.json --variants V0,TO,TL --repeat 3
```

Permissions: `npm ls`, `venv/bin/pip`, `cargo test` and `run_tests` are not in
omnis's shipped allow-list; the campaign added temporary `allow` rules scoped
with `cwd: $TOKOPT_DIR` to `~/.omnis/permissions.json` (back it up, restore after).
