# k8s-ai-bench après la couche de validation Kubernetes — campagne valide

**Date** : 2026-09-05
**Contexte** : re-run de la suite principale après deux correctifs — le sémaphore
par session côté omnis (`3b5dd17`, qui invalidait
[la campagne précédente](omnis-k8s-validator-starvation-2026-09-05.md)) et la
détection d'`ask_user` côté harnais.
**Données** :
[`deepseek-v4-flash-k8s-ai-bench-2026-09-05.jsonl`](deepseek-v4-flash-k8s-ai-bench-2026-09-05.jsonl)
(72 tâches, avec l'ordre d'exécution, `blocked_by_ask_user`, et les coûts par agent).
**Vérification de prix** : **234/234** footers `omnis-agent: usage` recalculés
agent par agent depuis leurs propres compteurs de tokens et confrontés au montant
imprimé — 84/84, 77/77, 73/73. Aucun swap no-op.

## Verdict

| | Pass@1 | hors escalade | août | coût | part validateur |
|---|---|---|---|---|---|
| **deepseek-v4-flash** | **21/24 — 87,5 %** | **21/23 — 91,3 %** | 21/24 | **$4,03** | $1,34 (33 %) |
| qwen3.6-35b-a3b (`balanced`) | 14/24 — 58,3 % | 14/17 — 82,4 % | 23/24 | $4,01 | $1,31 (33 %) |
| qwen3.5-397b-a17b (`high`) | 18/24 — 75,0 % | 18/21 — 85,7 % | 22/24 | $9,44 | $3,75 (40 %) |

- **deepseek tient exactement son score d'août** (21/24) là où `balanced` chute de
  23/24 à 14/24 et `high` de 22/24 à 18/24. Il devient le **meilleur des trois**
  sur cette suite, ce qui inverse la conclusion du 1ᵉʳ septembre.
- **Mais la chute des deux baselines n'est pas un défaut de raisonnement** — elle
  est dominée par des blocages que le modèle ne peut pas lever. Voir plus bas.
- **Le coût double à quadruple**, et **un tiers à 40 % part dans le validateur**.

## Le fait central : 11 tâches bloquées par une escalade

La couche de validation refuse une commande `Bash`, et omnis **escalade ce refus en
demande de confirmation** au lieu de rendre un refus terminal. En headless personne
ne peut répondre. Les 11 occurrences, tous tiers confondus, portent le **même**
message :

```
omnis-agent: aborted - a tool call asked the user to confirm, and nothing here
can answer: **A validation hook is refusing `Bash`.**
```

Décomposition des 24 tâches par tier :

| tier | succès | échec réel | **bloqué par escalade** | timeout |
|---|---|---|---|---|
| deepseek | 21 | 1 | **1** | 1 |
| balanced | 14 | 2 | **7** | 1 |
| high | 18 | 3 | **3** | 0 |

Tâches bloquées :

- **deepseek** : `debug-app-logs`
- **balanced** : `create-pod-mount-configmaps`, `create-pod-resources-limits`,
  `fix-rbac-wrong-resource`, `fix-service-routing`,
  `multi-container-pod-communication`, `setup-dev-cluster`, `statefulset-lifecycle`
- **high** : `create-pod`, `create-simple-rbac`, `multi-container-pod-communication`

**Ce n'est pas un jeu de tâches impossibles** : une seule
(`multi-container-pod-communication`) est bloquée chez deux tiers, aucune chez les
trois. Le taux d'escalade varie donc avec le modèle — cohérent avec une règle qui
juge la **forme** de la commande (« prouvablement en lecture seule ou refus »), pas
son intention. Un modèle qui écrit des invocations directes et simples passe ; un
modèle qui compose, substitue ou enveloppe se fait refuser.

C'est **à la fois** un signal modèle et un défaut de plomberie, et il faut le lire
des deux façons :

- **Comme signal modèle** : deepseek déclenche 1 escalade, `balanced` 7. Sur une
  flotte tournant derrière ce garde-fou, c'est une différence opérationnelle réelle.
