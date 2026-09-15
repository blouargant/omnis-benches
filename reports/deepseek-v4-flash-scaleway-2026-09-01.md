# `deepseek-v4-flash-0731` (Scaleway) face aux tiers omnis de la LLM Gateway

**Date** : 2026-09-01
**Question** : comment `deepseek-v4-flash-0731` se compare-t-il aux modèles déjà
configurés dans omnis, sur les résultats et sur le prix ?
**Données brutes** : [`deepseek-v4-flash-scaleway-2026-09-01.jsonl`](deepseek-v4-flash-scaleway-2026-09-01.jsonl)
(42 enregistrements, champs `variant` / `scaleway_model` / `suite` /
`search_degraded` ajoutés).

## Verdict

Sur la suite **code**, à correction strictement identique (**8/8 PASS** pour les
trois modèles), deepseek-v4-flash coûte **0,65× `balanced`** et **0,22× `high`**.
C'est le meilleur rapport résultat/prix des trois sur ce périmètre.

Trois réserves, détaillées plus bas : il **n'est pas exposé par la gateway** (donc
inutilisable par omnis en l'état), son **streaming est 3–4× plus grossier**, et la
suite **deep research n'a pas tranché** (backend de recherche dégradé côté
baselines).

## 1. Disponibilité — le point bloquant

La gateway expose 68 modèles ; **aucun deepseek**. Les modèles Scaleway y
apparaissent sous `*-scaleway` (`qwen3.6-35b-a3b-scaleway`, `glm-5.2-scaleway`, …).
`deepseek-v4-flash-0731` n'est joignable qu'en **direct chez Scaleway**
(`SCALEWAY_API_BASE_URL`, déjà dans le `.env` du repo).

Conséquence : l'adopter demande soit d'ajouter la route côté gateway, soit de
déclarer un second provider dans `models.json` pointant en direct sur Scaleway —
ce que fait le harnais de ce bench.

## 2. Ce à quoi il se compare (alias gateway résolus via `/model/info`)

| tier omnis | modèle réel | in $/M | out $/M | cache-in $/M |
|---|---|---|---|---|
| `hosted` | `hosted_vllm/Qwen/Qwen3.6-27B` (auto-hébergé) | 0,04 | 0,27 | — |
| `simple` | `scaleway/gemma-4-26b-a4b-it` | 0,2625 | 0,525 | — |
| `balanced` | `scaleway/qwen3.6-35b-a3b` | 0,26 | 1,58 | — |
| **candidat** | **`scaleway/deepseek-v4-flash-0731`** | **0,42** | **0,84** | **0,084** |
| `high` | `scaleway/qwen3.5-397b-a17b` | 0,63 | 3,78 | — |
| `premium` | `claude-sonnet-4-6` | 3,15 | 15,75 | 0,30 |

La gateway applique une conversion EUR→USD **×1,05 sans marge** sur les modèles
Scaleway (vérifié barreau par barreau contre la grille publique Scaleway : €0,25 /
€1,50 pour qwen3.6-35b-a3b → $0,2625 / $1,575 ≈ les 0,26 / 1,58 configurés). Le
prix retenu pour deepseek suit la même convention (€0,40 / €0,80 / €0,08 → $0,42 /
$0,84 / $0,084), donc les chiffres ci-dessous **sont** l'économie gateway.

**Le profil de prix est atypique et c'est tout l'enjeu** : output 1,9× moins cher
que `balanced`, mais input 1,6× plus cher. Ce qui renverse l'équation, c'est que
deepseek est le **seul de la famille Scaleway à avoir un prix de cache**.

## 3. Protocole

- **Rail unique : Scaleway direct** pour les trois modèles. Motif : deepseek n'est
  pas sur la gateway, et `balanced`/`high` sont eux-mêmes des routes `scaleway/*` —
  les mesurer en direct donne le même chemin réseau et **échappe au cache de
  réponses de la gateway** qui invalide `--repeat` (cf.
  [squad-bench-balanced-2026-08-13.md](squad-bench-balanced-2026-08-13.md)). Les
  répétitions sont donc ici de vrais échantillons.
