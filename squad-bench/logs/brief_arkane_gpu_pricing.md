# Brief — GPU pricing comparison: Arkane Cloud vs French GPU cloud providers

## Context
Due diligence on Arkane Cloud (arkanecloud.com, French EURL, Lyon). Already fetched from arkanecloud.com/pricing/ (first-party, USD, billed per second):

| GPU | On-demand $/GPU/hr |
|---|---|
| B300 (288 GB) | 8.99 |
| B200 (180 GB) | 7.99 |
| H200 (141 GB) | 5.99 |
| H100 (80 GB) | 3.99 (multi-GPU: 2x=7.98, 4x=15.96, 8x=31.92/hr) |
| RTX PRO 6000 (96 GB) | 2.49 |
| A100 (80 GB) | 2.29 |
| L40S (48 GB) | 1.79 |
| RTX 6000 Ada (48 GB) | 1.49 |
| RTX A6000 (48 GB) | 0.99 |

Reserved H100 "from $1.65/hr/GPU" (quote-based clusters 2–5 yr). NVMe storage $0.2/GB/mo. CPU from $0.16/hr.

## Your task
Fetch the CURRENT public GPU pricing (as of today) of French GPU cloud providers, from each provider's own pricing page where possible, and build a per-GPU-model comparison table against Arkane Cloud's numbers above.

Providers to cover (French-headquartered; note any that are not actually French-headquartered if you find otherwise):
1. **Scaleway** (scaleway.com) — GPU instances: L40S, H100, A100 if available. Instance-level prices (include egress/transfer costs if listed).
2. **OVHcloud** (ovhcloud.com) — GPU public cloud instances (L40S, H100 if available) and dedicated GPU servers; note hourly vs monthly.
3. **Papers** (papers.space) — H100 pricing (on-demand, spot if listed).
4. **Owlii** (owlii.com) — GPU fleet prices (H100, A100, B200 if listed).
5. **Fulact** (fulact.com) — H100/B200 if listed.
6. **GreenNode** (green-node.com) — French neocloud; H100/B200 prices if public (may be quote-only — say so).
7. **Inference.net** (inference.net) — French (Paris); H100 prices if public.

For each provider report:
- Price per GPU per hour (convert monthly prices to hourly: /730) and the currency
- GPU models offered
- Spot/preemptible prices if published
- Egress / data transfer fees (per GB) if listed — important for the comparison
- Whether datacenters are in France/EU
- Source URL for each price

Deliverable: (1) the comparison table aligned on GPU model and $/hr (convert EUR→USD at the live rate you find, state the rate), (2) a short paragraph on where Arkane is cheapest/most expensive per model, (3) notes on egress fees and reservation discounts that change the real cost.

Every price must carry its source URL and the date fetched. If a provider has no public pricing (quote-only), say so explicitly — do not estimate.
