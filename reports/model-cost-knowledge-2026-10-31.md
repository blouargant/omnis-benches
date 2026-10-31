# Squad Knowledge : coût vs qualité selon les modèles de la LLM Gateway ChapsVision

**Date** : 2026-10-30 → 2026-10-31
**Outils** : `squad-bench/bench.py` (+ `--answer-asks`), `squad-bench/setup-modelcost.sh`,
`squad-bench/judge_modelcost.py`, tâches `squad-bench/tasks-modelcost.json`
**Données brutes** : `model-cost-knowledge-2026-10-31.jsonl` (1 record par run, champ `variant`),
`model-cost-knowledge-2026-10-31-scores.jsonl` (notes des juges)
**omnis** : `/usr/bin/omnis-server` installé + config `/etc/omnis`, un serveur isolé par variante
(`OMNIS_HOME` dédié, `bypassPermissions`)

---

## 1. Verdict

- **Le seul levier qui réduit le coût sans perte de qualité mesurable : `knowledge_leader` sur
  `qwen3.8-27b-scaleway` (V7).** −25 % de coût, −40 % de durée, note moyenne 6,0 contre 5,4 pour la
  référence. À confirmer sur plus d'échantillons avant bascule (§6).
- **DeepSeek v4.1 flash** (le dernier ajouté, 27/10) **n'économise rien** : en `web_agent` il donne
  les meilleures réponses (7,4/10) mais coûte ×2,1 ; en leader il ne sait pas doser la profondeur et
  coûte ×2 à ×5 sans gain de qualité.
- **`web_agent` doit rester sur `Balanced`** : c'est le premier poste de coût (~60 %), et aucun modèle
  avec cache testé (DeepSeek v4.1, Qwen3.8) ne le bat — leur prix d'entrée (0,63 \$/M) est 2,4× celui
  de `Balanced` (0,26 \$/M), et le cache Scaleway ne prend que 38–52 % des tokens.
- **`Hosted` ne peut pas servir de `web_agent`** : saturé par la fan-out (§5.2).
- **`claude-sonnet-5-5` est inutilisable via la gateway en l'état** (§5.1) — à retester après correctif.

## 2. Ce qui coûte (historique de production)

Sur les 162 tours web-UI passés (≈ 75 \$), le squad Knowledge fait ≈ 99 % du coût :

| Agent | Tokens entrée | Coût |
|---|---|---|
| `web_agent` (balanced) | 138 M | 38,3 \$ |
| `knowledge_leader` (premium = Sonnet 4.6) | 17 M | 28,3 \$ |
| `research_critic` (high) | 11 M | 7,2 \$ |

`web_agent` est coûteux par **volume** (son contexte est renvoyé à chaque étape, coût quadratique) ;
le leader l'est par **prix**, mais son cache Anthropic est très efficace (≈ 92 % de lecture cache dans
le banc), si bien qu'il ne pèse que ≈ 0,9 \$ sur une recherche approfondie de 3,5 \$.

## 3. Méthode

**Questions** (réelles, tirées de vos sessions) :
`mc-lmcache` (recherche approfondie LMCache × vLLM × Qwen3.6-27B), `mc-netbird` (NetBird Agent
Network × LiteLLM, ciblée), `mc-arkane` (Arkane Cloud + comparatif tarifs GPU FR), `mc-kserve`
(KServe + vLLM, parallélismes).

**Variantes** (seuls 3 agents changent ; tout le reste = config livrée) :

| | knowledge_leader | web_agent | research_critic |
|---|---|---|---|
| V0 référence | premium (Sonnet 4.6) | balanced (Qwen3.6-35B) | high (Qwen3.5-397B) |
| V1 | claude-sonnet-5-5 | balanced | high |
| V2 | deepseek-v4.1-flash | balanced | high |
| V3 | premium | deepseek-v4.1-flash | high |
| V4 | premium | hosted (max_instances 3) | high |
| V5 | deepseek-v4.1-flash | deepseek-v4.1-flash | deepseek-v4.1-flash |
| V7 | qwen3.8-27b | balanced | high |
| V8 | premium | qwen3.8-27b | high |

`web_fetcher` (normalement sur `Hosted`) a été mis sur `Balanced` dans **toutes** les variantes
(§5.2) ; les coûts « équivalent prod » ci-dessous le recalculent au prix de `Hosted`.

