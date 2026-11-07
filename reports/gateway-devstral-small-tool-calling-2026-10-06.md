# Devstral-Small sur la LLM Gateway : les tool calls sont perdus en streaming — le modèle est sain

**Date** : 2026-10-06
**Gateway** : `https://llm-gateway.ai.chapsvision.com/llm-gateway` (LiteLLM 1.93.0)
**Modèle** : `Devstral-Small` → `hosted_vllm/mistralai/Devstral-Small`
  `api_base` = `https://lab.ai.chapsvision.com/production/api/Production/Devstral-Small/v1/v1`
**Outil** : `model-probe/probe.py` + `gateway-devstral-small-tool-calling-2026-10-06-probe.py`
**Statut** : 🔴 **bloquant pour le mode agent** — le remède est côté **déploiement vLLM de Devstral-Small**, pas côté omnis ni côté modèle.

---

## 1. Verdict

Le retour utilisateur est **confirmé et reproductible** : en streaming, Devstral-Small
renvoie de la prose dans `delta.content` et **aucun** `delta.tool_calls`.

Mais la conclusion qu'on en tire spontanément — « le modèle ne comprend pas les appels
de fonctions » — est **fausse**. Le modèle émet parfaitement le tool call. C'est la
**couche de service qui l'avale**, et uniquement sur le chemin `stream=true` +
`tool_choice=auto`.

| Chemin | Résultat |
|---|---|
| **non-streaming**, `tool_choice=auto` | ✅ `finish_reason=tool_calls`, `get_weather` |
| **streaming**, `tool_choice=auto` | 🔴 **0 delta**, `finish_reason=stop` |
| **streaming**, `tool_choice=required` | ✅ `get_weather({"city": "Paris"})`, JSON valide |
| **streaming**, `tool_choice` nommé | ✅ `get_weather({"city": "Paris"})`, JSON valide |
| **streaming**, sans `tools` | ✅ prose normale (24-62 chunks) |

`model-probe` complet : **7 pass / 2 fail / 0 warn / 8 info**, exit 1.

```
FAIL * Tool calling (streaming)           NO tool call over streaming (0/3)
FAIL * Parameterless tool over streaming  parameterless tool LOST in streaming (0/3)
                                          but works non-streaming
PASS * Tool calling (non-streaming)       tool call returned (finish_reason=tool_calls)
PASS * Tool result round-trip             model consumed the tool result and answered
INFO   tool_choice=required               tool_choice=required forces a tool call
```

Le reste est sain : chat, streaming, instruction système, usage, `max_tokens`,
`temperature`. **Seul le tool-calling en streaming est cassé.**

## 2. Preuve que le modèle génère bien le tool call

La comptabilité de tokens tranche, et c'est l'observation décisive. Même prompt
(avec nonce), une fois en streaming, une fois non :

| Appel | `completion_tokens` | Ce qui arrive au client |
|---|---|---|
| non-streaming, `auto` | **12** | `tool_calls: [get_weather]`, `finish_reason=tool_calls` |
| streaming, `auto` | **12** | **rien** — `content=''`, 0 delta, `finish_reason=stop` |

**Les 12 tokens sont facturés dans les deux cas.** Le modèle a produit exactement la
même sortie ; en streaming elle n'est simplement jamais transmise. Ce n'est donc ni une
question de capacité du modèle, ni une question de `tools` stripé par la gateway (le
paramètre arrive bien, sinon le non-streaming échouerait aussi).

Et quand on force le modèle à parler *avant* d'appeler l'outil, on obtient
**précisément le symptôme rapporté par l'utilisateur** — la prose passe, le tool call
disparaît :

```
system: "Always briefly state what you are about to do, then call the appropriate tool."
user:   "Weather in Paris?"
→ finish=stop  out_tok=21  tcDeltas=0
  text='I will fetch the current weather for Paris.'
```

