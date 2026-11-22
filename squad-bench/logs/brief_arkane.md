# Draft brief — Arkane Cloud : solidité + comparatif tarifaire GPU France

Original user question (verbatim, French): "Que peux-tu trouver sur arkanecloud.com ? est-ce un fournisseur solide ? est-ce qu'il y a des avis dessus ? Compare aussi les tarifs d'Arkane Cloud avec d'autres fournisseurs GPU français."

## 1. Identity (fetched from arkanecloud.com/legal-notice/, /about-us/, press)
- Legal entity: ARKANE, EURL (single-shareholder SAS-like micro-form), capital 1,000 EUR. RCS Lyon 888 755 766. HQ: 55 ter av. René Cassin, 69009 Lyon. Founded 2020, CEO Julien Gauthier.
- Positioning: "Sovereign AI Cloud", own infrastructure (not reselling hyperscaler). Datacenters: Lyon (nLighten colo) + Paris/La Courneuve (Digital Realty colo).
- Products: Models API (per token), Serverless GPU (per second, scale-to-zero), Cloud GPU (per second, SSH), GPU Clusters (reserved).
- GPU lineup claimed: B300 (288 GB), B200, H200, H100, A100, L40S, RTX PRO 6000, RTX 6000 Ada, RTX A6000. Cluster: 1,000 GPU deployed, expandable to 6,000 (liquid cooling, 135 kW/rack).
- Partners claimed: NVIDIA, Supermicro, HPE, Digital Realty, nLighten, VAST Data (official VAST press release), PNY, Hugging Face, Megaport, Equinix.
- SLA public page: Compute/Serverless 99.5%, Storage 99.99%, inference API 99%; service credits 10/25/50%, capped 50%.

## 2. Solidity signals
- POSITIVE: own hardware, major partners (VAST Data press release is third-party verifiable), public detailed SLA, Blackwell available early, 60-70% of clients US (Megaport interview), active recruiting, FRnOG presence, Hugging Face org page.
- RISK: capital social 1,000 EUR; no public funding round found (Tracxn: "has not raised any funding rounds yet"); team 2-10 (Les Pépites Tech, 2023) vs 8-10 (2026 sources); NO ISO 27001 / SOC 2 / HDS certification found anywhere; no published real uptime figures (they claim a public status page — not independently verified).
- UNRESOLVED: how the 1,000-GPU build is financed; exact current headcount; whether status page exists and what it shows.

## 3. Reviews / reputation
- NO customer reviews exist anywhere: 0 reviews on Les Pépites Tech, no Trustpilot/G2/HN/Glassdoor customer pages, no complaints found, no Reddit organic discussion (only PR cross-posts of the same VAST Data sentence in unrelated subreddits — possibly spam).
- Only neutral mentions: r/eutech lists ("another competitor", "European neocloud"); Machine Relations Index: 0.01% citation rate, #113/361 in AI infrastructure (very low visibility).
- Interpretation: B2B/enterprise, early-stage, under-the-radar; absence of reviews is a finding, not evidence of quality either way.

## 4. Arkane pricing (fetched from arkanecloud.com/pricing/ + FAQ; USD, billed per second, prepaid credit, no minimum)
- RTX A6000 $0.99/h | L40S $1.79/h | A100 $2.29/h | H100 $3.99/h | H200 $5.99/h | B200 $7.99/h | B300 $8.99/h (cloud GPU); serverless +10-15% (B300 $9.99/h).
- No spot pricing published. Egress: homepage claims "no surprise egress fees" but NO published rate (unverified). Storage NVMe $0.20/GB/month. CPU from $0.16/h.
- Third-party (AIMiningCo, snippets only, page blocked): Arkane H200 ~2.2x and L40S ~2.8x the cheapest marketplace alternatives (Nebius, Vast.ai etc.) — i.e. premium vs global GPU marketplaces, not necessarily vs France.

## 5. French competitors (fetched official pages)
OVHcloud (Gravelines, FR; per-hour billing; no egress in EU; Savings Plans -15%/-30%):
- L40S $1.80/h | H100 PCIe $2.99/h | A100 $3.07/h | H200 (8x node) $6.20/GPU/h | no Blackwell.
Scaleway (PAR-2, FR; per-minute billing; GPUs NOT eligible for savings plans; no egress; 99.5% SLA):
- L4 €0.79/GPU/h | L40S €1.46-1.47/GPU/h | H100 PCIe €2.86/GPU/h | H100-SXM €6.61/GPU/h | B300-SXM €7.50/GPU/h | no A100, no H200.
- Source: scaleway.com/en/choose-the-right-gpu/ (official).
Market: French commercial GPU cloud ≈ OVHcloud + Scaleway + Arkane (Vexxhost excluded — no FR datacenter, no public GPU per-GPU price list).

## 6. Price deltas vs Arkane (approx EUR: $1 ≈ €0.92-0.95, early 2026)
- H100: Arkane $3.99 (~€3.7-3.8) vs OVH $2.99 (~€2.8) vs Scaleway €2.86 (PCIe) / €6.61 (SXM) → Arkane ~15-40% above OVH/Scaleway PCIe, below SXM.
- L40S: Arkane $1.79 vs OVH $1.80 vs Scaleway €1.46 → Arkane near-parity with OVH, ~20% above Scaleway.
- A100: Arkane $2.29 vs OVH $3.07 → Arkane ~25% cheaper (only OVH offers A100 among French).
- H200: Arkane $5.99 vs OVH $6.20 → near parity (OVH is 8-GPU node figure).
- B300: Arkane $8.99 vs Scaleway €7.50 → Arkane ~15-20% above; OVH not available.
- Billing: Arkane per-second (finest), Scaleway per-minute, OVH per-hour. None of the three offer spot.
- Currency: Arkane bills in USD from a French company (FX nuance for EU buyers); FR peers bill EUR.

## 7. Draft verdict (to be reviewed)
Arkane is a real, young (2020), small (≤10 people), French sovereign GPU provider with genuinely own infrastructure and early Blackwell, but weak financial transparency (1k EUR capital, no public funding, no ISO 27001/SOC 2) and zero customer reviews. Technically credible for short/experimental workloads and Blackwell access; for long-term enterprise commitment, require proof of finances/certifications. Pricing: mid-to-premium vs France — cheaper than OVH on A100, parity on H200/L40S, ~15-40% above OVH/Scaleway on H100, ~15-20% above Scaleway on B300; per-second billing is a real advantage for short jobs; no spot anywhere in France; egress policy unverified.

## Open questions
1. Funding source for the 1,000-GPU build (no public round found).
2. Does the public status page exist; what is real uptime history? (claim unverified)
3. Egress fees: "no surprise egress" claim, no published rate.
4. OVH H200 $6.20 figure is per-GPU on an 8-GPU node — confirm per-GPU granularity before using in delta.
5. Scaleway B300 €7.50/GPU/h: is the 8-GPU node mandatory? (multi-GPU minimums unconfirmed)
