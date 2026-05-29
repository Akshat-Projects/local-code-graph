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
# def stream_llm_response(repo_name: str, question: str, max_tokens: int, target_path: str):
#     """Parses JSON-lines stream with a rolling buffer to perfectly catch fragmented <think> tags."""
#     payload = {
#         "repo_name": repo_name, 
#         "question": question, 
#         "max_tokens": max_tokens if max_tokens > 0 else None,
#         "target_path": target_path
#     }
#     try:
#         with requests.post(f"{API_BASE}/query", json=payload, stream=True) as response:
#             if response.status_code != 200:
#                 yield "error", f"Error: Backend returned {response.status_code}"
#                 return
            
#             # Use a rolling buffer to assemble fragmented text characters
#             raw_buffer = ""
#             is_thinking = False
            
#             # Structural substrings that indicate a tag boundary is forming
#             partial_starts = ["<", "<t", "<th", "<thi", "<thin", "<think"]
#             partial_ends = ["<", "</", "</t", "</th", "</thi", "</thin", "</think"]
            
#             for line in response.iter_lines():
#                 if not line:
#                     continue
                
#                 data = json.loads(line.decode('utf-8'))
                
#                 print(f"RAW PAYLOAD: {data}", flush=True)
                
#                 if data["type"] == "chunk":
#                     raw_buffer += data["content"]
                    
#                     # 1. Catch the START of a thought (<think>)
#                     if "<think>" in raw_buffer and not is_thinking:
#                         parts = raw_buffer.split("<think>")
#                         text_before = parts[0]
                        
#                         # Yield any text that arrived right before the tag
#                         if text_before:
#                             yield "text", text_before
                            
#                         is_thinking = True
#                         raw_buffer = parts[1] # Retain anything that arrived after the tag
                        
#                     # 2. Catch the END of a thought (</think>)
#                     if "</think>" in raw_buffer and is_thinking:
#                         parts = raw_buffer.split("</think>")
#                         text_before = parts[0]
                        
#                         # Yield the final piece of the thought loop
#                         if text_before:
#                             yield "thought", text_before
                            
#                         is_thinking = False
#                         yield "thought_end", ""
#                         raw_buffer = parts[1] # Retain anything that arrived after closing tag
                        
#                     # 3. Stream the content incrementally
#                     if is_thinking:
#                         # Hold the buffer back if it's currently spelling out </think>
#                         if not any(raw_buffer.endswith(p) for p in partial_ends):
#                             yield "thought", raw_buffer
#                             raw_buffer = ""
#                     else:
#                         # Hold the buffer back if it's currently spelling out <think>
#                         if not any(raw_buffer.endswith(p) for p in partial_starts):
#                             yield "text", raw_buffer
#                             raw_buffer = ""
                            
#                 elif data["type"] == "telemetry":
#                     st.session_state.latest_telemetry = data
#                     render_telemetry_ui(data)
                    
#     except Exception as e:
#         yield "error", f"Connection error: {str(e)}"

# def stream_llm_response(repo_name: str, question: str, max_tokens: int, target_path: str):
#     """Yields typed events (thinking vs text) so the UI can route them to different containers."""
#     payload = {
#         "repo_name": repo_name, 
#         "question": question, 
#         "max_tokens": max_tokens if max_tokens > 0 else None,
#         "target_path": target_path
#     }
#     try:
#         with requests.post(f"{API_BASE}/query", json=payload, stream=True) as response:
#             if response.status_code != 200:
#                 yield "error", f"Error: Backend returned {response.status_code}"
#                 return
            
#             is_thinking = False
#             for line in response.iter_lines():
#                 if not line:
#                     continue
                
#                 data = json.loads(line.decode('utf-8'))
                
#                 if data["type"] == "chunk":
#                     token = data["content"]
                    
#                     # Intercept tags to toggle states
#                     if "<think>" in token:
#                         is_thinking = True
#                         token = token.replace("<think>", "")
#                     if "</think>" in token:
#                         is_thinking = False
#                         token = token.replace("</think>", "")
#                         yield "thought_end", ""
                    
#                     if token:  # If there is content left to show
#                         if is_thinking:
#                             yield "thought", token
#                         else:
#                             yield "text", token
                            
