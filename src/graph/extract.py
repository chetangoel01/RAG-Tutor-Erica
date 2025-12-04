"""
Modal-based entity extraction using vLLM on A100-80GB GPUs.

Uses Qwen3-32B for extraction with thinking mode DISABLED for clean JSON output.
PARALLELIZED across multiple GPUs using Modal's .map() for 10x speedup.

Extracts: concepts, relations, AND examples (worked examples, code, math derivations)

Usage:
    # First, export chunks from MongoDB to JSON
    python export_chunks.py
    
    # Run extraction on Modal (uses 10 parallel GPUs by default)
    modal run extract.py --input chunks.json --output extractions.json
    
    # For testing with a small batch
    modal run extract.py --input chunks.json --output extractions.json --max-chunks 100
    
    # Adjust parallelism
    modal run extract.py --input chunks.json --output extractions.json --num-gpus 5
"""

import modal
import json
from typing import Optional

# =============================================================================
# Modal App Definition
# =============================================================================

app = modal.App("erica-extraction")

# Docker image with vLLM and dependencies
# Need vLLM >= 0.8.5 for Qwen3 support
vllm_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "vllm>=0.8.5",
        "torch>=2.1.0",
        "transformers>=4.45.0",
        "huggingface_hub",
    )
)


# =============================================================================
# Extraction Prompt (System + User) - NOW INCLUDES EXAMPLES
# =============================================================================

SYSTEM_PROMPT = """You are an expert at extracting AI/ML concepts from educational content.
You always respond with valid JSON only, no markdown, no explanations, no thinking."""

USER_PROMPT_TEMPLATE = """Extract AI/ML concepts, their relationships, and worked examples from this educational text.

For each CONCEPT, provide:
- title: The canonical name (e.g., "Gradient Descent")
- definition: A brief 1-2 sentence definition
- difficulty: "beginner", "intermediate", or "advanced"
- aliases: Alternative names as a list

For RELATIONS between concepts found:
- prereq_of: Concept A must be understood before Concept B
- is_a: Concept A is a type of Concept B (e.g., "CNN is_a Neural Network")
- part_of: Concept A is a component of Concept B
- contrasts_with: Concepts that are alternatives or opposites
- sibling: Concepts at the same level

For EXAMPLES (worked examples, code snippets, mathematical derivations, case studies):
- text: Brief description of the example (1-2 sentences)
- concept: Which concept this example demonstrates (must match a concept title exactly)
- example_type: One of "code", "math", "case_study", "walkthrough", "diagram"

IMPORTANT:
- Only extract concepts actually discussed in the text
- Examples should be concrete illustrations, not just mentions
- Use exact concept titles in relations and examples
- Return ONLY valid JSON, no markdown code blocks

Return format:
{{"concepts": [{{"title": "...", "definition": "...", "difficulty": "...", "aliases": []}}], "relations": [{{"source": "...", "target": "...", "relation_type": "..."}}], "examples": [{{"text": "...", "concept": "...", "example_type": "..."}}]}}

If nothing found: {{"concepts": [], "relations": [], "examples": []}}

TEXT:
{text}"""


# =============================================================================
# vLLM Model Class - Each instance runs on its own GPU
# =============================================================================

