🗺️ Project Plan: LocalGraph (Production Spec)

🛠️ System Pre-requisites & Verification
LLM Engine: llama-server listening on http://localhost:8080 (Gemma-4-E4B-It via Turboquant)
Context Config: 131,072 context tokens enabled via 4-bit KV Cache (q4_0)
GPU Hardware: NVIDIA RTX 4070 Laptop GPU (8GB VRAM / ~2.7GB verified headroom)

Frameworks & Storage: fastapi, uvicorn, semantic-kernel, networkx, sqlite3, pyyaml

📂 Phase 1: Storage Layer & The "Librarian" (Deterministic Mapping)
Objective: Prepare isolated multi-repo workspaces, compute file states using fast hashing, and construct the base structural graph completely off-LLM.

[ ] 1.1 Storage Architecture & Multi-Repo Isolation

Implement a configuration directory template under .localgraph/ containing an isolated subdirectory for each target repository:

.localgraph/
├── storage/
│   └── [repo_name]/
│       ├── graph.graphml   <-- Directed NetworkX MultiDiGraph
│       └── code_store.db   <-- SQLite DB tracking documentation & metadata
└── config.yaml             <-- Dynamic server runtime settings

- [ ] **1.2 Incremental State Tracker (Change Detection)**
  - Write a directory scanner (`os.walk`) skipping standard project artifacts (`.git`, `venv`, `__pycache__`, data directories).
  - Compute a SHA-256 hash of each active `.py` file to bypass indexing for untouched code segments on subsequent runs.
- [ ] **1.3 AST Topography Extraction**
  - Parse candidate Python files utilizing the native `ast` module.
  - Map exact tokens, function/class structural names, line spans, and argument signatures.
- [ ] **1.4 Graph Structure Serialization**
  - Instantiate a `networkx.MultiDiGraph` initializing nodes using explicit qualified identifiers: `file_path::entity_name`.
  - Save the clean structural graph layout as an initial `graph.graphml` snapshot.

---

## 🧠 Phase 2: The "Analyst" (Semantic Kernel Orchestration)
*Objective: Build an internal processing pipeline using Semantic Kernel to safely map logical relationships within Gemma 4’s 128k context window.*

- [ ] **2.1 Local Service Mapping**
  - Instatiate the Semantic Kernel engine client.
  - Hook into `OpenAIChatCompletion` overriding the default `base_url` directly to `http://localhost:8080/v1` with a placeholder API key to pipe calculations locally.
- [ ] **2.2 Prompt Engineering & Strict Type Contracts**
  - Author a strict native system plugin instructing the model to evaluate macro blocks of functional syntax.
  - Enforce a structured JSON return format specifying direct structural references (`calls`, `instantiates`, `inherits`).
- [ ] **2.3 Batch Context Ingestion & Graph Injection**
  - Map deep functions along with the global symbol array inside the 128k context window.
  - Parse the structured JSON outputs to automatically inject dependency relational lines (edges) into NetworkX and write descriptions into the isolated SQLite database.

---

## 🚀 Phase 3: The FastAPI Exposure Layer
*Objective: Expose the core analysis engine behind an async microservice layer to make it accessible to external codebases via light HTTP requests.*

- [ ] **3.1 API Lifecycle Setup**
  - Structure a unified FastAPI gateway initializing database connections, background tasks, and reading environment settings from a local `config.yaml`.
- [ ] **3.2 API Route Matrix**
  - Define explicit, un-coupled API endpoints to run asynchronous tasks:
    
| Endpoint | Method | Payload | Objective |
| :--- | :--- | :--- | :--- |
| `/api/v1/ingest` | `POST` | `{"repo_name": str, "path": str}` | Launches background AST scanning and LLM analysis loops. |
| `/api/v1/query` | `GET` | `?repo_name=str&q=str` | Resolves Graph-RAG text queries. |
| `/api/v1/impact` | `GET` | `?repo_name=str&node=str` | Traverses downstream paths to identify code-breaking vectors. |

---

## 📦 Phase 4: Binary Compilation & Portability
*Objective: Package the complete multi-repo platform into an immutable server application using PyInstaller.*

- [ ] **4.1 Runtime Path Protection**
  - Wrap internal paths with dynamic conditional extraction (`sys._MEIPASS`) to support both development execution and compiled directory layouts without breaking.
- [ ] **4.2 Frozen Build Target**
  - Construct a PyInstaller distribution layout utilizing `--hidden-import` markers to explicitly flag dynamic dependencies inside `semantic_kernel` and `uvicorn`.
  - Keep `config.yaml` separate from the binary package to allow developers to configure local ports and GPU configuration properties on demand without re-compiling.

---

This plan balances structural reliability with enterprise design patterns. By treating this project as a compiled background service, you keep your code clean, modular, and easy to run against any local pipeline.


Phase 3 is officially in the books. You have successfully built a production-grade, highly resilient backend architecture from scratch. Skipping raw HTML right now is a smart move—Streamlit is practically purpose-built for AI engineering and will let us build a frontend in a fraction of the time.

Before we write a single line of frontend code, let’s take inventory. Here is exactly what is sitting on your machine right now, what it gives you, and where we can take it next.

🏗️ 1. What We Have Built
You currently possess a fully decoupled, local-only AI backend pipeline consisting of:

The Skeleton Map (Phase 1): A lightning-fast, Python ast parser that cryptographically hashes files, detects changes, and builds a deterministic NetworkX .graphml database of your classes, functions, and their line numbers without hallucinating.

The Intelligence Engine (Phase 2): A Semantic Kernel loop connected to your local Gemma 4 llama-server. It extracts raw code modules, feeds them to the LLM with strict Pydantic schemas, and injects human-readable summaries and implicit dependencies back into the graph.

