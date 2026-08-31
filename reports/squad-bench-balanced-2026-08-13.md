# squad-bench sur `balanced` — validation comportementale après le correctif gateway

**Date** : 2026-08-13
**Contexte** : suite au correctif des alias LiteLLM
([gateway-balanced-tool-calling-2026-08-13.md](gateway-balanced-tool-calling-2026-08-13.md)),
`model-probe` déclarait `Balanced` bon sur les 4 checks critiques d'outils. Ce run
vérifie l'étage au-dessus : **comment la squad s'en sert réellement**.
**Verdict** : ✅ **9 / 9 runs PASS**, 0 `ask_user`, 0 `subagent_errors`.

## Protocole

- Serveur omnis dev sur `http://127.0.0.1:8080`, squad `coding`, `squad-bench/tasks.json`
  (4 tâches, toutes en `cwd: sandbox` → copie temporaire git-isolée).
- Tier forcé via l'override hot-reloadable de `~/.omnis/models.json`
  (`override_model_ref: "balanced"`, `override_model_enabled: true`) puis
  `POST /api/config/reload` — la voie documentée, `OMNIS_CONFIG_DIRS` ne redirigeant
  pas le registre d'agents.
- **Prix vérifié sur les 9 enregistrements** : `in_per_m: 0.26`, `out_per_m: 1.58` pour
  `coder`, `code_scout` et `code_docs` — c'est bien le tier `balanced`, pas un swap
  no-op (le contrôle obligatoire du CLAUDE.md).
- `~/.omnis/models.json` **restauré** à son état d'origine (`override_model_ref:
  "hosted"`, `override_model_enabled: false`) + reload en fin de run.

## Résultats — premiers passages (mesures à froid, les seules exploitables)

| Tâche | statut | `correct` | wall | ttfb | `token_events` | coût | redispatch | `ask_user` | outils du sous-agent |
|---|---|---|---|---|---|---|---|---|---|
| `search-single` | done | **PASS** | 15,6 s | 1756 ms | 165 | $0.0208 | 0 | 0 | `code_scout`: Grep×7, Read×1 |
| `search-multi` | done | **PASS** | 13,0 s | 1555 ms | 250 | $0.0183 | 1 | 0 | `code_scout`: Grep×5, Read×2 |
| `symbol-fields` | done | **PASS** | 8,6 s | 1379 ms | 158 | $0.0139 | 0 | 0 | `code_scout`: Grep×2, Read×1 |
| `docs-lookup` | done | **PASS** | 123 s | 1277 ms | 704 | $0.0550 | 0 | 0 | `code_docs`: WebSearch×2, WebFetch×3 |

**Coût de la suite à froid : $0.1080** pour 4 tâches.

Ce qu'il faut lire dans la colonne « outils » : les sous-agents ont réellement
**exécuté** des Grep, Read, WebSearch et WebFetch. C'est la confirmation
bout-en-bout que les `tool_calls` natifs circulent à travers omnis — avant le
correctif, le modèle n'aurait rendu que de la prose.

Autres signaux sains :

- `token_events` de 84 à 704 → streaming **token par token**, pas de réponse en
  2-3 gros blocs (le défaut relevé sur `premium` dans le README).
- `ttfb` 1,2-1,8 s à froid, cohérent sur les 4 tâches.
- `delegations` conformes au design : `code_scout` pour la recherche, `code_docs`
  pour la doc. Aucun sous-agent appelé hors de son rôle.
- `redispatches=1` sur `search-multi` : le leader appelle `code_scout` deux fois pour
  une question en deux volets (retry-with-backoff **et** cache LRU). C'est du
  découpage légitime, pas du flailing — les deux runs le font à l'identique et
  répondent juste.

## Réserve méthodologique : le cache du gateway invalide `--repeat`

Le cache de réponses du gateway (relevé au §5 du rapport gateway) rend les
répétitions **non indépendantes** — le prompt d'une tâche étant fixe, la 2ᵉ exécution
tape la même clé de cache :

| Tâche | 1er (à froid) | répétition 1 | répétition 2 |
|---|---|---|---|
| `search-single` | 15637 ms / 165 ev / $0.0208 | 2644 ms / 101 ev / $0.0123 | 2682 ms / 101 ev / $0.0123 |
| `search-multi` | 12965 ms / 250 ev / $0.0183 | 1881 ms / 144 ev / $0.0107 | — |
| `symbol-fields` | 8575 ms / 158 ev / $0.0139 | 1688 ms / 84 ev / $0.0077 | — |
| `docs-lookup` | 122937 ms / 704 ev / $0.0550 | 46230 ms / 539 ev / $0.0610 | — |

Les répétitions sont ~5× plus rapides et ~40 % moins chères, et les deux répétitions
de `search-single` sont **rigoureusement identiques** (101 `token_events`, $0.0123,
mêmes outils) — signature d'un replay de cache, pas d'un échantillon.
`docs-lookup` est la seule à y échapper : ses WebSearch/WebFetch injectent du contenu
externe variable, donc les prompts en aval diffèrent et manquent le cache.

**Conséquence pratique : sur ce gateway, `--repeat N` ne mesure pas la variance du
modèle.** Seul le premier passage est une mesure. Pour échantillonner réellement, il
faut faire varier le prompt (nonce par run) ou désactiver le cache côté gateway.

## Observation à surveiller

Chaque réponse s'ouvre par un écho de la consigne — « *Understood: you want me
to…* », « *Understood: You want me to find (1)…* ». Sans effet sur `correct`, mais
c'est du token de sortie payé pour rien et une cible naturelle d'ajustement
d'`instruction.md` si on veut resserrer.

Sur le run à froid de `docs-lookup`, la réponse mentionne « *The first call timed out.
Let me retry* » alors que `subagent_errors` vaut 0 : soit le leader narre un incident
que le flux SSE n'a pas matérialisé en frame d'erreur, soit le compteur ne capte pas
ce cas. À creuser si les 123 s se reproduisent — c'est la seule tâche lente de la
suite.

## Conclusion

`balanced` fait tourner la squad `coding` correctement sur les 4 tâches, avec de
vrais appels d'outils, du streaming fin, aucune demande de permission et aucune
erreur de sous-agent. Combiné au `model-probe` (9 pass / 0 fail / 0 warn), le tier
est bon pour omnis à **$0.26 / $1.58 par M**, contre $3.15 / $15.75 pour `premium`.

Reste l'arbitrage du §8 du rapport gateway : le thinking forcé consomme le budget
`max_tokens` (sous ~300 tokens, la réponse est entièrement absorbée par le
raisonnement), donc ne pas plafonner `max_tokens` sur ce tier.

## Rejouer

```bash
# override du tier dans le models.json du serveur, puis :
curl -s -X POST http://127.0.0.1:8080/api/config/reload
python3 squad-bench/bench.py --suite --deadline 420 --out balanced.jsonl
# et vérifier que chaque record porte bien in_per_m=0.26 / out_per_m=1.58
```
