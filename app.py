import streamlit.components.v1 as components
import json
import requests
import streamlit as st
from config import settings
from streamlit_autorefresh import st_autorefresh
from streamlit_agraph import agraph, Node, Edge, Config

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

# ==========================================
# SIDEBAR: CONTROL ROOM & TELEMETRY
# ==========================================
with st.sidebar:
    st.header("⚙️ Codebase Ingestion")
    
    repo_input = st.text_input("Repository Name", key="active_repo_input")
    repo_input_sanitized = repo_input.strip().replace(" ", "_")
    st.session_state.active_repo = repo_input_sanitized
    path_input = st.text_input("Local Source Path", key="target_path")
    
    if st.button("Ingest & Analyze Codebase", use_container_width=True):
        if st.session_state.is_generating:
            st.session_state.interruption_message = (
                "⚠️ Response generation was interrupted because a codebase ingestion was started."
            )
            st.session_state.is_generating = False
            
        st.session_state.active_repo = repo_input_sanitized
        try:
            res = requests.post(f"{API_BASE}/ingest", json={"repo_name": repo_input_sanitized, "target_path": path_input})
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
        st_autorefresh(interval=2500, key="ingestion_state_refresh")
        

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

# Create two main tabs
tab_chat, tab_map = st.tabs(["💬 AI Assistant", "🕸️ Interactive Architecture Map"])

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
            width=0.5,
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


# ==========================================
# TAB 1: CHAT INTERFACE & RENDER LOOP
# ==========================================
with tab_chat:
    # Drain prefill before anything else
    prompt_to_run = None
    if st.session_state.prefill_prompt:
        prompt_to_run = st.session_state.prefill_prompt
        st.session_state.prefill_prompt = None

    if st.session_state.interruption_message:
        st.session_state.messages.append({
            "role": "assistant",
            "content": st.session_state.interruption_message
        })
        st.session_state.interruption_message = None

    # Render history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if msg.get("thought"):
                with st.expander("💭 Thought Process", expanded=False):
                    st.markdown(msg["thought"])
            st.markdown(msg["content"])

    # Merge typed input and prefill into one variable
    typed_prompt = st.chat_input("Ask a question about your codebase...")
    prompt = typed_prompt or prompt_to_run   # ← prefill wins if nothing typed

    if prompt:
        st.session_state.is_generating = True
        try:
            st.chat_message("user").markdown(prompt)
            st.session_state.messages.append({"role": "user", "content": prompt})
            
            if st.session_state.ingest_job_id:
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": "⚠️ Codebase ingestion is currently running. "
                               "This response may use a partially updated graph."
                })

            with st.chat_message("assistant"):
                thought_container = st.status("💭 Thinking...", expanded=True)
                thought_placeholder = thought_container.empty()
                thought_text = ""
                answer_container = st.empty()
                answer_text = ""
                is_thinking = False

                for event_type, chunk in stream_llm_response(
                    st.session_state.active_repo, prompt, max_tokens_val, st.session_state.target_path
                ):
                    if event_type == "thought":
                        is_thinking = True
                        thought_text += chunk
                        thought_placeholder.markdown(thought_text)
                    elif event_type == "text":
                        if is_thinking:
                            thought_container.update(
                                label="💭 Thought process complete", state="complete", expanded=False
                            )
                            is_thinking = False
                        answer_text += chunk
                        answer_container.markdown(answer_text)
                    elif event_type == "error":
                        st.error(chunk)

                st.session_state.messages.append({
                    "role": "assistant",
                    "thought": thought_text if thought_text else None,
                    "content": answer_text
                })
        finally:
            st.session_state.is_generating = False


