# Local-Code-Graph RAG 

A fully private, local Graph-RAG (Retrieval-Augmented Generation) system designed to map, understand, and query large codebases without sending your proprietary code to the cloud.

##  Features

* **100% Local Inference:** Powered by `llama.cpp` and Semantic Kernel, routing strictly to your local GPU (optimized for models like Gemma 4).
* **Codebase Semantic Mapping:** Uses `networkx` to build a structural and semantic GraphML representation of your repository, understanding how files and classes interact.
* **Dynamic Sub-Graph Retrieval:** Prevents memory bandwidth bottlenecks (KV Cache overflow) by extracting only the Top-K relevant nodes and their 1-hop neighbors before injecting them into the LLM context.
* **Streaming Streamlit UI:** A responsive chat interface that natively parses and renders fragmented JSON-Lines streams.
* **Reasoning Tag Parser:** Includes a custom state-machine to perfectly intercept and render `<think>` tags from reasoning models into clean Markdown blockquotes.
* **Real-Time Telemetry:** Tracks and displays generation stats (Tokens Per Second, Time Taken, Prompt vs. Generated Tokens) instantly in the UI.

##  Architecture

The system is decoupled into two primary services:

1. **The Backend Engine (FastAPI):** - Handles asynchronous codebase ingestion and AST parsing.
   - Manages the NetworkX graph database.
   - Executes dynamic Graph Retrieval and streams JSONL responses via Semantic Kernel.
2. **The Command Center (Streamlit):**
   - Provides a unified dashboard for triggering background ingestion jobs with real-time progress polling.
   - Manages the streaming chat interface, telemetry UI, and token limit controls.

##  Getting Started

### Prerequisites
* Python 3.12+
* [uv](https://github.com/astral-sh/uv) package manager
* `llama.cpp` (`llama-server`) installed and accessible in your path.

### 1. Boot the LLM Engine
Start your local inference server (e.g., Gemma 4).

```bash
cd ~/llama.cpp/build

./bin/llama-server -m ~/llmhost/model/gemma-4-E4B-it-Q4_K_M.gguf -ngl 999 -c 131072 -fa on -ctk q4_0 -ctv q4_0 --host 0.0.0.0 --port 8080 --jinja --pooling rank
```

### 2. Start the Backend API
In a new terminal, launch the FastAPI server:

```bash
uv run main.py
```
(The server will boot on http://localhost:8000)

### 3. Launch the Streamlit UI
In a third terminal, start the frontend dashboard:

```Bash
uv run streamlit run app.py
```
(The UI will open at http://localhost:8501)

 Usage
---
Ingest a Repository: Use the left sidebar in the UI to point the system at a local folder. Click "Ingest & Analyze" and watch the real-time progress bar as the system builds the GraphML map.

Set Parameters: Adjust the Max Output Tokens slider to control the verbosity of the model and keep local inference snappy.

Query your Code: Ask complex architectural questions. The backend will filter the graph, and the frontend will beautifully render the model's reasoning process and final answer.

 Tech Stack
---
Frontend: Streamlit, Requests

Backend: FastAPI, Uvicorn, Semantic Kernel, NetworkX

AI: llama.cpp, Gemma 4