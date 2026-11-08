# WebFetch : plan au lieu d'une page coupée — A/B (2026-11-08)

**Branche omnis** `feat/webfetch-outline` (074690f) contre `develop` (281f9b3).
Spec : `omnis/docs/superpowers/specs/2026-11-08-webfetch-outline-design.md`.
Données : `webfetch-outline-2026-11.jsonl` (une ligne par exécution, champ
`variant`), notes du juge : `webfetch-outline-2026-11-scores.jsonl`.

- **W2** = omnis `develop` : une page longue est coupée en tête (50 000 puis 32 000 caractères).
- **W3** = la branche : la navigation est retirée, la page revient entière si
  elle tient, sinon son plan ; l'agent lit ensuite `section`, `find` ou `part`.

Mêmes modèles des deux côtés (`setup-modelcost.sh` : leader `premium`,
`web_agent` `balanced`, `web_fetcher` `balanced`), recherche Serper.

## 1. Verdict

**La branche coûte 22 à 29 % de moins, sans écart de qualité mesurable.** La
règle de décision du plan (« exactitude pas plus basse, tokens totaux pas plus
hauts ») est tenue : les deux moyennes des notes diffèrent de −0,18 et −0,10 point
sur 10, loin du bruit (p = 0,54 et 0,80), et aucune réponse de la branche n'est
plafonnée pour une erreur grave sur l'équipe Knowledge.

| Banc | Exécutions | Note W2 | Note W3 | Δ | p | Coût W2 | Coût W3 | Tokens d'entrée |
|---|---|---|---|---|---|---|---|---|
| Knowledge (3 questions × 4) | 12 / 12 | 7,70 | 7,52 | −0,18 | 0,54 | 1,99 $ | 1,41 $ (−29 %) | 2,48 M → 1,76 M (−29 %) |
| Sondes `web_agent` / `web_fetcher` (6 × 6) | 34 / 35 | 6,56 | 6,46 | −0,10 | 0,80 | 0,96 $ | 0,75 $ (−22 %) | 2,96 M → 2,23 M (−25 %) |

Note = moyenne des deux juges (Opus 5.5, GPT-5.5) par réponse, notée à l'aveugle
au milieu de toutes les réponses de la même question, les deux branches mêlées.
p = test de permutation des étiquettes à l'intérieur de chaque question (5 000
tirages).

## 2. Par question

| Question | W2 | W3 |
|---|---|---|
| mc-kserve | 7,38 | 7,62 |
| mc-moe (le cas d'origine) | 7,85 | 7,67 |
| mc-netbird | 7,88 | 7,25 |
| cv-agent-compare | 7,25 | 5,92 |
| cv-agent-lookup | 6,08 | 6,92 |
| cv-agent-pg | 8,20 | 6,80 |
| cv-fetch-check | 4,25 | 5,17 |
| cv-fetch-open | 7,70 | 8,08 |
| cv-fetch-pg | 6,33 | 5,92 |

Les écarts par question vont dans les deux sens et restent à la taille du bruit
entre échantillons d'une même branche (jusqu'à 3 points sur `cv-agent-compare`).
Les reproches des juges portent sur des affirmations inventées ou datées (une
issue LiteLLM introuvable, une valeur par défaut de vLLM 0.6.4), présentes des
deux côtés, pas sur des contenus manquants.

## 3. Ce que les agents font des nouveaux paramètres

Équipe Knowledge, 12 exécutions par branche :

| | W2 | W3 |
|---|---|---|
| `WebFetch` | 86 | 94 |
| … avec `selector` | 49 | 0 |
| … avec `find` | — | 28 |
| … avec `section` | — | 7 |
| … avec `part` / `raw` | — | 0 / 0 |
| `WebSearch` | 42 | 39 |

Sur develop, le leader passait un `selector` à plus d'une récupération sur deux
(sa consigne le demandait) ; sur la branche il cherche un terme (`find`) ou lit
une section. `part` et `raw` n'ont servi à aucune exécution.

## 4. Exécutions écartées

Trois exécutions de sonde sont écartées, des échecs du relais Balanced du banc
(il doit seulement transmettre la question) : une réponse vide (W2
`cv-fetch-open`), le relais qui écrit « web_agent » au lieu de l'appeler (W3
`cv-agent-pg`), et une réponse réduite à « Answer: » (W2 `cv-agent-pg`). Aucune ne passe
par `WebFetch`.

## 5. Incidents et limites

- **Première passe invalide** : `omnis-benches/.env` définit `SERPER_KEY=` vide,
  ce qui écrasait la clé de `../omnis/.env` ; la recherche ne renvoyait rien sur
  les deux serveurs. Il faut sourcer `.env` **puis** `../omnis/.env`.
- `judge_modelcost.py` ne note que le dernier échantillon de chaque fichier
  `V*.jsonl` ; pour noter tous les échantillons, chaque échantillon est mis dans
  son propre fichier (`VW2s1.jsonl`, …).
- Les sous-agents n'enregistrent pas les arguments de leurs appels d'outils dans
  la conversation : l'usage de `section`/`find` n'est mesuré que pour le leader.
- Une réponse de `web_fetcher` (W3) cite « Default: 0 --gpu-memory-utilization… »,
  la fin de l'option précédente collée à la bonne. Non reproduit : docs.vllm.ai
  répondait 429 après le banc. Les réponses de develop à la même question ont une
  note plus basse (4,25 contre 5,17).
- 4 échantillons par question Knowledge, 6 par sonde : un écart d'environ un demi-point
  ne serait pas détectable.

## 6. Reproduction

```bash
set -a; . ./.env; . ../omnis/.env; set +a        # cet ordre : .env vide SERPER_KEY
W=$(mktemp -d)
env -u OMNIS_CONFIG_PATH squad-bench/setup-modelcost.sh $W start W2,W3   # ports 8201 / 8202
python3 squad-bench/bench.py --server http://127.0.0.1:8201 --token bench \
  --tasks squad-bench/tasks-callvolume.json --suite --repeat 6 --deadline 1200 \
  --keep --answer-asks --nonce --out $W/cv-W2.jsonl
# idem 8202 → cv-W3 ; puis mc-netbird, mc-kserve, mc-moe (tasks-modelcost.json) × 4
# un fichier par échantillon, puis :
python3 squad-bench/judge_modelcost.py <dir> --out <dir>/scores.jsonl
squad-bench/setup-modelcost.sh $W stop W2,W3
```
