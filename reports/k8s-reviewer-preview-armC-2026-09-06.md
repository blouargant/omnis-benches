# Deux runs de la MÊME configuration : le bruit de k8s-ai-bench est plus grand que tous les effets mesurés ici

**Date** : 2026-09-06
**Question initiale** : le correctif du hook (`reviewer_preview_ok`) tient-il sa
promesse — −45 % de délégations, −24 % de coût — à l'échelle des 24 tâches ?
**Réponse** : **non**, et le run de contrôle explique pourquoi personne ne
pouvait le savoir : à **configuration strictement identique**, cette suite fait
basculer **5 verdicts sur 24** et bouge ses compteurs de comportement de 15 à
36 %. Le plancher de bruit dépasse l'effet recherché.
**Données** :
[`…-armC.jsonl`](deepseek-v4-flash-k8s-ai-bench-2026-09-06-armC.jsonl) ·
[`…-armC2.jsonl`](deepseek-v4-flash-k8s-ai-bench-2026-09-06-armC2.jsonl).

## Dispositif

Binaire omnis compilé le 2026-09-06 à 17:15 depuis `feat/k8s-reviewer-may-preview`,
config injectée par `OMNIS_SYSTEM_CONFIG_DIR` depuis une copie du `/etc/omnis`
**installé** — hook, `registry/` et `instruction.md` vérifiés identiques au HEAD
du dépôt, seul `models.json` diffère pour l'override deepseek. 24 tâches,
`CONCURRENCY=1`, cluster kind neuf, rail Scaleway direct.

- **arm B** — hook pré-correctif, instruction v1 (référence historique).
- **arm C** — build installé. `price check: 67/67`.
- **arm C2** — **répétat pur de arm C** : binaire, hook, instruction, override et
  suite identiques, vérifiés fichier par fichier avant lancement.
  `price check: 79/79`. 74 min.

## Le résultat central

| | arm C | arm C2 | |
|---|---|---|---|
| Pass@1 | 19/24 | 21/24 | **±2 tâches** |
| coût total | $3,98 | $5,64 | **1,42×** |
| délégations | 70 | 67 | |
| appels validateur | 602 | 721 | |
| timeouts harnais | 3 | 0 | |

Apparié sur les 21 tâches ayant produit un footer dans les deux runs :

| | arm C | arm C2 | écart |
|---|---|---|---|
| coût | $3,98 | $4,35 | +9 % |
| délégations | 66 | 56 | **−15 %** |
| appels validateur | 602 | 542 | −10 % |
| `kubectl diff` | 75 | 53 | **−29 %** |
| `kubectl apply` | 183 | 118 | **−36 %** |
| Pass@1 | 19 | 19 | 0 |

**Rien n'a changé entre ces deux colonnes.** Cinq verdicts basculent quand même :

| tâche | arm B | arm C | arm C2 |
|---|---|---|---|
| `create-pod` | FAIL | FAIL | **OK** |
| `fix-pending-pod` | OK | timeout | **OK** |
| `fix-service-routing` | OK | timeout | **OK** |
| `resize-pvc` | timeout | timeout | FAIL |
| `statefulset-lifecycle` | OK | OK | **FAIL** |

Les durées par tâche varient dans les mêmes proportions, sans rien changer non
plus : `debug-app-logs` 297 s → 88 s, `scale-deployment` 63 s → 156 s,
`fix-pending-pod` 605 s → 150 s.

## Ce que ça invalide

**Le −45 % de délégations et le −24 % de coût de la sonde à 4 tâches.** Le même
répétat sans aucun changement produit −15 % de délégations. La sonde mesurait du
bruit.

**Et, en partie, ma propre analyse A/B de l'instruction.** J'y écrivais que le
`diff` ×2,3 et les délégations **+26 %** étaient « les seuls signaux robustes,
parce qu'ils portent sur des centaines d'événements ». Le répétat montre que les
délégations bougent de 15 % et les `apply` de 36 % à configuration figée :

- `diff` **×2,28** (A→B) contre une oscillation à config figée de **×1,41** —
  au-dessus du bruit, le signal tient : l'instruction est bien lue et appliquée.