# ==========================================
# TAB 2: INTERACTIVE ARCHITECTURE MAP
# ==========================================
with tab_map:
    st.markdown("### Codebase Topography")
    st.caption("Explore the semantic relationships using the custom Graphify engine.")
    
    layout_style = st.radio(
        "Select Graph Layout:",
        ["🌐 Organic (Physics)", "📂 Hierarchical (Tree)"],
        horizontal=True
    )
    
    if st.button("🔄 Render Map", use_container_width=True):
        with st.spinner("Fetching topography from LocalGraph Engine..."):
            try:
                res = requests.get(
                    f"{API_BASE}/ingest/visualize/{st.session_state.active_repo}",
                    params={"target_path": st.session_state.target_path}
                )
                
                if res.status_code == 200:
                    graph_data = res.json()
                    
                    vis_nodes = []
                    community_counts = {}
                    node_colors = {} 
                    
                    tableau10 = ["#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F", 
                                 "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC"]
                    
                    for n in graph_data.get("nodes", []):
                        comm_id = n.get("group", "0")
                        
                        if comm_id not in community_counts:
                            community_counts[comm_id] = 0
                        community_counts[comm_id] += 1
                        
                        color_hex = tableau10[int(comm_id) % len(tableau10)]
                        node_colors[n["id"]] = color_hex 
                        
                        vis_nodes.append({
                            "id": n["id"],
                            "label": n["label"],
                            "title": n["title"],
                            "size": n["size"],
                            "shape": n["shape"],
                            "font": n.get("font"),
                            "color": {"background": color_hex, "border": color_hex},
                            "community": comm_id,
                            "community_name": f"Community {comm_id}",
                            "_file_type": n["type"]
                        })
                        
                    vis_edges = []
                    for e in graph_data.get("edges", []):
                        source_color = node_colors.get(e["source"], "#4a5568")
                        vis_edges.append({
                            "from": e["source"], 
                            "to": e["target"], 
                            "label": e["label"],
                            "color": source_color, 
                            "width": 0.4           
                        })
                        
                    # --- FIX 1: SORT THE LEGEND ---
                    vis_legend = []
                    # Sort the dictionary items strictly by their integer community ID
                    sorted_communities = sorted(community_counts.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else x[0])
                    
                    for cid, count in sorted_communities:
                        vis_legend.append({
                            "cid": cid, 
                            "color": tableau10[int(cid) % len(tableau10)], 
                            "label": f"Community {cid}", 
                            "count": count
                        })
                    
                    js_nodes = json.dumps(vis_nodes)
                    js_edges = json.dumps(vis_edges)
                    js_legend = json.dumps(vis_legend)

                    if layout_style == "📂 Hierarchical (Tree)":
                        js_physics_config = """
                        layout: {
                          hierarchical: { enabled: true, direction: "UD", sortMethod: "directed", levelSeparation: 150, nodeSpacing: 100 }
                        },
                        physics: {
                          solver: 'hierarchicalRepulsion',
                          hierarchicalRepulsion: { centralGravity: 0.0, springLength: 100, springConstant: 0.01, nodeDistance: 120 }
                        },
                        """
                    else:
                        js_physics_config = """
                        physics: {
                          solver: 'forceAtlas2Based',
                          forceAtlas2Based: { gravitationalConstant: -50, centralGravity: 0.005, springLength: 220, springConstant: 0.05, damping: 0.6, avoidOverlap: 1.0 },
                          stabilization: { iterations: 200, fit: true }
                        },
                        """

                    html_head = """
                    <!DOCTYPE html>
                    <html lang="en">
                    <head>
                    <meta charset="UTF-8">
                    <script src="https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"></script>
                    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
                    <style>
                      * { box-sizing: border-box; margin: 0; padding: 0; }
                      body { background: #0f0f1a; color: #e0e0e0; font-family: -apple-system, sans-serif; display: flex; height: 100vh; overflow: hidden; }
                      #graph { flex: 1; }
                      #sidebar { width: 280px; background: #1a1a2e; border-left: 1px solid #2a2a4e; display: flex; flex-direction: column; overflow: hidden; }
                      #search-wrap { padding: 12px; border-bottom: 1px solid #2a2a4e; }
                      #search { width: 100%; background: #0f0f1a; border: 1px solid #3a3a5e; color: #e0e0e0; padding: 7px 10px; border-radius: 6px; font-size: 13px; outline: none; margin-bottom: 8px; }
                      #search:focus { border-color: #4E79A7; }
                      #search-results { max-height: 140px; overflow-y: auto; padding: 4px 12px; border-bottom: 1px solid #2a2a4e; display: none; }
                      .search-item { padding: 4px 6px; cursor: pointer; border-radius: 4px; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
                      .search-item:hover { background: #2a2a4e; }
                      #info-panel { padding: 14px; border-bottom: 1px solid #2a2a4e; min-height: 140px; }
                      #info-panel h3 { font-size: 13px; color: #aaa; margin-bottom: 8px; text-transform: uppercase; }
                      #info-content { font-size: 13px; color: #ccc; line-height: 1.6; }
                      #info-content .field { margin-bottom: 5px; }
                      #info-content .field b { color: #e0e0e0; }
                      #info-content .empty { color: #555; font-style: italic; }
                      
                      /* NEW: Custom Markdown Styling for the Chat */
                      .md-content p { margin-bottom: 6px; }
                      .md-content code { background: #2a2a4e; padding: 2px 4px; border-radius: 3px; font-family: monospace; font-size: 11px; color: #F6E05E; }
                      .md-content pre { background: #0f0f1a; padding: 8px; border-radius: 4px; overflow-x: auto; margin-bottom: 6px; border: 1px solid #3a3a5e; }
                      .md-content pre code { background: transparent; color: #e0e0e0; padding: 0; }
                      .md-content ul, .md-content ol { padding-left: 20px; margin-bottom: 6px; }
                      
                      .neighbor-link { display: block; padding: 2px 6px; margin: 2px 0; border-radius: 3px; cursor: pointer; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; border-left: 3px solid #333; }
                      .neighbor-link:hover { background: #2a2a4e; }
                      #neighbors-list { max-height: 160px; overflow-y: auto; margin-top: 4px; }
                      #legend-wrap { flex: 1; overflow-y: auto; padding: 12px; }
                      #legend-wrap h3 { font-size: 13px; color: #aaa; margin-bottom: 10px; text-transform: uppercase; }
                      .legend-item { display: flex; align-items: center; gap: 8px; padding: 4px 0; cursor: pointer; border-radius: 4px; font-size: 12px; }
                      .legend-item:hover { background: #2a2a4e; padding-left: 4px; }
                      .legend-item.dimmed { opacity: 0.35; }
                      .legend-dot { width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }
                      .legend-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
                      .legend-count { color: #666; font-size: 11px; }
                      #legend-controls { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; padding: 4px 0; }
                      #legend-controls label { display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 12px; color: #aaa; user-select: none; }
                      #legend-controls label:hover { color: #e0e0e0; }
                      .legend-cb, #select-all-cb { appearance: none; -webkit-appearance: none; width: 14px; height: 14px; border: 1.5px solid #3a3a5e; border-radius: 3px; background: #0f0f1a; cursor: pointer; position: relative; flex-shrink: 0; }
                      .legend-cb:checked, #select-all-cb:checked { background: #4E79A7; border-color: #4E79A7; }
                      .legend-cb:checked::after, #select-all-cb:checked::after { content: ''; position: absolute; left: 3.5px; top: 1px; width: 4px; height: 7px; border: solid #fff; border-width: 0 2px 2px 0; transform: rotate(45deg); }
                      #select-all-cb:indeterminate { background: #4E79A7; border-color: #4E79A7; }
                      #select-all-cb:indeterminate::after { content: ''; position: absolute; left: 2px; top: 5px; width: 8px; height: 2px; background: #fff; border: none; transform: none; }
                    </style>
                    </head>
                    <body>
                    <div id="graph"></div>
                    <div id="sidebar">
                      <div id="search-wrap">
                        <input id="search" type="text" placeholder="Search nodes..." autocomplete="off">
                        <label style="color:#aaa; font-size:12px; cursor:pointer; display:flex; align-items:center; gap:6px; margin-top:8px;">
                          <input type="checkbox" id="isolate-cb" class="legend-cb"> Isolate Focus (1-Hop)
                        </label>
                        <div id="search-results"></div>
                      </div>
                      
                      <div id="info-panel">
                        <h3>Node Info</h3>
                        <div id="info-content"><span class="empty">Click a node to inspect it</span></div>
                      </div>
                      
                      <div id="node-chat-wrap" style="display: none; padding: 14px; border-bottom: 1px solid #2a2a4e; flex-direction: column; gap: 8px;">
                        <h3 style="font-size: 13px; color: #aaa; text-transform: uppercase;">Ask this Node</h3>
                        <div id="node-chat-history" style="max-height: 150px; overflow-y: auto; font-size: 12px; color: #ccc; display: flex; flex-direction: column; gap: 6px;"></div>
                        <input id="node-chat-input" type="text" placeholder="e.g. What does this function do?" autocomplete="off" style="width: 100%; background: #0f0f1a; border: 1px solid #3a3a5e; color: #e0e0e0; padding: 7px 10px; border-radius: 6px; font-size: 12px; outline: none;">
                      </div>

                      <div id="legend-wrap">
                        <h3>Communities</h3>
                        <div id="legend-controls">
                          <label><input type="checkbox" id="select-all-cb" checked onchange="toggleAllCommunities(!this.checked)">Select All</label>
                        </div>
                        <div id="legend"></div>
                      </div>
                    </div>
                    <script>
                    """

                    js_data = f"""
                    const API_BASE = "{API_BASE}";
                    const REPO_NAME = "{st.session_state.active_repo}";
                    const RAW_NODES = {js_nodes};
                    const RAW_EDGES = {js_edges};
                    const LEGEND = {js_legend};
                    """

                    js_logic = """
                    function esc(s) {
                      return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
                    }

                    const nodesDS = new vis.DataSet(RAW_NODES.map(n => ({
                      id: n.id, label: n.label, color: n.color, size: n.size,
                      font: n.font, title: n.title, shape: n.shape,
                      _community: n.community, _community_name: n.community_name,
                      _file_type: n._file_type
                    })));

                    const edgesDS = new vis.DataSet(RAW_EDGES.map((e, i) => ({
                      id: i, from: e.from, to: e.to, label: e.label,
                      width: e.width, color: e.color,
                      arrows: { to: { enabled: true, scaleFactor: 0.5 } },
                    })));

                    const container = document.getElementById('graph');
                    const network = new vis.Network(container, { nodes: nodesDS, edges: edgesDS }, {
                      """ + js_physics_config + """
                      interaction: { hover: true, tooltipDelay: 100, hideEdgesOnDrag: true },
                      nodes: { borderWidth: 1.5 },
                      edges: { smooth: { type: 'continuous', roundness: 0.2 }, selectionWidth: 3 },
                    });

                    network.once('stabilizationIterationsDone', () => {
                      if (network.physics) network.setOptions({ physics: { enabled: false } });
                    });

                    let currentSelectedNode = null;
                    const hiddenCommunities = new Set();
                    
                    // --- FIX 2: AUTO-FIT CAMERA LOGIC ---
                    function applyIsolation() {
                      const isolate = document.getElementById('isolate-cb').checked;
                      if (isolate && currentSelectedNode) {
                        const neighbors = network.getConnectedNodes(currentSelectedNode);
                        const visibleNodes = [currentSelectedNode, ...neighbors];
                        const visibleSet = new Set(visibleNodes);
                        
                        const updates = RAW_NODES.map(n => ({
                          id: n.id,
                          hidden: hiddenCommunities.has(n.community) || !visibleSet.has(n.id)
                        }));
                        nodesDS.update(updates);
                        
                        // Tell vis.js to calculate the exact bounding box and scale to fit beautifully!
                        setTimeout(() => { network.fit({ nodes: visibleNodes, animation: true, padding: 50 }); }, 50);
                      } else {
                        const updates = RAW_NODES.map(n => ({
                          id: n.id,
                          hidden: hiddenCommunities.has(n.community)
                        }));
                        nodesDS.update(updates);
                        
                        if (currentSelectedNode) {
                            setTimeout(() => { network.focus(currentSelectedNode, { scale: 1.2, animation: true }); }, 50);
                        } else {
                            setTimeout(() => { network.fit({ animation: true }); }, 50);
                        }
                      }
                    }

                    document.getElementById('isolate-cb').addEventListener('change', applyIsolation);

                    function showInfo(nodeId) {
                      const n = nodesDS.get(nodeId);
                      if (!n) return;
                      const neighborIds = network.getConnectedNodes(nodeId);
                      const neighborItems = neighborIds.map(nid => {
                        const nb = nodesDS.get(nid);
                        const color = nb ? nb.color.background : '#555';
                        return `<span class="neighbor-link" style="border-left-color:${esc(color)}" onclick="focusNode(${JSON.stringify(nid)})">${esc(nb ? nb.label : nid)}</span>`;
                      }).join('');
                      document.getElementById('info-content').innerHTML = `
                        <div class="field"><b>${esc(n.label)}</b></div>
                        <div class="field">Type: ${esc(n._file_type || 'unknown')}</div>
                        <div class="field">Community: ${esc(n._community_name)}</div>
                        ${neighborIds.length ? `<div class="field" style="margin-top:8px;color:#aaa;font-size:11px">Neighbors (${neighborIds.length})</div><div id="neighbors-list">${neighborItems}</div>` : ''}
                      `;
                    }

                    function focusNode(nodeId) {
                      currentSelectedNode = nodeId;
                      network.selectNodes([nodeId]);
                      showInfo(nodeId);
                      applyIsolation(); // Triggers the auto-fit camera
                    }

                    let hoveredNodeId = null;
                    network.on('hoverNode', params => { hoveredNodeId = params.node; container.style.cursor = 'pointer'; });
                    network.on('blurNode', () => { hoveredNodeId = null; container.style.cursor = 'default'; });
                    
                    // ... [Keep focusNode and showInfo above this] ...

                    const chatWrap = document.getElementById('node-chat-wrap');
                    const chatHistory = document.getElementById('node-chat-history');
                    const chatInput = document.getElementById('node-chat-input');

                    // FIX: Trigger chat UI when clicking directly on the canvas
                    network.on('selectNode', params => {
                      currentSelectedNode = params.nodes[0];
                      showInfo(currentSelectedNode);
                      applyIsolation();
                      
                      // Show chat box!
                      chatWrap.style.display = 'flex';
                      chatHistory.innerHTML = '';
                    });
                    
                    network.on('deselectNode', () => {
                      currentSelectedNode = null;
                      document.getElementById('info-content').innerHTML = '<span class="empty">Click a node to inspect it</span>';
                      applyIsolation();
                      
                      // Hide chat box!
                      chatWrap.style.display = 'none';
                    });

                    // Update focusNode just in case you use the search bar
                    function focusNode(nodeId) {
                      currentSelectedNode = nodeId;
                      network.selectNodes([nodeId]);
                      showInfo(nodeId);
                      applyIsolation(); 
                      
                      // Show chat box!
                      chatWrap.style.display = 'flex';
                      chatHistory.innerHTML = '';
                    }

                    // --- THE STREAMING & MARKDOWN CHAT LOGIC ---
                    chatInput.addEventListener('keypress', async function(e) {
                        if (e.key === 'Enter' && chatInput.value.trim() !== '') {
                            const question = chatInput.value.trim();
                            chatInput.value = '';
                            
                            chatHistory.innerHTML += `<div style="color: #F6E05E; margin-bottom: 6px;"><b>You:</b> ${esc(question)}</div>`;
                            chatHistory.scrollTop = chatHistory.scrollHeight;
                            
                            // 1. Initial State: Show "Thinking..."
                            const msgId = 'ai-msg-' + Date.now();
                            chatHistory.innerHTML += `<div style="color: #e0e0e0; margin-bottom: 12px;"><b>AI:</b> <span id="${msgId}" style="color: #aaa; font-style: italic;">Thinking...</span></div>`;
                            chatHistory.scrollTop = chatHistory.scrollHeight;
                            
                            const aiContainer = document.getElementById(msgId);
                            let fullMarkdown = "";
                            let isFirstChunk = true; // Flag to track if we need to remove "Thinking..."

                            try {
                                const response = await fetch(`${API_BASE}/query/node/${REPO_NAME}`, {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ node_id: currentSelectedNode, question: question })
                                });
                                
                                if (!response.ok) {
                                    aiContainer.innerHTML = `<span style="color: #E15759;">Error: ${response.statusText}</span>`;
                                    return;
                                }

                                const reader = response.body.getReader();
                                const decoder = new TextDecoder("utf-8");

                                while (true) {
                                    const { done, value } = await reader.read();
                                    if (done) break;
                                    
                                    // 2. Once the first chunk arrives, clear "Thinking..."
                                    if (isFirstChunk) {
                                        aiContainer.innerHTML = ""; 
                                        aiContainer.style.fontStyle = "normal"; // Reset italics
                                        aiContainer.classList.add("md-content"); // Enable Markdown styles
                                        isFirstChunk = false;
                                    }
                                    
                                    const chunkText = decoder.decode(value, { stream: true });
                                    fullMarkdown += chunkText;
                                    
                                    // 3. Stream the parsed markdown
                                    aiContainer.innerHTML = marked.parse(fullMarkdown);
                                    chatHistory.scrollTop = chatHistory.scrollHeight;
                                }
                                
                            } catch (error) {
                                aiContainer.innerHTML = `<span style="color: #E15759;">Connection lost.</span>`;
                            }
                        }
                    });
                    
                    network.on('deselectNode', () => {
                      currentSelectedNode = null;
                      document.getElementById('info-content').innerHTML = '<span class="empty">Click a node to inspect it</span>';
                      applyIsolation();
                    });

                    const searchInput = document.getElementById('search');
                    const searchResults = document.getElementById('search-results');
                    searchInput.addEventListener('input', () => {
                      const q = searchInput.value.toLowerCase().trim();
                      searchResults.innerHTML = '';
                      if (!q) { searchResults.style.display = 'none'; return; }
                      const matches = RAW_NODES.filter(n => n.label.toLowerCase().includes(q)).slice(0, 20);
                      if (!matches.length) { searchResults.style.display = 'none'; return; }
                      searchResults.style.display = 'block';
                      matches.forEach(n => {
                        const el = document.createElement('div');
                        el.className = 'search-item'; el.textContent = n.label;
                        el.style.borderLeft = `3px solid ${n.color.background}`; el.style.paddingLeft = '8px';
                        el.onclick = () => { focusNode(n.id); searchResults.style.display = 'none'; searchInput.value = ''; };
                        searchResults.appendChild(el);
                      });
                    });
                    
                    document.addEventListener('click', e => {
                      if (!searchResults.contains(e.target) && e.target !== searchInput) searchResults.style.display = 'none';
                    });

                    const selectAllCb = document.getElementById('select-all-cb');

                    function updateSelectAllState() {
                      const total = LEGEND.length; const hidden = hiddenCommunities.size;
                      selectAllCb.checked = hidden === 0; selectAllCb.indeterminate = hidden > 0 && hidden < total;
                    }

                    function toggleAllCommunities(hide) {
                      document.querySelectorAll('.legend-item').forEach(item => { hide ? item.classList.add('dimmed') : item.classList.remove('dimmed'); });
                      document.querySelectorAll('.legend-cb').forEach(cb => { cb.checked = !hide; });
                      LEGEND.forEach(c => { if (hide) hiddenCommunities.add(c.cid); else hiddenCommunities.delete(c.cid); });
                      applyIsolation(); 
                      updateSelectAllState();
                    }

                    const legendEl = document.getElementById('legend');
                    LEGEND.forEach(c => {
                      const item = document.createElement('div'); item.className = 'legend-item';
                      const cb = document.createElement('input'); cb.type = 'checkbox'; cb.className = 'legend-cb'; cb.checked = true;
                      cb.addEventListener('change', (e) => {
                        e.stopPropagation();
                        if (cb.checked) { hiddenCommunities.delete(c.cid); item.classList.remove('dimmed'); } 
                        else { hiddenCommunities.add(c.cid); item.classList.add('dimmed'); }
                        applyIsolation(); 
                        updateSelectAllState();
                      });
                      item.innerHTML = `<div class="legend-dot" style="background:${c.color}"></div><span class="legend-label">${c.label}</span><span class="legend-count">${c.count}</span>`;
                      item.prepend(cb);
                      item.onclick = (e) => { if (e.target === cb) return; cb.checked = !cb.checked; cb.dispatchEvent(new Event('change')); };
                      legendEl.appendChild(item);
                    });
                    """

                    html_foot = """
                    </script>
                    </body>
                    </html>
                    """
                    
                    custom_html = html_head + js_data + js_logic + html_foot
                    components.html(custom_html, height=800, scrolling=False)
                    # st.html(custom_html)
                    
            except Exception as e:
                st.error(f"Failed to connect to API: {e}")
