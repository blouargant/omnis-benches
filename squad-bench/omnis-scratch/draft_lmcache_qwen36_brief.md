# DRAFT BRIEF — LMCache + vLLM for groxaxo/Qwen3.6-27B-GPTQ-Pro-4bit on 2 GPUs (no NVLink)

User question: "Is it interesting to use LLM Cache with vLLM for a Quantized Qwen3.6 27B GPTQ Pro model that run on 2 GPUs (no nvlink) on the same host? Pros and cons? Known bugs of using lmcache with Qwen3.6-27B?"

## Verdict (draft)
Yes, LMCache is genuinely interesting for this model — and arguably MORE interesting than for a plain transformer — because vLLM's native mamba-hybrid prefix caching is itself experimental (align mode was slower than no caching in vLLM's own MRV1 bench; stale-state CoW bug; `--mamba-cache-mode` deprecated for removal in v0.34.0, and the vLLM fixed-slots performance fix does NOT work with any KV connector). LMCache MP mode is the only documented, recipe-validated path to cross-request KV reuse for Qwen3.6-27B. BUT: it is only worth it if your workload has repeated prefixes / multi-turn / contexts that overflow the GPU KV cache, and it is NOT validated on the GPTQ quantized checkpoint (only on the BF16 model).

## Premise check
1. "Qwen3.6 27B" is REAL: Qwen/Qwen3.6-27B, released 2026-04-22, hybrid Gated-DeltaNet + Gated Attention (16 of 64 layers full-attention, full_attention_interval=4, 4 KV heads x head_dim 256, hidden 5120), 262K context, vision-language (image-text-to-text). Model card: huggingface.co/Qwen/Qwen3.6-27B
2. "GPTQ Pro" = groxaxo/Qwen3.6-27B-GPTQ-Pro-4bit (GPTQModel 6.1.0 + FOEM, 4-bit, group 128, 18.7 GB weights, model_type qwen3_5). Intended vLLM path: `--quantization gptq_marlin --dtype float16`. Author's tested config: 2x RTX 3090, TP=2, `--disable-custom-all-reduce`, max-model-len 65536, 64 tok/s. -> The 2-GPU TP=2 premise is CORRECT and is the author-recommended topology.
3. No NVLink: TP=2 still works (vLLM custom all-reduce only drops out beyond 2 PCIe-only GPUs; the author's own command disables custom all-reduce anyway). PP=2 not recommended (vLLM positions PP for slow interconnect/multi-node; PP has active OOM bugs on Qwen3-class models, e.g. vllm#63505).
4. Single 24GB GPU: NOT viable beyond trivial context — weights 18.7GB + overhead leave no KV budget; author recommends 2 GPUs. 2-GPU premise holds. (Note: GDN linear-attention state is constant-size per sequence, so KV cost grows with seq length only through the 16 full-attention layers — ~64KB/token total -> ~0.5 GB per 8K-token sequence; one sub-agent's 0.438MB/token figure wrongly assumed GDN state grows per-token — needs re-verification, but does not change the 2-GPU conclusion.)

## Pros of LMCache here
- Only documented path to KV cache reuse beyond GPU HBM for this hybrid model (CPU L1 + optional L2: NVMe/POSIX/Redis/S3); vLLM's SimpleCPUOffloadConnector is experimental.
- MP mode: separate daemon -> no GIL contention, no fate-sharing with vLLM process, shared L1 across multiple vLLM pods on the host.
- Chunk-level (784-token block for this model) prefix reuse; docs claim 3-10x TTFT reduction for multi-turn/RAG; official bench: 75% TTFT reduction (757->185 ms), 41% duration reduction, Qwen3-8B long-doc QA.
- Recipe-validated for Qwen3.6-27B (docs.lmcache.ai/recipes/qwen3_5.html; PR #3645 merged Jun 2026): `lmcache server --chunk-size 784 --separate-object-groups --l1-size-gb 100` + vLLM `--enable-prefix-caching --mamba-cache-mode align --kv-transfer-config {"kv_connector":"LMCacheMPConnector","kv_role":"kv_both"}`.
- KV cache is fp16/bf16 regardless of GPTQ weight quantization -> quantization theoretically orthogonal to what LMCache stores (INFERENCE — no doc/issue statement found confirming GPTQ+LMCache works).

## Cons / risks
- Hybrid-model support is young and bug-prone: open issues #5600 (prefix hits restore a mamba state vLLM never computed — Oct 2026), #5675 (Mamba hybrid + MTP5: deterministic spec-decode degeneration), #5407 (chunkSize prevents heterogeneous fleets). Recipe caveats: NOT bit-exact (score-level only), byte-opaque pages must not be shared across engines with different attention backends/kernel block sizes, vLLM mamba prefix caching in align mode is experimental, vision KV caching NOT validated.
- Not validated on the GPTQ-Pro checkpoint: LMCache recipe tests the BF16 Qwen3.6-27B; closest quantized data points are Qwen3.6-27B-INT8 (issue #4345, MTP garbage on long prompts, stale) and Qwen3.8-27B-INT4 on TP=2 (issue #5860, WSL2-only direct-copy fault). No issue specifically documents GPTQ + LMCache on this model.
- Quantization is a load-only concern for KV but adds a third variable: known vLLM GPTQ bugs in the qwen3_5 code path (#63598 MoE-only, #63630 partial-dense-only — neither applies to this fully-quantized dense checkpoint, but the code path is actively churning).
- Extra operational surface: separate daemon to run/version (LMCache releases are rc-tagged: latest 0.5.7rc3); known MP connector crashes (#5937 aborted-request assert -> EngineDeadError; PR open); PYTHONHASHSEED=0 requirement.
- If your working set fits in GPU HBM, LMCache hit rate stays 0 (LMCache docs: vLLM native cache serves everything; LMCache only pays when reuse spills out of GPU cache).
- PCIe TP=2 penalty: no vLLM-issued benchmark found for TP=2 PCIe vs NVLink; community data (vllm#56128, withdrawn RFC) showed PCIe all-reduce eating 26-52% of GPU-busy time at TP=4 — at TP=2 the impact is much smaller but unquantified.

## Known-bug catalogue most relevant to this exact stack (LMCache x Qwen3.6-class hybrid x TP=2 x quantized)
- #4345 Qwen3.6-27B-INT8 + MTP: garbage output on long prompts (vLLM 0.25.1 / LMCache 0.5.1) — stale, likely fixed by #4128 in 0.5.2. Do NOT run MTP + LMCache.
- #5860 Qwen3.8-27B-INT4 TP=2: illegal memory access in direct-copy path — WSL2 only; fix PR #5861 open; LMCache 0.5.4 (pre-#5308) unaffected.
- #5600 Mamba hybrid: prefix hits restore a state vLLM never computed — OPEN, the scariest correctness bug for this model family.
- #5675 Mamba hybrid + MTP5 spec-decode degeneration — OPEN.
- #5937 MP connector abort race -> EngineCore crash — OPEN, workaround: keep L1 retention (LRU) instead of L2-only.
- #939 (closed, cleared): GPTQ-INT4 Qwen2.5-72B output divergence was vLLM batch nondeterminism, not LMCache.

## Alternatives the user did not name
1. vLLM native APC alone (`--enable-prefix-caching`, align mode for mamba): zero extra components, but vLLM's own MRV1 bench showed align mode slower than no caching on Qwen3.5-4B multi-turn (141.9 vs 71.7 ms p50 TTFT) and the fixed-slots perf fix (PR #64303) does not work with any KV connector; GPU-only, no CPU offload.
2. vLLM SimpleCPUOffloadConnector: built-in CPU offload, experimental, with Prometheus metrics; avoids the LMCache daemon but unproven for mamba hybrids.
3. SGLang (model card lists it as a supported engine; radix cache with different hybrid-state handling) — different ecosystem, unassessed here.
4. Do nothing: if context is short and prefixes don't repeat, native APC alone or even no caching is fine.

## Recommendation (draft)
- Prerequisite: measure first. Run the model with `--enable-prefix-caching` and look at vLLM prefix-cache hit metrics on a representative workload. If hit rate is low or the working set fits in 2x24 GB HBM, LMCache adds risk for ~0 gain.
- If you proceed: vLLM 0.32.0 + LMCache >=0.5.7rc3 MP mode, single LMCache daemon, L1 sized to free host RAM, `--chunk-size 784 --separate-object-groups`, vLLM per recipe + the author's `--disable-custom-all-reduce`, NO MTP/speculative decoding, NO CacheBlend, text-only (vision unvalidated). Verify with the gsm8k store-vs-retrieve check pattern before trusting output; expect score-level, not bit-exact, equivalence.
- Measurement to prove/disprove: TTFT and prefix-hit rate with LMCache on vs off over your real multi-turn/RAG traffic, for >= a few days (bug #5523-style corruption is intermittent: "days fine, then breaks after an hour").

## Confidence
Medium. Highest-risk unverified cell: GPTQ-quantized weights + LMCache + hybrid mamba state + TP=2 — no fetched source covers that exact intersection.