**Qualité** : deux juges de familles différentes (`claude-opus-5-5`, `gpt-5.5`) notent en aveugle
toutes les réponses d'une question ensemble (lettres et ordre aléatoires), sur 0–10 : exactitude,
complétude, sources, utilité + note globale (plafonnée à 5 en cas d'erreur factuelle sérieuse).
Les juges ne vérifient pas sur le web : ils recoupent les réponses entre elles.

## 4. Résultats

### 4.1 Coût (équivalent prod) et qualité

| | Coût 4 questions | Durée | Qualité (moy. 2 juges) | exact. | compl. | sources | utilité |
|---|---|---|---|---|---|---|---|
| **V0 référence** | **5,86 \$** | 41 min | **5,4** | 5,2 | 7,5 | 5,9 | 6,2 |
| **V7 leader Qwen3.8** | **4,39 \$ (−25 %)** | **25 min** | **6,0** | 6,2 | 7,1 | 6,8 | 6,8 |
| V3 web_agent DeepSeek | 12,19 \$ (×2,1) | 71 min | **7,4** | 7,2 | 9,0 | 7,6 | 8,2 |
| V2 leader DeepSeek | 11,63 \$ (×2,0) | 98 min | 6,5 | 6,5 | 8,1 | 7,0 | 7,2 |
| V8 web_agent Qwen3.8 | 10,31 \$ (×1,8) | 49 min | 6,0 | 5,9 | 7,4 | 6,6 | 6,4 |
| V5 tout DeepSeek | 30,92 \$ (×5,3) | 144 min | 6,0 | 5,6 | 9,2 | 6,9 | 7,1 |
| V1 leader Sonnet 5.5 | — | — | non comparable (§5.1) | | | | |
| V4 web_agent Hosted | — | — | arrêté (§5.2) | | | | |

### 4.2 Coût par question (équivalent prod, \$)

| | lmcache | netbird | arkane | kserve |
|---|---|---|---|---|
| V0 | 3,28 | 0,37 | 1,52 | 0,69 |
| V7 | 3,16 | **0,08** | **0,84** | **0,32** |
| V3 | 5,68 | 0,89 | 3,60 | 2,03 |
| V2 | 3,19 | 3,79 | 2,99 | 1,66 |
| V8 | 4,54 | 0,46 | 3,89 | 1,42 |
| V5 | 13,26 | 6,31 | 5,72 | 5,62 |

### 4.3 Qualité par question (note globale, moyenne des 2 juges)

| | lmcache | netbird | arkane | kserve |
|---|---|---|---|---|
| V0 | 5,0 | 7,5 | 4,5 | 4,5 |
| V7 | 7,0 | 4,5 | 5,5 | 7,0 |
| V3 | 7,0 | 7,5 | 8,0 | 7,0 |
| V2 | 7,0 | 6,0 | 7,0 | 6,0 |
| V8 | 4,0 | 6,5 | 7,0 | 6,5 |
| V5 | 7,0 | 6,5 | 6,0 | 4,5 |

## 5. Constats

### 5.1 `claude-sonnet-5-5` : sortie plafonnée à 4096 tokens par la gateway — défaut de config

Sans `max_tokens` dans la requête (omnis n'en envoie pas), la gateway répond
`finish_reason: length` à **4096 tokens**, *thinking* activé et inclus. Mesuré directement (rapport
de 1200 mots demandé) : Sonnet 5.5 → `length` à 4096 ; Premium/Sonnet 4.6 → `stop` à 2350 ;
deepseek-v4.1 → `stop` à 4700–5700. `/model/info` annonce pourtant `max_output_tokens: 64000`
pour les deux Sonnet — l'ID `claude-sonnet-5-5` est vraisemblablement inconnu de la version de
LiteLLM, qui retombe sur son défaut.

Effets dans omnis : réponse finale tronquée au préambule (deux fois sur LMCache : 631 et 719
caractères), briefs de délégation tronqués → `sub-agent "research_critic": missing 'request'`, et
boucle de re-délégation (NetBird : 20 min / 3,40 \$ contre 2 min / 0,37 \$).

**Correctif côté gateway** : `max_tokens: 64000` dans les `litellm_params` de la route
`claude-sonnet-5-5` (idem probablement `claude-haiku-5-5`, `claude-opus-5-5`, `claude-fable-5-1`,
même date d'ajout). Sonnet 5.5 étant 33 % moins cher que Sonnet 4.6 (2,1/10,5 vs 3,15/15,75),
c'est **le candidat leader à retester en priorité** une fois corrigé.

### 5.2 `Hosted` sature sous la fan-out des `web_agent`

V4 (web_agent sur `Hosted`, fan-out 10) + V6 : 12 requêtes longues en parallèle ont rendu `Hosted`
muet (> 45 s pour « Say OK ») pendant **≈ 1 h 35**, bloquant aussi les autres variantes via
`web_fetcher` (sur `Hosted` en prod). Relancé seul avec `max_instances: 3` : un appel `web_agent`
a pris 10 min, puis plus aucun retour pendant 15 min → arrêté. **`Hosted` (Qwen3.6-27B, 2 GPU) ne
peut pas tenir le rôle `web_agent`**, quel que soit son prix. Attention aussi à `web_fetcher` (prod) :
une recherche approfondie avec critic lui envoie 75–300 appels.

### 5.3 Le cache Scaleway fonctionne, mais ne compense pas le prix d'entrée

| web_agent | lecture cache | coût web_agent (lmcache) |
|---|---|---|
| balanced (pas de cache) | 0 % | 2,20 \$ |
| qwen3.8-27b | 38 % | 3,43 \$ |
| deepseek-v4.1 | 49–52 % | 4,04 \$ |

Il faudrait > 73 % de lecture cache pour qu'un modèle à 0,63/0,126 \$/M batte `Balanced` à
0,26 \$/M sur l'entrée seule — et leur sortie est plus chère. Test direct qwen3.8 : 2 hits sur 6
appels à préfixe stable (même intermittence par nœud que DeepSeek, cf. rapport du 2026-09-15).

### 5.4 Un leader moins cher n'est utile que s'il dose la recherche

DeepSeek en leader a transformé la question ciblée NetBird en recherche approfondie :
10 délégations + critic, 11,8 M tokens de web_agent, **13× le coût** de la référence pour une réponse
plus courte. Qwen3.8 a fait l'inverse (1 délégation, 52 s, 0,08 \$), en expliquant pourquoi le
protocole « deep research » ne s'appliquait pas. **La capacité du leader à choisir le bon niveau de
profondeur pèse plus que son prix au token.**

Défauts relevés sur V7 (Qwen3.8 leader) : une erreur factuelle centrale sur NetBird (« les groupes
doivent venir de l'IdP »), et une réponse en français à une question posée en anglais (LMCache).
DeepSeek appelle des outils inexistants (`load_softskills`, `linux-admin`, `liteparse`) puis se
corrige.

### 5.5 La référence n'a pas « acheté » de qualité

V0 (Sonnet 4.6 leader) obtient la note la plus basse : erreurs factuelles relevées par les deux
juges sur Arkane (SLA, SecNumCloud), KServe (confusion runtime HF / serveur vLLM) et LMCache.

## 6. Limites — à lire avant de décider

- **Un échantillon par question et par variante.** Écart moyen entre les deux juges : 1,1 point ;
  deux runs identiques du banc ont déjà différé de 1,85× en coût. L'écart de qualité V7 vs V0
  (6,0 vs 5,4) **n'est pas significatif** ; ce qu'on peut dire : V7 n'est pas visiblement moins bon
  et coûte moins cher.
- Juges sans accès web : l'exactitude est un recoupement, pas une vérification.
- `web_fetcher` sur `Balanced` + 4–5 variantes en parallèle → quelques `429` Scaleway, qui ont pu
  pénaliser un peu toutes les variantes (les agents ont réessayé).
- 4 questions, toutes du squad Knowledge (les autres squads pèsent < 1 % du coût historique).

## 7. Recommandations

1. **Corriger la route `claude-sonnet-5-5`** (et les autres Claude 5.x) sur la gateway (§5.1), puis
   retester V1.
2. **Confirmer V7** : V0 et V7 × 3 répétitions sur ces 4 questions (≈ 30 \$). Si V7 tient, basculer
   `knowledge_leader` sur `qwen3.8-27b-scaleway` (entrée catalogue dans `models.json`,
   `context_length` ≤ 229376) — et corriger la consigne de langue de réponse.
   *État au 2026-10-31 : confirmation non faite.* Deux tentatives ont échoué : la première à cause
   d'une fuite des questions `ask_user` entre sessions (corrigée dans `bench.py` et dans omnis),
   la seconde parce que le budget d'équipe de la gateway (250 \$) a été atteint au bout de
   ≈ 10 min (429 « Budget has been exceeded »). À relancer une fois le budget relevé.
3. **Garder `web_agent` sur `Balanced`.** Le levier restant est structurel, pas le modèle : moins de
   tokens par session web_agent (cf. protocole `variants.json` V1/V3 : `max_instances`, délégation
   du fetch à `web_fetcher`).
4. **Ne pas utiliser DeepSeek v4.1 en leader.** En `web_agent`, seulement si la qualité prime sur le
   coût (meilleure note, ×2,1).
5. **Prévenir l'exploitant de `Hosted`** : saturation de ≈ 1 h 35 sous 12 requêtes longues
   parallèles ; `web_fetcher` en prod l'expose au même risque lors des recherches approfondies.

## 8. Reproduction

```bash
set -a; . ../omnis/.env; set +a
W=$(mktemp -d)
env -u OMNIS_CONFIG_PATH squad-bench/setup-modelcost.sh $W start V0,V7      # ports 8190 / 8197
python3 squad-bench/bench.py --server http://127.0.0.1:8190 --token bench \
  --tasks squad-bench/tasks-modelcost.json --suite --deadline 3600 --keep --answer-asks --out $W/V0.jsonl
# … idem V7 sur 8197, puis :
python3 squad-bench/judge_modelcost.py $W --out $W/scores.jsonl
squad-bench/setup-modelcost.sh $W stop
```