# # ==========================================
# # TAB 2: INTERACTIVE ARCHITECTURE MAP
# # ==========================================
# with tab_map:
#     st.markdown("### Codebase Topography")
#     st.caption("Explore the semantic relationships using the custom Graphify engine.")
    
#     # --- NEW: Re-added Layout Toggle ---
#     layout_style = st.radio(
#         "Select Graph Layout:",
#         ["🌐 Organic (Physics)", "📂 Hierarchical (Tree)"],
#         horizontal=True
#     )
    
#     if st.button("🔄 Render Map", use_container_width=True):
#         with st.spinner("Fetching topography from LocalGraph Engine..."):
#             try:
#                 res = requests.get(f"{API_BASE}/ingest/visualize/{st.session_state.active_repo}")
                
#                 if res.status_code == 200:
#                     graph_data = res.json()
                    
#                     vis_nodes = []
#                     community_counts = {}
#                     node_colors = {} # <-- NEW: Lookup dict for edge colors
                    
#                     tableau10 = ["#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F", 
#                                  "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC"]
                    
#                     for n in graph_data.get("nodes", []):
#                         comm_id = n.get("group", "0")
                        
#                         if comm_id not in community_counts:
#                             community_counts[comm_id] = 0
#                         community_counts[comm_id] += 1
                        
