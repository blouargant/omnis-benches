# LMCache + vLLM on Qwen3.6-27B (GPTQ-Pro-4bit), 2 GPUs, no NVLink — decision brief

## 1. Verdict
**Yes, LMCache can be interesting — but only for one workload shape (multi-turn / RAG / repeated long prefixes whose KV working set overflows GPU HBM), and only after you smoke-test the exact stack yourself.** As of today, nobody has published a verification of the exact intersection you are asking about (GPTQ weights + LMCache + hybrid mamba state + TP=2): the LMCache recipe validates the **BF16** Qwen3.6-27B, **text only**. Until your own store-vs-retrieve equivalence check passes, treat any production deployment as a no-go, and remember cached runs are **not bit-exact** (score-level validation only, per LMCache docs).

## 2. Premise check — what we challenged in your question
1. **"Qwen3.6 27B" is real** — `Qwen/Qwen3.6-27B`, released 2026-04-22, 27B dense, **hybrid Gated-DeltaNet (48 layers) + Gated Attention (16 of 64 layers full-attention)**, 4 KV heads × head_dim 256, hidden 5120, 262K native context, **vision-language** (image-text-to-text). ([HF model card](https://huggingface.co/Qwen/Qwen3.6-27B))
2. **"GPTQ Pro" = `groxaxo/Qwen3.6-27B-GPTQ-Pro-4bit`** — GPTQModel 6.1.0 + FOEM, 4-bit, group 128, **18.7 GB weights**, `model_type: qwen3_5`. Intended vLLM path: `--quantization gptq_marlin --dtype float16`. The author's own tested config is **2× RTX 3090, TP=2, `--disable-custom-all-reduce`, max-model-len 65536, ~64 tok/s** — so your 2-GPU TP=2 topology is exactly the author-recommended one. ([HF model page](https://huggingface.co/groxaxo/Qwen3.6-27B-GPTQ-Pro-4bit))
3. **No NVLink is fine.** vLLM's custom all-reduce only disables itself beyond 2 PCIe-only GPUs; at TP=2 it stays active (and the model author disables it anyway in the recommended command). PP=2 is *not* the alternative to reach for: vLLM positions PP for multi-node/slow interconnects, and PP on Qwen3-class models has active bugs (illegal memory access / gibberish output — vllm#63505, fixed by PR #64165). **Your "2 GPUs" premise holds**: 18.7 GB weights + overhead leave no useful KV budget on a single 24 GB card.
4. **KV-cost correction (verified):** GDN linear-attention state is **constant-size per sequence**; per-token KV grows only through the 16 full-attention layers: 2(K+V) × 4 heads × 256 × 2 B = 4 KB/token/layer → **~64 KB/token ≈ 0.5 GB per 8K-token sequence**. Long context is far cheaper in KV than a pure transformer of the same size — this is exactly why a 27B "262K" model can serve on consumer GPUs, and why GPU HBM may hold more of your working set than you expect (relevant to whether LMCache even gets hits — see §3).

## 3. Analysis

### 3.1 Why LMCache is unusually relevant for *this* model
- vLLM's **native** mamba-hybrid prefix caching is itself young: align mode was **slower than no caching** in vLLM's own MRV1 bench on Qwen3.5-4B multi-turn (141.9 ms vs 71.7 ms p50 TTFT), there was a stale-state CoW bug, and the perf fix (PR #64303 "fixed state slots") is **currently incompatible with any KV connector** (the PR author states connectors "need loads into the running slot instead of the row" — future work, not a permanent block). `--mamba-cache-mode` is deprecated and removed in v0.34.0. ([vLLM PR #64303](https://github.com/vllm-project/vllm/pull/64303), [PR #64838](https://github.com/vllm-project/vllm/pull/64838))
- LMCache MP mode is **the only currently documented and actively tested path** for KV reuse beyond GPU HBM on this hybrid family, with a dedicated, merged recipe for Qwen3.6-27B (PR #3645): block/chunk size **784**, `--separate-object-groups`, connector `LMCacheMPConnector`, `kv_role: kv_both`, plus `--enable-prefix-caching --mamba-cache-mode align`. ([docs.lmcache.ai/recipes/qwen3_5](https://docs.lmcache.ai/recipes/qwen3_5.html), [hybrid_models](https://docs.lmcache.ai/mp/hybrid_models.html))
- LMCache's benefit is conditional by design: its own docs say hit rate **stays 0 while the working set fits in GPU HBM** and rises once reuse spills out. Given the cheap KV of §2.4, on 2×24 GB with modest concurrency your prefixes may already be served by vLLM's in-GPU cache — so **measure first** (see §6).

### 3.2 Pros (LMCache for your stack)
- **CPU L1 (+ optional L2: NVMe/POSIX/Redis/S3) extends effective KV capacity** past 2×24 GB HBM — the only documented way to do that for this hybrid model; vLLM's built-in `SimpleCPUOffloadConnector` is experimental and unproven for mamba hybrids.
- **MP daemon architecture**: process isolation (a cache fault can't kill vLLM), no GIL contention, L1 shareable by multiple vLLM instances on the host.
- **Documented gains**: 75% mean-TTFT reduction (757→185 ms) and 41% shorter benchmark duration in the official long-doc-QA benchmark (Qwen3-8B — not your model; treat as directional). A "10×" figure exists only in a blog title about MoE inference and is unverified.
- **Quantization orthogonality (inference, unverified)**: GPTQ quantizes weights only; the KV cache stays fp16/bf16, which is what LMCache stores. No fetched source *confirms* this path on your exact checkpoint — that is the gap to smoke-test.

### 3.3 Cons / risks
- **The hybrid-model path is young and has open correctness bugs** (all still **open** as of late Oct 2026):
  - **#5600** — Mamba hybrids: a prefix hit can restore a state vLLM never computed. *The scariest one for your model family.*
  - **#5675** — hybrid + MTP5 speculative decoding: deterministic spec-decode degeneration.
  - **#5937** — MP connector abort-race → `EngineCore` crash (workaround: keep L1 retention, avoid L2-only).
  - **#5523** — intermittent KV corruption ("duct" token loop), correlated with L1 eviction pressure under long prefills.
- **Not validated on your checkpoint**: the recipe tests BF16 `Qwen/Qwen3.6-27B`; closest quantized data points are Qwen3.6-27B-**INT8** + MTP garbage on long prompts (#4345, open/stale, believed fixed by #4128 in 0.5.2) and Qwen3.8-27B-**INT4** TP=2 illegal-memory-access (#5860, WSL2-only, fix PR #5861 open). **No published result for GPTQ + LMCache on this model.**
- **Not bit-exact**: LMCache docs state cached-vs-fresh generation is not bit-exact for GDN hybrids (no batch-invariant mode) — validate at score level, never by token diff.
- **Vision unvalidated**: the recipe covers **text** generation only. If you intend to serve images, LMCache caching of vision KV is unverified.
- **Operational surface**: a second daemon to run, version, and monitor; current stable is **0.5.6**, newest is **0.5.7rc3 (pre-release)**; `PYTHONHASHSEED=0` required for cross-process hashing.
- **PCIe TP=2 penalty is real but unquantified** for your case: no vLLM-issued TP=2 PCIe-vs-NVLink benchmark exists; a withdrawn community RFC (vllm#56128) measured PCIe all-reduce at 26–52% of GPU-busy time **at TP=4** — TP=2 is materially smaller, unmeasured. Note this cost exists *with or without* LMCache.

### 3.4 Known-bug quick table (LMCache × your stack)

| Issue | Stack | Symptom | Status |
|---|---|---|---|
| [#5600](https://github.com/LMCache/LMCache/issues/5600) | Mamba hybrid, prefix hit | Restores state vLLM never computed | **Open** |
| [#5675](https://github.com/LMCache/LMCache/issues/5675) | Hybrid + MTP5 | Spec-decode degeneration, garbage | **Open** |
| [#5937](https://github.com/LMCache/LMCache/issues/5937) | MP connector, aborted request | EngineCore crash (fix PR #5938 open) | **Open** |
| [#5523](https://github.com/LMCache/LMCache/issues/5523) | Hybrid + L2, L1 pressure | Intermittent token corruption | **Open** |
| [#4345](https://github.com/LMCache/LMCache/issues/4345) | Qwen3.6-27B-INT8 + MTP | Garbage on long prompts | Open (stale); believed fixed by #4128 in 0.5.2 |
| [#5860](https://github.com/LMCache/LMCache/issues/5860) | Qwen3.8-27B-INT4, TP=2 | Illegal memory access (WSL2 only) | Open; PR #5861 open; 0.5.4 unaffected |
| [#939](https://github.com/LMCache/LMCache/issues/939) | GPTQ Qwen2.5-72B, TP=2 | First-vs-cached output divergence | Closed — **root cause was vLLM batch nondeterminism, not LMCache** |

## 4. Alternatives you didn't name

| Option | What it is | When it wins |
|---|---|---|
| **vLLM native APC only** (`--enable-prefix-caching`, align mode) | Zero extra components, GPU-only reuse | Working set fits in 2×24 GB HBM; you want minimal ops. Beware: align mode has shown *negative* TTFT deltas in vLLM's own 4B-bench and the perf fix is currently connector-incompatible. |
| **vLLM `SimpleCPUOffloadConnector`** | In-tree CPU offload with Prometheus metrics | You want CPU-tier offload without a second daemon; experimental and unproven on mamba hybrids. |
| **SGLang + HiCache** | SGLang's built-in hierarchical cache has **explicit hybrid Mamba/GDN support** and Qwen3.6-27B cookbook support (≥0.5.10, `--mamba-radix-cache-strategy`); the model card also lists SGLang | You can switch engines — potentially a simpler single-process path to hybrid KV reuse without LMCache's daemon. GPTQ support in SGLang for this checkpoint: **unassessed** (open item). |
| **Do nothing / plain serving** | No prefix caching at all | Short contexts, no repeated prefixes — caching buys nothing and only adds risk. |

## 5. Recommendation
**Two-gate decision:**

**Gate 1 — is caching worth it at all?** Serve with `--enable-prefix-caching` (native APC) on your real traffic and watch the hit rate: Prometheus `rate(vllm:prefix_cache_hits[5m]) / rate(vllm:prefix_cache_queries[5m])`, or the "prefix cache hit rate" INFO log line. If your working set fits in GPU HBM or prefixes rarely repeat → stop here; LMCache adds risk for ~0 gain.

**Gate 2 — is *this* stack safe?** If Gate 1 says yes, deploy the recipe config and **smoke-test the exact intersection** before trusting it:
```bash
lmcache server --chunk-size 784 --separate-object-groups --l1-size-gb <free-host-RAM> --eviction-policy LRU
vllm serve groxaxo/Qwen3.6-27B-GPTQ-Pro-4bit \
  --quantization gptq_marlin --dtype float16 --trust-remote-code \
  --tensor-parallel-size 2 --disable-custom-all-reduce \
  --max-model-len 65536 --gpu-memory-utilization 0.92 \
  --enable-prefix-caching --mamba-cache-mode align \
  --kv-transfer-config '{"kv_connector":"LMCacheMPConnector","kv_role":"kv_both","kv_connector_extra_config":{"lmcache.mp.host":"localhost","lmcache.mp.port":5555}}'
```
- vLLM 0.32.0 (latest stable); LMCache **0.5.6 stable** (or 0.5.7rc3 if you need the newest fixes — **pre-release**).
- **NO MTP / speculative decoding** (bugs #4345, #5675), **NO CacheBlend/CacheGen** (not supported on hybrids), **text-only** (vision unvalidated), L1 retention on (avoid the #5937 L2-only crash window).
- **Equivalence check**: run a fixed eval set (e.g. gsm8k-style, the pattern LMCache's own CI uses) with cache cold and warm; compare at **score level**, not token level. Divergence beyond score noise = do not deploy.
- **Watch for a few days**: known corruption bugs are intermittent ("days fine, then breaks after an hour" — #5523). Alert on `lmcache_mp_l1_memory_usage_bytes` watermark/eviction spikes.
- **Falsifying measurement**: TTFT and cache-hit rate, LMCache on vs off, on your real multi-turn/RAG traffic for ≥ a few days. If the TTFT gap is <~30%, the operational risk is not worth it.

## 6. Confidence & open questions
- **Confidence: medium.** Premises, recipe, and bug catalogue are well-sourced; the core recommendation rests on an intersection nobody has published.
- **The open question that would most change the decision:** does `groxaxo/Qwen3.6-27B-GPTQ-Pro-4bit` + vLLM 0.32.0 + LMCache MP + TP=2 produce *correct* (not divergent, not garbage) output under prefix reuse? No fetched source answers it — only your Gate-2 test can.
- Secondary: exact SGLang+HiCache + GPTQ maturity (potential simpler alternative); a published TP=2 PCIe-vs-NVLink throughput number.

Confidence: medium — the single question that would most change the recommendation: **do your own store-vs-retrieve outputs match (at score level) on the GPTQ checkpoint, or not?**