#                 elif data["type"] == "telemetry":
#                     st.session_state.latest_telemetry = data
#                     render_telemetry_ui(data)
#     except Exception as e:
#         yield "error", f"Connection error: {str(e)}"


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
    # with st.chat_message("assistant"):
    #     # Setup separate containers for thoughts and final markdown answer
    #     thought_container = st.status("💭 Thinking...", expanded=True)
    #     thought_text = ""
        
    #     answer_container = st.empty()
    #     answer_text = ""
        
    #     # Consume the advanced stream generator
    #     for event_type, chunk in stream_llm_response(
    #         st.session_state.active_repo, prompt, max_tokens_val, st.session_state.target_path
    #     ):
    #         if event_type == "thought":
    #             thought_text += chunk
    #             thought_container.markdown(thought_text)
    #         elif event_type == "thought_end":
    #             # Collapse the container once thinking is done
    #             thought_container.update(label="💭 Thought process complete", state="complete", expanded=False)
    #         elif event_type == "text":
    #             answer_text += chunk
    #             answer_container.markdown(answer_text)
    #         elif event_type == "error":
    #             st.error(chunk)

    #     # Save complete generation to session state history
    #     st.session_state.messages.append({
    #         "role": "assistant",
    #         "thought": thought_text if thought_text else None,
    #         "content": answer_text
    #     })

# import time
# import json
# import requests
# import streamlit as st
# from config import settings

# # --- Configuration & State ---
# st.set_page_config(page_title="LocalGraph AI", layout="wide", page_icon="🧠")

# API_BASE = settings.BACKEND_ENDPOINT

# if "messages" not in st.session_state:
#     st.session_state.messages = []
# if "active_repo" not in st.session_state:
#     st.session_state.active_repo = "Latest"
# if "target_path" not in st.session_state:
#     st.session_state.target_path = "./my_mock_test"
# if "ingest_job_id" not in st.session_state:
#     st.session_state.ingest_job_id = None
# if "latest_telemetry" not in st.session_state:
#     st.session_state.latest_telemetry = None

# # ==========================================
# # SIDEBAR: CONTROL ROOM & TELEMETRY
# # ==========================================
# with st.sidebar:
#     st.header("⚙️ Codebase Ingestion")
    
#     repo_input = st.text_input("Repository Name", value=st.session_state.active_repo)
#     path_input = st.text_input("Local Source Path", key="target_path")
    
#     if st.button("Ingest & Analyze Codebase", use_container_width=True):
#         st.session_state.active_repo = repo_input
#         try:
#             res = requests.post(f"{API_BASE}/ingest", json={"repo_name": repo_input, "target_path": path_input})
#             if res.status_code == 202:
#                 st.session_state.ingest_job_id = res.json()["job_id"]
#             else:
#                 st.error(f"Failed to start ingestion: {res.text}")
#         except requests.exceptions.ConnectionError:
#             st.error("Cannot connect to API server on localhost:8000")

#     # Ingestion Poller
#     if st.session_state.ingest_job_id:
#         st.divider()
#         progress_bar = st.progress(0)
#         status_text = st.empty()
#         job_id = st.session_state.ingest_job_id
#         is_polling = True
        
#         while is_polling:
#             try:
#                 status_res = requests.get(f"{API_BASE}/ingest/status/{job_id}").json()
#                 status = status_res.get("status")
                
#                 if status == "processing":
#                     details = status_res.get("details", {})
#                     if details:
#                         progress_bar.progress(details.get("progress_percent", 0))
#                         status_text.caption(f"Analyzing: {details.get('current_file', '...')}")
#                 elif status == "completed":
#                     progress_bar.progress(100)
#                     status_text.success("Ingestion Complete!")
#                     st.session_state.ingest_job_id = None
#                     is_polling = False
#                 elif status == "failed":
#                     status_text.error("Failed!")
#                     is_polling = False
#             except Exception:
#                 is_polling = False
#             time.sleep(1)
            
#     st.divider()
#     st.subheader("⚙️ Generation Settings")
    
#     # 0 means "no limit" (we handle this logic in the backend)
#     max_tokens_val = st.slider(
#         "Max Output Tokens", 
#         min_value=0, 
#         max_value=2048, 
#         value=0, 
#         step=128,
#         help="Set to 0 for no limit. Lower values keep inference fast."
#     )
    

#     # --- NEW: REAL-TIME TELEMETRY WIDGET ---
#     st.divider()
#     st.subheader("📊 Generation Stats")
    
#     # Create an empty container so we can inject data into the sidebar LATER
#     telemetry_container = st.empty()
    
#     def render_telemetry_ui(data):
#         """Formats the JSON telemetry into a clean Streamlit Info box."""
#         telemetry_container.info(
#             f"⏱️ **Time:** {data.get('time_taken')}s\n\n"
#             f"⚡ **Speed:** {data.get('tps')} t/s\n\n"
#             f"🪙 **Tokens:** {data.get('total_tokens')} "
#             f"({data.get('prompt_n')}P + {data.get('predicted_n')}G)"
#         )
        
