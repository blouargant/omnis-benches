# BRIEF — LMCache + vLLM for a GPTQ "Pro" Qwen3.6-27B on 2 GPUs (PCIe, no NVLink)

## Original question
"Is it interesting to use LLM Cache with vLLM for a Quantized Qwen3.6 27B GPTQ Pro model that run on 2 GPUs (no nvlink) on the same host? What are the pros and cons? Is there a known bug of using lmcache with Qwen3.6-27B model?"

## 1. Verdict
**Yes, it is "interesting" — but only if your workload has repeated prefixes (multi-turn, RAG, agents) AND your KV working set exceeds what fits on the GPU(s).** As of **LMCache 0.5.6 (Oct 15, 2026) + a recent vLLM (not 0.26.x)**, Qwen3.6-27B is an *officially validated* LMCache model with real prefix reuse (attention KV **and** Gated-DeltaNet state). If your traffic is single-shot unique prompts, or your working set fits in GPU KV (vLLM's native prefix caching already handles it), LMCache adds PCIe-transfer and operational overhead for little. The bigger decision lever on your box is **which 2-GPU topology you run** (TP=2 vs PP=2 vs DP=2 over PCIe) — that choice can matter more than the cache layer.

## 2. Premise check — what we challenged in your question
1. **"Qwen3.6 27B" is real, but it is a HYBRID model.** `Qwen/Qwen3.6-27B`: 64 layers, **48 Gated-DeltaNet linear-attention + 16 full-attention** (3:1), 262K context, multimodal (arch `Qwen3_5ForConditionalGeneration`) ([HF model card](https://huggingface.co/Qwen/Qwen3.6-27B), [vLLM Qwen3-Next support blog](https://vllm.ai/blog/2025-09-11-qwen3-next)). This single fact drives most of the LMCache caveats below.
2. **"GPTQ Pro" is a community label, not a quantization format** (publisher `groxaxo`, GPTQModel/FOEM quants, served with `--quantization gptq_marlin`). vLLM fully supports GPTQ in v0.33.0 (latest); not deprecated ([RFC #30136](https://github.com/vllm-project/vllm/issues/30136) defers deprecation — "too many models exist"). vLLM warns "GPTQ is not fully optimized" ([#9240](https://github.com/vllm-project/vllm/issues/9240)) — the GPTQ kernel path is slower than FP8/Marlin-native.
3. **2 GPUs are not needed for the weights.** 4-bit 27B ≈ 17–18 GB weights → fits one GPU. Your second GPU buys KV-cache headroom / concurrency. Your exact shape is in fact the one validated on the model card: `groxaxo/Qwen3.6-27B-GPTQ-Pro-4bit` is **test-verified on 2× RTX 3090, TP=2, `--disable-custom-all-reduce`, max-model-len 65536** (262K OOMs on 2×3090).
4. **TP=2 over PCIe is not the only — and per vLLM docs not the recommended — way to use 2 GPUs without NVLink.** vLLM docs: "if the GPUs on the node do not have NVLINK interconnect (e.g. L40S), leverage **pipeline parallelism instead of tensor parallelism** for higher throughput and lower communication overhead" ([parallelism_scaling](https://docs.vllm.ai/en/stable/serving/parallelism_scaling/)). Since vLLM 0.30/0.32, FlashInfer PCIe-IPC all-reduce (default in 0.32) recovers only ~5% step time on Gen4 (eurokommerz benchmark). **DP=2** (`--data-parallel-size 2 --tensor-parallel-size 1`) gives ~50% throughput at moderate concurrency with *zero* inter-GPU traffic if the model fits one GPU (JarvisLabs, Qwen3-32B on 2×A100). If you are on 24 GB cards, TP=2 is the only option that fits; if you have one 48 GB+ card, consider 1 GPU or DP.

## 3. What LMCache actually does for Qwen3.6-27B today (version-anchored)
- **Validated:** [docs.lmcache.ai/recipes/qwen3_5.html](https://docs.lmcache.ai/recipes/qwen3_5.html) lists `Qwen/Qwen3.6-27B (1 GPU, block size N=784) — Status: Validated with LMCache`. [hybrid_models page](https://docs.lmcache.ai/mp/hybrid_models.html): MP connector "stores and retrieves the KV cache for every group, so prefix caching and KV reuse work the same way they do for plain models."
- **Timeline:** early 2026 the hybrid guard forced 0% external hits (PR #2879); **Jun 16, 2026** announcement: Mamba/GDN state stored/retrieved as opaque pages → full reuse; **v0.5.6** (Oct 15, 2026) fixed full-hit Mamba checkpoint restoration ([#5249](https://github.com/LMCache/LMCache/releases)).
- **Evidence of real hits on this model:** [issue #4514](https://github.com/LMCache/LMCache/issues/4514) (Qwen3.6-27B, LMCache 0.5.3): prefix hit rate 60% → 80% with LMCache.
- **Required config:** `--enable-prefix-caching --mamba-cache-mode align --kv-transfer-config '{"kv_connector":"LMCacheMPConnector","kv_role":"kv_both"}'`; server: `lmcache server --chunk-size 784 --separate-object-groups --l1-size-gb <N>`.
- **Hybrid-specific constraints:** text-only validation (image/video KV not validated); CacheBlend/CacheGen/L2-serde **not supported**; not bit-exact on hits (score-level equivalence only); `align` mode is experimental upstream in vLLM.
- **Quantization angle:** N=784 page geometry is weight-quant-independent (derived from head dims + GDN state). LMCache stores KV at the **vLLM KV dtype** (bf16 by default), independent of GPTQ weight quant. **No report exists of the btbtyler09/groxaxo GPTQ checkpoints running with LMCache** — nearest evidence: `nvidia/Qwen3.6-27B-NVFP4` hit silent corruption on vLLM 0.26.0 (fixed [#4253](https://github.com/LMCache/LMCache/pull/4253), then verified 91.6% hit rate, issue #4247), and `RedHatAI/Qwen3.8-27B-INT4` (GPTQ-4bit, same arch) works in MP mode.
- **GPTQ note:** the GPTQ-Pro card keeps ViT + MTP at BF16 and `in_proj_a/b` at FP16 — weight-mixed, but KV geometry unchanged.

## 4. Pros (for this setup)
- Working set > GPU KV: L1 CPU-DRAM tier keeps evicted prefixes (LMCache benchmark: TTFT −75% on long-doc QA; MindStudio: >99% recovery vs 0% for GPU-only cache at overflow).
- Cache survives engine restart/crash (no fate-sharing).
- **DP=2 synergy:** with 2 replicas each having separate native APC, the per-node LMCache MP server (shared L1) lets replicas share cached prefixes over local DRAM — the natural companion to the topology switch in §2.4.
- L2 backends (Redis/S3/NIXL/FS) if you later go multi-node.

## 5. Cons (for this setup)
- If your working set fits GPU KV, LMCache mostly adds PCIe store/retrieve traffic, a separate daemon, ABI-matching burden (PyTorch/CUDA wheel alignment — see [#36771](https://github.com/vllm-project/vllm/issues/36771)), and ~20–30 s restart penalty (MindStudio).
- Hybrid-model bug surface is large and recent → you must pin versions and watch release notes.
- Not bit-exact on cache hits (GDN backends lack batch-invariant mode).
- Vision KV not validated — fine if you serve text-only.
- `#4514` also reports **max concurrent requests decreased** with LMCache on Qwen3.6-27B under load — a real throughput cost, not free.

## 6. Known bugs relevant to Qwen3.6-27B + GPTQ + LMCache
**No bug is filed as "Qwen3.6 + GPTQ + LMCache" specifically.** Relevant ones, nearest first:
- [#4247](https://github.com/LMCache/LMCache/issues/4247) (fixed #4253): silent multilingual-token-salad corruption on hybrids with vLLM 0.26.0 MP connector → **avoid vLLM 0.26.x**; fix verified on NVFP4 Qwen3.6-27B.
- [#4972](https://github.com/LMCache/LMCache/issues/4972) (**open** in 0.5.6): L2 serde (fp8/turboquant) crashes on GPTQ-4bit Qwen3.8-27B (same arch, chunk 784) → **do not enable L2 serde** on this arch.
- [#5344](https://github.com/LMCache/LMCache/issues/5344) (open core): torn TP prefix on L1 allocation failure under TP>1 → partially written prefix could corrupt output; risk lower on TP=2 small models, nonzero.
- [#4701](https://github.com/LMCache/LMCache/issues/4701): hybrid persistence silently stores 1 of N kernel pages (open).
- [#4385](https://github.com/LMCache/LMCache/issues/4385) (in-process only): cross-request KV contamination on disk L2 → use **MP mode**.
- [#2061](https://github.com/LMCache/LMCache/issues/2061)/#1739/#2903: **`PYTHONHASHSEED=0` mandatory with TP>1** (in-process) for deterministic hashing.
- [#939](https://github.com/LMCache/LMCache/issues/939): GPTQ-INT4 amplified non-determinism → ~10% cached-vs-fresh divergence (attributed to vLLM, not LMCache).
- vLLM [#47194](https://github.com/vllm-project/vllm/issues/47194): prefix caching + **MTP3 spec-decode** correctness regression on Qwen3.5/3.6 hybrids (partial fix v0.28.0) → don't combine MTP + cache until verified. Also the GPTQ-Pro card itself reports `spec_decode_num_accepted_tokens_total=0` on 2×3090 — MTP gives nothing there.
- vLLM [#49182](https://github.com/vllm-project/vllm/issues/49182): multimodal rank-0 CUDA OOM under TP.

## 7. Alternatives you didn't ask about
| Option | When it wins | Caveat |
|---|---|---|
| **vLLM native APC only** (on by default in V1) | Working set fits GPU KV, single instance, text-only | 60% hits already in #4514 without LMCache |
| **vLLM native tiered KV offloading** (since v0.22, `TieringOffloadingSpec` via `--kv-transfer-config`; fs/S3/P2P tiers) | Want CPU/disk tier + DP/instance sharing **without an external daemon**; [vllm.ai blog, 2026-09-10](https://vllm.ai/blog/2026-09-10-tiered-kv-offloading) | Designed for hybrids ("state-space layers offload and reload their state alongside attention KV") but **Qwen3.6 not named in validated list**, and open bugs on hybrids: [#61970](https://github.com/vllm-project/vllm/issues/61970) (EngineCore crash), [#567](https://github.com/1CatAI/1Cat-vLLM/issues/567) (GDN align + offload assert). #63565 fixed. Younger than LMCache for hybrids. |
| **Topology switch: DP=2 or PP=2** | Likely the biggest win on a PCIe box (see §2.4) | DP needs model to fit 1 GPU (true for 24 GB cards only if you keep max-model-len modest); PP adds pipeline bubbles but is the vLLM-documented choice for PCIe |
| **FP8 official checkpoint** (`Qwen/Qwen3.6-27B-FP8`) | Faster kernels than GPTQ | [#55291](https://github.com/vllm-project/vllm/issues/55291) token-collapse bug reported; only if your GPUs can host it |

## 8. Recommendation
1. **Decide the topology first** (it dominates the caching decision): benchmark TP=2 (your current) vs PP=2 vs DP=2 on your real workload. On 24 GB cards TP=2 is the only fit; on ≥48 GB, test DP=2 (zero PCIe traffic) and PP=2.
2. **If you add a cache tier:** pin **LMCache ≥ 0.5.6** + a recent vLLM **not 0.26.x** (0.28+ is the safe window given the hybrid fixes; the recipe page does not print an explicit vLLM version — validate with the recipe), **MP mode only**, recipe flags exactly as §3, **no L2 serde**, **no MTP**, `PYTHONHASHSEED=0`, text-only serving. NOTE: the LMCache Qwen3.6 recipe carries **no vLLM version pin** — "0.28+" is an inference from the hybrid-fix timeline (v0.28.0 #51113, 0.26.0 corruption fixed in #4253/#5249), not a validated upper window. Your exact vLLM (0.28.x / 0.30.x / 0.33.x) must be validated against the recipe's command line + a determinism probe before production, because both sides ship frequently and the compatibility page warns the combination can be "incompatible even when both packages import successfully".
3. **Measure before you believe it:** A/B on your representative workload — TTFT P50/P99, throughput, and the engine's `prefix_cache_hit_rate` (external vs internal) with the cache layer off vs on; run a temp-0 determinism probe (cached vs fresh) given the GPTQ sensitivity in #939 and the non-bit-exact caveat.
4. **Falsify the benefit:** if your hit rate without LMCache is already ≥80% (i.e. working set fits GPU KV) and you run a single instance, drop LMCache — APC covers you at zero overhead.

## 9. Confidence and open questions
- **Confidence: medium-high.** Everything load-bearing traces to fetched sources (model card, vLLM/LMCache docs & issues, release notes).
- **Open:** (1) nobody has publicly reported the GPTQ-Pro checkpoints + LMCache together — your first run is, in a sense, the validation; (2) the exact vLLM version the qwen3_5 recipe was validated against is not printed; (3) #5344 (torn TP prefix) core fix timing; (4) no direct TP2/PP2/DP2 PCIe benchmark exists for this exact model+quant; (5) native tiered offloading vs LMCache head-to-head on Qwen3.6 is unmeasured.

Confidence: medium-high
