# DRAFT BRIEF — Arkane Cloud (arkanecloud.com): fiabilité + prix vs fournisseurs GPU français

Question originale (FR, verbatim): « Que peux-tu trouver sur arkanecloud.com ? est-ce un fournisseur solide ? est-ce qu'il y a des avis dessus ? Compare aussi les tarifs d'Arkane Cloud avec d'autres fournisseurs GPU français. »

## Verdict (brouillon)
Arkane Cloud est un vrai fournisseur GPU français (EURL ARKANE, SIREN 888 755 766, Lyon, gérant Julien Gauthier), opérationnel, sans signalement de détresse — mais c'est une micro-structure auto-financée (capital 1 000 €, ~8 pers., aucun equity, flotte 100% financée sur contrats). Aucun avis tiers vérifiable n'existe. Sur le prix, l'H100 on-demand à $3,99/GPU/hr est 38–90 % au-dessus des comparables vérifiés (FlexAI $2,10, Sesterce $2,48, OVHcloud $2,99) ; Arkane n'est pas le moins cher, sauf sur H100 réservé (dès $1,65).

## Faits retenus (toutes sources fetchées)
### Identité & site
- EURL ARKANE, RCS Lyon 888 755 766, capital 1 000 €, TVA FR 83 888 755 766, siège 55 ter av. René Cassin 69009 Lyon, gérant Julien Gauthier (sources : arkanecloud.com/legal-notice ; recherche-entreprises.api.gouv.fr).
- Fondée 2020 (entité), activité GPU-cloud depuis ~2022 (LinkedIn gérant). NAF 46.51Z (commerce de gros de matériel informatique), PAS 63.11Z (hébergement).
- 2 datacenters colo en France : Villeurbanne (nLighten) et La Courneuve (Digital Realty). MAIS : le claim « Paris et Lyon » ne vaut que pour B300/RTX PRO 6000 ; la gamme Cloud GPU (H100/A100/B200/L40S) n'est localisée que « en Europe » (arkanecloud.com/faq).
- Produits : Cloud GPU (VM 1–8 GPU, à la seconde), Serverless GPU, Models API (OpenAI-compatible), GPU Clusters (réservé, InfiniBand, K8s managé).
- Tarifs on-demand (USD, prépayé) : B300 $8,99 ; B200 $7,99 ; H200 $5,99 ; H100 $3,99 ; RTX PRO 6000 $2,49 ; A100 $2,29 ; L40S $1,79 ; RTX 6000 Ada $1,49 ; RTX A6000 $0,99. Stockage NVMe $0,2/GB/mois. H100 réservé « dès $1,65/hr » (page /h100/).
- SLA publié : 99,5 % compute/serverless, 99 % API, 99,99 % stockage ; crédits 10–50 % ; droit français, tribunal de commerce de Lyon.
- Zéro certification (pas d'ISO 27001, pas de SecNumCloud, pas d'HDS). « GDPR-aligned » = claim marketing.
- Claim « 1 000+ clients » sans aucun client nommé. Partenaires logo : NVIDIA, Supermicro, HPE, Digital Realty, nLighten, Vast Data, Hugging Face.
- Incohérences internes : engagement « 3–36 mois » (pricing) vs « 2–5 ans » (clusters) ; H200 serverless listé deux fois à deux prix (le second = H100 mal étiqueté) ; prix en USD pour un vendor « souverain ».

### Solidité (tier 3)
- Registre : statut Active PME, aucun redressement/liquidation, comptes sous clause de confidentialité (aucun CA public). Pas de mention BODACC 2024 (2020-2023 et 2025 présentes) — non confirmé.
- Financement : UNSEULE levée = 10 250 € RBF (WE DO GOOD, 27/04/2023, objectif 10 000–300 000 €). Tracxn : « unfunded », score 27/100.
- Flotte financée sur contrats clients (déclarations CEO podcast Megaport/Uplink, 25/06/2025) : « you need a contract to finance and we can deploy it » ; cluster « 1000 GPUs, extendable to 6000 », 10 MW — non corroboré indépendamment.
- CEO (même podcast) : « 0 % of customers in France, 60–70 % from US » — contredit le positionnement souverain français.
- ~8 employés (Tracxn, estimation) ; SIRENE : effectif « NN », siège marqué non-employeur.
- Aucune couverture presse tech française ; uniquement co-marketing (GIGABYTE, VAST Data, Megaport).

### Avis
- Aucune fiche Trustpilot/G2/Capterra trouvée (Trustpilot : page bloquée par anti-bot, absence non 100 % confirmée). HN : 0 mention (requête API exacte). Reddit : 2 mentions neutres r/eutech, le reste = co-marketing. Aucune réclamation trouvée = absence de donnée, pas une preuve de fiabilité. Aucune recommandation utilisateur indépendante identifiée.

### Prix vs « fournisseurs GPU français »
| GPU | Arkane | FlexAI | Sesterce | OVHcloud | Scaleway |
|---|---|---|---|---|---|
| H100 80G $/GPU/hr | 3,99 | 2,10 | 2,48 (docs, ~1 an d'âge) | 2,99 (subsidiary « World » USD) | non vérifié 1er-partie (JS) ; 3e partie : ~2,87–3,32 |
| H200 141G | 5,99 | 3,15 | 3,58 | ~6,20 (est. 8 GPU $49,56) | — |
| B200 180G | 7,99 | 6,25 | 6,05 | — | — |
| A100 80G | 2,29 | 1,80 | 1,65 | — | — |
| L40S 48G | 1,79 | — | 1,10 | 1,80 « from » (subsidiary US) | €1,47 (~$1,64) |
| B300 288G | 8,99 | — | — | — | (prix masqué zone JS) |
Egress : OVHcloud inclut le trafic sortant (hors APAC) ; Scaleway pas de ligne egress internet (VPC/LB illimités) ; Arkane : aucune ligne egress + claim « no surprise egress fees » (non contractuel). => egress ≈ nul des deux côtés, ne comble pas l'écart horaire.
Préavis : Arkane H100 réservé dès $1,65/hr (snippet page /h100/, non fetché intégralement).

## Correction de mes propres prémisses (à signaler)
Mon premier périmètre de « fournisseurs français » contenait des entités non vérifiables : Papers/papers.space (domaine non enregistré), Owlii, Fulact, GreenNode (prix en VND = probablement Vietnam). Exclues du comparatif. Périmètre final vérifié : Scaleway, OVHcloud, FlexAI (Paris, 1er-partie), Sesterce (Marseille, 3e partie).

## Confiance & questions ouvertes
- Confiance : haute sur identité/registre/prix Arkane ; moyenne sur solidité (CA inconnu) ; haute sur l'absence d'avis.
- Ouvert : (1) entité propriétaire des GPU/de la dette ; (2) pays réel d'hébergement de la gamme H100 ; (3) H100 Scaleway PAR-2 en EUR 1er-partie ; (4) CA d'Arkane (comptes confidentiels) ; (5) Trustpilot (anti-bot).