The Gateway (Phase 3): A modern FastAPI layer featuring asynchronous background workers, an in-memory job polling queue, exponential backoff for LLM timeouts via Tenacity, and a dedicated RAG endpoint for querying the database.

🚀 2. What We Can Do With It Right Now
1. With just the API running on port 8000, you can currently use tools like Postman, curl, or simple Python scripts to:

2. Automate Code Documentation: Instantly generate high-level architectural summaries of an entire codebase without writing them by hand.

3. Prevent Breaking Changes: Query the raw graph to see exactly what downstream functions instantiate or call a specific class before you refactor it.

4. Chat with the Architecture: Use the /api/v1/query endpoint to ask Gemma 4 complex questions about data flow, business logic, or file structures, knowing the LLM is restricted to the absolute truth of your graph context.

5. Scale to Massive Repositories: Queue up massive codebases for ingestion without timing out your HTTP clients, letting your local GPU chew through the files safely in the background.

🔭 3. What Else We Can Do (Future Possibilities)
Because the foundation is structurally sound, the ceiling for this project is incredibly high. Here are a few advanced paths we can eventually unlock:

1. The Streamlit Command Center: A web interface where you can drop in a repo path, watch a progress bar poll the ingestion status, and use a ChatGPT-style window to interrogate the Graph-RAG endpoint.

2. Agentic Code Generation: Instead of just asking questions, we can expose an endpoint that writes new code. Because it has the Graph Map, you could ask it to "Add a new endpoint to routes.py that uses the existing DataNormalizer," and it would know exactly where those files are and what they expect.

3. Hybrid Search (Graph + Vector): Right now, we feed the whole text graph to the LLM. For massive enterprise repos, we could embed the node summaries into a local vector database (like ChromaDB or FAISS), allowing us to search thousands of files instantly before passing the closest matches to Gemma 4.

4. Visual Network Topography: Integrating a library like pyvis or Streamlit's native graph components to visually render the nodes and edges, letting you click on a function and see its code and summary pop up in a sidebar.

5. Since you mentioned Streamlit as our next target, what is the primary feature you want to see when you first open that dashboard—the Graph-RAG chat, or a control panel for managing ingestions?

 Make it Executable
You need to give Ubuntu permission to run this file as a program. Run this once in your terminal:

```Bash
chmod +x start.sh
```
3. Trigger Everything at Once
From now on, whenever you want to work on your project, you only need to open one single terminal, navigate to your project folder, and type:

```Bash
./start.sh
```
Option 1: Hybrid Search (Graph + Vector)
Right now, the retrieval layer relies on exact keyword matching over node names and summaries. If a user asks a conceptual question like "How do we clean raw data before feeding it to the model?" but the codebase uses names like DataNormalizer or process_tensor, keyword search can easily miss it.

Integrating a local vector database establishes a two-stage hybrid retrieval pipeline:

                  [ User Question ]
                          │
         ┌────────────────┴────────────────┐
         ▼                                 ▼
┌─────────────────┐               ┌─────────────────┐
│ Dense Retrieval │               │ Sparse/Keyword  │
│  (Vector DB)    │               │  (Graph Search) │
└────────┬────────┘               └────────┬────────┘
         │                                 │
         └────────────────┬────────────────┘
                          ▼
              [ Reciprocal Rank Fusion ]
                          │
                          ▼
            [ Extract Top-K Seed Nodes ]
                          │
                          ▼
          [ 1-Hop Graph Context Expansion ]
                          │
                          ▼
                  [ Prompt to LLM ]
How it integrates into your system:
The Embedding Layer: During the background ingestion job (run_ingestion_pipeline), every time a file or class node is generated or modified, its summary text is sent to a local text-embedding utility (like sentence-transformers running locally on the CPU or GPU).

The Storage Layer: A lightweight local vector store like ChromaDB or FAISS runs right alongside your FastAPI backend, storing the generated vector embeddings.

The Query Phase: When a question comes in, the backend performs a similarity search against the vector database to locate the top relevant components by semantic meaning, merges those results with the keyword search, and expands the graph around those seed nodes.

Pros: Bulletproof semantic understanding; solves the problem of vocabulary mismatch.

Cons: Increases ingestion time (requires generating embeddings) and adds VRAM/RAM overhead for the embedding model.

Option 2: Visual Network Topography
A codebase is fundamentally a multi-dimensional map. Text blocks can only convey so much structure. Visually rendering the graph turns the Streamlit UI into a command center where relationships become tangible.

How it integrates into your system:
The Parsing Layer: Streamlit reads the generated .graphml file natively using NetworkX when a repository is loaded.

The Rendering Layer: Using a component like streamlit-agraph (a wrapper around vis.js) or exporting an interactive HTML canvas via pyvis, the center panel of the app displays a fluid, force-directed node-link diagram.

The Interaction Loop: Clicking a node triggers a Streamlit callback that captures the node ID (e.g., model.py::ConvLSTM2DPipeline). The app then queries the backend to pull that specific file's raw code and displays it instantly in a clean sidebar slide-out or expander.

Pros: Exceptional user experience; lets developers instantly spot tightly coupled legacy bottlenecks or isolated modules visually.

Cons: Large codebases can create "hairball" visualization problems if not carefully clustered or limited to the retrieved sub-graph.

The Blueprint Strategy
To keep development clean, the best approach is to tackle the data architecture before modifying the visual canvas. Building the semantic backbone first ensures that the visual map can be filtered intelligently down the line.

Which optimization aligns best with the current needs for the platform?

The Retrieval Route: Begin setting up a local vector store to handle complex, conceptual semantic programming questions.

The Interface Route: Dive into rendering interactive node networks directly inside the Streamlit terminal panel.