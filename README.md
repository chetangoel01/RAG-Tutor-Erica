# Erica - AI Course Tutor with GraphRAG

An AI-powered tutor for the Introduction to AI course, built with GraphRAG (Graph-based Retrieval Augmented Generation).

## Student Questions (M4 Deliverable)

Example outputs from Erica for three student questions can be found in the `student_questions/` folder:
- **Q1**: "What is attention in transformers and can you provide a python example of how it is used ?"
- **Q2**: "What is CLIP and how it is used in computer vision applications?"
- **Q3**: "Can you explain the variational lower bound and how it relates to Jensen's inequality?"

These PDFs demonstrate Erica's ability to provide comprehensive, well-structured answers using the knowledge graph. See the [Reproducing Student Questions Results](#reproducing-student-questions-results) section for instructions on how to reproduce these results.

## Project Structure

```
erica-tutor/
├── docker-compose.yml      # Container orchestration
├── Dockerfile              # Main app container
├── requirements.txt        # Python dependencies
├── .env.example           # Environment template
├── .env                   # Your local config (git-ignored)
│
├── src/                   # Source code
│   ├── config/           # Configuration management
│   ├── ingestion/        # M2: Data ingestion pipeline
│   ├── graph/            # M3: Knowledge graph construction
│   ├── retrieval/        # M4: Query & retrieval
│   └── generation/       # M4: Answer generation
│
├── notebooks/             # Jupyter notebooks for development
│   ├── 01_verify_environment.ipynb
│   ├── 02_ingestion.ipynb
│   ├── 03a_modal_extraction.ipynb
│   ├── 03b_build_knowledge_graph.ipynb
│   └── 04_embed_concept.ipynb
│
├── data/                  # Data storage
│   ├── raw/              # Raw ingested content
│   ├── processed/        # Processed chunks
│   └── exports/          # Graph exports, visualizations
│
└── config/               # Configuration files
    └── prompts/          # LLM prompt templates
```

## Quick Start (Mac M1 Pro + OpenRouter)

### 1. Prerequisites