21 tokens de sortie : ~9 pour la phrase, ~12 pour le tool call. Le client ne reçoit
que la phrase. **L'observation mitmproxy de l'utilisateur est exacte** ; c'est son
interprétation (« il génère de la prose *au lieu* d'appeler ») qui inverse cause et
effet : il appelle, et l'appel est effacé en route.

## 3. Périmètre : c'est ce déploiement-là, pas la gateway

Trois modèles partagent le **même provider LiteLLM (`hosted_vllm`), la même gateway et
le même hôte** `lab.ai.chapsvision.com`. Témoins décisifs :

| Modèle | `litellm_params.model` | stream + `auto` |
|---|---|---|
| **`Devstral-Small`** | `hosted_vllm/mistralai/Devstral-Small` | 🔴 `finish=stop`, 0 delta |
| `ChapsVision` | `hosted_vllm/Qwen/Qwen3.6-27B` | ✅ `finish=tool_calls`, 4 deltas |
| `Qwen3.6-27B-ChapsVision` | `hosted_vllm/Qwen/Qwen3.6-27B` | ✅ `finish=tool_calls`, 4 deltas |

Ce qui est **écarté** par ces témoins :

- ❌ un bug LiteLLM générique (même version, même route `hosted_vllm`, les voisins passent) ;
- ❌ la cost-map figée de 2026-08-13 (cf. le rapport DeepSeek) : les trois modèles ont
  `supports_function_calling: null` et les trois reçoivent bien `tools` — ce n'est
  **pas** le mécanisme de strip décrit en août ;
- ❌ un problème de prompt ou de squad omnis : tout est reproduit en HTTP brut.

Il reste **le serveur vLLM de Devstral-Small lui-même**.

## 4. Cause racine probable

> ⚠️ Partie **inférée** : l'upstream répond 401 depuis l'extérieur
> (`lab.ai.chapsvision.com/.../v1/models`), je ne peux pas lire sa ligne de commande.
> Tout ce qui précède est mesuré ; ce qui suit est l'explication la plus économique.

Le faisceau est net. Dans vLLM, les deux chemins ne passent pas par le même code :

- `tool_choice="required"` / nommé → **décodage guidé** : la sortie est contrainte au
  schéma JSON de l'outil et émise par un chemin dédié. **Fonctionne ici.**
- `tool_choice="auto"` → **tool-call parser** (`--tool-call-parser`) : le serveur doit
  repérer le token natif du modèle (`[TOOL_CALLS]` pour les architectures Mistral, dont
  Devstral) dans le flux libre et le convertir en `delta.tool_calls`. **C'est ce
  chemin-là qui échoue, et seulement en streaming.**

Le parser est donc **présent mais à moitié câblé** : sa branche non-streaming
(`extract_tool_calls`) marche, sa branche streaming
(`extract_tool_calls_streaming`) ne produit rien et laisse le texte du tool call être
filtré sans être réémis. Classe de bug connue du parser `mistral` de vLLM ; les
déploiements Qwen voisins utilisent un parser différent (`hermes`), qui stream
correctement — ce qui explique l'asymétrie exacte observée en §3.

Indice corroborant : **même en mode `required`, où le tool call passe,
`finish_reason` vaut `stop` au lieu de `tool_calls`** (les témoins Qwen renvoient bien
`tool_calls`). La plomberie tool-calling de ce déploiement est incohérente de bout en
bout, pas seulement sur une branche.

**À vérifier côté admin** sur le serveur vLLM de Devstral-Small : les flags
`--enable-auto-tool-choice`, `--tool-call-parser mistral`, le `--chat-template`
associé, et la version de vLLM (comparer avec celle des déploiements Qwen qui, eux,
fonctionnent).

## 5. Impact sur omnis

**Bloquant.** omnis streame chaque tour (cf. `CLAUDE.md`, le rail SSE), et un agent doit
rester libre de répondre en prose *ou* d'appeler un outil — c'est exactement
`tool_choice=auto`, le seul mode cassé. Conséquence concrète : l'agent annonce son
intention et n'agit jamais, la boucle d'outillage ne démarre pas. En l'état,
**Devstral-Small n'est pas utilisable comme modèle d'agent dans omnis.**

`tool_choice=required` **n'est pas un contournement** : il force un appel d'outil même
quand aucun n'est pertinent — mesuré, prompt « Just say hello » → `get_weather({"city":
"London"})`. Un agent perdrait la capacité de simplement répondre.

Contournements, par ordre de préférence :

1. **Réparer le déploiement vLLM** (§4) — le seul vrai correctif.
2. **`disable_streaming` pour ce modèle dans omnis** : le non-streaming est sain
   (c'est ce que suggère déjà le message de `model-probe`). Coût : plus de rendu
   token-par-token dans l'UI pour ce modèle.
3. **Ne pas câbler Devstral-Small dans un squad** en attendant ; `ChapsVision` /
   `Qwen3.6-27B-ChapsVision` sont sains sur le même hôte.

## 6. Constat secondaire (non bloquant)

La carte `/model/info` de `Devstral-Small` est **vide de métadonnées** : `mode: null`,
tous les `supports_*` à `null`, `input_cost_per_token: 0.0`, `output_cost_per_token:
0.0`, et `max_input_tokens = max_output_tokens = max_tokens = 128000`.

Deux conséquences, à signaler sans urgence :

- **coûts à 0** → tout bench ou toute comptabilité omnis chiffrera ce modèle à **$0**,
  ce qui le fait passer pour gratuit dans une comparaison de tiers ;
- `max_output_tokens = max_input_tokens = 128000` est le **piège de réservation de
  sortie** déjà documenté dans `CLAUDE.md` : une fenêtre pleine + une réservation de
  sortie se valident contre la *somme*. La valeur sûre serait `128000 − max_output`.

C'est la politique déjà retenue après l'incident DeepSeek : **déclarer
`supports_function_calling` + `max_input_tokens`/`max_output_tokens` + les prix sur
chaque fiche de modèle**, puis passer `model-probe --only tools` avant de câbler le
modèle dans un squad.

## 7. Reproduction

```bash
cd omnis-benches
set -a; . ./.env; set +a

