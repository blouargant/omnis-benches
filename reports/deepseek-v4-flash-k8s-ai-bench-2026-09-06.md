# k8s-ai-bench après les correctifs du garde-fou Kubernetes

**Date** : 2026-09-06
**Contexte** : troisième passage de la suite principale. Le
[premier](omnis-k8s-validator-starvation-2026-09-05.md) était invalidé par
l'affamement du validateur ; le
[deuxième](deepseek-v4-flash-k8s-ai-bench-2026-09-05.md) était biaisé par
11 escalades `ask_user` sans réponse possible. omnis a depuis corrigé les trois
points identifiés.
**Données** :
[`deepseek-v4-flash-k8s-ai-bench-2026-09-06.jsonl`](deepseek-v4-flash-k8s-ai-bench-2026-09-06.jsonl)
(72 tâches, ordre d'exécution, `blocked_by_ask_user`, `blocked_unattended`, coûts par agent).
**Vérification de prix** : **222/222** footers recalculés agent par agent
(77/77, 76/76, 69/69). Aucun swap no-op.

## Le résultat qui compte : plus aucun blocage

**0 escalade `ask_user` et 0 blocage « unattended » sur les 72 tâches**, contre 11
au passage précédent. Et `OMNIS_NON_INTERACTIVE=1` n'a **jamais eu à servir** : les
correctifs amont ont supprimé les refus eux-mêmes, ils n'ont pas seulement rendu le
blocage propre. C'est mieux que ce que je proposais.

Les trois correctifs, vérifiés sur un cluster réel avant la campagne :

| commande | avant | maintenant |
|---|---|---|
| `kubectl exec … -- cat fichier` | refus catégorique, sans issue | **allow** |
| `kubectl exec … -- sh -c "rm -rf /data"` | refus | refus, motif précis |
| `kubectl attach` / `attach -i` | refus des deux | **allow** / refus motivé |
| `apply` dans un namespace absent | `diff failed: NotFound`, impasse | même erreur **+ la marche à suivre** |
| escalade sans audience | carte `ask_user` → pendaison | refus terminal « this run is unattended » |

Le garde-fou reste entier : `exec -- sh -c` et `attach -i` restent refusés. La
nouvelle règle (`CONTAINER_ACCESS_VERBS`) applique la doctrine d'inversion du hook
**à la commande interne** — elle prouve que ce qui s'exécute dans le conteneur est
en lecture seule, au lieu de juger le verbe `exec` en bloc.

## Verdict

| | Pass@1 | hors 2 tâches non discriminantes | coût | $/réussite | validateur |
|---|---|---|---|---|---|
| deepseek-v4-flash | 20/24 — 83,3 % | 20/22 — 90,9 % | **$4,03** | **$0,201** | 41 % |
| qwen3.6-35b-a3b (`balanced`) | 19/24 — 79,2 % | 19/22 — 86,4 % | $6,31 | $0,332 | 38 % |
| qwen3.5-397b-a17b (`high`) | **21/24 — 87,5 %** | **21/22 — 95,5 %** | $11,48 | $0,547 | 41 % |

Évolution depuis le passage biaisé : `balanced` **+5** (14→19) et `high` **+3**
(18→21) — exactement les tâches que les escalades bloquaient. deepseek passe de 21 à
20, à l'intérieur du bruit.

**Les trois modèles tiennent maintenant dans une bande de 2 tâches sur 24.** À une
seule exécution par tâche, cet écart n'est pas départageable : je ne classe pas les
modèles sur la justesse ici. **Le discriminant est le coût** — deepseek est
**1,6× moins cher que `balanced` et 2,8× moins cher que `high`**, et il a le meilleur
coût par réussite des trois.

## Deux échecs communs aux trois, non imputables aux modèles

**`create-pod` — fragilité du vérificateur amont.** Les trois écrivent
`image: nginx:latest` ; `verify.sh` exige la chaîne littérale :

```bash
IMAGE=$(kubectl get pod $POD -n $NAMESPACE -o jsonpath='{.spec.containers[0].image}')
if [ "$IMAGE" != "nginx" ]; then echo "Pod is using incorrect image: $IMAGE"; exit 1; fi
```

`nginx:latest` est la même image, et c'est l'écriture explicite canonique. La tâche
passait avant parce que les agents écrivaient `nginx` nu.

**C'est un effet de second ordre du garde-fou, et il vaut d'être noté** : en liant
l'attestation au **contenu** du manifeste, la couche de validation pousse les agents
à écrire des manifestes plutôt que des commandes impératives — et un auteur de
manifeste met un tag explicite. Le garde-fou a changé la *forme* d'expression, ce
qui fait tomber un vérificateur qui compare une chaîne exacte. Rien à corriger côté
omnis ; c'est `verify.sh` qui devrait accepter `nginx` et `nginx:latest`.

**`setup-dev-cluster`** échoue pour les trois, comme aux deux passages précédents et
en août. Propriété de la tâche.

En les retirant, le dénominateur discriminant est **22**, d'où la colonne « hors 2
tâches » ci-dessus.

## Échecs restants, par modèle

| modèle | échecs (hors les 2 communs) |
|---|---|
| deepseek | `create-pod-mount-configmaps` (timeout), `resize-pvc` (timeout) |
| balanced | `fix-crashloop` (timeout), `fix-probes` (timeout), `multi-container-pod-communication` |
| high | `rolling-update-deployment` |

Les timeouts sont maintenant rares (2, 2, 1) et ne forment plus de bloc : ce sont
des tâches lentes isolées, pas la signature d'un serveur bloqué. `resize-pvc`
continue de résister à deepseek — c'est la tâche où il refusait d'installer un
driver CSI en août ; elle mérite un examen à part si elle compte pour vous.

## Le coût de la validation reste le vrai sujet

| | coût | dont validateur | cache |
|---|---|---|---|
| deepseek | $4,03 | $1,65 — **41 %** | 63,8 % |
| balanced | $6,31 | $2,42 — 38 % | 0 % |
| high | $11,48 | $4,75 — 41 % | 0 % |

**Le `k8s_validator` consomme environ 40 % de la facture de chaque tier.** Il
re-dérive les faits depuis le cluster vivant pour chaque changement, alors que le
hook a déjà exécuté `kubectl diff` **et** un dry-run serveur et en garde la sortie
dans `preview`. Le commit `1c6aa48` fait déjà circuler les verdicts d'attestation
*vers* l'entrée du hook ; le trajet inverse — injecter le `preview` déjà calculé
dans le briefing du validateur — reste la piste d'économie la plus directe.

Second levier : le validateur tourne en `model_ref: high`. C'est un vérificateur,
pas un planificateur, et `high` coûte 2,8× deepseek pour un écart de justesse d'une
tâche sur 22.

## Recommandation

1. **Sur cette suite, deepseek-v4-flash reste le meilleur rapport** : meilleur coût
   par réussite ($0,201 contre $0,332 et $0,547), à une justesse que rien ne
   distingue à k=1.
2. **`high` n'achète pas sa prime.** Une tâche de plus sur 22, pour 2,8× le prix.
3. **Réutiliser le `preview` du hook dans le briefing du validateur** — ~40 % de la
   facture est en jeu.
4. **Signaler `create-pod` en amont** : accepter `nginx` et `nginx:latest`.
5. **Rejouer à k ≥ 3 avant toute bascule.** C'est la réserve que je maintiens depuis
   le début et elle est plus vraie que jamais maintenant que les trois modèles sont
   à deux tâches d'écart.