#                         color_hex = tableau10[int(comm_id) % len(tableau10)]
#                         node_colors[n["id"]] = color_hex # Save color for edges
                        
#                         vis_nodes.append({
#                             "id": n["id"],
#                             "label": n["label"],
#                             "title": n["title"],
#                             "size": n["size"],
#                             "shape": n["shape"],
#                             "font": n.get("font"),
#                             "color": {"background": color_hex, "border": color_hex},
#                             "community": comm_id,
#                             "community_name": f"Community {comm_id}",
#                             "_file_type": n["type"]
#                         })
                        
#                     vis_edges = []
#                     for e in graph_data.get("edges", []):
#                         # --- NEW: Edge inherits color from its source node ---
#                         source_color = node_colors.get(e["source"], "#4a5568")
                        
#                         vis_edges.append({
#                             "from": e["source"], 
#                             "to": e["target"], 
#                             "label": e["label"],
#                             "color": source_color, # Colored edges!
#                             "width": 0.4           # Slightly thicker to show off the color
#                         })
                        
#                     vis_legend = []
#                     for cid, count in community_counts.items():
#                         vis_legend.append({
#                             "cid": cid, 
#                             "color": tableau10[int(cid) % len(tableau10)], 
#                             "label": f"Community {cid}", 
#                             "count": count
#                         })
                    
