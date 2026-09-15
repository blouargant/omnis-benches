# Cache de prompt DeepSeek/Scaleway : enquête sur le taux de hit erratique

**Date** : 2026-09-15
**Question** : le cache de préfixe de `deepseek-v4-flash-0731` paraît aléatoire (~50%).
Y a-t-il un vrai défaut côté endpoint Scaleway, et comment l'établir rigoureusement ?
**Méthode** : `superpowers:systematic-debugging` — cause racine avant tout correctif.

---

## 1. Verdict

**Non, il n'y a pas de défaut de l'endpoint Scaleway.** Le comportement mesuré est
*exactement* dans l'enveloppe que Scaleway documente, et cette enveloppe est
explicitement non garantie.

**Mais il y a bien un problème réel — ailleurs** : sur charge omnis, le taux de cache
effectif est de **3,7%**, soit plus d'un ordre de grandeur sous la bande documentée.
La cause est **structurelle** (le motif d'accès d'omnis), pas un bug.

## 2. Ce que Scaleway documente (verbatim)

> « Scaleway caches tokens automatically, using heuristics that **optimize both
> throughput and availability**. »
> « the platform persists the cache automatically and **evicts it based on request
> frequency** »
> « For workloads with recurring prefixes, such as conversational or agentic use cases,
> you can expect a **cache hit ratio between 50% and 90%, though this value is not
> guaranteed** »
> « Cache is isolated per project »

Pour les *Dedicated Deployments* : « The input cache is **fully dedicated to your usage
and included in the price**. »