- délégations **×1,26** (A→B) contre **×1,18** à config figée — **pas
  distinguable**. La conclusion « l'instruction n'a pas fait baisser les
  délégations » reste vraie (elles n'ont certainement pas baissé), mais la
  hausse de +26 % ne doit plus être présentée comme un fait établi.

**`create-pod` n'est pas un échec déterministe.** Il échouait en arm A, B et C
sur le `nginx:latest` que son vérificateur amont rejette ; il **passe** en C2.
Le défaut de vérificateur est réel, mais il ne se déclenche pas à tous les coups.

## Ce que ça ne remet pas en cause

Le correctif du hook reste actif et correct — sondé directement sur le build
installé, les trois orthographes de dry-run du relecteur passent, tandis que
l'apply réel, `--dry-run=none` et le `--dry-run` nu restent refusés. Ce qui
tombe, c'est sa justification chiffrée, pas sa justesse : refuser un dry-run au
relecteur est faux, un dry-run ne persiste rien.

## Les correctifs du harnais fonctionnent

arm C2 est le premier run avec les trois réglages actifs, et ils font
exactement ce pour quoi ils ont été posés.

| | arm C | arm C2 |
|---|---|---|
| timeouts harnais (trous noirs à $0) | 3 | **0** |
| échecs longs **nommés et chiffrés** | 0 | 2 |

`resize-pvc` (556 s, $0,932) et `statefulset-lifecycle` (588 s, $0,761) sortent
désormais en `agent encountered error: exit status 1` **avec leur footer de
coût**, au lieu de disparaître en `task timed out after 10m0s` sans rien.

**Le raccourcissement de 600 s à 540 s n'a coûté aucune tâche ici**, et je l'ai
vérifié plutôt que supposé : aucune tâche du run ne se termine entre 540 s et
600 s, et les deux qui touchent la limite dépassaient déjà le mur de 600 s du
harnais (`statefulset-lifecycle` : 352 s en arm C, 588 s en arm C2 — elle aurait
été tuée dans les deux cas, en trou noir sous l'ancien réglage). Le risque
existe néanmoins pour une tâche qui finirait honnêtement dans cette fenêtre de
60 s ; `OMNIS_BENCH_DEADLINE` reste réglable.

Rappel du télescopage corrigé — trois budgets valaient 10 minutes **exactement** :
le timeout de tâche du harnais (`eval.go`), `OMNIS_BENCH_DEADLINE` (600 s) et
`defaultStreamStallTimeout` d'omnis (`core/llm/stall.go`). Le harnais gagnait
toujours, donc le garde-fou anti-flux-gelé d'omnis — pourtant porteur d'un
message clair — ne pouvait jamais s'exprimer.

## Conséquence méthodologique

**Cette suite ne peut pas trancher un effet inférieur à ~1,4× sur les
compteurs de comportement, ni de ±2 tâches sur le Pass@1, à k=1.** Toute
comparaison future doit :

1. **apparier** — une tâche tuée ne produit pas de footer et compte $0, donc le
   run qui plante le plus paraît le moins cher (le « −9 % » brut de arm C était
   entièrement cet artefact) ;
2. **répéter** — un bras unique ne mesure rien en dessous du plancher ci-dessus ;
3. ne pas confondre **mécanisme** et **gain** : une sonde à 4 tâches peut établir
   qu'un chemin de code s'active, jamais chiffrer ce qu'il rapporte.

Autre limite d'instrument : **le trafic d'outils du validateur est invisible
dans `log.txt`** (seul le flux leader/éditeur atteint le stdout capturé par le
harnais). Mesurer le comportement du garde-fou exige une trace de hook
instrumentée, pas un `grep`.

## Observation annexe

Bloqué par l'absence de redimensionneur CSI, l'agent de `resize-pvc` a lancé
`cat /home/bertrand/Documents/Dev/omnis/registry/agents/k8s_validator/instruction.md` :
il est allé introspecter la configuration d'omnis dans le checkout de
l'utilisateur au lieu de s'arrêter. L'étape 8 de l'instruction
(« STOP ON A MISSING CAPABILITY ») avait été ajoutée précisément pour cette
tâche et n'est pas suivie — c'est aussi la tâche la plus chère des deux runs
(127 appels validateur, $0,93). Piste distincte, à traiter séparément.