#                     js_nodes = json.dumps(vis_nodes)
#                     js_edges = json.dumps(vis_edges)
#                     js_legend = json.dumps(vis_legend)

#                     # --- NEW: Dynamic Physics based on Streamlit Radio ---
#                     if layout_style == "📂 Hierarchical (Tree)":
#                         js_physics_config = """
#                         layout: {
#                           hierarchical: { enabled: true, direction: "UD", sortMethod: "directed", levelSeparation: 150, nodeSpacing: 100 }
#                         },
#                         physics: {
#                           solver: 'hierarchicalRepulsion',
#                           hierarchicalRepulsion: { centralGravity: 0.0, springLength: 100, springConstant: 0.01, nodeDistance: 120 }
#                         },
#                         """
#                     else:
#                         js_physics_config = """
#                         physics: {
#                           solver: 'forceAtlas2Based',
#                           forceAtlas2Based: { gravitationalConstant: -50, centralGravity: 0.005, springLength: 220, springConstant: 0.05, damping: 0.6, avoidOverlap: 1.0 },
#                           stabilization: { iterations: 200, fit: true }
#                         },
#                         """

#                     html_head = """
#                     <!DOCTYPE html>
#                     <html lang="en">
#                     <head>
#                     <meta charset="UTF-8">
#                     <script src="https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"></script>
#                     <style>
#                       * { box-sizing: border-box; margin: 0; padding: 0; }
#                       body { background: #0f0f1a; color: #e0e0e0; font-family: -apple-system, sans-serif; display: flex; height: 100vh; overflow: hidden; }
#                       #graph { flex: 1; }
#                       #sidebar { width: 280px; background: #1a1a2e; border-left: 1px solid #2a2a4e; display: flex; flex-direction: column; overflow: hidden; }
#                       #search-wrap { padding: 12px; border-bottom: 1px solid #2a2a4e; }
#                       #search { width: 100%; background: #0f0f1a; border: 1px solid #3a3a5e; color: #e0e0e0; padding: 7px 10px; border-radius: 6px; font-size: 13px; outline: none; margin-bottom: 8px; }
#                       #search:focus { border-color: #4E79A7; }
#                       #search-results { max-height: 140px; overflow-y: auto; padding: 4px 12px; border-bottom: 1px solid #2a2a4e; display: none; }
#                       .search-item { padding: 4px 6px; cursor: pointer; border-radius: 4px; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#                       .search-item:hover { background: #2a2a4e; }
#                       #info-panel { padding: 14px; border-bottom: 1px solid #2a2a4e; min-height: 140px; }
#                       #info-panel h3 { font-size: 13px; color: #aaa; margin-bottom: 8px; text-transform: uppercase; }
#                       #info-content { font-size: 13px; color: #ccc; line-height: 1.6; }
#                       #info-content .field { margin-bottom: 5px; }
#                       #info-content .field b { color: #e0e0e0; }
#                       #info-content .empty { color: #555; font-style: italic; }
#                       .neighbor-link { display: block; padding: 2px 6px; margin: 2px 0; border-radius: 3px; cursor: pointer; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; border-left: 3px solid #333; }
#                       .neighbor-link:hover { background: #2a2a4e; }
#                       #neighbors-list { max-height: 160px; overflow-y: auto; margin-top: 4px; }
#                       #legend-wrap { flex: 1; overflow-y: auto; padding: 12px; }
#                       #legend-wrap h3 { font-size: 13px; color: #aaa; margin-bottom: 10px; text-transform: uppercase; }
#                       .legend-item { display: flex; align-items: center; gap: 8px; padding: 4px 0; cursor: pointer; border-radius: 4px; font-size: 12px; }
#                       .legend-item:hover { background: #2a2a4e; padding-left: 4px; }
#                       .legend-item.dimmed { opacity: 0.35; }
#                       .legend-dot { width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }
#                       .legend-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#                       .legend-count { color: #666; font-size: 11px; }
#                       #legend-controls { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; padding: 4px 0; }
#                       #legend-controls label { display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 12px; color: #aaa; user-select: none; }
#                       #legend-controls label:hover { color: #e0e0e0; }
#                       .legend-cb, #select-all-cb { appearance: none; -webkit-appearance: none; width: 14px; height: 14px; border: 1.5px solid #3a3a5e; border-radius: 3px; background: #0f0f1a; cursor: pointer; position: relative; flex-shrink: 0; }
#                       .legend-cb:checked, #select-all-cb:checked { background: #4E79A7; border-color: #4E79A7; }
#                       .legend-cb:checked::after, #select-all-cb:checked::after { content: ''; position: absolute; left: 3.5px; top: 1px; width: 4px; height: 7px; border: solid #fff; border-width: 0 2px 2px 0; transform: rotate(45deg); }
#                     </style>
#                     </head>
#                     <body>
#                     <div id="graph"></div>
#                     <div id="sidebar">
#                       <div id="search-wrap">
#                         <input id="search" type="text" placeholder="Search nodes..." autocomplete="off">
#                         <label style="color:#aaa; font-size:12px; cursor:pointer; display:flex; align-items:center; gap:6px; margin-top:8px;">
#                           <input type="checkbox" id="isolate-cb" class="legend-cb"> Isolate Focus (1-Hop)
#                         </label>
#                         <div id="search-results"></div>
#                       </div>
#                       <div id="info-panel">
#                         <h3>Node Info</h3>
#                         <div id="info-content"><span class="empty">Click a node to inspect it</span></div>
#                       </div>
#                       <div id="legend-wrap">
#                         <h3>Communities</h3>
#                         <div id="legend-controls">
#                           <label><input type="checkbox" id="select-all-cb" checked onchange="toggleAllCommunities(!this.checked)">Select All</label>
#                         </div>
#                         <div id="legend"></div>
#                       </div>
#                     </div>
#                     <script>
#                     """

