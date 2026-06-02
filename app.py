import re
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
    st.session_state.active_repo = "Latest"
if "target_path" not in st.session_state:
    st.session_state.target_path = "./my_mock_test"
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
    
    repo_input = st.text_input("Repository Name", value=st.session_state.active_repo)
    repo_input = repo_input.strip().replace(" ", "_")
    path_input = st.text_input("Local Source Path", key="target_path")
    
    if st.button("Ingest & Analyze Codebase", use_container_width=True):
        if st.session_state.is_generating:
            st.session_state.interruption_message = (
                "⚠️ Response generation was interrupted because a codebase ingestion was started."
            )
            st.session_state.is_generating = False
            
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

        # Search highlight — override color if name matches
        base_color = n["color"]
        if search_term and search_term.lower() in n["label"].lower():
            base_color = "#F6E05E"  # bright yellow highlight
            
        # AFTER — wrap in HTML so vis.js renders a tooltip, never navigates
        # safe_title = f"<div style='max-width:200px;white-space:normal'>{n['title']}</div>"

        nodes.append(Node(
            id=n["id"],
            label=n["label"],
            # title=safe_title,
            title=n["title"],
            color=base_color,
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
            width=0.8,
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
            # interaction={
            #     "navigationButtons": show_minimap,
            #     "keyboard": True,
            # },
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
                    "gravitationalConstant": -250,
                    "centralGravity": 0.002,
                    "springLength": 350,
                    "springConstant": 0.02,
                    "damping": 0.8,
                    "avoidOverlap": 1.0,
                },
                "stabilization": {"enabled": True, "iterations": 3000, "updateInterval": 25},
                "minVelocity": 0.75,
            },
            # vis.js navigation options — forwarded as kwargs
            # whether this works depends on your streamlit-agraph version
            navigation=show_minimap,
            # interaction={
            #     "navigationButtons": show_minimap,
            #     "keyboard": True,
            # },
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
    st.caption("Explore the semantic relationships between files, classes, and functions.")

    layout_style = st.radio(
        "Select Graph Layout:",
        ["🌐 Organic (Physics-Driven)", "📂 Hierarchical (Tree)"],
        horizontal=True
    )

    col_toggle1, col_toggle2, col_toggle3 = st.columns(3)
    with col_toggle1:
        show_functions = st.toggle("Show all function nodes", value=False)
    with col_toggle2:
        isolate_mode = st.toggle("Isolate selected node", value=False)
    with col_toggle3:
        show_minimap = st.toggle("Navigation buttons", value=False) 

    # Search bar
    search_term = st.text_input(
        "🔍 Highlight node by name", 
        placeholder="e.g. GraphAnalyst, query_engine...",
        label_visibility="collapsed"
    )

    if st.button("🔄 Render Map", use_container_width=True):
        with st.spinner("Fetching topography from LocalGraph Engine..."):
            try:
                res = requests.get(f"{API_BASE}/ingest/visualize/{st.session_state.active_repo}")

                if res.status_code == 200:
                    # ✅ Store raw unfiltered data in session state — used by expand/isolate
                    st.session_state.raw_graph_data = res.json()
                    st.session_state.expanded_classes = set()
                    st.session_state.selected_node = None
                    st.session_state.isolate_node = None
                else:
                    st.error("Could not load graph. Have you ingested the repository yet?")
            except Exception as e:
                st.error(f"Failed to connect to API: {e}")


    # ─────────────────────────────────────────────────────────
    # Render
    # ─────────────────────────────────────────────────────────
    if st.session_state.raw_graph_data is not None:
        nodes, edges = build_graph_objects(
            st.session_state.raw_graph_data,
            show_functions,
            search_term,
            st.session_state.expanded_classes,
            st.session_state.isolate_node if isolate_mode else None,
        )
        config = build_config(layout_style, show_minimap=show_minimap)

        graph_col, detail_col = st.columns([3, 1])

        with graph_col:
            # ── Legend ────────────────────────────────────────
            st.markdown(
                """
                <div style="display:flex; gap:18px; align-items:center; 
                            margin-bottom:8px; font-size:13px; color:#a0aec0;">
                    <span><span style="display:inline-block; width:14px; height:14px; 
                        background:#63B3ED; border-radius:3px; 
                        margin-right:5px; vertical-align:middle;"></span>File</span>
                    <span><span style="display:inline-block; width:14px; height:14px; 
                        background:#F6AD55; border-radius:50%; 
                        margin-right:5px; vertical-align:middle;"></span>Class</span>
                    <span><span style="display:inline-block; width:14px; height:14px; 
                        background:#68D391; border-radius:50%; 
                        margin-right:5px; vertical-align:middle;"></span>Function / Method</span>
                    <span style="margin-left:auto; font-style:italic; font-size:11px;">
                        Click a class node to expand its methods</span>
                </div>
                """,
                unsafe_allow_html=True
            )
            # Inject a small script to override window.open inside the agraph iframe and prevent double click routing/navigation without console log noise
            st.markdown(
                """
                <img src="x" onerror="
                  (function() {
                    if (window.__override_open_done) return;
                    window.__override_open_done = true;
                    function disableDoubleClickOpen() {
                        const iframes = document.querySelectorAll('iframe');
                        iframes.forEach(iframe => {
                            try {
                                if (iframe.contentWindow && !iframe.contentWindow.__override_open) {
                                    iframe.contentWindow.__override_open = true;
                                    iframe.contentWindow.open = function(url, target, features) {
                                        return null;
                                    };
                                }
                            } catch (e) {}
                        });
                    }
                    setInterval(disableDoubleClickOpen, 100);
                  })()
                " style="display:none;">
                """,
                unsafe_allow_html=True
            )

            try:
                clicked = agraph(nodes=nodes, edges=edges, config=config)
            except Exception as e:
                clicked = None

        # ── Handle click ──────────────────────────────────────
        # if clicked and clicked != st.session_state.selected_node:
        if clicked:
            st.session_state.selected_node = clicked

            # Isolate mode: store which node to isolate
            if isolate_mode:
                st.session_state.isolate_node = clicked
            else:
                st.session_state.isolate_node = None

            # Click-to-expand: if it's a class and functions are hidden, toggle its methods
            if not show_functions:
                clicked_node_data = next(
                    (n for n in st.session_state.raw_graph_data["nodes"]
                     if n["id"] == clicked), None
                )
                if clicked_node_data and clicked_node_data.get("type") == "class":
                    if clicked in st.session_state.expanded_classes:
                        st.session_state.expanded_classes.discard(clicked)
                    else:
                        st.session_state.expanded_classes.add(clicked)
            st.rerun()
        # elif not clicked and st.session_state.selected_node is not None:
        #     st.session_state.selected_node = None
        #     st.session_state.isolate_node = None
        #     st.rerun()

        # ── Node detail panel ─────────────────────────────────
        with detail_col:
            if st.session_state.selected_node:
                node_data = next(
                    (n for n in st.session_state.raw_graph_data["nodes"]
                     if n["id"] == st.session_state.selected_node), None
                )
                if node_data:
                    ntype = node_data.get("type", "unknown").upper()
                    icon = {"FILE": "📄", "CLASS": "📦", "FUNCTION": "⚙️"}.get(ntype, "🔷")

                    st.markdown(f"### {icon} {node_data['label']}")
                    st.caption(f"`{node_data['id']}`")
                    st.divider()

                    # Summary (stored in title after wrapping, so use raw title)
                    st.markdown("**Summary**")
                    st.markdown(node_data.get("summary", "No summary available."))
                    # st.markdown(node_data.get("title", "No summary available."))
                    # raw_title = node_data.get("title", "No summary available.")
                    # clean_summary = re.sub(r"<[^>]+>", "", raw_title).strip()  # strip the div wrapper
                    # st.markdown(clean_summary or "No summary available.")
                    st.divider()

                    # Find edges involving this node
                    related = [
                        e for e in st.session_state.raw_graph_data["edges"]
                        if e["source"] == st.session_state.selected_node
                        or e["target"] == st.session_state.selected_node
                    ]
                    if related:
                        st.markdown("**Relationships**")
                        for e in related[:8]:  # cap at 8 to avoid overflow
                            if e["source"] == st.session_state.selected_node:
                                st.caption(f"→ `{e['target'].split('::')[-1]}` ({e['label'] or 'links to'})")
                            else:
                                st.caption(f"← `{e['source'].split('::')[-1]}` ({e['label'] or 'links from'})")
                    st.divider()

                    # ✅ "Ask AI" button — switches to chat tab and prefills context
                    ask_label = node_data['label']
                    ask_file = node_data['id'].split("::")[0]
                    prefill = f"Explain the `{ask_label}` {ntype.lower()} in `{ask_file}` in detail."
                    if st.button("💬 Ask AI about this", use_container_width=True):
                        st.session_state.prefill_prompt = prefill
                        st.rerun()
                        # st.session_state.messages.append({"role": "user", "content": prefill})
                        # st.session_state.active_tab = "chat"   # signal to switch tab
                        # st.rerun()

                    if isolate_mode and st.session_state.isolate_node:
                        if st.button("🔍 Clear Isolation", use_container_width=True):
                            st.session_state.isolate_node = None
                            st.rerun()
            else:
                st.caption("Click any node to see details here.")
                if not show_functions:
                    st.caption("💡 Click a class node to expand its methods.")
                    
