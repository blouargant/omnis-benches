# Le `k8s_validator` affame le serveur partagé — bug omnis bloquant pour k8s-ai-bench

**Date** : 2026-09-05
**Contexte** : re-test Kubernetes demandé après la mise à jour omnis du 2026-09-04
(67 commits, tous consacrés à la **couche de validation des changements
Kubernetes**).
**Verdict** : la campagne k8s-ai-bench est **invalidée** — elle mesure un bug
serveur, pas les modèles. Le bug est identifié, localisé dans le code, et
reproductible.
**Données** :
[`omnis-k8s-validator-starvation-2026-09-05.jsonl`](omnis-k8s-validator-starvation-2026-09-05.jsonl)
(54 tâches, avec l'ordre d'exécution et le compte d'appels au validateur) et
[`omnis-k8s-hook-trace-2026-09-05.jsonl`](omnis-k8s-hook-trace-2026-09-05.jsonl)
(65 invocations du hook chronométrées).

## Le bug

> **Le sémaphore `max_instances` d'un sous-agent est partagé par toutes les
> sessions du serveur. Une invocation de `k8s_validator` qui ne rend jamais la
> main retient l'unique jeton — et toute mutation Kubernetes de toute session
> ultérieure bloque jusqu'au timeout de la tâche.**

Chaîne de code :

- `k8s_validator/agent.json` déclare `"max_instances": 1`.
- `build_subagents.go:295` enveloppe chaque sous-agent dans
  `newConcurrentAgentTool(wrapped, cfg.MaxInstances)`.
- `concurrent_agent_tool.go:67` crée le sémaphore : `sem: make(chan struct{}, max)`.
- `concurrent_agent_tool.go:102-107` : `Run` fait `acquire(ctx)` puis
  `defer func() { <-t.sem }()`. La libération est correcte **si `Run` retourne** —
  un `inner.Run` qui ne retourne jamais retient le jeton indéfiniment.
- `concurrent_agent_tool.go:120-131` : `acquire` **attend** (`select` sur
  `t.sem <- struct{}{}` ou `ctx.Done()`). Les appelants suivants font donc la
  queue, ils ne sont pas rejetés.
- **Portée** : `instance.go:143` construit `Squads map[string]*SquadInstance` une
  fois **par génération de configuration**, pas par session. Le sémaphore vit
  donc aussi longtemps que la génération de config du serveur, et **toutes les
  sessions le partagent**.

k8s-ai-bench utilise délibérément **un seul serveur pour tout le run** (24
sessions successives). C'est exactement la topologie qui transforme un jeton
retenu en panne totale.

## La preuve

Ordre d'exécution réel, verdict, et nombre d'appels au `k8s_validator` :

| tier | 1ʳᵉ tâche en timeout | appels validateur | Pass@1 |
|---|---|---|---|
| deepseek-v4-flash | **#10** | 2,5,4,1,4,4,2,2,2 sur les 9 premières, puis **0 partout** | 9/24 |
| qwen3.6-35b-a3b (`balanced`) | **#2** | 5 sur la 1ʳᵉ, puis **0 partout** | 3/24 |
| qwen3.5-397b-a17b (`high`) | **#1** | **0 dès le départ** | interrompu à 6/24 |

Séquence deepseek (`.` = réussi, `T` = timeout) :

```
 1..9   . . . f . . . . .      (f = create-network-policy, échec au mérite, comme en août)
10..22  T T T T T T T T T T T T T
23      .                      list-images-for-pods — LECTURE SEULE, aucune mutation
24      T
```

Quatre faits qui verrouillent le diagnostic :

1. **Après la bascule, le validateur n'est plus jamais appelé** : 0 invocation sur
   les 14 tâches en timeout de deepseek, 23 sur 24 pour balanced. Les agents ne le
   sollicitent pas et échouent — ils **attendent son jeton**.
2. **La seule tâche qui passe après la bascule est la seule sans mutation.**
   `list-images-for-pods` (#23) n'a jamais besoin du validateur et réussit
   normalement, au milieu d'un bloc de timeouts.
3. **Les 39 tâches expirent à exactement `10m0s`** — le timeout par tâche du
   harness, pas une durée de travail.
4. **La même tâche réussit en 2 min 21 sur un serveur neuf.** `fix-crashloop`, qui
   expire à 10 min en campagne, passe en **141 s** en exécution isolée (cluster
   `k8s-diag` dédié, serveur frais) — validateur appelé, 22 appels, tâche
   **success**. Et ce run isolé tournait *pendant* le tier `high`, donc sous plus
   de charge, pas moins.

## Ce que ce n'est pas

**Ce n'est pas le hook qui coûte du temps.** Le hook `PreToolUse` a été instrumenté
(shim de chronométrage autour de `k8s-validate.py`, dans une copie de config
dédiée). Sur le run réussi de 141 s :

- **65 invocations, 4,4 s cumulées — 3 % de la durée de la tâche.**
- L'invocation la plus lente : **0,13 s**.
- Décisions : 59 `allow`, 5 `deny`, 1 indéterminée.
- Réparties sur `k8s_investigator` (30), `k8s_validator` (26), `k8s_editor` (9).

**Ce n'est pas non plus une régression de justesse des modèles.** Les tâches en
timeout produisent des logs de 1 à 10 ko — l'agent n'a quasiment rien écrit avant
d'être tué. Il n'y a pas de raisonnement à juger.

## Reproduction minimale

```bash
cd k8s-ai-bench
TASK_PATTERN='^[^g]' CONCURRENCY=1 ./run.sh
```

Observer, dans l'ordre d'exécution : les premières tâches mutantes réussissent avec
des `[tool] k8s_validator` dans `log.txt`, puis à partir d'un certain rang **toutes**
les tâches mutantes expirent à 10m0s avec **zéro** `[tool] k8s_validator`, tandis
qu'une tâche purement en lecture continue de passer.

Contre-épreuve — la même tâche sur un serveur neuf :

```bash
cd k8s-ai-bench
TASKS_DIR=<copie de tasks/ avec fix-crashloop seul> SHARED_CLUSTER=k8s-diag ./run.sh
```

→ `success` en 2m21s.

## Pistes de correction (côté omnis)

1. **Porter le sémaphore à la session, pas à la génération de config.** C'est la
   correction de fond : une session qui part en vrille ne doit pas pouvoir
   assécher les suivantes.
2. **Borner l'attente** dans `acquire` : un `acquire` sans deadline transforme une
   fuite en interblocage silencieux. Un timeout explicite rendrait une erreur
   lisible (« pas de slot validateur libre ») au lieu d'un timeout de tâche muet.
3. **Borner `inner.Run`** : le `defer` de libération est correct, le problème est
   qu'on peut ne jamais l'atteindre.
4. À défaut, **`max_instances` > 1 sur `k8s_validator`** ne fait que reculer
   l'échéance — chaque jeton retenu rapproche la panne.

## Contournement pour benchmarker en attendant

Ne pas partager le serveur entre tâches. Deux voies :

- `CLUSTER_PROVIDER=vcluster` — `run.sh` reprend alors le chemin **un serveur par
  tâche**.
- Ou lancer `run.sh` par lots courts (≤ 8 tâches) avec un serveur neuf à chaque
  lot, puis recoller les résultats.

Tant que ce n'est pas fait, **k8s-ai-bench ne peut pas produire de comparatif de
modèles** : les rangs d'exécution décident du résultat plus que les modèles.

## Ce qui reste exploitable de ce re-test

Le volet **squad-bench `tasks-kubernetes.json`** est valide — il n'exerce aucune
mutation, donc jamais le validateur (0 sollicitation sur 36 runs), et n'est pas
touché par le bug. Résultats dans
[`deepseek-v4-flash-k8s-2026-09-04.jsonl`](deepseek-v4-flash-k8s-2026-09-04.jsonl) :

| | 12/12 correct | panier | vs août |
|---|---|---|---|
| deepseek-v4-flash | ✅ | **$0,1166** — 0,74× | 1,2× |
| qwen3.6-35b-a3b | ✅ | $0,1574 — 1,00× | 0,9× |
| qwen3.5-397b-a17b | ✅ | $0,2954 — 1,88× | 0,9× |

Justesse inchangée depuis août pour les trois. L'avantage de prix de deepseek se
resserre (0,60× → 0,74×) mais reste réel.

## Deux défauts du protocole `README-kubernetes.md` corrigés au passage

Tous deux latents en août, révélés par les nouveaux comportements d'agent.

1. **`permissions.ask` est un `valueList` — concaténé entre couches.** Un
   `"ask": []` dans la couche du bench ne retire **rien** : les 33 règles `ask` de
   `/etc/omnis/permissions.json` (dont `Bash(rm *)`) restaient actives. Comme
   squad-bench ne répond jamais à `ask_user`, un agent qui écrit puis supprime un
   manifeste temporaire pendait jusqu'au deadline. La couche de validation rend ça
   fréquent : elle lie l'attestation au **contenu** du manifeste, ce qui pousse les
   agents à passer par des fichiers. **Correctif** : le tombstone
   `permissions.ask_removed`, qui retire par égalité profonde.
2. **Le regex de deny du README refusait des lectures.**
   `\bkubectl\b[^|;&]*\b(...|debug|...)\b` matche `debug` **à l'intérieur** de
   `tmp-debug-shell`, `debug-probe`, `debug-cm` — le tiret crée une frontière de
   mot. Toute commande nommant ces pods était refusée, y compris
   `kubectl describe pod debug-probe`, alors que c'est précisément le travail de
   `clean-identify`/`clean-suspect`. **Correctif** : exiger une espace avant le
   verbe (`[^|;&]*\s(verbe)(\s|$)`) — RE2 n'a pas de lookbehind. Vérifié : les 4
   mutations restent refusées, les 3 lectures passent.

## Autre effet de la mise à jour, à connaître

**`--dry-run` n'est pas un chemin de lecture reconnu.** Testé directement sur le
hook :

| commande | verdict |
|---|---|
| `kubectl diff -f x.yaml` | allow |
| `kubectl apply --dry-run=server -f x.yaml` | **deny** |
| `kubectl apply --server-side --dry-run=server -f x.yaml` | **deny** |
| `helm upgrade … --dry-run` | **deny** (attestation exigée) |

La procédure documentée du `k8s_editor` — « previews every change with kubectl/helm
diff **and dry-run** » — est donc à moitié bloquée. Un modèle l'a constaté de
lui-même en cours de tâche : *« The hook is flagging `kubectl apply` even for
dry-run »*. Ce n'est pas nécessairement un défaut (la règle inversée assume de
refuser tout ce qui n'est pas prouvablement en lecture), mais la description de
l'agent devrait cesser de promettre le dry-run.
