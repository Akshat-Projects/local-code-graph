import time
import json
import requests
import streamlit as st
from config import settings

# --- Configuration & State ---
st.set_page_config(page_title="LocalGraph AI", layout="wide", page_icon="🧠")

API_BASE = settings.BACKEND_ENDPOINT

if "messages" not in st.session_state:
    st.session_state.messages = []
if "active_repo" not in st.session_state:
    st.session_state.active_repo = "Latest"
if "ingest_job_id" not in st.session_state:
    st.session_state.ingest_job_id = None
if "latest_telemetry" not in st.session_state:
    st.session_state.latest_telemetry = None

# ==========================================
# SIDEBAR: CONTROL ROOM & TELEMETRY
# ==========================================
with st.sidebar:
    st.header("⚙️ Codebase Ingestion")
    
    repo_input = st.text_input("Repository Name", value=st.session_state.active_repo)
    path_input = st.text_input("Local Source Path", value="./my_mock_test")
    
    if st.button("Ingest & Analyze Codebase", use_container_width=True):
        st.session_state.active_repo = repo_input
        try:
            res = requests.post(f"{API_BASE}/ingest", json={"repo_name": repo_input, "target_path": path_input})
            if res.status_code == 202:
                st.session_state.ingest_job_id = res.json()["job_id"]
            else:
                st.error(f"Failed to start ingestion: {res.text}")
        except requests.exceptions.ConnectionError:
            st.error("Cannot connect to API server on localhost:8000")

    # Ingestion Poller
    if st.session_state.ingest_job_id:
        st.divider()
        progress_bar = st.progress(0)
        status_text = st.empty()
        job_id = st.session_state.ingest_job_id
        is_polling = True
        
        while is_polling:
            try:
                status_res = requests.get(f"{API_BASE}/ingest/status/{job_id}").json()
                status = status_res.get("status")
                
                if status == "processing":
                    details = status_res.get("details", {})
                    if details:
                        progress_bar.progress(details.get("progress_percent", 0))
                        status_text.caption(f"Analyzing: {details.get('current_file', '...')}")
                elif status == "completed":
                    progress_bar.progress(100)
                    status_text.success("Ingestion Complete!")
                    st.session_state.ingest_job_id = None
                    is_polling = False
                elif status == "failed":
                    status_text.error("Failed!")
                    is_polling = False
            except Exception:
                is_polling = False
            time.sleep(1)
            
    st.divider()
    st.subheader("⚙️ Generation Settings")
    
    # 0 means "no limit" (we handle this logic in the backend)
    max_tokens_val = st.slider(
        "Max Output Tokens", 
        min_value=0, 
        max_value=2048, 
        value=0, 
        step=128,
        help="Set to 0 for no limit. Lower values keep inference fast."
    )
    

    # --- NEW: REAL-TIME TELEMETRY WIDGET ---
    st.divider()
    st.subheader("📊 Generation Stats")
    
    # Create an empty container so we can inject data into the sidebar LATER
    telemetry_container = st.empty()
    
    def render_telemetry_ui(data):
        """Formats the JSON telemetry into a clean Streamlit Info box."""
        telemetry_container.info(
            f"⏱️ **Time:** {data.get('time_taken')}s\n\n"
            f"⚡ **Speed:** {data.get('tps')} t/s\n\n"
            f"🪙 **Tokens:** {data.get('total_tokens')} "
            f"({data.get('prompt_n')}P + {data.get('predicted_n')}G)"
        )
        
    st.divider()
    if st.button("🗑️ Clear Chat History", use_container_width=True):
        st.session_state.messages = []
        st.session_state.latest_telemetry = None
        st.rerun()

    # Re-render existing telemetry if it exists in state
    if st.session_state.latest_telemetry:
        render_telemetry_ui(st.session_state.latest_telemetry)
    else:
        telemetry_container.caption("Awaiting query...")

# ==========================================
# MAIN PANEL: GRAPH-RAG TERMINAL
# ==========================================
st.title("🧠 LocalGraph RAG Terminal")
st.caption(f"Currently querying isolated graph database: **{st.session_state.active_repo}**")


# --- Helper: Advanced Streaming Generator ---
def stream_llm_response(repo_name: str, question: str, max_tokens: int):
    """Parses JSON-lines stream with a State Machine to perfectly catch fragmented <think> tags."""
    payload = {"repo_name": repo_name, "question": question, "max_tokens": max_tokens if max_tokens > 0 else None}
    try:
        with requests.post(f"{API_BASE}/query", json=payload, stream=True) as response:
            if response.status_code != 200:
                yield f"Error: Backend returned {response.status_code}"
                return
            
            raw_buffer = ""
            is_thinking = False
            
            # Substrings that indicate we might be in the middle of receiving a tag
            partial_starts = ["<", "<t", "<th", "<thi", "<thin", "<think"]
            partial_ends = ["<", "</", "</t", "</th", "</thi", "</thin", "</think"]
            
            for line in response.iter_lines():
                if line:
                    data = json.loads(line.decode('utf-8'))
                    
                    if data["type"] == "chunk":
                        raw_buffer += data["content"]
                        
                        # 1. Catch the START of a thought
                        if "<think>" in raw_buffer and not is_thinking:
                            parts = raw_buffer.split("<think>")
                            text_before = parts[0]
                            
                            # Yield any text that came before the tag
                            if text_before:
                                yield text_before
                                
                            is_thinking = True
                            yield "\n\n> 💭 **Model Thinking...**\n> "
                            raw_buffer = parts[1] # Keep what comes AFTER the tag
                            
                        # 2. Catch the END of a thought
                        if "</think>" in raw_buffer and is_thinking:
                            parts = raw_buffer.split("</think>")
                            text_before = parts[0]
                            
                            # Yield the final thought, ensuring blockquote formatting
                            if text_before:
                                yield text_before.replace("\n", "\n> ")
                                
                            is_thinking = False
                            yield "\n\n---\n\n"
                            raw_buffer = parts[1]
                            
                        # 3. Stream the content safely
                        if is_thinking:
                            # Hold the buffer if we are currently spelling </think>
                            if not any(raw_buffer.endswith(p) for p in partial_ends):
                                # Replace newlines to maintain the gray blockquote styling
                                yield raw_buffer.replace("\n", "\n> ")
                                raw_buffer = ""
                        else:
                            # Hold the buffer if we are currently spelling <think>
                            if not any(raw_buffer.endswith(p) for p in partial_starts):
                                yield raw_buffer
                                raw_buffer = ""
                                
                    elif data["type"] == "telemetry":
                        st.session_state.latest_telemetry = data
                        render_telemetry_ui(data)
                        
            # Flush anything left over when the stream ends
            if raw_buffer:
                if is_thinking:
                    yield raw_buffer.replace("\n", "\n> ")
                else:
                    yield raw_buffer
                        
    except requests.exceptions.ConnectionError:
        yield "Error: Could not connect to API."


# Render chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Chat Input
if prompt := st.chat_input("Ask a question about the codebase architecture..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        response_stream = stream_llm_response(st.session_state.active_repo, prompt, max_tokens_val)
        full_response = st.write_stream(response_stream)
        
    st.session_state.messages.append({"role": "assistant", "content": full_response})
    
    