# with tab_map:
#     st.markdown("### Codebase Topography")
#     st.caption("Explore the semantic relationships between files, classes, and functions.")

#     layout_style = st.radio(
#         "Select Graph Layout:",
#         ["🌐 Organic (Physics-Driven)", "📂 Hierarchical (Tree)"],
#         horizontal=True
#     )
#     show_functions = st.toggle("Show function nodes", value=False)

#     if st.button("🔄 Render Map", use_container_width=True):
#         with st.spinner("Fetching topography from LocalGraph Engine..."):
#             try:
#                 res = requests.get(f"{API_BASE}/ingest/visualize/{st.session_state.active_repo}")

#                 if res.status_code == 200:
#                     graph_data = res.json()

#                     if not show_functions:
#                         fn_ids = {
#                             n["id"] for n in graph_data["nodes"]
#                             if n.get("type") == "function"
#                         }
#                         graph_data["nodes"] = [n for n in graph_data["nodes"] if n["id"] not in fn_ids]
#                         graph_data["edges"] = [e for e in graph_data["edges"]
#                                                if e["source"] not in fn_ids and e["target"] not in fn_ids]

#                     nodes = [Node(
#                         id=n["id"], label=n["label"], title=n["title"],
#                         color=n["color"], size=n["size"], group=n.get("group"),
#                         shape=n.get("shape", "dot"),
#                         font=n.get("font", {"size": 9, "color": "#718096"}),
#                     ) for n in graph_data["nodes"]]

