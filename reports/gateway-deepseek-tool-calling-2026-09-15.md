# DeepSeek v4 Flash sur la LLM Gateway : tool-calling cassé — le correctif d'août a vieilli

**Date** : 2026-09-15
**Gateway** : `https://llm-gateway.ai.chapsvision.com/llm-gateway` (LiteLLM)
**Modèle** : `deepseek-v4-flash-scaleway` → `scaleway/deepseek-v4-flash-0731`
  (déployé le **2026-09-14 15:55 UTC**, `created_by: 1011`)
**Outil** : `model-probe/probe.py`
**Statut** : ✅ **corrigé le 2026-09-15** — la route est passée au patron `openai/` (§4, option structurelle). Vérification après correctif en **§8** : **9 pass / 0 fail / 0 warn**, aucune régression sur les routes `scaleway/` voisines.
**Statut initial** : 🔴 bloquant pour le mode agent — le modèle est sain, la gateway était en cause.

---

## 1. Verdict

| Rail | Chat | Tool-calling | Détail |
|---|---|---|---|
| **Gateway** `deepseek-v4-flash-scaleway` | ✅ | 🔴 **0 / 4 critiques** | `5 pass / 4 fail / 1 warn` — exit 1 |
| **Scaleway direct** `deepseek-v4-flash-0731` | ✅ | ✅ **7 / 7** | streaming, non-streaming, sans-paramètre, round-trip, parallèle, `tool_choice=required` |

Le modèle **sait parfaitement appeler des outils**. Il ne les reçoit jamais à travers la
gateway. C'est la **même classe de bug que le 2026-08-13**, mais **pas la même cause** —
voir §3, c'est le point important.

Détail des 4 échecs critiques côté gateway :

```
FAIL * Tool calling (non-streaming)      no tool call (finish_reason=stop)
FAIL * Tool calling (streaming)          NO tool call over streaming (0/3)
FAIL * Parameterless tool over streaming parameterless tool not called (0/3)
FAIL * Tool result round-trip            model did not call the tool (finish_reason=stop)
WARN   tool_choice=required              accepté mais aucun appel émis
```

Le modèle le dit lui-même : *« no tool definitions (such as `get_weather`) have actual… »*.

## 2. Preuve que `tools` n'atteint pas le modèle

Outil au nom indevinable (`xq7_frobnicate_wumpus`), puis « liste les outils dont tu disposes » :

| Appel | Réponse |
|---|---|
| scaleway **direct**, avec `tools` | `xq7_frobnicate_wumpus` → **voit l'outil** |
| gateway **`Balanced`**, avec `tools` (témoin OK) | `xq7_frobnicate_wumpus` → **voit l'outil** |
| gateway **deepseek**, avec `tools` | `NONE` → **aveugle** |
| gateway **deepseek**, **sans** `tools` | `NONE` → *strictement identique* |

Envoyer `tools` ou ne pas l'envoyer produit la même réponse : le paramètre est
**supprimé avant l'appel upstream**. `tool_choice=required` est accepté sans effet,
donc il est strippé lui aussi — cohérent avec les 5 params d'outils jetés en bloc
(mécanisme LiteLLM détaillé en §2 du rapport du 2026-08-13).

## 3. Cause racine : la carte de prix figée en août ne connaît pas DeepSeek

Rappel du mécanisme (inchangé) : pour un « provider JSON » comme `scaleway`,
`dynamic_config.get_supported_openai_params` appelle `supports_function_calling()`,
qui fait un **lookup littéral** dans la cost-map sur la clé `scaleway/<model>`.
Absence → `False` → les 5 params d'outils sont retirés **sans le moindre avertissement**.

Ce qui est nouveau, c'est **pourquoi** la clé manque. Deux observations qui, ensemble,
ne laissent qu'une explication :

| Observation | Mesure |
|---|---|
| **A.** Les routes qui **marchent** déclarent des IDs **courts** — `scaleway/qwen3.6-35b-a3b`, `scaleway/qwen3.5-397b-a17b`, `scaleway/mistral-medium-3.5-128b`… (vérifié via `/model/info`) | ces clés **n'existent pas** dans la cost-map amont actuelle : ni en clé de premier niveau, ni en `aliases` (vérifié sur les 3958 entrées, 19 clés `scaleway/`) |
| **B.** La route qui **échoue** déclare `scaleway/deepseek-v4-flash-0731` | cette clé **existe** en amont, avec `supports_function_calling: true`, `max_output_tokens: 32768` |