#                     js_data = f"""
#                     const RAW_NODES = {js_nodes};
#                     const RAW_EDGES = {js_edges};
#                     const LEGEND = {js_legend};
#                     """

#                     js_logic = """
#                     function esc(s) {
#                       return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
#                     }

#                     const nodesDS = new vis.DataSet(RAW_NODES.map(n => ({
#                       id: n.id, label: n.label, color: n.color, size: n.size,
#                       font: n.font, title: n.title, shape: n.shape,
#                       _community: n.community, _community_name: n.community_name,
#                       _file_type: n._file_type
#                     })));

#                     const edgesDS = new vis.DataSet(RAW_EDGES.map((e, i) => ({
#                       id: i, from: e.from, to: e.to, label: e.label,
#                       width: e.width, color: e.color,
#                       arrows: { to: { enabled: true, scaleFactor: 0.5 } },
#                     })));

#                     const container = document.getElementById('graph');
#                     const network = new vis.Network(container, { nodes: nodesDS, edges: edgesDS }, {
#                       """ + js_physics_config + """
#                       interaction: { hover: true, tooltipDelay: 100, hideEdgesOnDrag: true },
#                       nodes: { borderWidth: 1.5 },
#                       edges: { smooth: { type: 'continuous', roundness: 0.2 }, selectionWidth: 3 },
#                     });

