# LiteLLM 1.93 : le provider `scaleway` supprime silencieusement `tools` — diagnostic et correctif

**Date** : 2026-08-13
**Gateway** : `https://llm-gateway.ai.chapsvision.com/llm-gateway` — LiteLLM **1.93.0**
**Symptôme** : depuis la montée en 1.93, aucun modèle Scaleway n'émet de `tool_calls`.
Les agents (omnis) reçoivent de la prose ou de faux appels d'outils en texte.
**Outils** : `model-probe/probe.py` + tests ciblés (repro en fin de document)
**Statut** : ✅ **corrigé** le 2026-08-13 — le gateway a été patché avec les alias du
§3.1. Vérification après correctif en **§8** : 10/10 routes scaleway réparées, aucune
régression sur les 44 autres modèles.

---

## 1. Périmètre : strictement le provider `scaleway`

Balayage des **54 modèles chat** du gateway, un appel avec un `tools` d'une fonction,
groupé par route provider :

| Route provider | Cassés | Détail |
|---|---|---|
| **`scaleway/`** | **10 / 10** | `Balanced`, `High`, `Simple`, `qwen3.6-35b-a3b-scaleway`, `qwen3.5-397b-a17b-scaleway`, `gemma-4-26b-a4b-it-scaleway`, `glm-5.2-scaleway`, `mistral-medium-3.5-128b-scaleway`, `devstral-2-123b-instruct-2512-scaleway`, `qwen3-coder-30b-a3b-instruct-scaleway` |
| `(direct)` anthropic / azure-openai | 0 / 29 | ✓ |
| `hosted_vllm/` | 0 / 6 | ✓ |
| `ovhcloud/` | 0 / 4 | ✓ |
| `gemini/` | 0 / 4 | ✓ |
| `openai/` | 0 / 1 | ✓ (`gpt-oss-120b-ovh`) |

Deux `ERR` non liés : `claude-3-7-sonnet` et `gemini-2.0-flash` renvoient 404 upstream.

**Les 10 modèles ne sont pas en cause** : appelés **en direct** sur
`https://api.scaleway.ai/v1`, ils émettent tous des `tool_calls` natifs, en streaming
comme en non-streaming (`model-probe --only tools` sur `qwen3.6-35b-a3b` : **4 pass /
0 fail**, `tool_choice=required` inclus).

Preuve que les outils n'atteignent même pas le modèle — un outil au nom indevinable
(`xq7_frobnicate_wumpus`) puis « liste les outils dont tu disposes » :

| Appel | Réponse |
|---|---|
| scaleway **direct** | `xq7_frobnicate_wumpus` → **voit l'outil** |
| gateway `ChapsVision` (témoin OK) | `xq7_frobnicate_wumpus` → **voit l'outil** |
| gateway `Balanced` | `NONE` → **aveugle** |
| gateway `Balanced`, **sans** `tools` envoyé | `NONE` → *identique* |

Le paramètre `tools` est donc **supprimé avant l'appel upstream**.

## 2. Cause racine

### La chaîne