Deux mots règlent la question : *heuristics* optimisant la **disponibilité** (donc le
routage de charge prime sur l'affinité de cache) et *eviction based on request
frequency* (donc un préfixe peu répété est le premier évincé).

## 3. Mesures

Préfixe unique par expérience (nonce) ⇒ départ garanti à froid. Rail **Scaleway
direct**, pour sortir la gateway de l'équation.

| Expérience | Résultat |
|---|---|
| **A** — 24 appels consécutifs, même préfixe | 11/24 (46%) — `........HH...HH..HHHHHHH` |
| **B/W** — 40 appels consécutifs | 24/40 (60%) — fenêtres de 10 : **6, 5, 7, 6** |
| **B/P** — 10 appels après **5 min** d'inactivité | 4/10 — pas de purge par TTL court |
| **B/C** — 8 appels **en parallèle** | 5/8 |
| **B/T** — 10 appels séquentiels **juste après la rafale** | **9/10** |

**Il n'y a pas de courbe de chauffe qui converge vers 100%** : le taux **plafonne vers
60%** et y reste (6, 5, 7, 6 sur quatre fenêtres consécutives). Lu sur les 24 appels de
l'expérience A seule, on croit voir une montée (2/12 puis 9/12) — c'est une illusion
d'échantillonnage que les 40 appels de B démentent. *Première leçon de méthode : 24
appels ne suffisaient pas.*

**La rafale parallèle est le seul levier trouvé** : 8 appels simultanés chauffent
plusieurs replicas d'un coup, après quoi le séquentiel monte à 9/10 — le haut de la
bande documentée.

### Corroboration indépendante par la latence

`x-envoy-upstream-service-time` (chrono serveur, hors réseau) confirme que la
télémétrie ne ment pas — un hit saute réellement le prefill :

| | médiane | minimum |
|---|---|---|
| appels `cached_tokens > 0` | 421–1569 ms | **318 ms** |
| appels `cached_tokens = 0` | 1032–2786 ms | **681 ms** |

Aucun miss n'est jamais descendu sous 681 ms ; les hits descendent à ~320 ms.

Le volume caché est **quantifié par blocs de 128 tokens** (13312 = 104×128,
11520 = 90×128) : quand ça cache, ça cache tout le préfixe, jamais une fraction.

## 4. L'écart omnis : 3,7%

Taux réel mesuré sur le bras DeepSeek de squad-bench (`cache_read_tok / prompt_tok`) :

| tâche | agent | calls | prompt_tok | cache_read | ratio |
|---|---|---|---|---|---|
| search-single | coder | 2 | 17117 | 0 | 0% |
| search-single | code_scout | 4 | 10454 | 0 | 0% |
| search-multi | coder | 2 | 33765 | 0 | 0% |
| search-multi | code_scout | 7 | 27801 | 6656 | 23,9% |
| symbol-fields | coder | 2 | 33097 | 0 | 0% |
| symbol-fields | code_scout | 3 | 11506 | 3328 | 28,9% |
| docs-lookup | coder | 2 | 34007 | 0 | 0% |
| docs-lookup | code_docs | 6 | 99834 | 0 | 0% |
| **TOTAL** | | | **267581** | **9984** | **3,7%** |

**Cause : le nombre d'appels par préfixe.** Mes expériences martèlent le *même* préfixe
20 à 40 fois — c'est ce qui permet d'atteindre 60%. omnis, lui, n'envoie un préfixe
donné que **2 à 7 fois**, puis ne le revoit jamais : chaque agent a son instruction et
son jeu d'outils, chaque tâche son énoncé. Avec 2 appels (`coder`, systématiquement),
il n'y a qu'**une seule** occasion de hit, qui ne se produit que si le second appel
retombe sur le replica du premier — et aucune accumulation de couverture n'est
possible. `coder` fait 0/4 ; `code_scout`, avec 3 à 7 appels, touche sur 2 tâches sur 3.
Le motif suit exactement le nombre d'appels.

La bande 50-90% de Scaleway vise des « recurring prefixes » **à volume**. Une session
d'agent courte avec un préfixe neuf n'est pas ce cas — et l'éviction « based on request
frequency » achève le peu qui aurait pu tenir.

Coût : à 3,7% l'input réel coûte **$0,1090** là où 50% donnerait $0,0674 (**+62%**) et
90% donnerait $0,0315 (**+246%**).

## 5. Une hypothèse séduisante — testée et RÉFUTÉE

En interposant un proxy journalisant les requêtes réellement émises par omnis, on
observe que le préfixe commun entre deux appels consécutifs d'un même agent ne fait que
**54 à 68%** des octets, alors que `system` et `tools` sont identiques. Cause :
`core/llm/openai.go:296` —

```go
func markCacheablePrefix(msgs []oaiMessage) {
	if msgs[0].Role == "system" { markMessageCacheable(&msgs[0]) }
	markMessageCacheable(&msgs[len(msgs)-1])   // le DERNIER message
}
```

`markMessageCacheable` **convertit une chaîne en liste** pour y loger le marqueur. Le
marqueur suivant le dernier message, celui du tour précédent **redevient une chaîne** :

```
0003:  syst:L*  user:L*
0004:  syst:L*  user:S   assi:S  tool:L*     <- user est passe de L a S
```

Ça *ressemble* à une destruction du préfixe. **Ce n'en est pas une.** Test discriminant
(expérience C) — chauffer en forme STRING, puis basculer en forme LISTE :

| phase | forme | hits |
|---|---|---|
| 1. chauffe | STRING | 7/20 (35%) |
| 2. bascule | **LISTE** | **7/12 (58%)** ← hérite du cache chauffé en STRING |
| 3. retour | STRING | 7/10 (70%) |
| 4. | LISTE | 7/10 (70%) |

La phase LISTE **ne repart pas à froid** : elle hérite. Et `prompt_tok` est identique à
±2 près (13628 / 13627 / 13626 / 13627). Les deux formes **tokenisent pareil** — le chat
template normalise les content-parts, et `cache_control` (convention Anthropic) est
**inerte** sur cet endpoint.

**Conclusion : le diff octet était un faux positif.** J'avais comparé du JSON, pas des
tokens. Les marqueurs `cache_control` d'omnis sont sans effet ici — ni utiles, ni
nuisibles. À ne pas ré-instruire.

## 6. Comment l'établir correctement (la méthode)

Ce qu'il faut faire pour que la mesure veuille dire quelque chose :

1. **Préfixe unique par expérience** (nonce dans le texte), sinon on hérite d'un état
   chauffé par une mesure précédente et on croit mesurer un départ à froid.
2. **≥ 20 appels** avant d'annoncer un taux. À 6 appels le résultat va de 0% à 100%
   selon l'endroit où l'on tombe — j'ai moi-même lu « 0/3 gateway vs 1/3 direct » et
   failli écrire « la gateway casse le cache », avant que 6 appels par rail ne donnent
   3/6 des deux côtés.
3. **Publier la SÉQUENCE, pas le pourcentage** (`...HH.HHHH`). Un taux nu cache la
   structure temporelle, qui est toute l'information.
4. **Corroborer par `x-envoy-upstream-service-time`**, indépendant de `cached_tokens` :
   si un « miss » est aussi rapide qu'un hit, c'est la télémétrie qui ment, pas le
   cache qui manque. (Vérifié ici : elle ne ment pas.)
5. **Mesurer le ratio qui compte** : `cache_read_tok / prompt_tok` sur la charge réelle,
   pas sur un préfixe martelé synthétiquement. Les deux chiffres diffèrent d'un facteur
   16 (60% contre 3,7%).
6. **Ne comparer que des rails** : gateway vs provider direct, même préfixe, même taille
   d'échantillon.

Scripts de mesure : `exp_c.py` et les variantes A/B (scratchpad de la session). À
promouvoir en outil du repo s'il faut suivre ça dans la durée.

## 7. Leviers

- **Rien à corriger côté omnis** — la sérialisation est hors de cause, et le motif
  d'accès (préfixe neuf par agent/tâche) est inhérent à ce qu'est un squad.
- **Déploiement dédié** : c'est la réponse documentée par Scaleway si l'économie de
  cache compte (« cache fully dedicated to your usage and included in the price »).
- **À l'échelle de la flotte**, le tableau s'améliore tout seul : plusieurs sessions
  concurrentes partageant l'instruction d'un même agent chauffent les replicas
  mutuellement — c'est exactement l'effet mesuré en B/T (9/10 après rafale parallèle).
  **Un run de bench isolé est donc le pire cas**, et sous-estime structurellement le
  cache de production.
- **Pour le benchmarking** : traiter ce cache comme un **facteur de confusion**, pas
  comme une propriété stable. Il fait varier le coût d'un même travail d'un facteur
  proche de 5 (0,42 vs 0,084 \$/M sur la part cachée) de façon non déterministe — c'est
  une source directe de la dispersion de 1,85x déjà documentée sur les mesures de coût.