#                     edges = [Edge(
#                         source=e["source"], target=e["target"], label=e["label"],
#                         color="#4a5568", width=0.8,
#                     ) for e in graph_data["edges"]]

#                     if layout_style == "📂 Hierarchical (Tree)":
#                         config = Config(
#                             width="100%", height=700, directed=True,
#                             hierarchical=True,
#                             layout={"hierarchical": {
#                                 "enabled": True, "direction": "UD",
#                                 "sortMethod": "directed", "levelSeparation": 150, "nodeSpacing": 100
#                             }},
#                             physics={
#                                 "hierarchicalRepulsion": {"centralGravity": 0.0, "springLength": 100,
#                                                           "springConstant": 0.01, "nodeDistance": 120},
#                                 "solver": "hierarchicalRepulsion"
#                             },
#                             nodeHighlightBehavior=True, highlightColor="#F7A072", collapsible=True
#                         )
#                     else:
#                         config = Config(
#                             width="100%", height=700, directed=True, hierarchical=False,
#                             physics={
#                                 "solver": "forceAtlas2Based",
#                                 "forceAtlas2Based": {
#                                     "gravitationalConstant": -250,
#                                     "centralGravity": 0.002,
#                                     "springLength": 350,
#                                     "springConstant": 0.02,
#                                     "damping": 0.8,
#                                     "avoidOverlap": 1.0,
#                                 },
#                                 "stabilization": {"enabled": True, "iterations": 3000, "updateInterval": 25},
#                                 "minVelocity": 0.75,
#                             },
#                             nodeHighlightBehavior=True, highlightColor="#F7A072", collapsible=True,
#                         )

#                     # ✅ Persist to session state so reruns don't wipe the graph
#                     st.session_state.graph_nodes = nodes
#                     st.session_state.graph_edges = edges
#                     st.session_state.graph_config = config
#                     st.session_state.selected_node = None

#                 else:
#                     st.error("Could not load graph. Have you ingested the repository yet?")
#             except Exception as e:
#                 st.error(f"Failed to connect to API: {e}")