#     st.divider()
#     if st.button("🗑️ Clear Chat History", use_container_width=True):
#         st.session_state.messages = []
#         st.session_state.latest_telemetry = None
#         st.rerun()

#     # Re-render existing telemetry if it exists in state
#     if st.session_state.latest_telemetry:
#         render_telemetry_ui(st.session_state.latest_telemetry)
#     else:
#         telemetry_container.caption("Awaiting query...")

# # ==========================================
# # MAIN PANEL: GRAPH-RAG TERMINAL
# # ==========================================
# st.title("🧠 LocalGraph RAG Terminal")
# st.caption(f"Currently querying isolated graph database: **{st.session_state.active_repo}**")


# # --- Helper: Advanced Streaming Generator ---
# def stream_llm_response(repo_name: str, question: str, max_tokens: int, target_path: str):
#     """Parses JSON-lines stream with a State Machine to perfectly catch fragmented <think> tags."""
#     payload = {
#         "repo_name": repo_name, 
#         "question": question, 
#         "max_tokens": max_tokens if max_tokens > 0 else None,
#         "target_path": target_path
#         }
#     try:
#         with requests.post(f"{API_BASE}/query", json=payload, stream=True) as response:
#             if response.status_code != 200:
#                 yield f"Error: Backend returned {response.status_code}"
#                 return
            
#             raw_buffer = ""
#             is_thinking = False
            
#             # Substrings that indicate we might be in the middle of receiving a tag
#             partial_starts = ["<", "<t", "<th", "<thi", "<thin", "<think"]
#             partial_ends = ["<", "</", "</t", "</th", "</thi", "</thin", "</think"]
            
#             for line in response.iter_lines():
#                 if line:
#                     data = json.loads(line.decode('utf-8'))
                    
#                     if data["type"] == "chunk":
#                         raw_buffer += data["content"]
                        
#                         # 1. Catch the START of a thought
#                         if "<think>" in raw_buffer and not is_thinking:
#                             parts = raw_buffer.split("<think>")
#                             text_before = parts[0]
                            
#                             # Yield any text that came before the tag
#                             if text_before:
#                                 yield text_before
                                
#                             is_thinking = True
#                             yield "\n\n> 💭 **Model Thinking...**\n> "
#                             raw_buffer = parts[1] # Keep what comes AFTER the tag
                            
#                         # 2. Catch the END of a thought
#                         if "</think>" in raw_buffer and is_thinking:
#                             parts = raw_buffer.split("</think>")
#                             text_before = parts[0]
                            
#                             # Yield the final thought, ensuring blockquote formatting
#                             if text_before:
#                                 yield text_before.replace("\n", "\n> ")
                                
#                             is_thinking = False
#                             yield "\n\n---\n\n"
#                             raw_buffer = parts[1]
                            
#                         # 3. Stream the content safely
#                         if is_thinking:
#                             # Hold the buffer if we are currently spelling </think>
#                             if not any(raw_buffer.endswith(p) for p in partial_ends):
#                                 # Replace newlines to maintain the gray blockquote styling
#                                 yield raw_buffer.replace("\n", "\n> ")
#                                 raw_buffer = ""
#                         else:
#                             # Hold the buffer if we are currently spelling <think>
#                             if not any(raw_buffer.endswith(p) for p in partial_starts):
#                                 yield raw_buffer
#                                 raw_buffer = ""
                                
#                     elif data["type"] == "telemetry":
#                         st.session_state.latest_telemetry = data
#                         render_telemetry_ui(data)
                        
#             # Flush anything left over when the stream ends
#             if raw_buffer:
#                 if is_thinking:
#                     yield raw_buffer.replace("\n", "\n> ")
#                 else:
#                     yield raw_buffer
                        
#     except requests.exceptions.ConnectionError:
#         yield "Error: Could not connect to API."


# # Render chat history
# for msg in st.session_state.messages:
#     with st.chat_message(msg["role"]):
#         st.markdown(msg["content"])

# # Chat Input
# if prompt := st.chat_input("Ask a question about the codebase architecture..."):
#     st.session_state.messages.append({"role": "user", "content": prompt})
#     with st.chat_message("user"):
#         st.markdown(prompt)

#     with st.chat_message("assistant"):
#         response_stream = stream_llm_response(
#             repo_name=st.session_state.active_repo, 
#             question=prompt, 
#             max_tokens=max_tokens_val,
#             target_path=st.session_state.target_path
#             )
#         full_response = st.write_stream(response_stream)
        
#     st.session_state.messages.append({"role": "assistant", "content": full_response})
    
    