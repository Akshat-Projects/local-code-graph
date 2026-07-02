# Local LLM Inference Benchmark

**Date:** 2026-07-01

Benchmarking speculative decoding (MTP), Flash Attention, KV cache quantization and long-context inference using `llama.cpp`.

---

# Hardware

| Component | Value |
|-----------|-------|
| GPU | NVIDIA RTX 4070 Laptop GPU (8 GB VRAM) |
| CPU | AMD Ryzen 7 7840HS |
| RAM | (Fill yours) |
| OS | Ubuntu 22.04 (WSL2) |
| CUDA Toolkit | 13.0.88 |
| NVIDIA Driver | 580.xx |

---

# llama.cpp

| Setting | Value |
|----------|-------|
| Commit | `0eca4d490` |
| Build | Release |
| CUDA Backend | Enabled |
| Flash Attention | Enabled |
| CUDA Architecture | 89 |
| KV Cache | q8_0 / q8_0 |

Build:

```bash
# This part is only for updating llama.cpp
git log -1 --oneline
cd ~/llama.cpp
git pull origin master
rm -rf build
# Below this is for fresh install and continuing with update
cmake -B build \
    -DGGML_CUDA=ON \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CUDA_ARCHITECTURES=89

cmake --build build -j$(nproc)
```

---
---
# Models

## Gemma 4

Main

```
gemma-4-E4B-it-UD-Q4_K_XL.gguf
```

Draft

```
gemma-4-E4B-it-Q8_0-MTP.gguf
```

---

## Qwen 3.5 MTP



```
Qwen3.5-9B-IQ4_NL-1.gguf
```
---
---

# Server Configuration

## Gemma

```bash
./bin/llama-server \
  -m ~/llmhost/model/gemma-4-E4B-it-UD-Q4_K_XL.gguf \
  --spec-draft-model ~/llmhost/model/gemma-4-E4B-it-Q8_0-MTP.gguf \
  --spec-type draft-mtp \
  --spec-draft-n-max 3 \
  -ngl 999 \
  -c 131072 \
  -fa on \
  -b 2048 \
  -ub 512 \
  -np 1 \
  -ctk q8_0 \
  -ctv q8_0
```

---

## Qwen

```bash
./bin/llama-server \
  -m ~/llmhost/model/Qwen3.5-9B-IQ4_NL-1.gguf \
  --spec-type draft-mtp \
  --spec-draft-n-max 3 \
  -ngl 999 \
  -c 131072 \
  -fa on \
  -b 2048 \
  -ub 512 \
  -np 1 \
  -ctk q8_0 \
  -ctv q8_0
```

---

# Gemma 4 Results

## Battery

| Config | TPS | Speedup |
|---------|----:|---------:|
| No MTP | **45.20** | 1.00× |
| MTP (2) | 65.30 | 1.44× |
| **MTP (3)** | **69.82** | **1.54×** |
| MTP (4) | 67.32 | 1.49× |
| MTP (5) | 63.64 | 1.41× |
| MTP (6) | 61.79 | 1.37× |

---

## Charging

| Config | TPS | Speedup |
|---------|----:|---------:|
| No MTP | **58.82** | 1.00× |
| MTP (2) | 87.72 | 1.49× |
| **MTP (3)** | **97.26** | **1.65×** |
| MTP (4) | 84.55 | 1.44× |
| MTP (5) | 85.26 | 1.45× |
| MTP (6) | 82.38 | 1.40× |

Peak VRAM:

```
5743 MiB / 8188 MiB
```

---

# Qwen 3.5 Results

## MTP Sweep (131k Context)

| spec-draft-n-max | TPS |
|-----------------:|----:|
| 2 | 47.29 |
| **3** | **50.19** |
| 4 | 43.87 |

Draft statistics:

```
Acceptance Rate : 61.2%
Accepted Tokens : 295 / 482
Mean Draft Len  : 2.22
```

Peak VRAM:

```
7925 MiB / 8188 MiB
```

---

## Context Scaling

| Context | VRAM | TPS |
|---------:|-----:|----:|
| 32k | 6288 MiB | ~48 |
| 64k | 7069 MiB | ~48 |
| 128k | 7925 MiB | ~48 |

Observation:

Decode throughput remained essentially constant despite the larger KV cache.

---

# Comparison

| Metric | Gemma 4 | Qwen 3.5 |
|---------|---------:|---------:|
| Active Parameters | ~4B | 9B Dense |
| Context | 131k | 131k |
| Best MTP n-max | 3 | 3 |
| Peak TPS | **97.26** | **50.19** |
| VRAM | 5.7 GB | 7.9 GB |
| Draft Acceptance | ~60% | 61% |

---

# Conclusions

## Gemma 4

- Dedicated assistant model provides substantial speculative decoding gains.
- Best configuration is `--spec-draft-n-max=3`.
- Achieved a 1.65× speedup while remaining well within 8 GB VRAM.

## Qwen 3.5

- Native MTP is functioning correctly.
- Best configuration is also `--spec-draft-n-max=3`.
- Throughput remained nearly constant from 32k to 128k context.
- Decode performance appears compute-bound rather than memory-bandwidth-bound.

---

# Notes

- Flash Attention is required when using quantized V-cache.
- The Gemma warning

```
Gemma4Assistant requires ctx_other to be set
```

is expected during memory fitting and does not prevent MTP.

- Battery mode significantly reduces throughput due to laptop GPU power limits.

---

# Future Work

## Models

- [ ] Gemma 4 12B

## Benchmarks

- [ ] Prompt processing throughput
- [ ] TTFT
- [ ] Code generation
- [ ] Long-context RAG
- [ ] Multi-turn chat
- [ ] Streaming latency
- [ ] Power consumption
- [ ] GPU utilization