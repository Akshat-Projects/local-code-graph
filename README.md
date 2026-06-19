# Local-Code-Graph RAG 

A fully private, local Graph-RAG (Retrieval-Augmented Generation) system designed to map, understand, and query large codebases without sending your proprietary code to the cloud.

##  Features

* **100% Local Inference:** Powered by `llama.cpp` and Semantic Kernel, routing strictly to your local GPU (optimized for models like Gemma 4).
* **Codebase Semantic Mapping:** Uses `networkx` to build a structural and semantic GraphML representation of your repository, understanding how files and classes interact.
* **Dynamic Sub-Graph Retrieval:** Prevents memory bandwidth bottlenecks (KV Cache overflow) by extracting only the Top-K relevant nodes and their 1-hop neighbors before injecting them into the LLM context.
* **Asynchronous & Highly Optimized:** Heavy AST parsing, Leiden community clustering, and graph querying are offloaded to background threads. The FastAPI event loop remains unblocked, providing extremely low-latency routing and ingestion orchestration.
* **Parallel LLM Analysis:** During Phase 2 knowledge graph enrichment, multiple LLM requests are batched and executed concurrently (via semaphores and `asyncio.gather`), drastically reducing overall indexing time.
* **Graph Caching Mechanism:** Prevents redundant XML parsing across queries by caching the parsed networkx graph in memory, reducing system overhead on subsequent questions.
* **Streaming Streamlit UI:** A responsive chat interface that natively parses and renders fragmented JSON-Lines streams.
* **Reasoning Tag Parser:** Includes a custom state-machine to perfectly intercept and render `<think>` tags from reasoning models into clean Markdown blockquotes.
* **Real-Time Telemetry:** Tracks and displays generation stats (Tokens Per Second, Time Taken, Prompt vs. Generated Tokens) instantly in the UI.

##  Architecture

The system is decoupled into two primary services:

1. **The Backend Engine (FastAPI):**
   - Handles asynchronous codebase ingestion and sequential AST parsing via an optimized background worker (`asyncio.to_thread`).
   - Executes parallel Phase 2 community clustering and LLM knowledge enrichment using async Semaphores.
   - Manages the NetworkX graph database with centralized caching to prevent redundant I/O.
   - Executes dynamic Graph Retrieval and streams JSONL responses via Semantic Kernel.
2. **The Command Center (Streamlit):**
   - Provides a unified dashboard for triggering background ingestion jobs with real-time progress polling.
   - Manages the streaming chat interface, telemetry UI, and token limit controls.

##  Getting Started

### Prerequisites
* Python 3.12+
* [uv](https://github.com/astral-sh/uv) package manager
* `llama.cpp` (`llama-server`) installed and accessible in your path.

### Unified Bootstrapping (`./start.sh`)

To simplify launching the private Graph-RAG ecosystem, a single unified startup script is provided. This script boots the LLM engine, FastAPI API, and Streamlit client in parallel and manages graceful shutdowns:

```bash
# Make the script executable (if needed)
chmod +x start.sh

# Start all services
./start.sh
```

The script performs the following operations:
1. **Local Inference Server:** Boots `llama-server` on port `8080`, loading your local GGUF weights (optimized for Gemma 4) with GPU offloading (`-ngl 999`) and a high context limit (`131072`).
2. **FastAPI Backend:** Boots the backend engine on http://localhost:8000 after allowing the LLM a 30-second window to load weights into VRAM.
3. **Streamlit UI Command Center:** Launches the frontend on http://localhost:8501.

*Note: Pressing `Ctrl+C` triggers a shell trap that sends SIGINT to all spawned services, terminating background tasks cleanly and preventing zombie processes.*

### Alternative Manual Boot

If you prefer starting services individually, run them in separate terminal windows:

1. **Boot the LLM Engine:**
   ```bash
   cd ~/llama.cpp/build
   ./bin/llama-server -m ~/llmhost/model/gemma-4-E4B-it-Q4_K_M.gguf -ngl 999 -c 131072 -fa on -ctk q4_0 -ctv q4_0 --host 0.0.0.0 --port 8080 --jinja --pooling rank
   ```
2. **Start the Backend API:**
   ```bash
   uv run main.py
   ```
3. **Launch the Streamlit UI:**
   ```bash
   uv run streamlit run app.py
   ```

---

## 🛠️ System Flow & Edge-Case Optimizations

During integration, the following core architecture and performance challenges were addressed to ensure stable local operation:

### 1. Persistent Threaded Streaming (UI Concurrency)
* **Challenge:** By default, Streamlit script execution is synchronous and re-runs from top to bottom on any UI interaction (e.g., resizing, clicking toggles). If a stream from the backend is running during a rerun, the HTTP stream gets severed, aborting the generation midway and starting over.
* **Optimization:** Decoupled UI interactions from network fetching by offloading the stream consumption to a background Python `threading.Thread`. The background runner consumes the backend's JSON-Lines stream and writes incoming tokens/telemetry directly to a thread-safe list in `st.session_state`. The UI reads from this buffer asynchronously, keeping the network pipeline alive across reruns.

### 2. State-Preserved View Navigation & Autorefresh Locking
* **Challenge:** Streamlit `st.tabs` unmounts inactive tab DOMs on switch. To show the streaming LLM chat response, a `500ms` auto-refresh (`st_autorefresh`) is required. However, if the user switches to view the `vis.js` interactive canvas, the autorefresh triggers a constant reload of the map iframe, locking the UI thread and freezing web rendering.
* **Optimization:** Replaced client-side tabs with a top-level `st.radio` control acting as a view-state selector. The `st_autorefresh` is programmatically wrapped to trigger **only** when the user is actively viewing the `💬 AI Assistant` tab *and* a stream is in progress. Switching to the `🕸️ Interactive Architecture Map` suspends refreshes, allowing smooth canvas rendering and preservation of user zoom/pan states.

### 3. Flicker-Free Layouts (React VDOM Stability)
* **Challenge:** Rendering streaming text inside dynamic placeholders like `st.empty()` results in repeated DOM node recreation. This leads to heavy layout flickering, visual shifts, and scrollbar bouncing as the container heights collapse.
* **Optimization:** Eliminated empty placeholder wrappers for standard content generation. Streamlit's React implementation natively diffs the updated markdown string in-place. Completed thought cycles are enclosed inside structured complete statuses (`st.status`), ensuring stable container sizing.

### 4. Config & Metadata Ingestion
* **Challenge:** Critical architecture clues reside in metadata files like `pyproject.toml` and `requirements.txt`, which are traditionally skipped by standard AST parsers.
* **Optimization:** Extended AST analysis boundaries by adding `.toml` and `.txt` extensions to the ingestion parser's supported extensions. This enables parsing configuration files to extract third-party library dependencies and map infrastructure linkages.

---

## 💻 Tech Stack

* **Frontend:** Streamlit, Requests, vis.js (via iframe)
* **Backend:** FastAPI, Uvicorn, Semantic Kernel, NetworkX, Leiden Community Clustering
* **Local Inference:** llama.cpp, Gemma 4 (Reasoning Model)
---
More features coming soon....