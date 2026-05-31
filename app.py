# import time
import json
import requests
import streamlit as st
from config import settings
from streamlit_autorefresh import st_autorefresh

# --- Configuration & State ---
st.set_page_config(page_title="LocalGraph AI", layout="wide", page_icon="🧠")

API_BASE = settings.BACKEND_ENDPOINT

if "messages" not in st.session_state:
    st.session_state.messages = []
if "active_repo" not in st.session_state:
    st.session_state.active_repo = "Latest"
if "target_path" not in st.session_state:
    st.session_state.target_path = "./my_mock_test"
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
    path_input = st.text_input("Local Source Path", key="target_path")
    
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
        # is_polling = True
        st_autorefresh(interval=1000, key="ingestion_state_refresh")
        

        try:
            status_res = requests.get(
                f"{API_BASE}/ingest/status/{job_id}"
            ).json()

            status = status_res.get("status")

            if status == "processing":
                details = status_res.get("details", {})

                if details:
                    progress_bar.progress(
                        details.get("progress_percent", 0)
                    )
                    status_text.caption(
                        f"Analyzing: "
                        f"{details.get('current_file', '...')}"
                    )

            elif status == "completed":
                progress_bar.progress(100)
                status_text.success(
                    "Ingestion Complete!"
                )
                st.session_state.ingest_job_id = None
                st.rerun()

            elif status == "failed":
                status_text.error("Failed!")
                st.session_state.ingest_job_id = None
                st.rerun()

        except Exception as e:
            status_text.error(
                f"Polling failed: {e}"
            )
        # while is_polling:
        #     try:
        #         status_res = requests.get(f"{API_BASE}/ingest/status/{job_id}").json()
        #         status = status_res.get("status")
                
        #         if status == "processing":
        #             details = status_res.get("details", {})
        #             if details:
        #                 progress_bar.progress(details.get("progress_percent", 0))
        #                 status_text.caption(f"Analyzing: {details.get('current_file', '...')}")
        #         elif status == "completed":
        #             progress_bar.progress(100)
        #             status_text.success("Ingestion Complete!")
        #             st.session_state.ingest_job_id = None
        #             is_polling = False
        #         elif status == "failed":
        #             status_text.error("Failed!")
        #             is_polling = False
        #     except Exception:
        #         is_polling = False
        #     time.sleep(1)
            
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
    
    # --- REAL-TIME TELEMETRY WIDGET ---
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
def stream_llm_response(repo_name: str, question: str, max_tokens: int, target_path: str):
    """Streams text, telemetry, and natively parsed reasoning API fields."""
    payload = {
        "repo_name": repo_name, 
        "question": question, 
        "max_tokens": max_tokens if max_tokens > 0 else None,
        "target_path": target_path
    }
    try:
        with requests.post(f"{API_BASE}/query", json=payload, stream=True) as response:
            if response.status_code != 200:
                yield "error", f"Error: Backend returned {response.status_code}"
                return
            
            for line in response.iter_lines():
                if not line:
                    continue
                
                data = json.loads(line.decode('utf-8'))
                
                if data["type"] == "chunk":
                    yield "text", data["content"]
                    
                elif data["type"] == "thought":
                    yield "thought", data["content"]
                    
                elif data["type"] == "telemetry":
                    st.session_state.latest_telemetry = data
                    render_telemetry_ui(data)
                    
    except Exception as e:
        yield "error", f"Connection error: {str(e)}"


# ==========================================
# CHAT INTERFACE & RENDER LOOP
# ==========================================

# 1. Render historical messages from session state
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg.get("thought"):
            with st.expander("💭 Thought Process", expanded=False):
                st.markdown(msg["thought"])
        st.markdown(msg["content"])

# 2. Catch new user input
if prompt := st.chat_input("Ask a question about your codebase..."):
    # Display user message
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    # Process Assistant Response
    # Process Assistant Response
    with st.chat_message("assistant"):
        thought_container = st.status("💭 Thinking...", expanded=True)
        thought_placeholder = thought_container.empty()
        thought_text = ""
        
        answer_container = st.empty()
        answer_text = ""
        
        is_thinking = False
        
        # Consume the advanced stream generator
        for event_type, chunk in stream_llm_response(
            st.session_state.active_repo, prompt, max_tokens_val, st.session_state.target_path
        ):
            if event_type == "thought":
                is_thinking = True
                thought_text += chunk
                # thought_container.markdown(thought_text)
                # --- FIX: Update the placeholder, do not append to the container! ---
                thought_placeholder.markdown(thought_text)
                
            elif event_type == "text":
                if is_thinking:
                    # The moment we receive standard text, the thinking phase is over!
                    thought_container.update(label="💭 Thought process complete", state="complete", expanded=False)
                    is_thinking = False
                    
                answer_text += chunk
                answer_container.markdown(answer_text)
                
            elif event_type == "error":
                st.error(chunk)

        # Save complete generation to session state history
        st.session_state.messages.append({
            "role": "assistant",
            "thought": thought_text if thought_text else None,
            "content": answer_text
        })
