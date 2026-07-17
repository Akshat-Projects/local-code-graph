"""
Provides a fully-featured Streamlit UI frontend for LocalGraph AI, enabling repository 
ingestion configuration, interactive vis.js graph visualization, and streaming chatbot queries.
"""

import streamlit.components.v1 as components
import json
import requests
import streamlit as st
import threading
from config import settings
from streamlit_autorefresh import st_autorefresh
from streamlit_agraph import agraph, Node, Edge, Config
from streamlit.components.v1 import html

from ui.graph_template import get_graph_html

# --- Configuration & State ---
st.set_page_config(page_title="LocalGraph AI", layout="wide", page_icon="🧠")

API_BASE = settings.BACKEND_ENDPOINT

# Session states handling helpers
if "messages" not in st.session_state:
    st.session_state.messages = []
if "active_repo" not in st.session_state:
    st.session_state.active_repo = settings.REPO_NAME
if "active_repo_input" not in st.session_state:
    st.session_state.active_repo_input = settings.REPO_NAME
if "target_path" not in st.session_state:
    st.session_state.target_path = settings.TARGET_REPO_PATH
if "ingest_job_id" not in st.session_state:
    st.session_state.ingest_job_id = None
if "latest_telemetry" not in st.session_state:
    st.session_state.latest_telemetry = None
if "is_generating" not in st.session_state:
    st.session_state.is_generating = False
if "interruption_message" not in st.session_state:
    st.session_state.interruption_message = None
if "graph_nodes" not in st.session_state:
    st.session_state.graph_nodes = None
if "graph_edges" not in st.session_state:
    st.session_state.graph_edges = None
if "graph_config" not in st.session_state:
    st.session_state.graph_config = None
if "selected_node" not in st.session_state:
    st.session_state.selected_node = None
if "raw_graph_data" not in st.session_state:   # ← fix for the raw_graph_data bug
    st.session_state.raw_graph_data = None
if "expanded_classes" not in st.session_state:  # tracks which classes are expanded
    st.session_state.expanded_classes = set()
if "isolate_node" not in st.session_state:      # isolate mode toggle
    st.session_state.isolate_node = None
if "prefill_prompt" not in st.session_state:
    st.session_state.prefill_prompt = None
if "temp_thought" not in st.session_state:
    st.session_state.temp_thought = ""
if "temp_content" not in st.session_state:
    st.session_state.temp_content = ""
if "generation_chunks" not in st.session_state:
    st.session_state.generation_chunks = []
if "generation_status" not in st.session_state:
    st.session_state.generation_status = {"status": "idle"}
if "view_mode" not in st.session_state:
    st.session_state.view_mode = "💬 AI Assistant"

# Top level autorefresh when background thread is active and user is viewing the chat
if st.session_state.is_generating and st.session_state.get("view_mode", "💬 AI Assistant") == "💬 AI Assistant":
    st_autorefresh(interval=500, key="chat_generation_refresh")