- **Serveur omnis dédié** sur `127.0.0.1:8095`, lancé en **foreground** (le fichier
  PID n'est écrit qu'en mode daemon → aucun conflit avec les instances dev de
  l'utilisateur sur :8080/:8081), `HOME` inchangé pour que la même
  `~/.omnis/registry/agents` (coder, code_scout, code_docs) soit sous test.
- **Override de modèle par la couche `.agents/` du CWD du serveur** — la plus
  prioritaire de la chaîne (`.agents` → `$OMNIS_HOME` → `/etc/omnis`), et
  `loadModelsConfig` **deep-merge toutes les couches**. `~/.omnis/models.json`
  n'a donc **jamais été modifié**.
- **Contrôle de prix obligatoire sur les 42 runs** : `82/82` enregistrements
  d'agents au prix du tier attendu. Aucun swap no-op.
- Suites : `tasks.json` (4 tâches, squad `coding`, sandbox git-isolé) et
  `tasks-web.json` (3 tâches, squad `knowledge`), `--repeat 2`, `--deadline 600`.
- Les enregistrements **`search_degraded`** ont été identifiés avec le détecteur
  du repo (`campaign.mark_search_degraded`) et **exclus de tous les chiffres**.

## 4. Gate de capacité — `model-probe`

`python3 model-probe/probe.py -u https://api.scaleway.ai/v1 -m deepseek-v4-flash-0731`
→ **9 pass / 0 fail**, tous les checks critiques OK, dont les quatre qui comptent
pour une squad :

- tool calling **non-streaming** et **streaming** (3/3),
- **tool parameterless over streaming** (3/3) — exactement là où GLM-5.2/Scaleway
  avait échoué,
- tool result round-trip.

Signaux annexes : caching **actif** (2304 tokens cachés sur la requête répétée),
parallel tool calls supportés, `tool_choice=required` honoré, usage en streaming
présent, **pas de `reasoning_content`** (non-thinking, ou masqué).

## 5. Résultats — suite `coding` (le comparatif concluant)

Correction : **8/8 PASS pour les trois modèles**. L'écart est donc purement
économique. Coût USD, médiane [min–max] sur 2 répétitions :

| tâche | deepseek-v4-flash | balanced (qwen3.6-35b) | high (qwen3.5-397b) |
|---|---|---|---|
| `search-single` | **$0,0116** [0,0109–0,0122] | $0,0163 [0,0160–0,0167] | $0,0433 [0,0337–0,0528] |
| `search-multi` | **$0,0087** [0,0077–0,0098] | $0,0210 [0,0200–0,0220] | $0,0555 [0,0517–0,0594] |
| `symbol-fields` | **$0,0050** [0,0050–0,0050] | $0,0134 [0,0129–0,0138] | $0,0345 [0,0330–0,0360] |
| `docs-lookup` | $0,0340 [0,0237–0,0442] | $0,0402 [0,0314–0,0490] | $0,1416 [0,1310–0,1522] |
| **panier** | **$0,0593 — 0,65×** | $0,0909 — 1,00× | $0,2749 — 3,02× |

**Lecture des plages** : contre `high`, les plages ne se recouvrent sur **aucune**
tâche — même résultat pour **4,6× moins cher**, c'est solide. Contre `balanced`,
elles ne se recouvrent pas sur `search-single`, `search-multi` et `symbol-fields`
(jusqu'à 2,7× d'écart) ; sur `docs-lookup` elles se recouvrent, donc **on ne peut
rien conclure de cette tâche-là**.

Vitesse (médiane) : comparable. deepseek est un peu plus lent que `balanced` sur
les petites tâches (11 s vs 5 s sur `symbol-fields`) et nettement plus rapide que
`high` sur `docs-lookup` (47 s vs 92 s).

## 6. Ce qui explique le prix : le cache

Sur l'ensemble des enregistrements propres de la campagne :

| modèle | prompt tokens | cache-read | taux | output |
|---|---|---|---|---|
| deepseek-v4-flash | 18 309 644 | 13 079 040 | **71,4 %** | 111 058 |
| qwen3.6-35b-a3b | 883 810 | 0 | **0 %** | 15 770 |
| qwen3.5-397b-a17b | 2 726 300 | 0 | **0 %** | 19 049 |

Les deux qwen ne renvoient **aucun** token caché — Scaleway ne les cache pas, ce que
confirme sa grille (prix de cache listé pour deepseek seul). Sur une charge d'agent,
massivement input-lourde et répétitive, c'est **le** facteur décisif : la portion
cachée de deepseek est facturée 0,084 $/M contre 0,26 $/M d'input non caché chez
`balanced`, soit 3,1× moins cher sur les ~71 % du prompt qui touchent le cache.

Le calcul est bien cache-aware côté squad-bench (correctif `note_model`) : vérifié
à la main sur un enregistrement — 33244 prompt / 16128 cache-read / 367 out donne
$0,008852, ce que le bench reporte exactement.

## 7. Suite `knowledge` — non concluante, et pourquoi

| tâche | deepseek-v4-flash | balanced | high |
|---|---|---|---|
| `web-lookup` | $0,0320 [0,0303–0,0337] / 24 s | $0,0076 [0,0055–0,0098] / 5 s | $0,4612 [0,1783–0,7442] / 352 s, 1 annulé |
| `web-canary` | **$0,0272** [0,0194–0,0349] / 23 s | $0,0299 [0,0298–0,0300] / 54 s | $0,0472 [0,0455–0,0490] / 48 s |
| `web-deep-ds7` | $0,918 (3 obs) et $2,234 (2 obs, annulé) | **2 runs dégradés → exclus** | $0,223 (0 obs, annulé) |

Trois choses à ne pas surinterpréter :

- **`web-lookup` : `balanced` est le moins cher parce qu'il ne fait pas le
  travail.** Ses deux runs font **0 fetch** et répondent depuis la mémoire
  paramétrique (1–2 appels leader, aucune délégation). deepseek délègue et fetche
  réellement. Les deux passent le `quality_gate` (le fait requis est trouvé), donc
  la comparaison de prix sur cette tâche compare deux comportements différents,
  pas deux efficacités.
- **`web-deep-ds7` n'a pas de baseline.** Les deux runs de `balanced` portent les
  marqueurs de dégradation du détecteur (`deadline exceeded`, `timeout`) et un run
  de `high` aussi → exclus. Il ne reste qu'un run `high` propre, annulé à 600 s
  avec **0 observation** et 35 `token_events` : il n'a rien produit. deepseek est
  le seul à avoir sorti des observations (3 et 2), mais à $0,92 et $2,23 avec une
  annulation.
- **L'emballement sur cette tâche n'est pas propre à deepseek** — contrairement à
  ce que le premier run laissait croire. `balanced` fait pire (166 fetches, 140
  appels, $1,25, 1063 s). Les deux modèles échouent à converger sur du deep
  research ; la tâche a une variance énorme et n=2 ne la départage pas.

## 8. Régression à connaître : granularité du streaming

`token_events` médian (les trois modèles, mêmes tâches) :

| tâche | deepseek | balanced | high |
|---|---|---|---|
| `search-single` | 53,5 | 227 | 141 |
| `search-multi` | 74,5 | 301,5 | 176,5 |
| `symbol-fields` | 37,5 | 134,5 | 92 |
| `docs-lookup` | 91 | 477 | 329 |

deepseek émet **3 à 5× moins d'événements** que `balanced` pour un travail
équivalent. Ce n'est pas une question de coût mais d'UI : la réponse arrive par
gros blocs au lieu de couler token par token. C'est le défaut déjà relevé sur
`premium` dans le README de squad-bench.

## 9. Défaut de configuration découvert (dépasse deepseek)

Le run annulé de deepseek sur `web-deep-ds7` finit sur :

```
400: This model's maximum context length is 262144 tokens.
However, you requested 32768 output tokens and you[r messages...]
```

Vérifié en direct sur l'endpoint Scaleway (erreur de validation, non facturée) :

| modèle Scaleway | contexte réel | plafond `max_completion_tokens` |
|---|---|---|
| `deepseek-v4-flash-0731` | 262144 | 32768 |
| `qwen3.6-35b-a3b` (= `balanced`) | 262144 | 32768 |
| `gemma-4-26b-a4b-it` (= `simple`) | — | 32768 |
| `qwen3.5-397b-a17b` (= `high`) | — | 16384 |

La réservation de sortie s'ajoute **au-dessus** du budget de contexte. Avec
`context_length: 256000` il ne reste que **6144 tokens de marge** pour une sortie
de 32768 : le plafond est faux par construction. Le bon réglage est
**`context_length: 229376`** (262144 − 32768).

**`/etc/omnis/models.json` déclare `balanced.context_length: 256000` — le même
piège y est donc latent en production**, invisible tant qu'aucun agent ne remplit
sa fenêtre. Il ne s'est pas déclenché ici parce que les runs de `balanced` sur la
tâche profonde étaient privés de recherche.

## 10. La recherche web était désactivée — `OMNIS_CONFIG_PATH`

**Corrigé le 2026-09-01 après coup.** Les runs `web-deep-ds7` de `balanced` ont
échoué sur des timeouts en se repliant sur DuckDuckGo. La cause n'est pas une
dégradation passagère du backend payant : **le serveur de bench n'a jamais eu de
backend payant.**

`OMNIS_CONFIG_PATH=/etc/omnis/agents.json` est exporté dans l'environnement du
shell (profil utilisateur — le serveur dev sur :8081 le porte aussi). C'est le
**bypass explicite** d'omnis : `loadRuntimeConfig` lit ce seul fichier *verbatim*
et court-circuite toute la chaîne de fusion pour `agents.json`. Or
`/etc/omnis/agents.json` **ne déclare pas `serper_key`** — seul
`~/.omnis/agents.json` le fait, et cette couche n'était pas fusionnée. La variable
`SERPER_KEY` était pourtant bien présente dans l'environnement du serveur : elle
n'a simplement jamais été lue.

Deux conséquences :

- **La suite `knowledge` de cette campagne a tourné sans Serper, pour les trois
  modèles.** C'est homogène, donc la comparaison reste interne, mais elle n'est
  **pas représentative de la production**. Les runs deepseek non signalés
  `search_degraded` étaient eux aussi sur DuckDuckGo — ce qui renforce la
  conclusion « non concluante » du §7 plutôt que de l'affaiblir.
- La suite `coding` n'est pas touchée : `docs-lookup` utilise WebSearch/WebFetch
  mais a réussi ses 2/2 sur les trois modèles, et aucun de ces runs ne porte de
  marqueur de dégradation.

**Le correctif** pour tout bench web futur : exporter
`OMNIS_CONFIG_PATH=<agents.json du bench>` pointant sur une config qui déclare
`serper_key`, ou désexporter la variable pour laisser la fusion opérer. Ajouter
`SERPER_KEY` au `.env` racine reste nécessaire (le CLAUDE.md l'impose) mais
**n'aurait pas suffi seul** — c'était mon diagnostic initial, et il était faux.

## Recommandation

1. **Sur du code, deepseek-v4-flash mérite d'être adopté** : résultat identique à
   `balanced`, 35 % moins cher, et 4,6× moins cher que `high`. L'avantage est
   structurel (le prix de cache), pas conjoncturel.
2. **Prérequis : l'exposer sur la gateway** (route `deepseek-v4-flash-0731-scaleway`,
   convention `*-scaleway` déjà en place). Attention au piège de l'alias LiteLLM
   documenté dans
   [gateway-balanced-tool-calling-2026-08-13.md](gateway-balanced-tool-calling-2026-08-13.md) :
   la cost-map doit porter la clé vendor-préfixée, sinon `tools` est silencieusement
   retiré. Repasser `model-probe` sur l'alias une fois la route créée.
3. **Régler `context_length: 229376`**, et corriger `balanced` dans
   `/etc/omnis/models.json` par la même occasion.
4. **Ne pas le mettre sur la squad `knowledge` sur cette base** : le deep research
   n'a pas été départagé, et la granularité de streaming se voit dans l'UI.
5. Pour refaire la mesure du deep research, il faut d'abord un backend de recherche
   sain (`SERPER_KEY` dans le `.env`) et `--repeat` ≥ 3 sur `web-deep-ds7`.
