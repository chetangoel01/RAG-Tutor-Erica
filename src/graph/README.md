# Modal-based Entity Extraction for Erica

This pipeline extracts AI/ML concepts and relationships from your course chunks using Modal's A100-80GB GPUs with vLLM for fast **parallel** inference.

## Overview

**Model**: Qwen3-32B (with thinking mode disabled for clean JSON output)  
**Parallelism**: 10 GPUs by default (configurable)

The pipeline:
1. **Export** chunks from MongoDB to JSON
2. **Process** on Modal with Qwen3-32B via vLLM (10 parallel GPUs)
3. **Import** results back into MongoDB

## Prerequisites

1. **Modal account**: Sign up at https://modal.com
2. **Modal CLI**: Install and authenticate

```bash
pip install modal
modal token new
```

3. **MongoDB running** with chunks from M2

## Quick Start

### 1. Export chunks from MongoDB

```bash
# Export all chunks
python export_chunks.py

# Or limit for testing
python export_chunks.py --limit 100
```

This creates `chunks.json`.

### 2. Run extraction on Modal

```bash
# Full run with 10 parallel GPUs (default)
modal run extract.py --input chunks.json --output extractions.json

# Test run (100 chunks, fewer GPUs)
modal run extract.py --input chunks.json --output extractions.json --max-chunks 100 --num-gpus 2

# Adjust parallelism (use more GPUs for faster processing)
modal run extract.py --input chunks.json --output extractions.json --num-gpus 10

# Adjust batch size per GPU
modal run extract.py --input chunks.json --output extractions.json --batch-size 16
```

### 3. Import results to MongoDB

```bash
# Import extractions
python import_extractions.py extractions.json

# Clear existing and reimport
python import_extractions.py extractions.json --clear
```

## Cost & Time Estimates

Modal pricing for A100-80GB: ~$3.50/hour/GPU

For ~9,000 chunks with **10 parallel GPUs**:
- Time: ~3-5 minutes (vs 30 min with 1 GPU)
- Cost: ~$2-3 (10 GPUs × 5 min × $3.50/hr)

| GPUs | Estimated Time | Estimated Cost |
|------|----------------|----------------|
| 1    | 25-30 min      | $1.50-2.00     |
| 5    | 5-7 min        | $1.50-2.00     |
| 10   | 3-5 min        | $2.00-3.00     |

Note: More GPUs = faster but slightly higher cost due to startup overhead.

## Why Qwen3-32B?

- Performs on par with Qwen2.5-72B but faster
- Fits comfortably on single A100-80GB
- Supports thinking mode toggle (disabled for structured extraction)
- Good balance of quality and speed

## Customization

### Batch size tuning

- Larger batch = faster (more parallelism) but more memory
- Start with 32, reduce to 16 or 8 if OOM errors

### Adjusting the prompt

Edit `SYSTEM_PROMPT` and `USER_PROMPT_TEMPLATE` in `extract.py` to change what gets extracted.

## Output Format

Each extraction result:
```json
{
  "chunk_id": "abc123",
  "source_url": "https://...",
  "concepts": [
    {
      "title": "Neural Network",
      "definition": "A computational model inspired by biological neural networks",
      "difficulty": "beginner",
      "aliases": ["NN", "ANN"]
    }
  ],
  "relations": [
    {
      "source": "CNN",
      "target": "Neural Network",
      "relation_type": "is_a"
    }
  ],
  "error": null
}
```

## Troubleshooting

### "CUDA out of memory"
Reduce batch size: `--batch-size 16` or `--batch-size 8`

### Slow first run
First run downloads the model (~60GB for Qwen3-32B). Subsequent runs use cached model.

### JSON parse errors
Some chunks produce invalid JSON. These are logged with `error` field. The pipeline continues with other chunks.

### Thinking mode leaking through
The script handles this by stripping `<think>...</think>` tags if they appear. If you see many such cases, check vLLM version (need >= 0.8.5).

## Files

- `extract.py` - Main Modal extraction script (Qwen3-32B)
- `export_chunks.py` - Export MongoDB chunks to JSON
- `import_extractions.py` - Import results back to MongoDB
- `README.md` - This file