# ==========================================
# SIDEBAR: CONTROL ROOM & TELEMETRY
# ==========================================
with st.sidebar:
    st.header("⚙️ Codebase Ingestion")
    
    repo_input = st.text_input("Repository Name", key="active_repo_input")
    repo_input_sanitized = repo_input.strip().replace(" ", "_")
    st.session_state.active_repo = repo_input_sanitized
    path_input = st.text_input("Local Source Path", key="target_path")
    run_llm = st.toggle("🧠 Run Deep LLM Analysis", value=True, help="Disable to instantly build the structural graph. You can run LLM summarization later by re-ingesting with this checked.")
    # show_configs = st.toggle("Show Infrastructure & Libraries", value=True)
    
    if st.button("Ingest & Analyze Codebase", width="stretch"):
        if st.session_state.is_generating:
            st.session_state.interruption_message = (
                "⚠️ Response generation was interrupted because a codebase ingestion was started."
            )
            st.session_state.is_generating = False
            
        st.session_state.active_repo = repo_input_sanitized
        try:
            res = requests.post(f"{API_BASE}/ingest", json={"repo_name": repo_input_sanitized, "target_path": path_input, "run_llm": run_llm})
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
        st_autorefresh(interval=3500, key="ingestion_state_refresh")
        

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

            
    st.divider()
    st.subheader("⚙️ Generation Settings")
    
    # 0 means "no limit" (we handle this logic in the backend)
    max_tokens_val = st.slider(
        "Max Output Tokens", 
        min_value=0, 
        max_value=2048, 
        value=0, 
        step=128,
        help="Set to 0 for no limit. Lower values keep inference fast, but may lead to incomplete generation."
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
    if st.button("🗑️ Clear Chat History", width="stretch"):
        st.session_state.messages = []
        st.session_state.latest_telemetry = None
        st.session_state.is_generating = False
        st.rerun()

    # Re-render existing telemetry if it exists in state
    if st.session_state.latest_telemetry:
        render_telemetry_ui(st.session_state.latest_telemetry)
    else:
        telemetry_container.caption("Awaiting query...")

# ==========================================
# MAIN PANEL: GRAPH TERMINAL
# ==========================================
st.title("🧠 Local CodeGraph Terminal")
st.caption(f"Currently querying isolated graph database: **{st.session_state.active_repo}**")

# Create navigation menu at the top
st.segmented_control(
    "Navigation",
    ["💬 AI Assistant", "🕸️ Interactive Architecture Map", "🔍 AST Search Explorer"],
    label_visibility="collapsed",
    key="view_mode"
)

# --- Helper: Threaded Query Runner ---
def background_query_runner(repo_name, question, max_tokens, target_path, chat_history, chunks_list, status_holder):
    status_holder["status"] = "running"
    payload = {
        "repo_name": repo_name, 
        "question": question, 
        "max_tokens": max_tokens if max_tokens > 0 else None,
        "target_path": target_path,
        "chat_history": chat_history
    }
    try:
        with requests.post(f"{API_BASE}/query", json=payload, stream=True, timeout=60) as response:
            if response.status_code != 200:
                chunks_list.append(("error", f"Error: Backend returned {response.status_code}"))
                status_holder["status"] = "error"
                return
            
            for line in response.iter_lines():
                if not line:
                    continue
                
                if status_holder.get("stop_requested", False):
                    status_holder["status"] = "stopped"
                    return
                    
                try:
                    data = json.loads(line.decode('utf-8'))
                    
                    if data["type"] == "chunk":
                        chunks_list.append(("text", data["content"]))
                    elif data["type"] == "status":
                        chunks_list.append(("status", data["content"]))
                    elif data["type"] == "thought":
                        chunks_list.append(("thought", data["content"]))
                    elif data["type"] == "telemetry":
                        chunks_list.append(("telemetry", data))
                except Exception:
                    pass
                    
            status_holder["status"] = "completed"
    except Exception as e:
        chunks_list.append(("error", f"Connection error: {str(e)}"))
        status_holder["status"] = "error"

# ─────────────────────────────────────────────────────────
# Graph assembly — runs on every rerun using session state
# ─────────────────────────────────────────────────────────
def build_graph_objects(raw_data, show_functions, search_term, expanded_classes, isolate_node):
    """
    Pure function: takes raw API data + UI state → returns (nodes, edges).
    Centralising this means every rerun (button click, node click, search)
    always produces a consistent graph without code duplication.
    """
    all_nodes = raw_data["nodes"]
    all_edges = raw_data["edges"]

    # 1. Determine which node IDs are visible
    visible_ids = set()
    for n in all_nodes:
        ntype = n.get("type")
        nid = n["id"]

        if ntype == "file":
            visible_ids.add(nid)
        elif ntype == "class":
            visible_ids.add(nid)
        elif ntype == "function":
            if show_functions:
                visible_ids.add(nid)
            else:
                # Check if parent class is expanded
                # Method IDs are "file.py::ClassName::method" — parent is "file.py::ClassName"
                parts = nid.split("::")
                parent_class_id = "::".join(parts[:2]) if len(parts) == 3 else None
                if parent_class_id and parent_class_id in expanded_classes:
                    visible_ids.add(nid)

    # 2. Isolate mode — restrict to clicked node + 1-hop
    if isolate_node and isolate_node in visible_ids:
        connected = {isolate_node}
        for e in all_edges:
            if e["source"] == isolate_node and e["target"] in visible_ids:
                connected.add(e["target"])
            if e["target"] == isolate_node and e["source"] in visible_ids:
                connected.add(e["source"])
        visible_ids = connected

    # 3. Build Node objects with search highlight
    nodes = []
    for n in all_nodes:
        if n["id"] not in visible_ids:
            continue

        highlight = search_term and search_term.lower() in n["label"].lower()
        nodes.append(Node(
            id=n["id"],
            label=n["label"],
            # title=safe_title,
            title=n["title"],
            color="#F6E05E" if highlight else None,
            size=n["size"],
            group=n.get("group"),
            shape=n.get("shape", "dot"),
            font=n.get("font", {"size": 9, "color": "#718096"}),
        ))

    # 4. Build Edge objects — only between visible nodes
    edges = [
        Edge(
            source=e["source"],
            target=e["target"],
            label=e["label"],
            color="#4a5568",
            width=0.3,
        )
        for e in all_edges
        if e["source"] in visible_ids and e["target"] in visible_ids
    ]

    return nodes, edges

def build_config(layout_style, show_minimap=False):
    if layout_style == "📂 Hierarchical (Tree)":
        return Config(
            width="100%", height=700, directed=True,
            hierarchical=True,
            layout={"hierarchical": {
                "enabled": True, "direction": "UD",
                "sortMethod": "directed", "levelSeparation": 150, "nodeSpacing": 100
            }},
            physics={
                "hierarchicalRepulsion": {
                    "centralGravity": 0.0, "springLength": 100,
                    "springConstant": 0.01, "nodeDistance": 120
                },
                "solver": "hierarchicalRepulsion"
            },
            interaction={
                "navigationButtons": show_minimap,
                "keyboard": True,
                "selectable": True,
                "selectConnectedEdges": False,
                "tooltipDelay": 300,
                "zoomView": True,
                "dragView": True,
                # This is the key — disable the double-click URL behaviour:
                "multiselect": False,
            },
            nodeHighlightBehavior=True, highlightColor="#F7A072", collapsible=True
        )
    else:
        return Config(
            width="100%", height=700, directed=True, hierarchical=False,
            physics={
                "solver": "forceAtlas2Based",
                "forceAtlas2Based": {
                    "gravitationalConstant": -60,
                    "centralGravity": 0.005,
                    "springLength": 100,
                    "springConstant": 0.08,
                    "damping": 0.4,
                    "avoidOverlap": 0.8,
                },
                "maxVelocity": 80,  
                "stabilization": {"enabled": True, "iterations": 200, "updateInterval": 25},
                "minVelocity": 0.5,
            },
            # vis.js navigation options — forwarded as kwargs
            # whether this works depends on your streamlit-agraph version
            navigation=show_minimap,
            interaction={
                "navigationButtons": show_minimap,
                "keyboard": True,
                "selectable": True,
                "selectConnectedEdges": False,
                "tooltipDelay": 300,
                "zoomView": True,
                "dragView": True,
                # This is the key — disable the double-click URL behaviour:
                "multiselect": False,
            },
            nodeHighlightBehavior=True, highlightColor="#F7A072", collapsible=True,
        )


def render_graph_health_banner(repo_name: str, layout_context: str = "visualizer"):
    """
    DRY Helper to fetch graph status and render warnings dynamically.
    layout_context can be 'visualizer' or 'chatbot'.
    """
    if not repo_name or not repo_name.strip():
        return False
    try:
        res = requests.get(
            f"{API_BASE}/query/status/{repo_name}",
            params={"target_path": st.session_state.target_path}
        )
        if res.status_code == 200:
            status = res.json()
            if not status.get("exists"):
                st.error("❌ No structural graph found. Please ingest the repository first.")
                return False
                
            pending = status.get("pending_summaries", 0)
            total = status.get("total_nodes", 0)
            pending_details = status.get("pending_details", [])
            
            if pending > 0:
                pending_list_str = "\n".join([f"- `{item['id']}` ({item['type']})" for item in pending_details])
                if layout_context == "chatbot":
                    st.warning(
                        f"⚠️ **Semantic Index Incomplete ({pending} / {total} nodes pending LLM analysis).**\n\n"
                        "The global AI Assistant matches your natural language questions against these summaries. "
                        "Because they are missing, complex or deep semantic queries will likely fail to surface relevant code block contexts. "
                        "Go to **Ingestion** and check *'Run Deep LLM Analysis'* to train the model."
                    )
                    with st.expander(f"🔍 View Pending Components ({pending})", expanded=False):
                        st.markdown(pending_list_str)
                else:
                    # Visualizer specific wording
                    st.warning(
                        f"⚠️ **Topography Pending Enrichment ({pending} / {total} nodes lack summaries).**\n\n"
                        "The map layout is structurally sound, but elements wrapped in dashed orange borders are currently unindexed. "
                        "Re-running ingestion with the LLM analysis active will safely resume processing missing fragments."
                    )
                    with st.expander(f"🔍 View Pending Components ({pending})", expanded=False):
                        st.markdown(pending_list_str)
                return False
            else:
                st.success(f"✅ Code Graph is 100% semantically indexed and healthy! ({total}/{total} nodes parsed)")
                return True
    except Exception as e:
        st.sidebar.error(f"Could not connect to health engine: {e}")
    return False



def stop_generation():
    """Callback triggered instantly when 'Stop' is clicked."""
    if "generation_status" in st.session_state:
        st.session_state.generation_status["stop_requested"] = True
    
    temp_thought = ""
    temp_content = ""
    for event_type, chunk in list(st.session_state.generation_chunks):
        if event_type == "status":
            temp_thought += f"- **{chunk}**\n\n"
        elif event_type == "thought":
            temp_thought += chunk
        elif event_type == "text":
            temp_content += chunk
            
    st.session_state.messages.append({
        "role": "assistant",
        "thought": temp_thought,
        "content": temp_content + "\n\n*(🛑 Stopped by User)*"
    })
    
    st.session_state.generation_chunks = []
    st.session_state.generation_status = {"status": "idle"}
    st.session_state.is_generating = False
    st.session_state.latest_telemetry = None

# ==========================================
# TAB 1: CHAT INTERFACE & RENDER LOOP
# ==========================================

if st.session_state.view_mode == "💬 AI Assistant":
    # 1. Handle prefill / Edit Button logic first
    if st.session_state.get("prefill_prompt"):
        st.info("✏️ Edit your prompt below:")
        edited_prompt = st.text_area("Your Prompt", value=st.session_state.prefill_prompt, height=100, key="edit_prompt_area")
        col_btn1, col_btn2 = st.columns([0.15, 0.85])
        with col_btn1:
            if st.button("🚀 Resend", width="stretch", key="resend_edit_btn"):
                st.session_state.messages.append({"role": "user", "content": edited_prompt})
                st.session_state.prefill_prompt = None
                st.session_state.latest_telemetry = None
                
                # Format history
                history_msgs = st.session_state.messages[:-1] 
                formatted_history = "\n".join([f"[{msg['role'].upper()}]: {msg['content']}" for msg in history_msgs])
                
                # Initialize background state
                st.session_state.generation_chunks = []
                st.session_state.generation_status = {"status": "pending", "stop_requested": False}
                st.session_state.is_generating = True
                
                # Start background thread
                t = threading.Thread(
                    target=background_query_runner,
                    args=(
                        st.session_state.active_repo,
                        edited_prompt,
                        4096,
                        st.session_state.target_path,
                        formatted_history,
                        st.session_state.generation_chunks,
                        st.session_state.generation_status
                    ),
                    daemon=True
                )
                t.start()
                st.rerun()
        with col_btn2:
            if st.button("❌ Cancel", width="stretch", key="cancel_edit_btn"):
                # Put original user message back before resetting to avoid loss of history
                st.session_state.messages.append({"role": "user", "content": st.session_state.prefill_prompt})
                st.session_state.prefill_prompt = None
                st.rerun()

    if st.session_state.get("interruption_message"):
        st.session_state.messages.append({
            "role": "assistant",
            "content": st.session_state.interruption_message
        })
        st.session_state.interruption_message = None

    # --- THE DRY WARNING BANNER ---
    render_graph_health_banner(st.session_state.active_repo, layout_context="chatbot")
    
    # 2. Render all past messages (History)
    for i, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                col1, col2 = st.columns([0.95, 0.05])
                with col1:
                    st.markdown(msg["content"])
                with col2:
                    # Only show Edit button for the absolute last user message
                    is_last_user = (i == len(st.session_state.messages) - 1) or \
                                   (i == len(st.session_state.messages) - 2 and st.session_state.messages[-1]["role"] == "assistant")
                    
                    if is_last_user:
                        if st.button("✏️", key=f"edit_{i}", help="Edit and resend this prompt"):
                            st.session_state.prefill_prompt = msg["content"]
                            st.session_state.messages = st.session_state.messages[:i]
                            st.rerun()
            else:
                if msg.get("thought"):
                    with st.expander("💭 Thought Process", expanded=False):
                        st.markdown(msg["thought"])
                st.markdown(msg["content"])

    # 3. Generation Logic (Triggered ONLY if the last message in history is from the user and generation state is active)
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user" and st.session_state.is_generating:
        
        with st.chat_message("assistant"):
            top_col1, top_col2 = st.columns([0.85, 0.15])
            
            # Reset temp states for this specific generation run
            temp_thought = ""
            temp_content = ""
            is_thinking = False
            last_status = "Thinking..."

            current_chunks = list(st.session_state.generation_chunks)
            for event_type, chunk in current_chunks:
                if event_type == "status":
                    is_thinking = True
                    last_status = chunk
                    temp_thought += f"- **{chunk}**\n\n"
                    
                elif event_type == "thought":
                    is_thinking = True
                    temp_thought += chunk
                    
                elif event_type == "text":
                    if is_thinking:
                        is_thinking = False
                    temp_content += chunk
                    
                elif event_type == "telemetry":
                    st.session_state.latest_telemetry = chunk
                
                elif event_type == "error":
                    st.error(chunk)

            # Render thought container using native st.status context to prevent layout shifts
            with top_col1:
                if temp_thought:
                    if is_thinking:
                        with st.status(f"⚙️ {last_status}", state="running", expanded=True):
                            st.markdown(temp_thought)
                    else:
                        with st.status("💭 Thought process complete", state="complete", expanded=False):
                            st.markdown(temp_thought)
                else:
                    st.status("💭 Thinking...", state="running", expanded=True)

            with top_col2:
                # The on_click callback saves the partial text BEFORE Streamlit reruns
                st.button("🛑 Stop", key="stop_btn", on_click=stop_generation)

            # Render standard markdown via a persistent placeholder to allow React VDOM in-place updates without redraws
            content_placeholder = st.empty()
            if temp_content:
                content_placeholder.markdown(temp_content)
                
            if st.session_state.latest_telemetry:
                render_telemetry_ui(st.session_state.latest_telemetry)

            # Check if background thread has finished
            bg_status = st.session_state.generation_status.get("status", "idle")
            if bg_status in ["completed", "error", "stopped"]:
                st.session_state.is_generating = False
                
                # Append completed message to history
                if bg_status == "completed":
                    st.session_state.messages.append({
                        "role": "assistant",
                        "thought": temp_thought,
                        "content": temp_content
                    })
                
                # Clear background variables
                st.session_state.generation_chunks = []
                st.session_state.generation_status = {"status": "idle"}
                st.rerun()

    # 4. CHAT INPUT (Absolute bottom of the script = Absolute bottom of the UI)
    if prompt := st.chat_input("Ask a question about your codebase...", disabled=st.session_state.is_generating):
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.session_state.latest_telemetry = None
        
        # Format history
        history_msgs = st.session_state.messages[:-1] 
        formatted_history = "\n".join([f"[{msg['role'].upper()}]: {msg['content']}" for msg in history_msgs])
        
        # Initialize background state
        st.session_state.generation_chunks = []
        st.session_state.generation_status = {"status": "pending", "stop_requested": False}
        st.session_state.is_generating = True
        
        # Start background thread
        t = threading.Thread(
            target=background_query_runner,
            args=(
                st.session_state.active_repo,
                prompt,
                4096,
                st.session_state.target_path,
                formatted_history,
                st.session_state.generation_chunks,
                st.session_state.generation_status
            ),
            daemon=True
        )
        t.start()
        st.rerun() # Instantly trigger the generation block above


# ==========================================
# TAB 2: INTERACTIVE ARCHITECTURE MAP
# ==========================================
elif st.session_state.view_mode == "🕸️ Interactive Architecture Map":
    st.markdown("### Codebase Topography")
    st.caption("Explore the semantic relationships. Click any node to open the embedded context inspector and chat sidepanel.")
    
    col_layout, col_hierarchy = st.columns(2)
    with col_layout:
        layout_style = st.radio(
            "Select Graph Layout:",
            ["🌐 Organic (Physics)", "📂 Hierarchical (Tree)"],
            horizontal=True,
            key="graph_layout_style_final"
        )
    with col_hierarchy:
        hierarchy_level = st.radio(
            "Select Clustering Level:",
            ["Macro-Communities", "Micro-Communities"],
            horizontal=True,
            key="graph_hierarchy_level",
            help="Leiden Clustering Levels:\n- Macro-Communities: Groups code files into broader systems/packages based on high-level dependencies.\n- Micro-Communities: Recursively sub-clusters macro groups into smaller, fine-grained module/class-level groupings. Note: Run ingestion again to calculate hierarchical clustering metadata for your codebase."
        )
    
    if st.button("🔄 Render Map", width="stretch"):
        with st.spinner("Fetching topography from LocalGraph Engine..."):
            try:
                res = requests.get(
                    f"{API_BASE}/ingest/visualize/{st.session_state.active_repo}",
                    params={"target_path": st.session_state.target_path,
                            "show_configs": True,
                            "hierarchy_level": "micro" if hierarchy_level == "Micro-Communities" else "macro"}
                )
                
                if res.status_code == 200:
                    graph_data = res.json()
                    st.session_state.last_graph_data = graph_data 
                    
                    vis_nodes = []
                    node_colors = {} 
                    
                    # --- NEW: 35-Color Dark-Mode Optimized Palette ---
                    extended_palette = [
                        # The Classics (Reliable baseline)
                        "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F", 
                        "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC",
                        # Cyberpunk / Neons (High contrast on dark bg)
                        "#00E5FF", "#FF007F", "#39FF14", "#FF4500", "#B452CD",
                        "#FEE715", "#00FF7F", "#FF3855", "#9D00FF", "#FFAA1D",
                        # Bright Pastels & Jewels (Easy on the eyes)
                        "#87CEFA", "#FFB6C1", "#98FB98", "#DDA0DD", "#F0E68C",
                        "#20B2AA", "#FF7F50", "#EE82EE", "#7B68EE", "#00FA9A",
                        # Bold Accents
                        "#FF8C00", "#1E90FF", "#C71585", "#32CD32", "#DAA520"
                    ]
                    
                    # 1. Group nodes by community and count them, then find the main node for each community
                    community_counts = {}
                    community_nodes = {}
                    for n in graph_data.get("nodes", []):
                        comm_id = str(n.get("group", "0"))
                        community_counts[comm_id] = community_counts.get(comm_id, 0) + 1
                        if comm_id not in community_nodes:
                            community_nodes[comm_id] = []
                        community_nodes[comm_id].append(n)

                    community_names = {}
                    for comm_id, nodes_in_comm in community_nodes.items():
                        def node_rank_key(node):
                            # Rank nodes by size (descending), then type score (descending), then alphabetically by label
                            nt = node.get("type", "unknown")
                            if nt == "file":
                                t_score = 3
                            elif nt == "class":
                                t_score = 2
                            elif nt == "function":
                                t_score = 0
                            else:
                                t_score = 1
                            return (node.get("size", 10), t_score, node.get("label", ""))
                        
                        best_node = max(nodes_in_comm, key=node_rank_key)
                        community_names[comm_id] = best_node.get("label") or f"Community {comm_id}"

                    # 2. Sort communities safely and numerically (handles 0_0, 10_1, etc.)
                    def safe_community_key(item):
                        cid = str(item[0])
                        if "_" in cid:
                            parts = cid.split("_")
                            try:
                                return (0, tuple(int(p) for p in parts))
                            except ValueError:
                                pass
                        
                        if cid.isdigit():
                            return (0, (int(cid),))
                            
                        # Fallback for string keys
                        return (1, cid)

                    sorted_communities = sorted(community_counts.items(), key=safe_community_key)

                    # 3. Assign colors to communities based on sorted order
                    community_colors = {}
                    for idx, (cid, _) in enumerate(sorted_communities):
                        community_colors[cid] = extended_palette[idx % len(extended_palette)]
                    
                    # 4. Safely Parse Nodes using the assigned community colors
                    for n in graph_data.get("nodes", []):
                        comm_id = str(n.get("group", "0"))
                        color_hex = community_colors.get(comm_id, "#4E79A7")
                        node_colors[n["id"]] = color_hex 
                        
                        vis_nodes.append({
                            "id": n["id"], 
                            "label": n.get("label", ""), 
                            "title": n.get("title", ""),
                            "summary": n.get("summary", ""),
                            "size": n.get("size", 10), 
                            "shape": n.get("shape", "dot"), 
                            "font": n.get("font"),
                            "color": {"background": color_hex, "border": color_hex}, 
                            "community": comm_id, 
                            "community_name": community_names.get(comm_id, f"Community {comm_id}"),
                            "group": comm_id,
                            "_file_type": n.get("type", "unknown"), 
                            "_is_pending": n.get("_is_pending", False)
                        })
                        
                    # 5. Safely Parse Edges (Absolutely NO "source" or "target" here!)
                    vis_edges = []
                    for e in graph_data.get("edges", []):
                        source_id = e.get("from")
                        target_id = e.get("to")
                        
                        if not source_id or not target_id:
                            continue
                            
                        source_color = node_colors.get(source_id, "#4a5568")
                        vis_edges.append({
                            "from": source_id, 
                            "to": target_id, 
                            "label": e.get("label", ""),
                            "title": e.get("title", ""),
                            "color": source_color,
                            "width": e.get("width", 0.4),
                            "dashes": e.get("dashes", False),
                            "arrows": e.get("arrows")
                        })
                        
                    # 6. Safely Parse Legend using the same community colors
                    vis_legend = []
                    for cid, count in sorted_communities:
                        color_hex = community_colors.get(cid, "#4E79A7")
                        vis_legend.append({
                            "cid": cid, 
                            "color": color_hex, 
                            "label": community_names.get(cid, f"Community {cid}"), 
                            "count": count
                        })
 
                    render_graph_health_banner(st.session_state.active_repo, layout_context="visualizer")
                    
                    js_nodes = json.dumps(vis_nodes)
                    js_edges = json.dumps(vis_edges)
                    js_legend = json.dumps(vis_legend)

                    if layout_style == "📂 Hierarchical (Tree)":
                        js_physics_config = "layout: { hierarchical: { enabled: true, direction: 'UD', sortMethod: 'directed', levelSeparation: 150, nodeSpacing: 100 } }, physics: { solver: 'hierarchicalRepulsion', hierarchicalRepulsion: { centralGravity: 0.0, springLength: 100, springConstant: 0.01, nodeDistance: 120 } },"
                    else:
                        js_physics_config = "physics: { solver: 'forceAtlas2Based', forceAtlas2Based: { gravitationalConstant: -50, centralGravity: 0.005, springLength: 220, springConstant: 0.05, damping: 0.6, avoidOverlap: 1.0 }, stabilization: { iterations: 200, fit: true } },"

                    st.session_state.saved_graph_html = get_graph_html(API_BASE, st.session_state.active_repo, st.session_state.target_path, js_nodes, js_edges, js_legend, js_physics_config)
                    st.rerun() 
                    
            except Exception as e:
                # This will print the EXACT python error if it fails
                st.error(f"Failed to connect to API or parse data: {str(e)}")

    # if "saved_graph_html" in st.session_state:
    #     components.html(st.session_state.saved_graph_html, height=800, scrolling=False)
    # === FIX: Move banner outside so it stays visible! ===
    if "saved_graph_html" in st.session_state:
        render_graph_health_banner(st.session_state.active_repo, layout_context="visualizer")
        st.iframe(st.session_state.saved_graph_html, height=800)
        # components.html(st.session_state.saved_graph_html, height = 800, scrolling=False)

elif st.session_state.view_mode == "🔍 AST Search Explorer":
    st.markdown("### 🔍 AST Structural Search Explorer")
    st.caption("Search your codebase using precise structural patterns or pre-built Tree-sitter S-expression queries.")
    
    search_type = st.radio(
        "Search Mode", 
        ["Graph Metadata Search", "Dynamic Tree-sitter Pattern Search"], 
        horizontal=True,
        help="AST (Abstract Syntax Tree) represents source code structure. Choose:\n- Graph Metadata Search: Search the NetworkX database for structural relations (like classes inheriting from BaseModel).\n- Dynamic Tree-sitter Pattern Search: Scan file contents directly on-the-fly using tree-sitter S-expression templates."
    )
    
    if search_type == "Graph Metadata Search":
        col1, col2 = st.columns(2)
        with col1:
            node_type = st.selectbox("Node Type", ["All", "file", "class", "function"], help="Filter structural elements by code representation type.")
            name_q = st.text_input("Name contains", placeholder="e.g. Ingestion", help="Search for code symbols containing this substring (case-insensitive).")
        with col2:
            inherits_q = st.text_input("Inherits from class", placeholder="e.g. BaseModel", help="Find classes that inherit from a specific parent class.")
            calls_q = st.text_input("Calls symbol", placeholder="e.g. get_logger", help="Find functions/classes that invoke a specific target method or function.")
            
        if st.button("Query Graph Structure", width="stretch"):
            filters = {}
            if node_type != "All":
                filters["node_type"] = node_type
            if name_q:
                filters["name"] = name_q
            if inherits_q:
                filters["inherits"] = inherits_q
            if calls_q:
                filters["calls"] = calls_q
                
            with st.spinner("Searching NetworkX Graph..."):
                try:
                    res = requests.post(f"{API_BASE}/query/search", json={
                        "repo_name": st.session_state.active_repo,
                        "target_path": st.session_state.target_path,
                        "query_type": "graph",
                        "filters": filters
                    })
                    if res.status_code == 200:
                        results = res.json().get("results", [])
                        if results:
                            import pandas as pd
                            st.success(f"Found {len(results)} matching code nodes!")
                            
                            tab1, tab2 = st.tabs(["📊 Quick Grid", "📄 Detailed Summaries"])
                            
                            with tab1:
                                df = pd.DataFrame(results)
                                
                                # Display line numbers as empty for file nodes or when zero
                                if "line_start" in df.columns:
                                    df["line_start"] = df.apply(lambda r: None if r.get("type") == "file" or r["line_start"] == 0 else r["line_start"], axis=1)
                                if "line_end" in df.columns:
                                    df["line_end"] = df.apply(lambda r: None if r.get("type") == "file" or r["line_end"] == 0 else r["line_end"], axis=1)
                                    
                                cols_order = ["name", "type", "file_path", "line_start", "line_end", "summary"]
                                existing_cols = [c for c in cols_order if c in df.columns]
                                df = df[existing_cols]
                                
                                st.dataframe(
                                    df,
                                    column_config={
                                        "name": st.column_config.TextColumn("Symbol Name", width="medium"),
                                        "type": st.column_config.TextColumn("Type", width="small"),
                                        "file_path": st.column_config.TextColumn("File Path", width="medium"),
                                        "line_start": st.column_config.NumberColumn("Start Line", format="%d", width="small"),
                                        "line_end": st.column_config.NumberColumn("End Line", format="%d", width="small"),
                                        "summary": st.column_config.TextColumn("Summary", width="large"),
                                    },
                                    width="stretch",
                                    hide_index=True
                                )
                                
                            with tab2:
                                import os
                                for idx, item in enumerate(results):
                                    name = item.get("name", "")
                                    ntype = item.get("type", "")
                                    file_path = item.get("file_path", "")
                                    line_start = item.get("line_start", 0)
                                    line_end = item.get("line_end", 0)
                                    summary = item.get("summary", "")
                                    
                                    line_info = f"Lines {line_start}-{line_end}" if line_start and line_end else "File Node"
                                    
                                    abs_path = os.path.join(st.session_state.target_path, file_path)
                                    file_url = f"file://{abs_path}"
                                    if line_start:
                                        file_url += f"#L{line_start}"
                                        
                                    header_emoji = "📁" if ntype == "file" else ("🧩" if ntype == "class" else "⚡")
                                    display_label = f"{header_emoji} {name} ({file_path}{f':{line_start}' if line_start else ''})"
                                    
                                    with st.expander(display_label):
                                        st.markdown(f"**Type:** `{ntype}` | **Location:** [{file_path}]({file_url}) ({line_info})")
                                        st.markdown("**Architectural Summary:**")
                                        st.markdown(summary if summary else "*No summary generated yet.*")
                        else:
                            st.info("No nodes match the structural filters.")
                    else:
                        st.error(f"Search failed: {res.text}")
                except Exception as e:
                    st.error(f"Error connecting to server: {e}")
                    
    else:  # Dynamic Tree-sitter Pattern Search
        col1, col2 = st.columns([1, 3])
        with col1:
            lang_ext = st.selectbox("Language / Extension", [".py", ".js", ".ts", ".tsx"], help="Filter scan range to files matching this language extension.")
            
            templates = ["Custom S-Expression", "exception_handlers", "decorators", "async_functions", "class_inheritance", "try_catch", "interfaces"]
            selected_template = st.selectbox("Pattern Template", templates, help="Choose a predefined pattern query or write a custom S-expression query.")
            
        with col2:
            if selected_template == "Custom S-Expression":
                pattern = st.text_area(
                    "Tree-sitter S-Expression Query", 
                    value="(function_definition) @match", 
                    height=150, 
                    help="Enter a valid Tree-sitter S-expression (e.g. '(except_clause) @match' to find Python try-except blocks). Must end with a capture tag like @match."
                )
            else:
                pattern = selected_template
                st.info(f"Using predefined structural template: `{pattern}`")
                
        if st.button("Run Tree-sitter Pattern Search", width="stretch"):
            with st.spinner("Scanning files on-the-fly via Tree-sitter..."):
                try:
                    res = requests.post(f"{API_BASE}/query/search", json={
                        "repo_name": st.session_state.active_repo,
                        "target_path": st.session_state.target_path,
                        "query_type": "tree-sitter",
                        "pattern": pattern,
                        "language_ext": lang_ext
                    })
                    if res.status_code == 200:
                        results = res.json().get("results", [])
                        if results:
                            st.success(f"Found {len(results)} occurrences across the codebase!")
                            for idx, match in enumerate(results):
                                with st.expander(f"📄 {match['file_path']} (Lines {match['start_line']}-{match['end_line']})"):
                                    st.code(match['snippet'], language=lang_ext[1:])
                        else:
                            st.info("No occurrences found matching the pattern.")
                    else:
                        st.error(f"Search failed: {res.text}")
                except Exception as e:
                    st.error(f"Error connecting to server: {e}")
        
