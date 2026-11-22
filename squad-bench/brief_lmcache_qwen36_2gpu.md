# Draft brief — LMCache + vLLM on a GPTQ-Pro quantized Qwen3.6-27B, 2 GPUs (no NVLink), same host

User's original question (verbatim): "Is it interesting to use LLM Cache with vLLM for a Quantized Qwen3.6 27B GPTQ Pro model that run on 2 GPUs (no nvlink) on the same host ? What are the pros and cons ? Is there are known bugs of using lmcache with Qwen3.6-27B model ?" (Bench run 3d0fd622)

## 1. Verdict

With currently released software, **LMCache is NOT worth enabling on this deployment as things stand** — not because LMCache is bad, but because (a) Qwen3.6-27B is a *hybrid Gated-DeltaNet (linear-attention) + full-attention* model, for which KV-cache reuse only started working in mid-2026 and is documented as **experimental and validated on 1 GPU only** (LMCache recipe `qwen3_5.html`); (b) vLLM's built-in prefix caching — which covers ~90% of LMCache's single-instance benefit — is **off by default for hybrid models** (vLLM `config/model.py`: `attn_type == "hybrid"` → "feature is still experimental", issue #40621), AND when you manually enable it (`--enable-prefix-caching --mamba-cache-mode align`) it **silently under-delivers**: a known geometry bug (#45238) can drop the hit rate to 0% (catastrophic case mitigated on current main by Marconi admission #37898; residual is ~halved hit rate + ~22% extra TTFT, and the loss is not visible in standard metrics); (c) the 2-GPU/PCIe premise itself is questionable: vLLM's own docs say if the model fits on one GPU, "distributed inference is probably unnecessary", and for no-NVLink nodes recommend pipeline (not tensor) parallelism. A 4-bit 27B (≈15 GB weights) plausibly fits on one GPU.

**LMCache becomes interesting only if** the workload is multi-instance (shared KV across separate vLLM processes) or KV demand exceeds one GPU's memory (e.g. 262K-token contexts: KV alone ≈16 GB on top of ≈15 GB weights — does NOT fit on a single 24 GB GPU). Even then, treat Qwen3.6 + LMCache as experimental and smoke-test first.

## 2. Premise check

| Premise | Finding |
|---|---|
| "Qwen3.6 27B" exists | REAL — official Qwen dense 27B, `Qwen3_5ForConditionalGeneration`, 64 layers = 16×(3× Gated-DeltaNet + 1× Gated-Attention), 262K native context, vision-language. It is **not** a plain transformer: 48 of 64 layers are linear-attention. (HF config.json; model card) |
| "GPTQ Pro" | Community project: groxaxo/GPTQ-Pro, a fork of GPTQModel; real HF model `groxaxo/Qwen3.6-27B-GPTQ-Pro-4bit`, served via `--quantization gptq_marlin`. Orthogonal to LMCache: KV cache stays fp16/bf16 regardless of weight quantization (vLLM quantized-kvcache docs). **However, no source validates the GPTQ-Pro checkpoint specifically** — LMCache validated only the unquantized `Qwen/Qwen3.6-27B`, 1 GPU. Treat the quantized checkpoint as unverified. |
| 2 GPUs, no NVLink | vLLM docs (parallelism_scaling.md, verbatim): "if the model fits on a single GPU, distributed inference is probably unnecessary. Run inference on that GPU." and "if the GPUs on the node do not have NVLINK interconnect (e.g. L40S), leverage pipeline parallelism instead of tensor parallelism for higher throughput and lower communication overhead." TP=2 over PCIe means 2 all-reduces per layer per token (64 layers → ~128 per token) over a link ~14× slower than NVLink. |
| Implicit goal: reuse benefit | LMCache value is proportional to prefix-reuse rate (shared system prompts, multi-turn, RAG). Not stated by user → decision rule given in §6. |

## 3. What LMCache actually does / pros / cons

Mechanics: KV connector (V1 engine, `LMCacheMPConnector` via `kv_connector_module_path` on vLLM ≥ 0.20.0); standalone `lmcache server` daemon (MP mode, recommended) over ZMQ; tiered L0 GPU → L1 CPU RAM → L2 disk/Redis. Benefits (tech report arXiv:2510.09665, vLLM v0.10.2–0.11.0): multi-round Q&A → 1.9–8.1× lower TTFT, 2.3–14× throughput; real traces 3.7–6.8× TTFT; ~400 Gbps CPU offload BW vs vLLM native 88 Gbps. Cons: extra process + CPU RAM (e.g. `--l1-size-gb 100` in the Qwen3.6 recipe); no benefit for unique prompts; remote-load latency can exceed prefill for short contexts (<256K at 32 Gbps); version coupling ("no single LMCache×vLLM pair guarantees every model/device/backend" — compatibility page); context truncation can halve hit ratio.

## 4. Known bugs (version-anchored)

- **Hybrid-model saga (Qwen3.5/3.6/3.8)**: LMCache #2845 & #3163 (2026): crashes / "hybrid KV cache manager" errors; interim guard PR #2879 (May 2026) made LMCache return **0% external cache hits** on hybrids to avoid word-salad output from unrestored Mamba state. Current docs (hybrid_models.html, recipes/qwen3_5.html) now claim Qwen3.5/3.6/3.8 hybrids ARE supported: state "reinterpreted as an opaque page", **Qwen3.6-27B listed as validated (1 GPU, N=784)**, caveats: "generation is not bit-exact" (score-level equivalence only, not token-level), "vLLM's Mamba prefix caching in `align` mode is experimental", **vision KV is not validated**, CacheBlend/CacheGen not supported (opaque pages). A contributor flagged the doc-vs-reality contradiction (Jul 2026); no maintainer-confirmed 2-GPU/hybrid validation found.
- **vLLM #40621** (closed not-planned, Sep 2026): prefix caching **off by default** for Qwen3.6-27B (hybrid); maintainer: hybrid prefix caching "still experimental". Note: when manually enabled it *runs* but yields 0%/reduced hits due to #45238 geometry — it is not merely "turned off".
- **vLLM #45238** (open, Jun 2026): hybrid APC **silently drops to 0% hit rate** when Mamba state checkpoint lands outside the shared prefix; partially mitigated on main (Marconi admission #37898) → residual "halved hit rate and ~22% TTFT", and "none of this is visible" to the operator.
- **LMCache #2061 / #2903**: 0% cache hits / no token reuse with TP>1 until `PYTHONHASHSEED=0` — **mandatory env var** across LMCache workers.
- **LMCache #2144**: PD-disagg + TP>1 hang, fixed in PR #2287 (Dec 2025).
- **LMCache #4247** (Jul 2026): **vLLM 0.26.0 changed the KV layout** from rank-5 K/V-split to rank-4 K/V-fused → "multilingual token salad" (garbled output) on cache hits for hybrid models. If you run vLLM 0.26.0+ this is severe. Workaround: pin vLLM < 0.26.0, or use the dynamic connector. (Critic-sourced; verify exact fix version before pinning.)
- **LMCache #259**: GPU OOM from temporary copy buffer on quantized models (2024-era) → lower `--gpu-memory-utilization`.
- **LMCache #1768**: repeated ABI breaks across vLLM/LMCache version pairs → pin a tested pair.
- **LMCache #2062**: V0 engine unsupported; V1 only.

## 5. Alternatives (not asked, but relevant)

| Option | When it wins |
|---|---|
| vLLM built-in APC (`--enable-prefix-caching --mamba-cache-mode align`) | Single instance, GPU-resident prefix reuse — the 90% case. Simplest; but hybrid-experimental + #45238 geometry bug; not default. |
| 1 GPU, no TP | If the 4-bit 27B fits (≈15 GB + KV; hybrid KV is small — only 16 full-attention layers): zero cross-GPU comms, and it matches LMCache's only validated Qwen3.6-27B recipe (1 GPU). |
| 2 replicas (model on each GPU) | Throughput for concurrent load without any inter-GPU communication. |
| LMCache MP mode (standalone server) | Multi-instance KV sharing, or KV beyond GPU capacity (very long 262K contexts, many sessions). |
| Mooncake / NIXL / Dynamo, SGLang RadixAttention | P/D disaggregation or RDMA clusters; overkill for a 2-GPU PCIe box. |

## 6. Recommendation

1. Decide single-GPU first: check `nvidia-smi` VRAM; if one card ≥24–32 GB, run the GPTQ-Pro-4bit model on ONE GPU (vLLM doc guidance + matches the only validated LMCache recipe).
2. If the workload has prefix reuse (multi-turn, shared system prompts): enable built-in APC with `--mamba-cache-mode align` and `--prefix-match-unit` tuning; measure "prefix cache hit rate" in vLLM logs before/after. This is the cheap test.
3. Add LMCache (MP mode) only if APC hit rates are being evicted by GPU capacity, or you run multiple instances: **do not hand-pick arbitrary versions** — the LMCache compatibility page states "there is no single LMCache × vLLM version pair that guarantees every model, connector, device, and storage backend"; use the **published stable image/wheel where vLLM and LMCache are built as one runtime stack** (LMCache ≥ 0.5.3 for hybrid support; 0.5.7rc3 current; vLLM ≥ 0.20.0 for the external connector, but **avoid vLLM 0.26.0+ until #4247 is resolved on your side**). Set `PYTHONHASHSEED=0` (mandatory — LMCache #2903, #2136, #2113), use the documented recipe (`lmcache server --chunk-size 784 --separate-object-groups --l1-size-gb 100 --eviction-policy LRU`), and smoke-test: same prompt twice → hit rate > 0 and an output-quality check (score-level, not bit-exact).
4. Falsifiable measurement: mean TTFT + external/prefix cache hit rate on your real prompt mix, APC-only vs APC+LMCache. If hit rate is ≈0, neither helps and the cost is pure overhead.

## 7. Confidence & open questions

Confidence: medium-high. Open: (1) whether the GPTQ-Pro-4bit checkpoint (vs unquantized official) is validated with APC/LMCache — docs validated only `Qwen/Qwen3.6-27B`; (2) hybrid + TP>1 with LMCache — no 2-GPU validation found; (3) whether the 0%-hits guard from PR #2879 is fully superseded on all code paths in 0.5.7 (docs say supported; last maintainer confirmation of non-zero hybrid hit rates not directly fetched).