- Docker Desktop for Mac (Apple Silicon)
- OpenRouter API key ([get one here](https://openrouter.ai/keys))
- ~8GB RAM allocated to Docker

### 2. Setup

```bash
# Clone and enter directory
cd erica-tutor

# Copy environment file
cp .env.example .env

# Edit .env - ADD YOUR OPENROUTER API KEY
nano .env
# Set: OPENROUTER_API_KEY=sk-or-v1-your-key-here

# Start all services
docker-compose up -d

# Check everything is running
docker-compose ps
```

### 3. Access Points

| Service       | URL                          | Purpose                    |
|---------------|------------------------------|----------------------------|
| **Streamlit App** | **http://localhost:8501** | **Main chat interface** |
| Jupyter       | http://localhost:8888        | Development notebooks      |
| Neo4j Browser | http://localhost:7474        | Knowledge graph visualization |
| Mongo Express | http://localhost:8081        | Document storage browser   |
| ChromaDB      | http://localhost:8000        | Vector DB API             |

### 4. Verify Installation

Open Jupyter at http://localhost:8888 and run `notebooks/01_verify_environment.ipynb` to verify all services are running correctly.

## Milestones

- [ ] **M1**: Environment and Tooling
- [ ] **M2**: Ingestion Pipeline
- [ ] **M3**: Knowledge Graph Construction
- [ ] **M4**: Query and Generation

## Docker Desktop Settings (Mac)

In Docker Desktop > Settings > Resources:
- Memory: 8GB minimum (10GB+ recommended)
- CPU: 4+ cores
- Disk: 20GB+

## Running the Application

### Quick Start

The Docker Compose setup automatically handles data restoration and embedding:

```bash
# Start all Docker services
docker-compose up -d

# Wait for services to be healthy (about 30 seconds)
docker-compose ps
```

**What happens automatically:**
1. If no data exists in MongoDB, the system automatically restores from the latest backup in `data/exports/backup_*`
2. If concepts exist but ChromaDB is empty, embeddings are automatically generated
3. Streamlit app starts and is available at **http://localhost:8501**

The app is ready to use once containers are running!

### Fresh Setup from Scratch

If you need to build the knowledge graph from scratch (e.g., no backup available or want to re-scrape the course website):

#### Step 1: Start Services

```bash
docker-compose up -d
docker-compose ps
```

#### Step 2: Ingest Course Materials (Optional - only if fresh scrape needed)

1. Open Jupyter at http://localhost:8888
2. Run `notebooks/02_ingestion.ipynb` to crawl and ingest course materials
   - This will populate MongoDB with pages, resources, and chunks
   - Processing time: ~5-10 minutes depending on network speed

#### Step 3: Extract Concepts and Build Knowledge Graph

1. **Export chunks** from MongoDB:
   ```bash
   docker-compose exec app python src/graph/export_chunks.py
   ```

2. **Run entity extraction** (requires Modal account and API key):
   ```bash
   # Install Modal CLI if needed: pip install modal
   modal run src/graph/extract.py --input data/exports/chunks.json --output data/exports/extractions.json
   ```
   - This extracts concepts, relations, and examples using Qwen3-32B on Modal's GPUs
   - Processing time: ~10-30 minutes depending on chunk count

3. **Import extractions** and build knowledge graph:
   - Run `notebooks/03b_build_knowledge_graph.ipynb` to:
     - Import extractions into MongoDB
     - Deduplicate concepts
     - Build Neo4j knowledge graph
     - Processing time: ~2-5 minutes

#### Step 4: Embed Concepts for Semantic Search

Run `notebooks/04_embed_concept.ipynb` to:
- Embed all concepts into ChromaDB for semantic search
- Processing time: ~1-2 minutes

#### Step 5: Create Backup (Recommended)

After building the knowledge graph, create a backup for future use:

```bash
python scripts/backup_databases.py
```

This creates a backup in `data/exports/backup_YYYYMMDD_HHMMSS/` that you can restore later.

### Using the Application

1. Open http://localhost:8501 in your browser
2. Ask questions about AI/ML concepts in the chat interface
3. Adjust settings in the sidebar:
   - **Semantic search results**: Number of seed concepts to retrieve (default: 5)
   - **Prerequisite depth**: How many levels of prerequisites to include (default: 2)
   - **Max concepts**: Maximum concepts in the explanation path (default: 15)
4. View retrieved context by expanding "📚 View Retrieved Context" to see:
   - Seed concepts found via semantic search
   - Explanation order (prerequisite path)
   - Number of resources and examples retrieved

## System Prompts

Erica uses carefully crafted prompts for different tasks. Here are the key prompts used in the system:

### Answer Generation Prompt

Used when generating responses to student questions (`src/generation/answer_generator.py`):

**System Prompt:**
```
You are Erica, an enthusiastic and knowledgeable AI tutor for an Introduction to AI course at a university.

## Your Personality
- You are patient, encouraging, and passionate about teaching AI/ML concepts
- You celebrate when students ask good questions
- You use analogies and real-world examples to make complex ideas accessible
- You're thorough but never condescending

## Your Teaching Style
1. **Start with intuition**: Before diving into technical details, explain WHY a concept matters and give an intuitive understanding
2. **Build from foundations**: Always explain prerequisite concepts first, building a solid foundation before advancing
3. **Use concrete examples**: Illustrate abstract concepts with specific examples, code snippets, or mathematical walkthroughs
4. **Connect the dots**: Show how concepts relate to each other and to the broader field of AI
5. **Summarize key points**: End with a concise summary of the main takeaways

## Response Format
- Use clear headings and subheadings to organize your explanation
- Include mathematical notation when relevant (use LaTeX: \( inline \) or \[ block \])
- Provide code examples when they help illustrate a concept
- Cite resources using [Resource: URL] format when referencing specific materials
- Aim for comprehensive explanations - don't rush through important details

## Important Guidelines
- If a concept has prerequisites, explain them first
- Use the examples from the knowledge graph to illustrate points
- When explaining algorithms, walk through them step-by-step
- If there are common misconceptions, address them
- Encourage the student and suggest related topics they might explore next

Remember: Your goal is not just to answer the question, but to help the student truly understand the concept and how it fits into the bigger picture of AI/ML.
```

**User Prompt Template:**
```
## Student's Question
{query}

## Knowledge Graph Context
{context}

---

Please provide a thorough, well-structured explanation that:
1. Starts with an intuitive overview of why this topic matters
2. Explains any prerequisite concepts the student needs to understand first
3. Dives deep into the main topic with examples and mathematical details where appropriate
4. Uses the provided examples to illustrate key points
5. Cites relevant resources for further reading
6. Ends with a summary and suggestions for what to learn next

Take your time and be comprehensive - the student wants to truly understand this topic.
```

### Entity Extraction Prompt

Used for extracting concepts, relations, and examples from course materials (`src/graph/extract.py`):

**System Prompt:**
```
You are an expert at extracting AI/ML concepts from educational content.
You always respond with valid JSON only, no markdown, no explanations, no thinking.
```

**User Prompt Template:**
```
Extract AI/ML concepts, their relationships, and worked examples from this educational text.

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
{"concepts": [{"title": "...", "definition": "...", "difficulty": "...", "aliases": []}], "relations": [{"source": "...", "target": "...", "relation_type": "..."}], "examples": [{"text": "...", "concept": "...", "example_type": "..."}]}

If nothing found: {"concepts": [], "relations": [], "examples": []}

TEXT:
{text}
```

## Reproducing Student Questions Results

The `student_questions/` folder contains example outputs from Erica for three questions:

1. **Q1**: "What is attention in transformers and can you provide a python example of how it is used ?"
2. **Q2**: "What is CLIP and how it is used in computer vision applications?"
3. **Q3**: "Can you explain the variational lower bound and how it relates to Jensen's inequality?"

### To Reproduce These Results:

1. **Start the application** - Docker Compose will automatically restore from backup if available

2. **Access the Streamlit app** at http://localhost:8501

3. **Ask each question** exactly as written:
   - Copy and paste the question from the PDF filename into the chat input
   - Wait for the retrieval and generation to complete (typically 10-30 seconds per question)

4. **Compare results**:
   - The generated answers should be similar in structure and content to the PDFs in `student_questions/`
   - Note: Exact text may vary slightly due to LLM non-determinism, but the concepts and explanations should match

5. **Export results** (optional):
   - Use your browser's print function (Cmd+P / Ctrl+P) to save the conversation as PDF
   - Or take screenshots of the chat interface

### Data Backup and Export

You can backup your complete database state (MongoDB, Neo4j, ChromaDB) for easy restoration:

```bash
# Create a backup
python scripts/backup_databases.py

# Backups are saved to: data/exports/backup_YYYYMMDD_HHMMSS/
```

To restore from a backup:
```bash
python scripts/restore_databases.py data/exports/backup_YYYYMMDD_HHMMSS
```

See `scripts/README.md` for more details on backup/restore operations.

### Troubleshooting

If answers don't match expected results:

- **Check knowledge graph**: Verify concepts are in Neo4j at http://localhost:7474
  - Login: `neo4j` / `erica_password_123`
  - Run: `MATCH (n:Concept) RETURN count(n)`
  
- **Check embeddings**: Verify concepts are embedded in ChromaDB
  - Check app logs: `docker-compose logs app | grep ChromaDB`
  
- **Check MongoDB**: Verify chunks and extractions exist
  - Access Mongo Express at http://localhost:8081
  - Check `chunks` and `extractions` collections

- **Re-run extraction**: If concepts are missing, re-run the extraction pipeline (see "Fresh Setup from Scratch" above)

## Development Workflow

1. Start services: `docker-compose up -d`
2. Open Jupyter: http://localhost:8888
3. Work in notebooks for experimentation
4. Move stable code to `src/` modules
5. Test in Streamlit app: http://localhost:8501
6. Commit often with meaningful messages