@app.cls(
    gpu="A100-80GB",
    image=vllm_image,
    timeout=3600,  # 1 hour max
    scaledown_window=300,  # Keep warm for 5 min
)
class Extractor:
    """vLLM-based extraction using Qwen3-32B with thinking disabled.
    
    Modal will spin up multiple containers (each with its own A100 GPU)
    to process batches in parallel.
    """
    
    model_name: str = "Qwen/Qwen3-32B"
    
    @modal.enter()
    def load_model(self):
        """Load vLLM model on container start."""
        import time
        from vllm import LLM, SamplingParams
        from transformers import AutoTokenizer
        
        start_time = time.time()
        print(f"[{time.time() - start_time:.1f}s] Starting to load {self.model_name}...")
        
        # Load tokenizer for chat template
        print(f"[{time.time() - start_time:.1f}s] Loading tokenizer...")
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_name, 
            trust_remote_code=True
        )
        print(f"[{time.time() - start_time:.1f}s] Tokenizer loaded")
        
        # Load vLLM engine
        print(f"[{time.time() - start_time:.1f}s] Loading vLLM engine (this may take 5-10 min on first run)...")
        print(f"[{time.time() - start_time:.1f}s] Downloading/loading model weights (~60GB)...")
        self.llm = LLM(
            model=self.model_name,
            tensor_parallel_size=1,
            dtype="bfloat16",
            max_model_len=8192,
            gpu_memory_utilization=0.90,
            seed=0,  # Explicit seed to avoid deprecation warning
        )
        
        # Sampling params for non-thinking mode (lower temperature for structured output)
        self.sampling_params = SamplingParams(
            temperature=0.3,
            top_p=0.95,
            top_k=20,
            max_tokens=2048,
            stop=["```", "\n\n\n"],
        )
        elapsed = time.time() - start_time
        print(f"[{elapsed:.1f}s] Model loaded successfully! ({elapsed/60:.1f} minutes)")
    
    def _build_prompt(self, text: str) -> str:
        """Build chat prompt with thinking DISABLED."""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(text=text)}
        ]
        
        # Apply chat template with enable_thinking=False
        # This disables the <think>...</think> reasoning mode
        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False  # CRITICAL: disable thinking for clean JSON
        )
        return prompt
    
    @modal.method()
    def extract_batch(self, chunks: list[dict]) -> list[dict]:
        """
        Extract concepts, relations, and examples from a batch of chunks.
        
        Args:
            chunks: List of chunk dicts with 'chunk_id', 'text', 'source_url'
        
        Returns:
            List of extraction results with same chunk_id
        """
        # Build prompts with chat template
        prompts = [
            self._build_prompt(chunk["text"][:3500])  # Leave room for prompt template
            for chunk in chunks
        ]
        
        # Batch inference
        outputs = self.llm.generate(prompts, self.sampling_params)
        
        results = []
        for chunk, output in zip(chunks, outputs):
            result = {
                "chunk_id": chunk["chunk_id"],
                "source_url": chunk.get("source_url", ""),
                "concepts": [],
                "relations": [],
                "examples": [],  # NEW: examples field
                "error": None,
            }
            
            try:
                raw_text = output.outputs[0].text.strip()
                
                # Remove any thinking tags if they somehow appeared
                if "<think>" in raw_text:
                    # Extract content after </think>
                    think_end = raw_text.find("</think>")
                    if think_end != -1:
                        raw_text = raw_text[think_end + 8:].strip()
                
                # Clean up common formatting issues
                if raw_text.startswith("```json"):
                    raw_text = raw_text[7:]
                if raw_text.startswith("```"):
                    raw_text = raw_text[3:]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3]
                raw_text = raw_text.strip()
                
                # Try to find JSON object in response
                if not raw_text.startswith("{"):
                    # Look for first { in response
                    json_start = raw_text.find("{")
                    if json_start != -1:
                        raw_text = raw_text[json_start:]
                
                # Find matching closing brace
                brace_count = 0
                json_end = 0
                for i, c in enumerate(raw_text):
                    if c == "{":
                        brace_count += 1
                    elif c == "}":
                        brace_count -= 1
                        if brace_count == 0:
                            json_end = i + 1
                            break
                if json_end > 0:
                    raw_text = raw_text[:json_end]
                
                # Parse JSON
                parsed = json.loads(raw_text)
                
                concepts = parsed.get("concepts", [])
                relations = parsed.get("relations", [])
                examples = parsed.get("examples", [])  # NEW: extract examples
                
                # Basic validation
                if not isinstance(concepts, list):
                    raise ValueError("concepts is not a list")
                if not isinstance(relations, list):
                    raise ValueError("relations is not a list")
                if not isinstance(examples, list):
                    examples = []  # Default to empty if not a list
                
                result["concepts"] = concepts
                result["relations"] = relations
                result["examples"] = examples  # NEW: include examples
            
            except json.JSONDecodeError as e:
                result["error"] = f"JSON parse error: {str(e)}"
                result["raw_response"] = output.outputs[0].text[:500]
            except Exception as e:
                result["error"] = str(e)
            
            results.append(result)
        
        return results


# =============================================================================
# Local Entry Point - Parallel Processing
# =============================================================================