# Suite complète : 7 pass / 2 fail, exit 1
python3 model-probe/probe.py -u "$OPENAI_BASE_URL" -m Devstral-Small -k "$OPENAI_API_KEY"

# Témoins : les voisins hosted_vllm du même hôte passent 4/4
python3 model-probe/probe.py -u "$OPENAI_BASE_URL" -m ChapsVision -k "$OPENAI_API_KEY" --only tools

# Repro minimale ciblée (streaming vs non-streaming vs required + témoins)
python3 reports/gateway-devstral-small-tool-calling-2026-10-06-probe.py
```

Sortie de référence de la repro minimale (2026-10-06) :

```
== Devstral-Small : le modele emet bien le tool call, le streaming+auto le perd ==
Devstral-Small   nonstream  tc=auto      finish=tool_calls  out_tok=12  calls=['get_weather']
Devstral-Small   stream     tc=auto      finish=stop        out_tok=12  calls=NONE text=''
Devstral-Small   stream     tc=required  finish=stop        out_tok=20  calls=['get_weather({"city": "Paris"})']
Devstral-Small   stream     tc=(named)   finish=stop        out_tok=7   calls=['get_weather({"city": "Paris"})']

== Le texte libre passe, lui : seul le tool call disparait ==
Devstral-Small   stream     tc=auto      finish=stop        out_tok=10  calls=NONE
                                         text='Hello! How can I assist you today?'