#     # ✅ Always render from session state — survives node-click reruns
#     if st.session_state.graph_nodes is not None:
#         clicked = agraph(
#             nodes=st.session_state.graph_nodes,
#             edges=st.session_state.graph_edges,
#             config=st.session_state.graph_config,
#         )
#         # After the agraph() call
#         if clicked and not show_functions:
#             clicked_type = next(
#                 (n["type"] for n in raw_graph_data["nodes"] if n["id"] == clicked), None
#             )
            
#             if clicked_type == "class":
#                 # Find all function nodes that belong to this class's file
#                 # and are called by or contained in this class
#                 child_fns = [
#                     n for n in raw_graph_data["nodes"]
#                     if n.get("type") == "function"
#                     and n["id"].startswith(clicked.split("::")[0])  # same file
#                 ]
#         if clicked:
#             st.session_state.selected_node = clicked

#         if st.session_state.selected_node:
#             st.info(f"**Selected Node:** `{st.session_state.selected_node}`")
# with tab_map:
#     st.markdown("### Codebase Topography")
#     st.caption("Explore the semantic relationships between files, classes, and functions.")
    
#     # --- NEW: Layout Style Toggle ---
#     layout_style = st.radio(
#         "Select Graph Layout:",
#         ["🌐 Organic (Physics-Driven)", "📂 Hierarchical (Tree)"],
#         horizontal=True
#     )
#     show_functions = st.toggle("Show function nodes", value=False)
    
#     if st.button("🔄 Render Map", use_container_width=True):
#         with st.spinner("Fetching topography from LocalGraph Engine..."):
#             try:
#                 res = requests.get(f"{API_BASE}/ingest/visualize/{st.session_state.active_repo}")
                
#                 if res.status_code == 200:
#                     graph_data = res.json()
                    
#                     # ✅ FILTER FIRST, before building any Node/Edge objects
#                     if not show_functions:
#                         fn_ids = {
#                             n["id"] for n in graph_data["nodes"]
#                             if n.get("type") == "function"   # ← precise, won't catch classes
#                         }
#                         graph_data["nodes"] = [
#                             n for n in graph_data["nodes"]
#                             if n["id"] not in fn_ids
#                         ]
#                         graph_data["edges"] = [
#                             e for e in graph_data["edges"]
#                             if e["source"] not in fn_ids
#                             and e["target"] not in fn_ids
#                         ]
                    
#                     # Convert JSON to agraph objects
#                     nodes = [Node(
#                         id=n["id"],
#                         label=n["label"],
#                         title=n["title"],
#                         color=n["color"],
#                         size=n["size"],
#                         group=n.get("group"),
#                         shape=n.get("shape", "dot"),
#                         font=n.get("font", {"size": 9, "color": "#718096"}),  # ← key fix
#                     ) for n in graph_data["nodes"]]

#                     edges = [Edge(
#                         source=e["source"], 
#                         target=e["target"], 
#                         label=e["label"],
#                         color="#4a5568",
#                         width=0.8
#                         ) for e in graph_data["edges"]]
                    
#                     if not show_functions:
#                         # Filter out function nodes and their edges from the payload
#                         fn_ids = {n["id"] for n in graph_data["nodes"] if n.get("shape") == "dot" 
#                                 and n["id"].count("::") == 1}
#                         # Keep files and classes only
#                         graph_data["nodes"] = [n for n in graph_data["nodes"] 
#                                             if n["id"] not in fn_ids]
#                         graph_data["edges"] = [e for e in graph_data["edges"] 
#                                             if e["source"] not in fn_ids 
#                                             and e["target"] not in fn_ids]
                                