Si la gateway lisait la carte **amont**, on observerait l'inverse exact : DeepSeek
fonctionnerait et les 6 autres seraient cassés. Donc :

> **La gateway sert la carte figée patchée le 2026-08-13** (via
> `LITELLM_MODEL_COST_MAP_URL` ou `LITELLM_LOCAL_MODEL_COST_MAP=True`, cf. §3.1 du
> rapport d'août). Cette carte contient bien les 6 alias qui réparent les routes
> historiques — mais elle est **antérieure** à l'ajout amont de
> `scaleway/deepseek-v4-flash-0731`, donc DeepSeek y est absent.

**Le correctif d'août est un correctif qui vieillit.** En figeant la carte, il a gelé
le périmètre des modèles Scaleway capables d'appeler des outils. **Tout modèle
Scaleway ajouté après le 2026-08-13 hérite du bug par construction** — DeepSeek est le
premier, il ne sera pas le dernier. Le rapport d'août prévoyait la discipline de
régénération « à chaque montée de version de litellm » ; il faut l'élargir à
**« à chaque ajout de modèle Scaleway »**.

## 4. Correctif

**Immédiat (une entrée)** — ajouter à la carte servie :

```json
"scaleway/deepseek-v4-flash-0731": {
  "litellm_provider": "scaleway", "mode": "chat",
  "input_cost_per_token": 4e-07, "output_cost_per_token": 8e-07,
  "cache_read_input_token_cost": 8e-08,
  "max_input_tokens": 256000, "max_output_tokens": 32768, "max_tokens": 32768,
  "supports_function_calling": true, "supports_tool_choice": true,
  "supports_prompt_caching": true, "supports_reasoning": true
}
```

Puis recharger à chaud : `POST /reload/model_cost_map`. Re-vérifier avec
`python3 model-probe/probe.py -u $OPENAI_BASE_URL -m deepseek-v4-flash-scaleway -k $OPENAI_API_KEY --only tools`
→ attendu **4 pass / 0 fail**.

**Durable (recommandé)** — régénérer l'overlay depuis la carte amont **courante**
(qui contient déjà DeepSeek et `scaleway/glm-5.2`, absent en août) en y ré-appliquant
les 6 alias d'IDs courts, avec le `assert canon in d` du rapport d'août.

**Structurel (le vrai remède)** — basculer les routes Scaleway sur le patron `openai/`
(§3.2 du rapport d'août) : `OpenAIGPTConfig.get_supported_openai_params` liste les
params d'outils **en dur** et **ne consulte jamais la cost-map**. Aucun stripping
possible, et surtout **aucune maintenance à chaque nouveau modèle** — ce qui supprime
définitivement la classe de bug plutôt que son instance du jour.

## 5. Autres constats (non bloquants)

- **`/model/info` ment sur la sortie** : il annonce `max_output_tokens: 256000`. La
  vraie limite, obtenue par erreur de validation non facturée (`max_tokens: 9999999`) :
  ```
  400 payload validation: max_completion_tokens is limited to 32768 for deepseek-v4-flash-0731
  ```
  → **32768**, conforme à la carte amont et au gotcha CLAUDE.md. Une entrée omnis pour
  ce modèle doit donc déclarer `context_length: 229376` (262144 − 32768, valeur mesurée
  le 2026-09-01), **jamais** 256000 : sinon un tour qui remplit la fenêtre échoue en 400.
- **Le 400 upstream remonte en 500 côté gateway** (`litellm.APIConnectionError`), ce qui
  masque une erreur client en erreur serveur. Cosmétique, mais trompeur en debug.
- **Reasoning** : modèle *thinking*, `reasoning_content` présent en stream **et** hors
  stream — pas la signature de panne streaming de GLM-5.2. ✅
- **Usage accounting** : `prompt`/`completion` remontés, chunk d'usage livré en fin de
  stream. ✅ Le calcul de coût omnis fonctionnera.
- **Prompt caching** : ✅ **fonctionne, mais intermittent** — mesuré §8.3 sur un préfixe
  stable de 11 620 tokens : **3 hits / 6 appels sur les deux rails** (gateway et Scaleway
  direct, chiffre identique), `cached_tokens: 11520` sur un hit (99 % du préfixe).
  L'intermittence est vraisemblablement une affinité de nœud côté Scaleway, pas un défaut
  gateway. ⚠️ Un échantillon de 3 appels donnait 0/3 côté gateway et 1/3 en direct — assez
  pour « conclure » à tort à une panne gateway. **Ne pas statuer sur ce cache en dessous de
  ~6 appels par rail.** Le prix cache-read déclaré (0.084 \$/M) est donc bien exercé : la
  facturation cache-aware d'omnis (`note_model`) est pertinente pour ce modèle.

## 6. Impact production

**Nul à ce jour.** `/etc/omnis/models.json` ne déclare aucun tier DeepSeek
(`balanced`/`high`/`hosted`/`premium`/`simple`/`imagegen`/`embedder`), et
`~/.omnis/models.json` a `override_model_enabled: false`. Le blocage est donc
**pré-production** : il interdit d'intégrer DeepSeek comme tier agent, il ne dégrade
rien de ce qui tourne.

⚠️ **Ne pas câbler DeepSeek dans un squad omnis tant que le §4 n'est pas appliqué** :
sans `tools`, les agents narreraient leur plan au lieu d'agir — un mode de panne qui
ressemble à un problème de prompt ou de modèle et coûte cher à diagnostiquer.

## 7. Reproduction

```bash
set -a; . ./.env; set +a
# cassé  : 4 fails critiques, exit 1
python3 model-probe/probe.py -u "$OPENAI_BASE_URL" -m deepseek-v4-flash-scaleway -k "$OPENAI_API_KEY" --only tools -v
# sain   : 7 pass, exit 0
python3 model-probe/probe.py -u "${SCALEWAY_API_BASE_URL%/}" -m deepseek-v4-flash-0731 -k "$SCALEWAY_API_KEY" --only tools,chat -v
# témoins : les voisins scaleway passent 4/4 → la plomberie gateway est saine
for M in Balanced qwen3.6-35b-a3b-scaleway mistral-medium-3.5-128b-scaleway; do
  python3 model-probe/probe.py -u "$OPENAI_BASE_URL" -m "$M" -k "$OPENAI_API_KEY" --only tools --no-color | tail -2
done
```


---

## 8. Vérification après correctif (2026-09-15)

### 8.1 Le correctif appliqué

`/model/info` confirme le changement de patron de route — c'est l'option **structurelle**
du §4, celle qui supprime la classe de bug et pas seulement son instance :

| | avant | après |
|---|---|---|
| `litellm_params.model` | `scaleway/deepseek-v4-flash-0731` | **`openai/deepseek-v4-flash-0731`** |
| `custom_llm_provider` | `scaleway` | **`openai`** |
| `api_base` | `https://api.scaleway.ai/v1/` | inchangé |
| `updated_at` | 2026-09-14T15:55 | **2026-09-15T11:27** |

`OpenAIGPTConfig.get_supported_openai_params` liste les params d'outils en dur et ne
consulte **jamais** la cost-map : DeepSeek ne dépend donc plus du snapshot figé d'août.

### 8.2 Résultats

`model-probe` complet sur la gateway : **9 pass / 0 fail / 0 warn / 8 info — exit 0**,
« all critical features OK ». Les 4 checks critiques d'outils qui échouaient passent tous :

```
PASS * Tool calling (non-streaming)      tool call returned (finish_reason=tool_calls)
PASS * Tool calling (streaming)          tool call received over the stream (3/3)
PASS * Parameterless tool over streaming parameterless tool streams correctly (3/3)
PASS * Tool result round-trip            model consumed the tool result and answered
INFO   Parallel tool calls               emitted 2 tool calls in one turn
INFO   tool_choice=required              tool_choice=required forces a tool call
```

**Garde-fou anti-cache** : `model-probe` utilise des prompts fixes, déjà joués ~1 h plus
tôt quand la route était cassée — un rejeu de cache aurait produit un **faux négatif**.
Contrôlé par un test à nonce variable : `cache_key: null` + `x-litellm-response-cost`
non nul sur chaque appel ⇒ appels à froid. Le modèle voit `xq7_frobnicate_wumpus` (il
était aveugle) et émet `finish_reason: tool_calls`.

### 8.3 Non-régression et effets de bord

| Contrôle | Résultat |
|---|---|
| Voisins `scaleway/` (`Balanced`, `High`, `Simple`) | **4 pass / 0 fail** chacun — les alias d'août tiennent toujours |
| Tarification | intacte, déclarée en dur dans `litellm_params` donc indépendante de la cost-map : **0.42 \$/M** in, **0.84 \$/M** out, **0.084 \$/M** cache-read |
| `supports_function_calling` / `_tool_choice` / `_reasoning` | `True` |
| Prompt caching | **3 hits / 6 appels**, identique sur les deux rails (préfixe 11 620 tok, `cached_tokens: 11520` sur hit) |
| Propagation d'erreur | **améliorée** : le 400 upstream remonte maintenant en **400** `BadRequestError` au lieu d'un **500** `APIConnectionError` — le masquage signalé au §5 a disparu avec la route `openai/` |

### 8.4 Ce qui reste vrai

- ~~**`/model/info` surestime toujours la sortie**~~ → **corrigé le 2026-09-15 11:37, voir §9.**
- **Les 10 autres routes `scaleway/*` restent suspendues au snapshot figé d'août.** Elles
  fonctionnent aujourd'hui, mais tout nouveau modèle Scaleway ajouté sur ce patron
  renaîtra cassé. Le patron `openai/` appliqué ici est le remède à généraliser.
- ✅ **DeepSeek est désormais utilisable comme tier agent dans omnis.**


---

## 9. Correction des métadonnées `/model/info` (2026-09-15 11:37)

### 9.1 Ce qui a changé

| Champ | avant | après | vérité terrain |
|---|---|---|---|
| `max_output_tokens` | 256000 | **32768** | ✅ exact |
| `max_input_tokens` | 256000 | **229376** | ✅ = 262144 − 32768 |
| `max_tokens` | 256000 | *inchangé* | ⚠️ voir §9.3 |

**Borne vérifiée au token près** (erreur de validation non facturée) :

```
max_tokens=32768  -> OK   (completion_tokens=16)
max_tokens=32769  -> 400  payload validation: max_completion_tokens is limited to 32768
```

Le tool-calling est **intact** après l'édition : **4 pass / 0 fail**. (Une édition de
`model_info` réécrit le déploiement entier côté LiteLLM — elle aurait pu refaire basculer
la route en `scaleway/`. Elle ne l'a pas fait : toujours `openai/deepseek-v4-flash-0731`.
Contrôle à refaire après **chaque** édition de la fiche modèle.)

### 9.2 Effet sur omnis : le prefill est maintenant correct tout seul

`server/provider_models.go` (l. 537-539) :

```go
ctxLen := mi.MaxInputTokens
if ctxLen == 0 {
    ctxLen = mi.MaxTokens
}
```

`max_input_tokens` étant désormais non nul, omnis en tire **`ContextLength: 229376`** —
exactement la valeur sûre. Le piège de réservation de sortie qui frappe le `balanced`
livré **ne peut plus se produire** pour ce modèle via le prefill. Sont également repris
au passage `input`/`output_cost_per_token` et **`cache_read_input_token_cost`**
(0.084 \$/M) → la facturation cache-aware de squad-bench sera juste, ce qui compte
puisque ce cache est réellement exercé (§8.3).

`model-probe` reflète le changement : `ctx=229376` au lieu de `ctx=256000` (il lit
`max_input_tokens`, cf. `checks/meta.py`).

### 9.3 Reste une incohérence mineure, à signaler sans urgence

`max_tokens` vaut toujours **256000**. Dans la convention LiteLLM, `max_tokens` est le
champ *legacy* qui **duplique `max_output_tokens`** — l'entrée amont de ce modèle porte
d'ailleurs `"max_tokens": 32768`. Ici il ne vaut ni la sortie (32768) ni l'entrée sûre
(229376).

**Sans conséquence pour omnis** : il ne lit `max_tokens` qu'en repli, quand
`max_input_tokens` est nul — cas qui ne se présente plus. Mais c'est une **mine dormante** :
tout client qui lit `max_tokens` comme budget de sortie (la convention LiteLLM) demandera
256000 et prendra un 400. À aligner sur **32768** au prochain passage.

---

## 10. Re-vérification 14:14 — retour volontaire sur `scaleway/`, le correctif tient

Contrôle demandé après une nouvelle modification de la configuration du modèle.
**Conclusion : le tool-calling fonctionne toujours (9 pass / 0 fail / 0 warn, exit 0),
mais pas pour la raison décrite au §8.** Ce paragraphe supersède le §8.1, le §8.3
(ligne « Propagation d'erreur ») et le §8.4.

### 10.1 La route est repassée sur le patron `scaleway/` — volontairement

| | §8 (11:27) | maintenant (14:14) |
|---|---|---|
| `litellm_params.model` | `openai/deepseek-v4-flash-0731` | **`scaleway/deepseek-v4-flash-0731`** |
| `custom_llm_provider` | `openai` | **`None`** (déduit du préfixe → `scaleway`) |
| `updated_at` | 2026-09-15T11:27 | **2026-09-15T14:14** |

Deux preuves indépendantes que le provider **Scaleway** est bien celui emprunté à
l'exécution — un `OpenAIException` serait remonté sur la route `openai/` :

```
kwarg inconnu   → 500 litellm.APIConnectionError: ScalewayException -
                  AsyncCompletions.create() got an unexpected keyword argument 'bogus_param_xyz'
temperature=999 → 500 litellm.APIConnectionError: ScalewayException - Error code: 400 -
                  {'message': 'temperature must be in [0, 2] …'}
```

**Ce n'est pas le piège du §9 qui a joué** : le détour par `openai/` a été **annulé
volontairement**, `scaleway/` est la configuration voulue. C'est donc bien cette
configuration-là qui est validée ci-dessous. (Le piège du §9 — éditer la carte d'un
modèle réécrit le déploiement et peut reverter `litellm_params.model` — reste vrai et
mérite toujours un `model-probe --only tools` après chaque édition de carte.)

### 10.2 Pourquoi ça marche quand même : c'est la cost-map qui a été réparée

Sur le chemin provider Scaleway, `tools` ne survit que si
`supports_function_calling(model, custom_llm_provider="scaleway")` renvoie `True`, ce qui
exige la clé dans la carte **effective**. Or elle résout aujourd'hui et ne résolvait pas
hier — alors que les drapeaux `supports_*` de la carte du modèle étaient **identiques les
deux jours** (`supports_function_calling: true` figurait déjà hier, §3). La carte du
modèle n'est donc **pas** le mécanisme.

> **La carte de prix servie contient désormais `scaleway/deepseek-v4-flash-0731`** — soit
> par le patch d'une entrée du §4, soit par un rafraîchissement depuis l'amont. Les 6
> alias d'IDs courts y sont toujours, puisque les voisins passent encore.

C'est donc le correctif **immédiat** du §4 qui est en place, pas le correctif
**structurel**. Conséquence inchangée : le prochain modèle Scaleway ajouté naîtra cassé
si la carte servie n'est pas mise à jour avec lui.

### 10.3 Résultats mesurés

| Contrôle | Résultat |
|---|---|
| `model-probe` complet, gateway | **9 pass / 0 fail / 0 warn / 8 info — exit 0** |
| 4 checks critiques d'outils | tous **PASS** |
| `tool_choice=required` | force bien un appel (c'était un `WARN` avant correctif) |
| Appels d'outils parallèles | 2 en un tour ✅ |
| Non-régression voisins | `Balanced`, `High`, `Simple`, `qwen3.6-35b-a3b`, `mistral-medium-3.5-128b` → **4 pass / 0 fail** chacun |
| `/model/info` contexte | `max_input_tokens: 229376`, `max_output_tokens: 32768` → omnis préremplit la **bonne** valeur |

### 10.4 Deux corrections à ce qui avait été écrit

1. **Le masquage 400→500 n'a PAS disparu** (le §8.3 l'annonçait corrigé, à tort — il
   l'était sur la route `openai/`, qui n'est plus en place) : `temperature: 999` donne un
   `400 BadRequestError` propre en direct et un **500 `APIConnectionError`** via la
   gateway.
2. **Le 400 de dépassement de `max_tokens` a disparu, lui** : `max_tokens: 9999999`
   renvoie maintenant **200** (contre un 400 hier et toujours un 400 en direct). LiteLLM
   clampe ou ignore la valeur face au `max_output_tokens: 32768` désormais déclaré.
   Effet de bord à connaître : **le truc du 400 non facturé pour découvrir le vrai
   plafond de sortie ne fonctionne plus à travers la gateway** — passer par le rail
   direct pour ça.