== Temoins : memes provider/hote/gateway, streaming+auto intact ==
ChapsVision              stream  tc=auto  finish=tool_calls  out_tok=188  calls=['get_weather({"city": "Paris"})']
Qwen3.6-27B-ChapsVision  stream  tc=auto  finish=tool_calls  out_tok=103  calls=['get_weather({"city": "Paris"})']
```

Chaque requête porte un **nonce** : le cache de réponses de la gateway (cf. `CLAUDE.md`,
gotcha `x-litellm-cache-key`) ne peut pas rejouer un verdict antérieur. Les en-têtes des
réponses mesurées ne portent d'ailleurs aucun marqueur de cache (`cache-control:
no-cache`).

## 8. Ce que cet incident ajoute aux précédents

Troisième incident de tool-calling sur cette gateway, et **troisième cause différente** :

| Date | Modèle | Cause | Symptôme |
|---|---|---|---|
| 2026-08-13 | `Balanced` (scaleway) | cost-map : id non préfixé vendeur | `tools` strippé, **0/4** |
| 2026-09-15 | `deepseek-v4-flash` | cost-map figée en août | `tools` strippé, **0/4** |
| **2026-10-06** | **`Devstral-Small`** | **parser streaming du serveur vLLM** | **`tools` reçu**, tool call perdu **en streaming seulement** |

La leçon de 2026-08/09 était « la gateway peut jeter `tools` sans prévenir ». Celle-ci
en ajoute une distincte et plus discrète : **un modèle peut recevoir `tools`, y répondre
correctement — et voir sa réponse détruite par la couche de transport.** Le non-streaming
seul aurait déclaré ce modèle bon (`PASS`). C'est exactement ce que le check
`Tool calling (streaming)` de `model-probe` existe pour attraper (né de la régression
GLM-5.2/Scaleway), et il l'a attrapé.

Corollaire pratique : **le signe distinctif est la comptabilité de tokens.** Un
`completion_tokens` identique entre streaming et non-streaming, avec une sortie vide
côté streaming, dit « le modèle a produit, le transport a perdu » — et évite d'accuser
le modèle, le prompt ou le squad.

---

## 9. Faut-il mettre à jour la version de vLLM ? (question posée le 2026-10-06)

**Réponse courte : oui, c'est le candidat le plus probable — mais ne pas le faire à
l'aveugle. Deux mesures de 30 secondes côté admin tranchent avant de toucher à la prod.**

### 9.1 Ce que les mesures disent de la config

Un test de round-trip a livré une information que je n'avais pas en §4 : rejouer un
historique avec un `tool_call_id` fabriqué renvoie un **400 explicite** —

```
Hosted_vllmException - Tool call id was call_1 but must be a-z, A-Z, 0-9,
with a length of 9
```

C'est le validateur de **`mistral_common`**. Il prouve que le déploiement tourne en
**`--tokenizer-mode mistral`**, c'est-à-dire sur le chemin natif Mistral — qui est la
configuration **recommandée** pour Devstral, pas une erreur de déploiement.

En recoupant avec le reste :

| Observation | Ce qu'elle élimine |
|---|---|
| tokenizer Mistral actif (erreur 400 ci-dessus) | ❌ « mauvais `--tokenizer-mode` » |
| aucune fuite de `[TOOL_CALLS]` / JSON brut dans `content` | ❌ « parser absent / `--enable-auto-tool-choice` oublié » — un parser **est** actif, il avale |
| extraction non-streaming correcte | ❌ « mauvais `--tool-call-parser` » — le parser correspond bien au modèle |
| `required`/nommé streament, **y compris 2 appels parallèles** (`get_weather` + `get_time`) | ❌ « la machinerie d'émission SSE est cassée » — elle fonctionne |

**Il ne reste aucun drapeau de lancement dont le changement réparerait le streaming
sans casser ce qui marche.** Ce qui est défaillant est du **comportement de code** :
la branche streaming du parser Mistral, et le `finish_reason`.

### 9.2 Le signal qui pointe vers la version

Le plus parlant n'est pas le bug lui-même mais **l'anomalie sur le chemin qui marche** :

| | tool calls streamés ? | `finish_reason` |
|---|---|---|
| `Devstral-Small`, `required` | ✅ oui | 🔴 **`stop`** |
| `Qwen3.6-27B-ChapsVision`, `auto` | ✅ oui | ✅ `tool_calls` |

Devstral renvoie `finish_reason: stop` **alors même qu'il vient d'émettre des
`tool_calls`**. C'est non conforme à la spec OpenAI, c'est indépendant du parser `auto`,
et le voisin Qwen **sur le même hôte** le fait correctement. Deux défauts distincts sur
la même plomberie tool-calling, tous deux corrigés dans vLLM au fil des versions, et un
voisin sain : le faisceau penche nettement vers **un vLLM plus ancien sur ce
déploiement-là**.

### 9.3 Les deux mesures à faire avant de bumper

1. **La version de vLLM des DEUX déploiements** (`GET /version` sur le serveur vLLM, ou
   le tag de l'image) — Devstral **et** un des Qwen qui fonctionnent.
   - Qwen plus récent → la cause est très probablement là ; aligner Devstral sur la
     même version est le geste évident.
   - Versions identiques → ce n'est pas « une version en retard » mais le **chemin
     parser Mistral** en particulier ; il faut alors viser une release qui corrige
     nommément ce point, sinon le bump ne changera rien.
2. **La ligne de lancement** : confirmer `--enable-auto-tool-choice`,
   `--tool-call-parser mistral`, `--tokenizer-mode mistral`.

Puis, après bump : **`model-probe --only tools` rejoue le verdict en 30 secondes**, et il
est binaire. C'est aussi le garde-fou contre une régression dans l'autre sens — le parser
Mistral de vLLM a cassé **et** reparé plusieurs fois ; une montée de version n'est pas
gratuite sur un modèle en production.

### 9.4 Ce qui débloque les utilisateurs sans attendre l'infra

Le non-streaming est sain. **`disable_streaming` pour ce modèle côté omnis** rend
Devstral-Small utilisable immédiatement, c'est réversible d'une ligne, et ça ne dépend
d'aucune décision infra. Coût : plus de rendu token-par-token pour ce modèle.

### 9.5 Deux constats annexes de ce test

- **La boucle agent est touchée à tous les tours, pas seulement au premier.** Au 2e tour
  (après un `role:tool`), en streaming `auto`, le modèle répond en prose et n'appelle
  jamais `get_time` ; la même conversation en non-streaming renvoie
  `finish_reason=tool_calls` + `get_time`. *(Contrairement au 1er tour, les sorties
  diffèrent ici en nombre de tokens — c'est cohérent avec le bug, pas une preuve au même
  titre que la mesure à 12 tokens de §2.)*
- **Contrainte d'ID à connaître : les 9 derniers caractères du `tool_call_id` doivent
  être alphanumériques.** Mesuré : `gt9fPERuj` (généré par le serveur) ✅,
  `ABC123xyz` ✅, `call_abcdefghijklmnop` ✅ (seuls les 9 derniers comptent),
  `call_1` 🔴 (trop court), **`chatcmpl-tool-9f3a2b1c` 🔴** — or c'est le format d'ID
  que génèrent par défaut vLLM et plusieurs stacks OpenAI-compatibles. omnis réutilise
  l'ID renvoyé par le modèle, donc la boucle normale passe ; mais **tout client qui
  fabrique ou réécrit des `tool_call_id`** (compaction d'historique, rejeu, framework
  d'agents) se prendra un 400 contre ce modèle.