#                     network.once('stabilizationIterationsDone', () => {
#                       if (network.physics) network.setOptions({ physics: { enabled: false } });
#                     });

#                     // --- ISOLATION LOGIC ---
#                     let currentSelectedNode = null;
#                     const hiddenCommunities = new Set();
                    
#                     function applyIsolation() {
#                       const isolate = document.getElementById('isolate-cb').checked;
#                       if (isolate && currentSelectedNode) {
#                         const neighbors = network.getConnectedNodes(currentSelectedNode);
#                         const visibleSet = new Set([currentSelectedNode, ...neighbors]);
#                         const updates = RAW_NODES.map(n => ({
#                           id: n.id,
#                           hidden: hiddenCommunities.has(n.community) || !visibleSet.has(n.id)
#                         }));
#                         nodesDS.update(updates);
#                       } else {
#                         const updates = RAW_NODES.map(n => ({
#                           id: n.id,
#                           hidden: hiddenCommunities.has(n.community)
#                         }));
#                         nodesDS.update(updates);
#                       }
#                     }

#                     document.getElementById('isolate-cb').addEventListener('change', applyIsolation);

#                     function showInfo(nodeId) {
#                       const n = nodesDS.get(nodeId);
#                       if (!n) return;
#                       const neighborIds = network.getConnectedNodes(nodeId);
#                       const neighborItems = neighborIds.map(nid => {
#                         const nb = nodesDS.get(nid);
#                         const color = nb ? nb.color.background : '#555';
#                         return `<span class="neighbor-link" style="border-left-color:${esc(color)}" onclick="focusNode(${JSON.stringify(nid)})">${esc(nb ? nb.label : nid)}</span>`;
#                       }).join('');
#                       document.getElementById('info-content').innerHTML = `
#                         <div class="field"><b>${esc(n.label)}</b></div>
#                         <div class="field">Type: ${esc(n._file_type || 'unknown')}</div>
#                         <div class="field">Community: ${esc(n._community_name)}</div>
#                         ${neighborIds.length ? `<div class="field" style="margin-top:8px;color:#aaa;font-size:11px">Neighbors (${neighborIds.length})</div><div id="neighbors-list">${neighborItems}</div>` : ''}
#                       `;
#                     }