1. En 1.93, `scaleway` est un **« JSON-configured provider »** déclaré dans
   [`litellm/llms/openai_like/providers.json`](https://github.com/BerriAI/litellm/blob/main/litellm/llms/openai_like/providers.json).
   Son entrée ne contient que deux clés — aucune déclaration de capacités :
   ```json
   "scaleway": { "base_url": "https://api.scaleway.ai/v1", "api_key_env": "SCW_SECRET_KEY" }
   ```
   (`ovhcloud`, qui fonctionne, n'est **pas** dans ce registre : il a un module natif.)

2. Ces providers reçoivent une config générée à la volée par
   [`litellm/llms/openai_like/dynamic_config.py`](https://github.com/BerriAI/litellm/blob/main/litellm/llms/openai_like/dynamic_config.py).
   Sa méthode `get_supported_openai_params` (l. 92-122) retire les params d'outils
   quand le modèle n'est pas *connu* comme supportant le function calling :

   ```python
   _supports_fc = supports_function_calling(model=model, custom_llm_provider=provider.slug)
   if not _supports_fc:
       tool_params = ["tools", "tool_choice", "function_call", "functions", "parallel_tool_calls"]
       for param in tool_params:
           if param in supported_params:
               supported_params.remove(param)
   ```

3. `supports_function_calling()` → `_supports_factory()` (`litellm/utils.py` l. 2429)
   fait un **lookup littéral** dans la carte de prix `model_prices_and_context_window.json`
   sur la clé `scaleway/<model>`. En cas d'absence : `except` → **`False`**, sans erreur.

4. `map_openai_params` (l. 124-141) ne recopie que les params présents dans
   `supported_params` ou `param_mappings`. Tout le reste est **jeté sans un mot**.

### Le mismatch exact

La carte de prix LiteLLM **connaît** ces modèles et les déclare
`supports_function_calling: true` — mais sous des ID **préfixés par le vendeur**.
Vérifié au tag `v1.93.0` (17 entrées `scaleway/`) :

| Clé présente dans la carte LiteLLM (fn=True) | Clé cherchée avec ta config | Résultat |
|---|---|---|
| `scaleway/qwen/qwen3.6-35b-a3b` | `scaleway/qwen3.6-35b-a3b` | **absent** → False |
| `scaleway/qwen/qwen3.5-397b-a17b` | `scaleway/qwen3.5-397b-a17b` | **absent** → False |
| `scaleway/google/gemma-4-26b-a4b-it` | `scaleway/gemma-4-26b-a4b-it` | **absent** → False |
| `scaleway/mistralai/mistral-medium-3.5-128b` | `scaleway/mistral-medium-3.5-128b` | **absent** → False |
| `scaleway/qwen/qwen3-coder-30b-a3b-instruct` | `scaleway/qwen3-coder-30b-a3b-instruct` | **absent** → False |
| `scaleway/mistralai/devstral-2-123b-instruct-2512` | `scaleway/devstral-2-123b-instruct-2512` | **absent** → False |
| *(aucune entrée GLM chez scaleway)* | `scaleway/glm-5.2` | **absent** → False |

Il n'y a pas non plus de repli : le fallback « clé nue » de `_supports_factory`
(#20885) cherche `qwen3.6-35b-a3b` sans préfixe — également absent.

Or l'API Scaleway, elle, expose les ID **courts** (`GET /models` :
`qwen3.6-35b-a3b`, `gemma-4-26b-a4b-it`, `mistral-medium-3.5-128b`, `glm-5.2`).
La config du gateway utilise donc les ID corrects pour l'upstream — mais ce sont
précisément ceux que le lookup LiteLLM ne trouve pas.

### Pourquoi ça a cassé en 1.93 — la chronologie

| Date | Commit | Effet |
|---|---|---|
| 2025-12-05 | `b2e8d3fd4` | mécanisme « providers OpenAI-compatibles en .json » |
| **2026-02-13** | **`37157ee35`** — `feat(scaleway): add scaleway provider (#21121)` | scaleway devient un provider JSON |
| **2026-02-16** | **`7bcef1490`** — `Fix: Exclude tool params for models without function calling support (#21125)` | **le bloc qui strippe `tools`** |

Le second commit, à 3 jours du premier, est la régression : un « fix » censé éviter
d'envoyer `tools` à des modèles qui ne les gèrent pas, dont le test de capacité
repose sur une carte de prix qui ne contient pas les ID tels qu'on les configure.

### Corroboration

- Un paramètre inconnu remonte jusqu'au SDK en kwarg nu :
  `litellm.APIConnectionError: ScalewayException - AsyncCompletions.create() got an
  unexpected keyword argument 'bogus_param_xyz'` → confirme le passage par le chemin
  client OpenAI des providers JSON (cf. issue [#26443](https://github.com/BerriAI/litellm/issues/26443)).
- Le périmètre du strip est **exactement** les 5 params d'outils listés ci-dessus.
  Vérifié sur litellm 1.93.0 installé en local : `response_format` **passe** (il vient
  de la liste `super()` d'OpenAI). Un `response_format=json_object` qui renvoie du
  contenu vide avec `max_tokens=200` est un effet du thinking forcé qui consomme le
  budget de sortie (814 car. de `reasoning_content`), pas un param jeté — avec
  `max_tokens=3000` le `{"ok":1}` revient normalement.
- `chat_template_kwargs`, lui, est bien jeté (voir §5).

## 3. Le correctif

### 3.1 Recommandé — correctif **100 % JSON**, sans toucher au code

La carte de prix supporte une clé **`aliases`** par entrée
(`_expand_model_aliases`, présente en v1.93.0) : chaque alias devient une entrée de
premier niveau pointant vers **le même dict** que l'entrée canonique. C'est
exactement le mécanisme qu'il faut — on déclare les ID courts comme alias des ID
préfixés vendeur, et le lookup de `supports_function_calling` aboutit.

Six alias suffisent pour 9 des 10 déploiements ; `glm-5.2`, absent de la carte
amont, demande une entrée autonome :

```python
# à appliquer sur model_prices_and_context_window.json de ta version pinnée
ALIASES = {
  "scaleway/qwen/qwen3.6-35b-a3b":                    ["scaleway/qwen3.6-35b-a3b"],
  "scaleway/qwen/qwen3.5-397b-a17b":                  ["scaleway/qwen3.5-397b-a17b"],
  "scaleway/google/gemma-4-26b-a4b-it":               ["scaleway/gemma-4-26b-a4b-it"],
  "scaleway/qwen/qwen3-coder-30b-a3b-instruct":       ["scaleway/qwen3-coder-30b-a3b-instruct"],
  "scaleway/mistralai/mistral-medium-3.5-128b":       ["scaleway/mistral-medium-3.5-128b"],
  "scaleway/mistralai/devstral-2-123b-instruct-2512": ["scaleway/devstral-2-123b-instruct-2512"],
}
NEW = {  # pas d'entrée canonique amont — prix repris de ton /model/info
  "scaleway/glm-5.2": {
    "litellm_provider": "scaleway", "mode": "chat",
    "input_cost_per_token": 1.89e-06, "output_cost_per_token": 5.775e-06,
    "max_input_tokens": 256000, "max_output_tokens": 16000, "max_tokens": 16000,
    "supports_function_calling": True, "supports_tool_choice": True,
    "supports_reasoning": True,
  },
}
for canon, al in ALIASES.items():
    d[canon]["aliases"] = al          # assert canon in d  → détecte un renommage amont
d.update(NEW)
```

**Résultat mesuré** sur litellm **1.93.0** installé en venv, via
`get_optional_params(model=…, custom_llm_provider="scaleway", tools=[…])` :

| | `supports_function_calling` | `tools` transmis |
|---|---|---|
| carte amont (état actuel) | False sur 7/7 | **0 / 7** |
| carte patchée | True sur 7/7 | **7 / 7** |

Avant patch, `get_optional_params` ne renvoie que `['stream']` ; après, `['stream',
'tools']`. Les 7 modèles distincts couvrent les 10 déploiements.

**Deux façons de le déployer, aucune ne touche au code :**

1. **Carte hébergée via `LITELLM_MODEL_COST_MAP_URL`** *(préféré)* — sers ta carte
   patchée depuis un fichier statique. **Rien n'est modifié dans l'image**, donc rien
   à re-patcher à chaque upgrade, et la route admin **`POST /reload/model_cost_map`**
   permet de recharger à chaud sans redémarrer le proxy. Vérifié : la carte servie sur
   un HTTP local donne bien `source: remote` + 7/7.
2. **Patcher `litellm/model_prices_and_context_window_backup.json` dans l'image
   + `LITELLM_LOCAL_MODEL_COST_MAP=True`.** Vérifié également (7/7). ⚠️ **L'env var est
   obligatoire** : par défaut litellm va chercher la carte distante sur GitHub
   (`source: remote`) et ton patch local est purement ignoré — c'est le piège
   principal de cette option. Contrepartie : tu gèles aussi les mises à jour de prix
   amont.

**Contraintes à respecter** (validation d'intégrité, `constants.py` v1.93.0) : la
carte servie doit contenir **≥ 50 modèles** et ne pas descendre sous **50 %** du
nombre d'entrées du backup, sinon litellm la rejette silencieusement et retombe sur
le backup. Donc : servir la **carte amont complète + tes ajouts** (2955 entrées dans
mon test), jamais un fragment. Les deux seuils sont surchargeables
(`MODEL_COST_MAP_MIN_MODEL_COUNT`, `MODEL_COST_MAP_MAX_SHRINK_RATIO`).

Discipline à prévoir : régénérer la carte patchée à chaque montée de version de
litellm (script d'overlay + `assert canon in d`, pour détecter tout renommage amont
des clés canoniques).

### 3.2 Alternative — sortir du provider JSON, passer par la route `openai/`

`OpenAIGPTConfig.get_supported_openai_params`
([`gpt_transformation.py`](https://github.com/BerriAI/litellm/blob/main/litellm/llms/openai/chat/gpt_transformation.py) l. 129-161)
liste `tools`, `tool_choice`, `functions`, `function_call`, `parallel_tool_calls` en
dur et **ne consulte jamais** la carte de prix. Aucun stripping possible.

```yaml
- model_name: Balanced
  litellm_params:
    model: openai/qwen3.6-35b-a3b            # ID court = celui que Scaleway expose
    api_base: https://api.scaleway.ai/v1
    api_key: os.environ/SCW_SECRET_KEY
  model_info:
    supports_function_calling: true          # pour /model/info (cosmétique ici)
```

Pourquoi c'est le bon choix :
- **déjà prouvé sur ton instance** : `gpt-oss-120b-ovh` (`openai/gpt-oss-120b`) et les
  6 routes `hosted_vllm/` passent les outils sans problème ;
- **un seul patron pour les 10**, sans exception par modèle ;
- garde les ID courts, les seuls que Scaleway garantit ;
- insensible aux futures évolutions de la carte de prix.

Coût : tu perds le pricing automatique de la carte `scaleway/*` — à redéclarer en
`input_cost_per_token` / `output_cost_per_token` dans `model_info` (tu le fais déjà,
tes prix par tier sont exposés correctement).

### 3.3 Alternative « diff minimal » — renommer vers l'ID préfixé

Fonctionne pour les modèles dont Scaleway tolère l'alias préfixé (vérifié : la
requête aboutit et les `tool_calls` reviennent) :

| Config actuelle | À remplacer par | Upstream accepte l'alias ? |
|---|---|---|
| `scaleway/qwen3.6-35b-a3b` | `scaleway/qwen/qwen3.6-35b-a3b` | ✓ |
| `scaleway/qwen3.5-397b-a17b` | `scaleway/qwen/qwen3.5-397b-a17b` | ✓ |
| `scaleway/gemma-4-26b-a4b-it` | `scaleway/google/gemma-4-26b-a4b-it` | ✓ |
| `scaleway/qwen3-coder-30b-a3b-instruct` | `scaleway/qwen/qwen3-coder-30b-a3b-instruct` | ✓ |
| `scaleway/mistral-medium-3.5-128b` | `scaleway/mistralai/mistral-medium-3.5-128b` | ✗ **404 upstream** |
| `scaleway/glm-5.2` | — | ✗ **aucune entrée GLM dans la carte** |

Donc : couvre 6 tiers sur 10 (dont `Balanced`, `High`, `Simple`), mais **casserait**
`mistral-medium` et laisse `glm-5.2` cassé. À réserver à un hotfix rapide sur
`Balanced`/`High`/`Simple`.

### 3.4 Ce qui ne marchera **pas** (à ne pas perdre de temps dessus)

- **`param_mappings` dans `providers.json`** — c'est la piste JSON qui paraît
  évidente : `map_openai_params` teste `param_mappings` **avant** `supported_params`
  et le court-circuite, donc un mapping identité `{"tools": "tools"}` devrait forcer
  le passage. **Ça ne marche pas** : en amont, `_check_valid_arg` (`utils.py` l. 4027-
  4030) fait `non_default_params.pop("tools")` **avant** l'appel à
  `map_openai_params`. Le param a déjà disparu. Et le loader JSON
  (`json_loader.py`, `SimpleProviderConfig`) ne lit que 8 clés — `base_url`,
  `api_key_env`, `api_base_env`, `base_class`, `param_mappings`, `constraints`,
  `special_handling`, `supported_endpoints` — aucune ne permet de déclarer des
  capacités. **`providers.json` est un cul-de-sac ; le levier JSON est la carte de
  prix (§3.1).**
- **`drop_params: false`** — ne corrige rien, mais **rend le bug visible** : au lieu du
  silence, litellm lève `UnsupportedParamsError: scaleway does not support
  parameters: ['tools'], for model=qwen3.6-35b-a3b` (HTTP 500). Vérifié en local sur
  1.93.0. Ton proxy a donc `drop_params: true` (c'est ce qui rend la perte muette).
  Utile comme canari une fois le correctif appliqué : avec la carte patchée, plus
  d'exception.
- **`model_info: supports_function_calling: true` sur le déploiement** — ton
  `/model/info` annonce **déjà** `True` pour `Balanced`, `High`, `Simple` et
  `qwen3.6-35b-a3b-scaleway`, et les outils sont malgré tout supprimés. Ce champ
  alimente la réponse `/model/info` mais pas `supports_function_calling()` du chemin
  de code fautif. (À confirmer côté config : si tu ne l'avais pas positionné, l'écart
  vient d'ailleurs — mais dans les deux cas le comportement observé ne change pas.)
- **Downgrade sous 1.93** : le commit fautif date de **février 2026**, donc antérieur
  à 1.93. Si ça marchait avant chez toi, c'est que la montée de version a aussi
  amené scaleway dans le registre JSON (ou que la config a migré de `openai/` vers
  `scaleway/` à cette occasion). Vérifie l'historique de ton `config.yaml` : la route
  d'avant est probablement exactement le correctif recommandé ci-dessus.

## 4. À remonter en amont

Deux défauts distincts, indépendants de ta config :

1. **`get_supported_openai_params` traite « modèle absent de la carte de prix » comme
   « ne supporte pas le function calling »**. Pour un provider OpenAI-compatible c'est
   un défaut par défaut inversé : l'absence de métadonnée n'est pas une absence de
   capacité. Un endpoint OpenAI-compatible devrait laisser passer `tools` par défaut.
2. **La perte de capacité est indétectable côté client** : sous `drop_params: true`
   (réglage courant en proxy, et le nôtre) rien n'est loggé en warning, et
   `/model/info` continue d'annoncer `supports_function_calling: true` — un agent n'a
   aucun moyen de savoir que ses outils ont été retirés. La suppression d'une capacité
   *annoncée* mériterait un warning inconditionnel, indépendamment de `drop_params`
   (dont le rôle légitime est de tolérer les params inutilisables, pas de masquer une
   incohérence de métadonnées).

Complément utile, et c'est le patch amont le plus simple : les clés `scaleway/*` de la
carte de prix sont préfixées vendeur (`scaleway/qwen/qwen3.6-35b-a3b`) alors que
l'API Scaleway expose les ID courts (`qwen3.6-35b-a3b`) — le lookup ne peut
structurellement pas aboutir pour une config écrite d'après `GET /models`. Le
mécanisme `aliases` existe déjà dans la carte (`_expand_model_aliases`) mais
**aucune entrée amont ne l'utilise** (0 sur 2954 en v1.93.0) : ajouter les alias
courts sur les 17 entrées `scaleway/*` réglerait le cas général pour tout le monde.
C'est une PR de quelques lignes de JSON, sans code.

À rattacher à [#26443](https://github.com/BerriAI/litellm/issues/26443) (même famille :
providers JSON et traitement des params), en citant les commits `37157ee35` et
`7bcef1490`.

## 5. Trouvailles annexes

- **Le mode thinking est actif via le gateway et pas en direct**, à requête identique
  (prose, sans outils) : `reasoning_content` 1141 car. via `Balanced`, absent en
  direct sur `qwen3.6-35b-a3b`. À chercher dans les `litellm_params` du déploiement
  (`chat_template_kwargs`, `reasoning_effort`, `extra_body`). Conséquence du bug
  principal : **le client ne peut pas le désactiver**, `chat_template_kwargs` étant
  jeté par le même filtre — les deux appels avec `thinking:false` renvoient
  exactement les mêmes 1141 car., signature d'une requête upstream identique.
  Effet de bord à connaître : le raisonnement **consomme le budget `max_tokens`**, donc
  un appel avec un `max_tokens` serré revient avec un `content` vide (c'est ce qui m'a
  d'abord fait croire à tort que `response_format` était jeté).
- **Un cache de réponses est actif** (`x-litellm-cache-key`) : deux requêtes
  identiques renvoient le **même `chatcmpl-id`**, byte-identique, sans en-tête
  `x-litellm-response-cost`. Pour une boucle d'agent, un retry à l'identique renvoie
  la même réponse — l'auto-correction par répétition est impossible. À arbitrer selon
  l'usage (utile pour du chat, nuisible pour de l'agentique).
- **`devstral-2-123b-instruct-2512-scaleway` ne sert pas devstral.** L'ID n'existe pas
  dans le `GET /models` de Scaleway, et l'upstream répond `served=qwen3.5-397b-a17b`
  (3 appels sur 3, avec et sans préfixe vendeur). Ce déploiement est mal étiqueté,
  indépendamment du bug outils.

## 6. Impact côté omnis (le déclencheur de l'enquête)

`model-probe` sur `Balanced` : **4 échecs critiques sur 4** (tool calling stream et
non-stream, outils sans paramètre, round-trip de résultat). Le reste passe (chat, SSE,
`usage` en streaming, ctx 256k).

En attendant le correctif gateway, les tiers utilisables pour omnis :

| Alias | Modèle | in / out ($/M) | `model-probe` |
|---|---|---|---|
| `ChapsVision` / `Hosted` | Qwen3.6-27B (vLLM interne) | **0.04 / 0.27** | **9 pass, 0 fail** |
| `Premium` | claude-sonnet-4-6 | 3.15 / 15.75 | outils OK |

`ChapsVision` rejette `tool_choice=required` (le direct Scaleway l'accepte) — à
vérifier si le routeur omnis s'en sert.

Note : la « GLM-5.2/Scaleway regression » notée dans le CLAUDE.md de ce repo n'était
pas un bug GLM — c'était déjà ce bug de gateway.

## 7. Reproduction

```bash
cd omnis-benches && set -a && . ./.env && set +a

# le constat
python3 model-probe/probe.py -u "$OPENAI_BASE_URL" -m Balanced -k "$OPENAI_API_KEY" --verbose

# le même modèle en direct : tout passe
python3 model-probe/probe.py -u "$SCALEWAY_API_BASE_URL" -m qwen3.6-35b-a3b -k "$SCALEWAY_API_KEY" --only tools

# la baseline verte sur le gateway
python3 model-probe/probe.py -u "$OPENAI_BASE_URL" -m ChapsVision -k "$OPENAI_API_KEY"
```

Preuve que `tools` est supprimé (outil au nom indevinable, réponse `NONE` = aveugle) :

```bash
curl -s "$OPENAI_BASE_URL/chat/completions" -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H 'Content-Type: application/json' -d '{
  "model":"Balanced",
  "messages":[{"role":"user","content":"List the EXACT names of every tool available to you. If none, reply exactly: NONE"}],
  "tools":[{"type":"function","function":{"name":"xq7_frobnicate_wumpus","parameters":{"type":"object","properties":{"zorble_id":{"type":"string"}},"required":["zorble_id"]}}}]}'
```

Avec ta clé **admin**, le diagnostic se fait en un appel — `tools` doit être absent de
la liste pour les routes scaleway :

```bash
curl -s -H "Authorization: Bearer $LITELLM_ADMIN_KEY" \
  "$OPENAI_BASE_URL/utils/supported_openai_params?model=Balanced"
```

(la clé projet renvoie `Only proxy admin can be used ... Route=/utils/supported_openai_params`)

### Valider le correctif JSON hors production

Le diagnostic **et** le correctif se vérifient sans toucher au gateway, dans un venv
jetable — c'est comme ça que le tableau 0/7 → 7/7 du §3.1 a été obtenu :

```bash
python3 -m venv v && ./v/bin/pip install -q "litellm==1.93.0"
cp "$(./v/bin/python -c 'import importlib.resources as r; print(r.files("litellm").joinpath("model_prices_and_context_window_backup.json"))')" pristine.json
```

```python
# verify_all.py — 0/7 avant patch, 7/7 après
from litellm.utils import get_optional_params, supports_function_calling
TOOLS = [{"type": "function", "function": {"name": "get_weather",
          "parameters": {"type": "object", "properties": {"location": {"type": "string"}},
                         "required": ["location"]}}}]
for m in ["qwen3.6-35b-a3b", "qwen3.5-397b-a17b", "gemma-4-26b-a4b-it",
          "qwen3-coder-30b-a3b-instruct", "mistral-medium-3.5-128b",
          "devstral-2-123b-instruct-2512", "glm-5.2"]:
    op = get_optional_params(model=m, custom_llm_provider="scaleway", tools=TOOLS, drop_params=True)
    print("PASS" if "tools" in op else "FAIL", f"scaleway/{m}",
          "fn=", supports_function_calling(model=m, custom_llm_provider="scaleway"))
```

```bash
./v/bin/python verify_all.py                                    # 0/7 — état actuel
# applique les aliases du §3.1 sur pristine.json -> patched.json, puis :
python3 -m http.server 8199 --directory . &
LITELLM_MODEL_COST_MAP_URL="http://127.0.0.1:8199/patched.json" ./v/bin/python verify_all.py   # 7/7
```

La carte est lue **une seule fois à l'import** de litellm : chaque scénario doit
tourner dans un processus neuf.

---

## 8. Vérification après correctif (2026-08-13)

Le gateway a été patché avec les alias du §3.1. Tests refaits avec des **prompts
porteurs d'un nonce unique** — indispensable, le cache de réponses du gateway
(§5) rejouerait sinon les échecs précédents et donnerait un faux négatif.

### Les 10 déploiements scaleway

| Déploiement | non-streaming | streaming |
|---|---|---|
| `Balanced`, `High`, `Simple` | ✓ `tool_calls` | ✓ `tool_calls` |
| `qwen3.6-35b-a3b-scaleway`, `qwen3.5-397b-a17b-scaleway` | ✓ | ✓ |
| `gemma-4-26b-a4b-it-scaleway`, `qwen3-coder-30b-a3b-instruct-scaleway` | ✓ | ✓ |
| `mistral-medium-3.5-128b-scaleway`, `devstral-2-123b-instruct-2512-scaleway` | ✓ | ✓ |
| `glm-5.2-scaleway` *(entrée autonome, pas un alias)* | ✓ | ✓ |

**10 / 10.** `glm-5.2`, qui n'avait aucune entrée canonique amont, fonctionne aussi —
l'entrée autonome est correcte.

### `model-probe` complet sur les trois tiers

| Tier | Résultat | Détail |
|---|---|---|
| `Balanced` | **9 pass, 0 fail, 0 warn** | tous critiques OK |
| `High` | **9 pass, 0 fail, 0 warn** | tous critiques OK |
| `Simple` | **9 pass, 0 fail, 0 warn** | tous critiques OK |

Les 4 checks critiques d'outils passent (streaming, non-streaming, outil sans
paramètre en streaming, round-trip de résultat), plus les appels parallèles. À noter :
`tool_choice=required` est passé de `WARN` (accepté mais aucun appel émis) à
**`INFO` — force bien un appel**, ce que `ChapsVision` ne fait pas.

### Non-régression et facturation

Balayage complet des 54 modèles chat : **0 cassé** (52 OK ; les 2 `ERR` restants sont
les 404 upstream préexistants sur `claude-3-7-sonnet` et `gemini-2.0-flash`). Aucune
route `(direct)`, `hosted_vllm/`, `ovhcloud/`, `gemini/`, `openai/` n'a bougé — les
alias n'ont pas d'effet de bord hors scaleway.

Facturation intacte : `x-litellm-response-cost` toujours émis sur `Balanced`, `High`,
`Simple`, `glm-5.2-scaleway`, et les prix de `/model/info` sont **identiques** à ceux
d'avant le patch (les alias, qui partagent le dict de l'entrée canonique amont, n'ont
pas écrasé le pricing déclaré dans la config).

### Ce qui reste ouvert

Le bug outils est clos ; les deux effets de bord du §5 sont inchangés et méritent un
arbitrage séparé :

1. **Le thinking forcé consomme le budget `max_tokens`** — c'est le risque le plus
   concret pour un agent. Mesuré sur `Balanced` :

   | `max_tokens` | `finish_reason` | reasoning | content | tool_calls |
   |---|---|---|---|---|
   | 200 | `length` | 791 car. | **0** | **0** ← appel perdu |
   | 400 | `tool_calls` | 955 car. | 0 | 1 |
   | 800 → 3000 | `tool_calls` | ~700-1000 car. | 0 | 1 |
   | 800 *(sans outils)* | `stop` | 1778 car. | 370 car. | — |

   En dessous de ~300 tokens de budget, la réponse est **entièrement absorbée par le
   raisonnement** : ni contenu ni appel d'outil, `finish_reason=length`. Côté omnis :
   ne pas plafonner `max_tokens` sur ces tiers (ou rester ≥ 1000). Côté gateway : le
   thinking vient de la config du déploiement (absent en direct sur Scaleway) et le
   client ne peut pas le désactiver, `chat_template_kwargs` étant filtré.

2. **Le cache de réponses reste actif** (`x-litellm-cache-key`, même `chatcmpl-id` sur
   deux requêtes identiques). Sans impact sur le tool calling, mais un retry à
   l'identique dans une boucle d'agent renvoie la même réponse — à arbitrer selon
   l'usage.

`Balanced` est désormais utilisable par omnis : à **$0.26 / $1.58 par M**, contre
$3.15 / $15.75 pour `Premium`, avec les mêmes garanties sur les outils.
