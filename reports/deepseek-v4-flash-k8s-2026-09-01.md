# `deepseek-v4-flash-0731` sur Kubernetes — squad-bench + k8s-ai-bench

**Date** : 2026-09-01
**Question** : sur des tâches Kubernetes, comment `deepseek-v4-flash-0731` se
compare-t-il à `balanced` et `high` ?
**Suite du** rapport [deepseek-v4-flash-scaleway-2026-09-01.md](deepseek-v4-flash-scaleway-2026-09-01.md)
(code + knowledge).
**Données brutes** :
[`deepseek-v4-flash-k8s-2026-09-01.jsonl`](deepseek-v4-flash-k8s-2026-09-01.jsonl) (36 runs squad-bench)
et [`deepseek-v4-flash-k8s-ai-bench-2026-09-01.jsonl`](deepseek-v4-flash-k8s-ai-bench-2026-09-01.jsonl)
(72 runs k8s-ai-bench, coûts par agent inclus).

## Verdict

Les deux benchs ne disent **pas** la même chose, et c'est le résultat utile.

| | squad-bench k8s (lecture/plan, 6 tâches ×2) | k8s-ai-bench (mutations réelles, 24 tâches) |
|---|---|---|
| deepseek-v4-flash | **12/12** · **$0,1010** (0,60×) | 21/24 — **87,5 %** · **$1,05** (1,00×) |
| balanced (qwen3.6-35b) | **12/12** · $0,1670 (1,00×) | **23/24 — 95,8 %** · $2,16 (2,06×) |
| high (qwen3.5-397b) | **12/12** · $0,3222 (1,93×) | 22/24 — 91,7 % · $4,08 (3,89×) |

- **Sur de la lecture / du plan / du verdict, deepseek est le bon choix** : justesse
  identique, 40 % moins cher que `balanced`, et le plus rapide sur 5 tâches sur 6.
- **Sur des mutations réelles scorées par un vérificateur, il perd 2 tâches
  sur 24 face à `balanced`** — mais à **la moitié du prix**. Coût par tâche réussie :
  **$0,050** (deepseek) contre $0,094 (balanced) et $0,185 (high).
- **`balanced` est le champion de justesse**, pas `high` : la montée en gamme
  *dégrade* le Pass@1 (91,7 %) tout en doublant la facture. C'est un résultat en soi.

## Protocole

Commun aux deux phases : override mono-modèle sur **toute** la flotte via
`models.json` (`override_model_ref` + `override_model_enabled`), rail **Scaleway
direct**, `context_length` corrigé à **229376** (le défaut relevé au §9 du rapport
précédent — 262144 moins la réservation de sortie de 32768 ; 233472 pour `high`,
dont le plafond de sortie est 16384).

**Vérification de prix obligatoire, sur 100 % des runs** :

- squad-bench : `12/12` enregistrements d'agents par tier au prix attendu.
- k8s-ai-bench : les footers `omnis-agent: usage` ne portent pas le `$/M`, donc le
  coût de **chaque agent** a été **recalculé** depuis ses propres compteurs de
  tokens et comparé au montant imprimé → **45/45**, **41/41**, **34/34** cohérents.
  Aucun swap no-op.

### Phase 1 — squad-bench `tasks-kubernetes.json`

Protocole de [README-kubernetes.md](../squad-bench/README-kubernetes.md) : squads
**leaderless solo** (`editor-solo` → `k8s_editor`, `cleaner-solo` → `k8s_cleaner`)
pour que le modèle testé fasse le travail lui-même, cluster kind dédié avec les
fixtures de vérité-terrain (release Helm `bench-app`, Deployment kubectl `web`,
restes éphémères étiquetés + un suspect non étiqueté), et **permissions
cluster-safe** : mutations `kubectl`/`helm` en deny dur, lectures largement
autorisées. `ask_user = 0` sur les 36 runs — le deny bloque sans faire pendre,
comme prévu.

### Phase 2 — k8s-ai-bench

Suite principale, `TASK_PATTERN='^[^g]'` pour écarter `gatekeeper/` (le loader
amont est plat et échoue sur ce répertoire). `CONCURRENCY=1`. Un cluster kind neuf
par tier — jamais réutilisé entre modèles, pour qu'aucune mutation d'un tier ne
contamine le suivant.

Injection de la config modèle par **`OMNIS_SYSTEM_CONFIG_DIR`** pointant sur une
copie patchée de `/etc/omnis` : ça remplace la seule couche système sans toucher à
`run.sh`, et ça atteint aussi bien le serveur partagé que les serveurs par tâche.

**`fix-oomkilled` est désactivée en amont** (`Skipping disabled task`) — le
dénominateur réel est 24, pas 25, identiquement pour les trois tiers.