#                     function focusNode(nodeId) {
#                       network.focus(nodeId, { scale: 1.4, animation: true });
#                       network.selectNodes([nodeId]);
#                       currentSelectedNode = nodeId;
#                       showInfo(nodeId);
#                       applyIsolation();
#                     }

#                     let hoveredNodeId = null;
#                     network.on('hoverNode', params => { hoveredNodeId = params.node; container.style.cursor = 'pointer'; });
#                     network.on('blurNode', () => { hoveredNodeId = null; container.style.cursor = 'default'; });
                    
#                     network.on('selectNode', params => {
#                       currentSelectedNode = params.nodes[0];
#                       showInfo(currentSelectedNode);
#                       applyIsolation();
#                     });
                    
#                     network.on('deselectNode', () => {
#                       currentSelectedNode = null;
#                       document.getElementById('info-content').innerHTML = '<span class="empty">Click a node to inspect it</span>';
#                       applyIsolation();
#                     });

#                     const searchInput = document.getElementById('search');
#                     const searchResults = document.getElementById('search-results');
#                     searchInput.addEventListener('input', () => {
#                       const q = searchInput.value.toLowerCase().trim();
#                       searchResults.innerHTML = '';
#                       if (!q) { searchResults.style.display = 'none'; return; }
#                       const matches = RAW_NODES.filter(n => n.label.toLowerCase().includes(q)).slice(0, 20);
#                       if (!matches.length) { searchResults.style.display = 'none'; return; }
#                       searchResults.style.display = 'block';
#                       matches.forEach(n => {
#                         const el = document.createElement('div');
#                         el.className = 'search-item'; el.textContent = n.label;
#                         el.style.borderLeft = `3px solid ${n.color.background}`; el.style.paddingLeft = '8px';
#                         el.onclick = () => { focusNode(n.id); searchResults.style.display = 'none'; searchInput.value = ''; };
#                         searchResults.appendChild(el);
#                       });
#                     });
#                     document.addEventListener('click', e => {
#                       if (!searchResults.contains(e.target) && e.target !== searchInput) searchResults.style.display = 'none';
#                     });

#                     const selectAllCb = document.getElementById('select-all-cb');

#                     function updateSelectAllState() {
#                       const total = LEGEND.length; const hidden = hiddenCommunities.size;
#                       selectAllCb.checked = hidden === 0; selectAllCb.indeterminate = hidden > 0 && hidden < total;
#                     }

#                     function toggleAllCommunities(hide) {
#                       document.querySelectorAll('.legend-item').forEach(item => { hide ? item.classList.add('dimmed') : item.classList.remove('dimmed'); });
#                       document.querySelectorAll('.legend-cb').forEach(cb => { cb.checked = !hide; });
#                       LEGEND.forEach(c => { if (hide) hiddenCommunities.add(c.cid); else hiddenCommunities.delete(c.cid); });
#                       applyIsolation(); // Re-apply visibility rules
#                       updateSelectAllState();
#                     }

#                     const legendEl = document.getElementById('legend');
#                     LEGEND.forEach(c => {
#                       const item = document.createElement('div'); item.className = 'legend-item';
#                       const cb = document.createElement('input'); cb.type = 'checkbox'; cb.className = 'legend-cb'; cb.checked = true;
#                       cb.addEventListener('change', (e) => {
#                         e.stopPropagation();
#                         if (cb.checked) { hiddenCommunities.delete(c.cid); item.classList.remove('dimmed'); } 
#                         else { hiddenCommunities.add(c.cid); item.classList.add('dimmed'); }
#                         applyIsolation(); // Re-apply visibility rules
#                         updateSelectAllState();
#                       });
#                       item.innerHTML = `<div class="legend-dot" style="background:${c.color}"></div><span class="legend-label">${c.label}</span><span class="legend-count">${c.count}</span>`;
#                       item.prepend(cb);
#                       item.onclick = (e) => { if (e.target === cb) return; cb.checked = !cb.checked; cb.dispatchEvent(new Event('change')); };
#                       legendEl.appendChild(item);
#                     });
#                     """

#                     html_foot = """
#                     </script>
#                     </body>
#                     </html>
#                     """
                    
#                     custom_html = html_head + js_data + js_logic + html_foot
#                     components.html(custom_html, height=800, scrolling=False)
                    
#             except Exception as e:
#                 st.error(f"Failed to connect to API: {e}")
