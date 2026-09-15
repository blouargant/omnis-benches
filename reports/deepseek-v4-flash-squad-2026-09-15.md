# DeepSeek v4 Flash en squad omnis (Coding) — premier passage au banc

**Date** : 2026-09-15
**Rail** : LLM Gateway ChapsVision → `deepseek-v4-flash-scaleway`
  (route `openai/deepseek-v4-flash-0731`, réparée le jour même — cf.
  `gateway-deepseek-tool-calling-2026-09-15.md`)
**Outil** : `squad-bench/bench.py --suite` (4 tâches, squad `Coding`)
**Données** : `deepseek-v4-flash-squad-2026-09-15.jsonl` (bras DeepSeek),
  `baseline-default-squad-2026-09-15.jsonl` (bras référence)

---

## 1. Verdict

**DeepSeek pilote le squad Coding correctement.** 4/4 tâches réussies, structure de
délégation **identique** à la config par défaut, 0 `ask_user`, 0 `subagent_errors`,
0 `forbidden_hits`. Le tool-calling réparé côté gateway tient sur un vrai parcours
d'agent, pas seulement sur une sonde de capacité.

**En revanche l'écart de coût observé n'est PAS établi** — voir §4. Un seul échantillon
par bras ne permet pas de conclure.

## 2. Méthode

Serveur omnis **dédié**, lancé en avant-plan sur `127.0.0.1:8099` depuis un CWD
temporaire contenant uniquement `.agents/models.json` (chaîne de config observée dans
le log : `[.agents /home/bertrand/.omnis /etc/omnis]`). `HOME` inchangé, donc les
agents benchés sont bien ceux de `~/.omnis/registry/agents`. Le serveur de dev de
l'utilisateur (:8080) n'a pas été touché.

| Bras | Modèles |
|---|---|
| **DeepSeek** | override single-model : **tous** les agents sur `deepseek` — 0.42 / 0.84 \$/M |
| **Référence** | défauts omnis : `coder` = **premium** 3.15 / 15.75, `code_scout` = **simple** 0.2625 / 0.525, `code_docs` = **balanced** 0.26 / 1.58 |

**L'override a été vérifié, pas supposé** (discipline CLAUDE.md). Le bloc `models` de
chaque enregistrement porte `in_per_m: 0.42 / out_per_m: 0.84` sur **les deux** agents,
et le coût se recalcule exactement : `coder` 33444 × 0.42/M + 712 × 0.84/M =
**0.014645 \$** = valeur enregistrée.

⚠️ **Un no-op a effectivement été attrapé en route** : basculer
`override_model_enabled` à `false` dans `.agents/models.json` **n'a pas été repris à
chaud** — la tâche suivante affichait encore 0.42/0.84. Il a fallu redémarrer le
serveur. Sans le contrôle de prix, le bras « référence » aurait mesuré DeepSeek en
croyant mesurer les défauts, et les deux bras auraient paru identiques.

`SERPER_KEY` est absent du `.env` du repo et du shell ; il a été repris de
l'environnement du serveur de dev pour que `docs-lookup` utilise le backend payant
(sinon repli DuckDuckGo → dégradation). **À ajouter au `.env` racine** comme le
prescrit CLAUDE.md.

## 3. Résultats

| Tâche | DeepSeek | Référence | coût DS | coût réf | ratio | wall DS | wall réf |
|---|---|---|---|---|---|---|---|
| `search-single` * | PASS | PASS | 0.022116 | 0.057098 | 2.58x | 26808 ms | 68078 ms |
| `search-multi` | PASS | PASS | 0.025236 | 0.037533 | 1.49x | 37042 ms | 34080 ms |
| `symbol-fields` | PASS | PASS | 0.018168 | 0.042886 | 2.36x | 32929 ms | 12140 ms |
| `docs-lookup` | PASS | PASS | 0.058244 | 0.052168 | **0.90x** | 48981 ms | 36536 ms |
| **TOTAL** | **4/4** | **4/4** | **0.123764** | **0.189685** | 1.53x | | |

\* `search-single` côté DeepSeek : l'enregistrement de la suite (4265 ms / \$0.0124) est
un **rejeu de cache gateway** — la même tâche avait tourné à froid quelques minutes plus
tôt lors de la vérification d'override (26808 ms / \$0.0221). C'est la signature décrite
dans CLAUDE.md (~5× plus rapide, ~40% moins cher). **La mesure à froid est celle
retenue ci-dessus** ; le JSONL conserve l'enregistrement caché tel quel.

Comportement identique sur les deux bras : mêmes délégations
(`code_scout`×1 / ×2 / ×1, `code_docs`×1), même unique redispatch sur `search-multi`,
`ask_user=0` et `subagent_errors=[]` partout. `docs-lookup` a bien fait ses recherches
web (4 fetches DS / 3 réf) — Serper fonctionnait.

## 4. Ce que ces chiffres ne prouvent PAS

CLAUDE.md fixe le seuil de résolution : **deux runs de configuration identique ont été
mesurés à 1.85x d'écart en coût**. Donc, à n=1 par bras :

- le total **1.53x ne franchit pas ce seuil** → **aucune conclusion de coût** ;
- `search-single` (2.58x) et `symbol-fields` (2.36x) le franchissent, mais sur un
  échantillon unique chacun ;
- `search-multi` (1.49x) et `docs-lookup` (0.90x) sont pleinement dans le bruit.

**La variance a été observée directement pendant ce run**, ce qui n'est pas une
citation mais une mesure : le bras référence a exécuté `symbol-fields` **deux fois à
configuration strictement identique** — une fois à froid (\$0.072939, **correct=False**)
et une fois dans la suite (\$0.042886, **PASS**). Soit **1.70x d'écart de coût et un
verdict qui bascule**, sans qu'une seule variable ait changé. Un rapport écrit sur le
premier échantillon aurait annoncé « DeepSeek bat premium en qualité » — ce qui est
faux.

Les durées sont encore moins exploitables : `symbol-fields` va de 12 s (réf) à 33 s
(DS), `search-single` de 27 s à 68 s, et le cache gateway contamine toute répétition.

## 5. Conclusion et suite

✅ **Acquis, solide** : DeepSeek est fonctionnellement apte comme tier agent — il
délègue, appelle ses outils, respecte les consignes read-only et produit des réponses
correctes sur les 4 tâches, au même niveau structurel que la config premium.

❓ **Non acquis** : tout énoncé de type « DeepSeek est N× moins cher ». Pour le trancher
il faut `campaign.py` (campagnes entrelacées, témoin de dérive V0, médianes **avec leur
dispersion**), pas `bench.py --suite` à un échantillon. Noter que `--repeat` **ne
suffira pas** sur ce rail : le cache gateway rejoue les prompts fixes. Il faut soit
varier les prompts par nonce, soit passer par le rail Scaleway direct qui échappe au
cache.

Réserve additionnelle sur la comparaison de coût : le tier `premium` du bras référence
**cache massivement** (18032 tokens de cache-read sur 36422 de prompt au run à froid,
~50%), là où DeepSeek n'a caché que par intermittence (0 / 6656 / 3328 / 0). Les deux
bras ne sont donc pas sur le même régime de cache, ce qui déplace le ratio dans un sens
difficile à prédire sans répétitions.