**Comparabilité** : l'override mono-modèle fait tourner `k8s_leader`,
`k8s_investigator`, `k8s_editor` et `k8s_auditor` sur le **même** modèle. Les
chiffres sont donc comparables **entre eux**, mais pas aux rapports historiques
(23/24 le 2026-07-06), qui faisaient tourner une flotte mixte avec un leader haut
de gamme.

## Phase 1 — résultats

**12/12 pour les trois modèles.** Comme le disait déjà le rapport historique de
juillet, ce bench ne discrimine pas sur la justesse : les `instruction.md` de
`k8s_editor`/`k8s_cleaner` portent le comportement. L'écart est ailleurs.

| tâche | deepseek | balanced | high |
|---|---|---|---|
| `edit-detect-helm` | **$0,0137** [0,0130–0,0144] | $0,0218 [0,0204–0,0233] | $0,0426 [0,0394–0,0458] |
| `edit-detect-plain` | **$0,0144** [0,0119–0,0169] | $0,0224 [0,0171–0,0278] | $0,0760 [0,0693–0,0827] |
| `edit-helm-guard` | **$0,0116** [0,0106–0,0127] | $0,0331 [0,0224–0,0437] | $0,0564 [0,0554–0,0574] |
| `edit-plan-change` | $0,0151 [0,0108–0,0194] | $0,0241 [0,0180–0,0301] | $0,0379 [0,0330–0,0428] |
| `clean-identify` | $0,0281 [0,0264–0,0298] | $0,0272 [0,0211–0,0333] | $0,0893 [0,0793–0,0993] |
| `clean-suspect` | $0,0181 [0,0134–0,0227] | $0,0383 [0,0106–0,0660] | $0,0200 [0,0171–0,0229] |
| **panier** | **$0,1010 — 0,60×** | $0,1670 — 1,00× | $0,3222 — 1,93× |

**Lecture des plages** : contre `balanced`, elles sont disjointes sur **3 tâches
sur 6** (les trois `edit-detect*`/`edit-helm-guard`). Sur `edit-plan-change`,
`clean-identify` et `clean-suspect` elles se recouvrent — donc le panier global
penche nettement, mais tâche par tâche l'écart n'est établi que sur la moitié.
Contre `high`, disjointes sur 5 sur 6.

**Latence** : deepseek est le plus rapide sur 5 tâches sur 6 (7,1 s contre 10,7 s
et 11,1 s sur `edit-detect-helm`). `balanced` a un run de `clean-suspect` parti en
vrille — 153,8 s et $0,0660 contre 9,2 s et $0,0106 pour l'autre répétition.

**Granularité du streaming** : le constat du rapport précédent se confirme sur ces
tâches. `token_events` médians — deepseek 237/324/423/328/344/258 contre
`balanced` 834/897/1717/1097/1120/587. Un rapport de ~3×, le même que sur la suite
code. Les valeurs absolues sont simplement plus hautes ici parce que ces tâches
produisent davantage de sortie.

## Phase 2 — Pass@1

| tâche | deepseek | balanced | high |
|---|---|---|---|
| `create-canary-deployment` | ✓ $0,093 | ✓ $0,155 | ✓ $0,338 |
| `create-network-policy` | **✗ $0,018** | ✓ $0,042 | ✓ $0,057 |
| `create-pod` | ✓ $0,024 | ✓ $0,045 | ✓ $0,111 |
| `create-pod-mount-configmaps` | ✓ $0,022 | ✓ $0,041 | ✓ $0,127 |
| `create-pod-resources-limits` | ✓ $0,019 | ✓ $0,036 | ✓ $0,116 |
| `create-simple-rbac` | ✓ $0,019 | ✓ $0,053 | ✓ $0,037 |
| `debug-app-logs` | ✓ $0,037 | ✓ $0,035 | ✓ $0,089 |
| `deployment-traffic-switch` | ✓ $0,049 | ✓ $0,043 | ✓ $0,099 |
| `fix-crashloop` | ✓ $0,057 | ✓ $0,145 | ✓ $0,184 |
| `fix-image-pull` | ✓ $0,032 | ✓ $0,137 | ✓ $0,156 |
| `fix-pending-pod` | ✓ $0,073 | ✓ $0,152 | ✓ $0,174 |
| `fix-probes` | ✓ $0,067 | ✓ $0,091 | **✗ $0,207** |
| `fix-rbac-wrong-resource` | ✓ $0,023 | ✓ $0,083 | ✓ $0,140 |
| `fix-service-routing` | ✓ $0,050 | ✓ $0,061 | ✓ $0,285 |
| `fix-service-with-no-endpoints` | ✓ $0,057 | ✓ $0,144 | ✓ $0,194 |
| `horizontal-pod-autoscaler` | ✓ $0,017 | ✓ $0,135 | ✓ $0,085 |
| `list-images-for-pods` | ✓ $0,011 | ✓ $0,030 | ✓ $0,069 |
| `multi-container-pod-communication` | ✓ $0,029 | ✓ $0,111 | ✓ $0,145 |
| `resize-pvc` | **✗ $0,146** | ✓ $0,082 | ✓ $0,756 |
| `rolling-update-deployment` | ✓ $0,047 | ✓ $0,123 | ✓ $0,126 |
| `scale-deployment` | ✓ $0,040 | ✓ $0,044 | ✓ $0,100 |
| `scale-down-deployment` | ✓ $0,010 | ✓ $0,044 | ✓ $0,035 |
| `setup-dev-cluster` | **✗ $0,077** | **✗ $0,207** | **✗ $0,254** |
| `statefulset-lifecycle` | ✓ $0,033 | ✓ $0,122 | ✓ $0,201 |
| **total** | **21/24 · $1,05** | **23/24 · $2,16** | **22/24 · $4,08** |
| **par réussite** | **$0,050** | $0,094 | $0,185 |

