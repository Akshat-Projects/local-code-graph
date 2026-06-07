#!/bin/bash

echo "Initializing LocalGraph RAG Ecosystem..."
echo "============================================"

# Function to handle Ctrl+C (SIGINT)
cleanup() {
    echo -e "\n Ctrl+C detected. Shutting down all services..."
    
    # Kill the processes using their stored PIDs
    if [ -n "$LLM_PID" ]; then kill $LLM_PID 2>/dev/null; fi
    if [ -n "$API_PID" ]; then kill $API_PID 2>/dev/null; fi
    if [ -n "$UI_PID" ]; then kill $UI_PID 2>/dev/null; fi
    
    echo "Graceful shutdown complete."
    exit 0
}

# Trap the SIGINT signal (Ctrl+C) and route it to the cleanup function
trap cleanup SIGINT

# 1. Boot the LLM (Subshell is used so we don't lose our current directory)
# Note: reasoning-budget is set to 2048 to avoid endless thinking loops. 
# You can change it to -1 to give the model completely free rein.
echo "[1/3] Booting Gemma 4 (llama-server)..."
(cd ~/llama.cpp/build && ./bin/llama-server \
  -m ~/llmhost/model/gemma-4-E4B-it-Q4_K_M.gguf \
  -ngl 999 \
  -c 131072 \
  -fa on \
  -ctk q4_0 \
  -ctv q4_0 \
  --host 0.0.0.0 \
  --port 8080 \
  --jinja \
  --pooling rank \
  --reasoning-budget 2048 \
  --reasoning off) &

# (cd ~/llama.cpp/build && ./bin/llama-server -m ~/llmhost/model/gemma-4-E4B-it-Q4_K_M.gguf -ngl 999 -c 131072 -fa on -ctk q4_0 -ctv q4_0 --host 0.0.0.0 --port 8080 --jinja --pooling rank) &
LLM_PID=$!

# Give the GPU a few seconds to load the 131k context weights into VRAM
sleep 30

# 2. Boot the FastAPI Backend
echo "[2/3] Booting FastAPI Backend..."
uv run main.py &
API_PID=$!

sleep 10

# 3. Boot the Streamlit UI
echo "[3/3] Booting Streamlit Command Center..."
uv run streamlit run app.py &
UI_PID=$!

sleep 3

echo "============================================"
echo "All systems operational!"
echo "UI is available at http://localhost:8501"
echo "Press Ctrl+C to terminate all services."
echo "============================================"

# Wait indefinitely so the script doesn't exit, keeping the traps alive
wait