- **Comme défaut** : un refus escaladé en `ask` est ininterprétable en headless.
  Un **refus terminal** laisserait l'agent reformuler — le hook le fait déjà pour
  l'attestation manquante (`check_attested` refuse sans jamais escalader, avec un
  commentaire expliquant précisément pourquoi l'escalade y serait un trou). La même
  doctrine appliquée à `refuse()` supprimerait les 11 blocages.

## Deux bascules qui disent quelque chose sur la mise à jour

**`create-network-policy`, deepseek : échec → réussite.** C'est exactement la tâche
que deepseek ratait en août sur une spec egress incomplète (`to:
[{namespaceSelector: {}}]` manquant). Le validateur a rattrapé le défaut :
`namespaceSelector` apparaît maintenant dans le manifeste appliqué. **Gain
directement attribuable à la couche de validation.**

**`fix-probes`, high : échec → réussite.** Deuxième gain, sur le tier qui la ratait
en août.

À l'inverse `resize-pvc` bascule en échec chez `balanced` **et** `high`, à coût
quasi nul ($0,000 et $0,009) — le garde-fou refuse tôt. En août, `balanced` la
« réussissait » en patchant directement `spec.capacity.storage` du PV, ce qui ne
redimensionne rien sur un volume `hostPath`. **La couche de validation ferme
précisément ce raccourci** : ce n'est pas une régression, c'est le contournement qui
n'est plus possible.

## Le coût

| | août | maintenant | facteur | cache |
|---|---|---|---|---|
| deepseek | $1,05 | **$4,03** | 3,9× | 62,4 % |
| balanced | $2,16 | $4,01 | 1,9× | 0 % |
| high | $4,08 | $9,44 | 2,3× | 0 % |

Le validateur consomme **431 à 582 appels par tier** et **33 à 40 % de la facture**.
Il double au moins le coût de chaque mutation : l'éditeur propose, le validateur
re-dérive les faits depuis le cluster vivant, puis atteste.

deepseek encaisse le mieux en valeur absolue parce qu'il est le seul à bénéficier du
cache — mais son facteur d'augmentation est le plus élevé (3,9×) parce que son point
de départ était le plus bas, et parce que le validateur cache mal (chaque revue
porte sur un contenu différent).

Coût par réussite : **deepseek $0,192**, `balanced` $0,286, `high` $0,524.

## Ce que je ne conclus pas

- **Le classement hors escalade (91,3 / 82,4 / 85,7 %) repose sur des dénominateurs
  différents** (23, 17, 21 tâches). Il indique une tendance, il ne la démontre pas.
- **Une seule exécution par tâche.** k8s-ai-bench sait faire du Pass@k ; les écarts
  de 1 à 3 tâches ne sont pas départagés à k=1.
- **Le lien « modèle → taux d'escalade » est plausible, pas établi.** Il faudrait
  extraire les commandes refusées et vérifier qu'elles diffèrent en forme, pas
  seulement en tâche. C'est le prochain pas utile, et il est peu coûteux : les logs
  contiennent déjà les commandes.

## Recommandation

1. **Côté omnis, prioriser le refus terminal.** Faire que `refuse()` suive la
   doctrine de `check_attested` — refuser sans escalader — supprimerait 11 blocages
   sur 72 tâches et rendrait la suite exploitable telle quelle. C'est le correctif
   au meilleur rapport.
2. **Sur cette suite, deepseek-v4-flash est maintenant le meilleur choix** :
   meilleur Pass@1 brut (87,5 %), meilleur hors escalade (91,3 %), meilleur coût par
   réussite ($0,192), et le seul à ne pas avoir régressé depuis août. Cela **inverse**
   la recommandation du rapport du 1ᵉʳ septembre, qui gardait `balanced` sur le
   chemin mutant.
3. **Ne pas monter sur `high`** : 2,3× le prix de deepseek pour un Pass@1 inférieur.
4. **Rejouer à k ≥ 3** avant toute bascule en production — surtout une fois le
   point 1 corrigé, puisqu'il change le dénominateur.