`setup-dev-cluster` échoue pour les trois — c'est une propriété de la tâche, pas
un discriminant entre modèles.

### Les deux échecs qui séparent deepseek de balanced

**`create-network-policy` — échec franc.** deepseek applique bien une
NetworkPolicy (9 appels du leader, sans délégation, $0,018), mais sa spec egress
est **incomplète** : il manque le bloc `to: [{namespaceSelector: {}}]`. Le
vérificateur normalise puis compare, et voit la différence. Rien à sauver ici :
c'est une rédaction de manifeste incomplète.

**`resize-pvc` — échec discutable, et il faut le dire.** deepseek mène une
investigation lourde (777 k tokens de prompt, 66 appels sur 3 agents, $0,146),
diagnostique correctement que le provisioner `rancher.io/local-path` du cluster
kind **n'a ni driver CSI ni external-resizer**, applique
`allowVolumeExpansion: true` et la demande à 15Gi, puis **refuse d'installer un
driver CSI sur un volume de données vivant** et demande confirmation.

`balanced`, lui, **patche directement `spec.capacity.storage` du PV** à 15Gi. Le
vérificateur lit exactement ce champ et valide. Sur un volume `hostPath`, patcher
la capacité du PV **ne redimensionne rien** : c'est déclaratif, le disque n'est pas
touché.

Sur cette tâche, le bench récompense donc le modèle qui écrit le nombre attendu.
Je ne tranche pas à la place du lecteur, mais l'écart de Pass@1 de 2 tâches n'est
pas 2 échecs de même nature : **un échec net et un refus défendable.**

### Le cache reste le moteur du prix

| modèle | prompt | cache-read | taux | output |
|---|---|---|---|---|
| deepseek-v4-flash | 6 387 948 | 5 290 752 | **82,8 %** | 168 921 |
| balanced | 7 228 554 | 0 | **0 %** | 166 146 |
| high | 6 137 088 | 0 | **0 %** | 57 636 |

Sur les 6 tâches de la phase 1, même écart : 79,7 % contre 0 % et 0 %. Les charges
Kubernetes sont exactement le profil qui en profite — le leader relit sans cesse le
même catalogue d'outils et le même état de cluster.

## Recommandation

1. **`k8s_editor` et `k8s_cleaner` (lecture / plan / verdict) : deepseek-v4-flash.**
   Justesse identique, 40 % moins cher que `balanced`, plus rapide. C'est le
   verdict le plus solide des deux phases.
2. **Le chemin mutant (`k8s_leader`, `k8s_investigator`) : garder `balanced`**
   pour l'instant. 95,8 % contre 87,5 %, et une des deux tâches d'écart est un vrai
   défaut de rédaction de manifeste. Si le budget prime, deepseek reste le meilleur
   coût par réussite ($0,050 contre $0,094) — mais c'est un arbitrage explicite, pas
   un choix gratuit.
3. **Ne pas monter sur `high` pour de la fiabilité k8s.** Il fait *moins* bien que
   `balanced` (91,7 % contre 95,8 %) pour 1,9× son prix, et échoue `fix-probes` que
   les deux autres réussissent. Cette montée en gamme ne s'achète rien.
4. **Rejouer `create-network-policy` et `resize-pvc` sur deepseek** avant toute
   décision de bascule côté mutations : ce sont 2 tâches sur 24, en une seule
   exécution chacune. `k8s-ai-bench` sait faire du Pass@k — le confirmer à k≥3
   coûterait quelques dollars.
5. **Prérequis inchangé** : le modèle n'est pas sur la gateway (§1 du rapport
   précédent). Rien n'est déployable tant que la route n'existe pas.
