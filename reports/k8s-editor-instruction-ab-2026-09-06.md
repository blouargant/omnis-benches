# A/B de l'instruction `k8s_editor` — la théorie du commit 2 est fausse

**Date** : 2026-09-06
**Question** : la réécriture de `k8s_editor/instruction.md` (commits `78cd667` +
`2cb223c`) fait-elle ce qu'elle annonce — faire baisser les délégations au
`k8s_validator` en faisant converger l'éditeur avec `kubectl diff` d'abord ?
**Réponse courte** : **non.** L'instruction est suivie, mais son mécanisme
supposé ne se produit pas. Le résultat net est légèrement positif, pour une
raison différente de celle écrite dans le commit.
**Données** :
[`k8s-editor-instruction-ab-2026-09-06.jsonl`](k8s-editor-instruction-ab-2026-09-06.jsonl)
(2 bras × 24 tâches, avec `kubectl_diff`, `kubectl_apply`,
`validator_delegations` et les coûts par agent).

## Dispositif

Le plus propre qu'on puisse avoir : **une seule variable**. Les deux bras sont
le même binaire omnis, le même hook `k8s-validate.py` (identique au repo,
vérifié), le même protocole, le même rail Scaleway direct, un cluster kind neuf
chacun. Les seuls commits entre les deux bras sont les deux qui réécrivent
`k8s_editor/instruction.md`.

- **Bras A (baseline)** : campagne du 2026-09-06, tier `sw-deepseek-flash`, 24 tâches.
- **Bras B (nouveau)** : même tier, même suite, instruction réécrite.

Un seul modèle (`deepseek-v4-flash-0731`) : c'est celui qui isole le mieux
l'effet de l'instruction, les deux autres tiers ayant été arrêtés une fois le
signal établi.

## Résultat

| | baseline | nouveau | écart |
|---|---|---|---|
| `kubectl diff` | 29 | **66** | **+128 %** |
| `kubectl apply` | 137 | 170 | +24 % |
| délégations validateur | 57 | **72** | **+26 %** |
| appels modèle validateur | 542 | 643 | +19 % |
| coût du tier | $4,03 | $4,37 | **+8 %** |
| Pass@1 | 20/24 | **21/24** | +1 |
| timeouts | 2 | **1** | −1 |
| ratio `diff`/`apply` | 0,21 | **0,39** | — |

## Ce que ça dit

**L'instruction est obéie.** Le `diff` plus que double et le ratio
`diff`/`apply` passe de 0,21 à 0,39. L'agent fait bien ce qu'on lui demande.

**Mais le mécanisme annoncé ne se produit pas.** Le commit 2 pose que converger
avec `diff` d'abord ferait **baisser** les délégations au validateur. Elles
**montent de 26 %**. Le décompte le dit sans ambiguïté :

```
diff    29 ->  66   (+128 %)
apply  137 -> 170   ( +24 %)
```

Si le `diff` avait remplacé des tentatives d'`apply`, le second nombre baisserait.
Il monte. **La phase de prévisualisation s'est ajoutée à la boucle
apply→refus→délégation, elle ne l'a pas remplacée.**

Par tâche, l'effet est dispersé et petit : délégations en hausse sur **9**
tâches, en baisse sur **1**, inchangées sur **14**. Le +26 % agrégé vient d'une
poignée de tâches, dont `setup-dev-cluster` (8 → 13, échec dans les deux bras).

## Le résultat net, et pourquoi il ne prouve pas grand-chose

+1 tâche réussie, −1 timeout, +8 % de coût. `create-pod-mount-configmaps`
bascule d'échec en réussite.

**Une tâche sur 24, à une exécution par bras, est dans le bruit.** Les seuls
signaux robustes ici sont comportementaux — le `diff` ×2,3 (l'instruction est
lue et appliquée) et les délégations +26 % (l'objectif est manqué) — parce
qu'ils portent sur des centaines d'événements, pas sur un verdict binaire.

Le coût mérite la même prudence : 16 tâches plus chères, 8 moins chères, écart
médian **+0,0077 $**, total **+0,34 $**. C'est un déplacement réel mais faible.

## Conséquence pour la PR

Le message du commit `2cb223c` annonce un mécanisme que la mesure contredit. Il
est déjà poussé sur `origin/feat/k8s-change-validation`, donc pas réécrit ici.
Trois options, par ordre de ma préférence :

1. **Commit de suivi qui corrige l'étape 7.** Son « converge avec `diff`
   d'abord, puis délègue **une seule fois** » ne produit pas la seconde moitié.
   Soit on trouve pourquoi l'agent redélègue malgré la consigne — l'hypothèse la
   plus simple est que chaque `apply` refusé relance une demande d'attestation
   indépendamment de ce que dit l'instruction, auquel cas **aucune formulation ne
   corrigera ça et le levier est côté hook**, pas côté prompt — soit on retire
   l'étape.
2. **Garder l'instruction, corriger la justification.** Elle achète +1 tâche et
   −1 timeout pour +8 %, ce qui est défendable ; mais le commit doit dire ça, pas
   promettre une baisse des délégations.
3. **Retirer le commit 2.** Le commit 1 (les trois corrections factuelles) reste
   valide indépendamment — c'est pour ça qu'ils étaient séparés.

Le commit 1 n'est pas concerné : il corrige des affirmations fausses, vérifiées
commande par commande contre un cluster réel, et ne prétend à aucun effet chiffré.

## Ce que la mesure suggère de faire à la place

Si les délégations sont déclenchées par le refus du hook plutôt que par le
jugement de l'agent, alors le prompt n'est pas le bon levier et la piste déjà
identifiée reste la bonne : **injecter le `preview` que le hook a déjà calculé
(`kubectl diff` + dry-run serveur) dans le briefing du validateur**. Ça n'attaque
pas le nombre de délégations mais leur coût unitaire — environ 9 appels modèle
chacune (643 appels pour 72 délégations dans le bras B).

Un test décisif et peu coûteux avant d'y toucher : instrumenter le hook pour
compter combien de refus `check_attested` émet par tâche, et le comparer au
nombre de délégations. S'ils sont égaux, la boucle est pilotée par le hook et
aucune instruction ne la réduira.