@app.local_entrypoint()
def main(
    input: str = "chunks.json",
    output: str = "extractions.json",
    batch_size: int = 32,
    max_chunks: Optional[int] = None,
    num_gpus: int = 10,
):
    """
    Run extraction on all chunks using PARALLEL GPU workers.

    Args:
        input: Path to JSON file with chunks
        output: Path to save extraction results
        batch_size: Number of chunks per batch per GPU
        max_chunks: Limit number of chunks for testing
        num_gpus: Number of parallel GPU workers (default: 10)
    """
    import time

    # Load chunks
    print(f"Loading chunks from {input}...")
    with open(input, "r") as f:
        chunks = json.load(f)

    if not isinstance(chunks, list):
        raise ValueError("Input JSON must be a list of chunk objects")

    total_chunks = len(chunks)
    if max_chunks is not None:
        chunks = chunks[:max_chunks]
        print(f"Limited to {max_chunks} chunks (test mode)")

    print(f"\n{'='*60}")
    print("PARALLEL EXTRACTION CONFIG")
    print(f"{'='*60}")
    print(f"Total chunks:    {len(chunks)} (of {total_chunks} available)")
    print(f"Batch size:      {batch_size} chunks/batch")
    print(f"Parallel GPUs:   {num_gpus}")
    print(f"Model:           Qwen3-32B (thinking disabled)")
    print(f"Extracting:      concepts, relations, AND examples")
    print(f"{'='*60}\n")

    # Split into batches
    batches: list[list[dict]] = []
    for i in range(0, len(chunks), batch_size):
        batches.append(chunks[i : i + batch_size])

    print(f"Created {len(batches)} batches")
    print(f"Processing with up to {num_gpus} parallel GPU workers...\n")

    extractor = Extractor()
    start_time = time.time()
    all_results: list[dict] = []

    # Process batches in windows of size num_gpus to cap parallelism
    for window_start in range(0, len(batches), num_gpus):
        window = batches[window_start : window_start + num_gpus]

        # Each batch in the window is sent as a separate .map task
        for result_batch in extractor.extract_batch.map(window, order_outputs=False):
            all_results.extend(result_batch)

            # Progress logging
            elapsed = time.time() - start_time
            chunks_done = len(all_results)
            rate = chunks_done / elapsed if elapsed > 0 else 0.0
            remaining = len(chunks) - chunks_done
            eta = remaining / rate if rate > 0 else 0.0

            print(
                f"  Progress: {chunks_done}/{len(chunks)} "
                f"({100 * chunks_done / len(chunks):.1f}%) | "
                f"{rate:.1f} chunks/sec | ETA: {eta:.0f}s"
            )

    # Save results
    print(f"\nSaving results to {output}...")
    with open(output, "w") as f:
        json.dump(all_results, f, indent=2)

    # Summary - NOW INCLUDES EXAMPLES
    elapsed = time.time() - start_time
    n_concepts = sum(len(r.get("concepts", [])) for r in all_results)
    n_relations = sum(len(r.get("relations", [])) for r in all_results)
    n_examples = sum(len(r.get("examples", [])) for r in all_results)
    n_errors = sum(1 for r in all_results if r.get("error"))

    print(f"\n{'='*60}")
    print("EXTRACTION COMPLETE")
    print(f"{'='*60}")
    print(f"Time:       {elapsed/60:.1f} min")
    print(f"Throughput: {len(all_results)/elapsed:.1f} chunks/sec")
    print(f"Chunks:     {len(all_results)}")
    print(f"Concepts:   {n_concepts}")
    print(f"Relations:  {n_relations}")
    print(f"Examples:   {n_examples}")  # NEW
    print(f"Errors:     {n_errors} ({100*n_errors/len(all_results):.1f}%)")
    print(f"Output:     {output}")
    print(
        f"\nCost estimate: ~${elapsed/3600 * 3.50 * num_gpus:.2f} "
        f"({num_gpus} GPUs @ $3.50/hr)"
    )

    if n_errors > 0:
        print("\nSample errors:")
        error_count = 0
        for r in all_results:
            if r.get("error") and error_count < 5:
                print(f"  - {r['chunk_id']}: {r['error'][:80]}")
                error_count += 1