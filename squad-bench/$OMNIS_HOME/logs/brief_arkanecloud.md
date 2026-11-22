# DRAFT — Arkane Cloud (arkanecloud.com) : fiabilité, avis, comparatif tarifaire GPU France
Date de recherche : 31/10/2026. Toutes les données ci-dessous proviennent de pages récupérées en session.

## 1. Identité (vérifiée via mentions légales du site)
- ARKANE (EURL), RCS Lyon 888 755 766, TVA FR 83 888 755 766, siège 55ter av. René Cassin, 69009 Lyon. Gérant : Julien Gauthier.
- Création INSEE 30/07/2020 (site revendique « founded in 2020 ») ; domaine arkanecloud.com enregistré octobre 2022. Capital social : 1 000 € (minimum légal).
- Sans lien avec Arkane Studios (studio de jeux vidéo, filiale Microsoft/Zenimax) — le site explique lui-même l'étymologie du nom.
- Pas de levée de fonds trouvée (Tracxn : « unfunded »). Comptes annuels « sous clause de confidentialité » (societe.com) ; CA non public. Effectif : 11–50 (LinkedIn).
- DC : Villeurbanne (colocation nLighten) + La Courneuve/Paris (Digital Realty). Partenaires cités : NVIDIA, Supermicro, HPE, Vast Data, Hugging Face, Megaport.
- GPU au catalogue : B300, B200, H200, H100, A100, L40S, RTX PRO 6000, RTX 6000 Ada, RTX A6000.
- Un cluster « ~1000 GPU » en construction à Paris annoncé par le CEO (interview Megaport) ; capacité revendiquée jusqu'à 6000 GPU.

## 2. Avis / réputation
- ZÉRO avis indépendants trouvés sur : Trustpilot, G2, TrustReviews (0), Qudata.ai (0), viabandwidth (« None yet »), Hacker News (0), Reddit (2 seules auto-promos du fondateur, mars 2024), X, forums FR, presse FR (aucun article trouvé chez Les Echos/01net/NextINpact/Silicon.fr — recherche limitée par bot-protection, à nuancer).
- Scamadviser : « Very Likely Safe » (SSL DigiCert valide ; réserves : WHOIS masqué, faible trafic).
- Aucune plainte trouvée non plus — mais l'absence de plainte est probablement un reflet de la petite base clients, pas une preuve de fiabilité.
- Pas de rapport de panne / incident public trouvé.
- Uniques éloges : contenu auto-publié (blog) + interview promotionnelle (podcast Megaport).

## 3. Tarifs Arkane (page https://arkanecloud.com/pricing/, « Prices in USD », facturation à la seconde)
| GPU | $/h on-demand |
|---|---|
| B300 (288 GB) | 8,99 |
| B200 (180 GB) | 7,99 |
| H200 141 GB | 5,99 |
| H100 80 GB | 3,99 |
| RTX PRO 6000 Blackwell | 2,49 |
| A100 80 GB | 2,29 |
| L40S | 1,79 |
| RTX 6000 Ada | 1,49 |
| RTX A6000 | 0,99 |
- Serverless : +~1$/h vs on-demand (B300 9,99, H200 6,99, L40S 1,99…), scale-to-zero.
- Clusters réservés : 2–5 ans, prix sur devis uniquement.
- API LLM : ex. Llama 3.3 70B 0,70$/M tokens ; DeepSeek-V4-Flash 0,20$/M.
- Stockage NVMe : 0,20 $/GB/mois. Pas de prix egress publié (« no surprise egress fees » = marketing, pas de garantie chiffrée).
- Gratuit : playground 10 requêtes / 10 jours, sans CB.

## 4. Concurrents FR (prix récupérés en session, $/GPU-h on-demand)
| GPU | Arkane | OVHcloud (Gravelines) | Scaleway (PAR) | Exoscale (via getdeploying, 31/10/2026) |
|---|---|---|---|---|
| H100 | 3,99 | 2,99 | 2,86 € (~3,18 $) | non listé |
| A100 80G | 2,29 | 3,07 | — | non listé |
| L40S | 1,79 | 1,80 | 1,47 € (~1,62 $) | non listé |
| H200 | 5,99 | 49,56 $/8 = 6,20 | — | — |
| B300 | 8,99 | non listé | ~7,50 $/GPU (8×) | sur devis |
| RTX PRO 6000 | 2,49 | — | — | 2,00–2,15 |
- Mistral AI « Compute » : pas de prix public (sur demande, réservé entreprise).
- IA Parc : domaines iaparc.com/.fr ne résolvent pas (DNS échec) — pas de prix public vérifiable ; signal faible d'accessibilité.
- Exoscale ne liste ni L40S ni A100 actuellement (source 3e parti) ; prix RTX PRO 6000 plus bas qu'Arkane.

## 5. Synthèse provisoire
- Solidité : entité légale réelle (2020, 11–50 salariés, infra physique propre, partenaires sérieux NVIDIA/Supermicro/Digital Realty/Vast) MAIS capital 1000 €, non financé, CA opaque, zéro avis client public, zéro couverture presse FR trouvée. Profil « bootstrapped mid-size opérateur » — crédible mais plus risqué qu'OVHcloud (groupe coté) ou Scaleway (bien capitalisé).
- Prix : compétitifs sur A100/L40S vs OVH (A100 2,29 vs 3,07), plus chers que Scaleway sur H100 (3,99 $ vs ~3,18 $), parmi les plus bas sur RTX PRO 6000. Les GPU nouvelle génération (B200/B300/H200) sont un vrai différenciateur : OVH n'a que H200, Scaleway a B300.
- Verdict provisoire : fournisseur réel et sérieux sur le papier, « souveraineté FR + GPU Blackwell à prix agressifs » est sa niche ; le risque = taille/capital et absence totale de preuve sociale. À tester via le playground gratuit + petit engagement avant engagement 2–5 ans.

## Open questions
1. CA réel et santé financière (comptes confidentiels).
2. Pression sur le réseau 200/100 Gbps — jamais vérifiée indépendamment.
3. SlA réel et expérience support — aucune donnée indépendante.