#                     # --- NEW: Dynamic Configuration based on Toggle ---
#                     if layout_style == "📂 Hierarchical (Tree)":
#                         config = Config(
#                             width="100%", height=700, directed=True,
#                             hierarchical=True,
#                             layout={
#                                 "hierarchical": {
#                                     "enabled": True, "direction": "UD",
#                                     "sortMethod": "directed", "levelSeparation": 150, "nodeSpacing": 100
#                                 }
#                             },
#                             physics={
#                                 "hierarchicalRepulsion": {"centralGravity": 0.0, "springLength": 100, "springConstant": 0.01, "nodeDistance": 120},
#                                 "solver": "hierarchicalRepulsion"
#                             },
#                             nodeHighlightBehavior=True, highlightColor="#F7A072", collapsible=True
#                         )
#                     else:
#                         config = Config(
#                             width="100%",
#                             height=700,
#                             directed=True,
#                             hierarchical=False,
#                             physics={
#                                 "solver": "forceAtlas2Based",
#                                 "forceAtlas2Based": {
#                                     "gravitationalConstant": -250,  # was -80, needs to be brutal
#                                     "centralGravity": 0.002,        # nearly zero — let nodes breathe
#                                     "springLength": 350,            # was 250, push neighbours further
#                                     "springConstant": 0.02,         # softer springs = more spread
#                                     "damping": 0.8,
#                                     "avoidOverlap": 1.0,
#                                 },
#                                 "stabilization": {
#                                     "enabled": True,
#                                     "iterations": 3000,            # was 2500
#                                     "updateInterval": 25,
#                                 },
#                                 "minVelocity": 0.75,               # stop earlier once stable
#                             },
#                             nodeHighlightBehavior=True,
#                             highlightColor="#F7A072",
#                             collapsible=True,
#                         )

#                     # Render the graph
#                     selected_node = agraph(nodes=nodes, edges=edges, config=config)
                    
#                     if selected_node:
#                         st.info(f"**Selected Node:** `{selected_node}`")
#                 else:
#                     st.error("Could not load graph. Have you ingested the repository yet?")
#             except Exception as e:
#                 st.error(f"Failed to connect to API: {e}")
# # ==========================================
# # TAB 2: INTERACTIVE ARCHITECTURE MAP
# # ==========================================

# with tab_map:
#     st.markdown("### Codebase Topography")
#     st.caption("Explore the semantic relationships between files, classes, and functions.")
    
#     if st.button("🔄 Render Map", use_container_width=True):
#         with st.spinner("Fetching topography from LocalGraph Engine..."):
#             try:
#                 # We will build this endpoint in the backend next!
#                 res = requests.get(f"{API_BASE}/ingest/visualize/{st.session_state.active_repo}")
                
#                 if res.status_code == 200:
#                     graph_data = res.json()
                    
#                     # Convert JSON to agraph objects
#                     nodes = [Node(id=n["id"], label=n["label"], title=n["title"], color=n["color"], size=n["size"]) for n in graph_data["nodes"]]
#                     edges = [Edge(source=e["source"], target=e["target"], label=e["label"]) for e in graph_data["edges"]]
                    
#                     # Configure the physics engine
#                     # Configure the physics engine for a clean, hierarchical tree
#                     config = Config(
#                         width="100%",
#                         height=700,
#                         directed=True,
                        
#                         # --- NEW: Hierarchical Tree Layout ---
#                         hierarchical=True,
#                         layout={
#                             "hierarchical": {
#                                 "enabled": True,
#                                 "direction": "UD",       # Up-Down tree (Files at top)
#                                 "sortMethod": "directed", # Arrows point down
#                                 "levelSeparation": 150,   # Vertical space between layers
#                                 "nodeSpacing": 100,       # Horizontal space between siblings
#                             }
#                         },
                        
#                         # Soften the physics so nodes don't bounce aggressively
#                         physics={
#                             "hierarchicalRepulsion": {
#                                 "centralGravity": 0.0,
#                                 "springLength": 100,
#                                 "springConstant": 0.01,
#                                 "nodeDistance": 120,
#                             },
#                             "solver": "hierarchicalRepulsion"
#                         },
                        
#                         nodeHighlightBehavior=True,
#                         highlightColor="#F7A072",
#                         collapsible=True
#                     )
#                     # config = Config(
#                     #     width="100%",
#                     #     height=700,
#                     #     directed=True, 
#                     #     physics=True, 
#                     #     hierarchical=False,
#                     #     nodeHighlightBehavior=True,
#                     #     highlightColor="#F7A072",
#                     #     collapsible=True
#                     # )
                    
#                     # Render the graph
#                     selected_node = agraph(nodes=nodes, edges=edges, config=config)
                    
#                     if selected_node:
#                         st.info(f"**Selected Node:** `{selected_node}`")
#                 else:
#                     st.error("Could not load graph. Have you ingested the repository yet?")
#             except Exception as e:
#                 st.error(f"Failed to connect to API: {e}")

