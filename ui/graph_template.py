import json
import streamlit as st


def get_graph_html(api_base, repo_name, target_path, js_nodes, js_edges, js_legend, js_physics_config):
    API_BASE = api_base
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
        
        #loading-overlay { position: absolute; top: 0; left: 0; right: 280px; bottom: 0; background: #0f0f1a; z-index: 100; display: flex; flex-direction: column; justify-content: center; align-items: center; color: #4E79A7; font-family: sans-serif; transition: opacity 0.3s; }
        .spinner { width: 40px; height: 40px; border: 4px solid #1a1a2e; border-top: 4px solid #4E79A7; border-radius: 50%; animation: spin 1s linear infinite; margin-bottom: 16px; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        
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
    <div id="loading-overlay">
        <div class="spinner"></div>
        <div style="font-size: 14px; font-weight: bold; letter-spacing: 1px;">CALCULATING TOPOGRAPHY</div>
        <div style="font-size: 11px; color: #aaa; margin-top: 8px;">Applying physics parameters...</div>
    </div>
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
        
        <div id="node-chat-pending-warning" style="display: none; font-size: 11px; color: #BAB0AC; font-style: italic; margin-bottom: 4px;"></div>
        
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

    # js_data = f"""
    # const API_BASE = "{API_BASE}";
    # const REPO_NAME = "{st.session_state.active_repo}";
    # const TARGET_PATH = "{st.session_state.target_path}";
    # const RAW_NODES = {js_nodes};
    # const RAW_EDGES = {js_edges};
    # const LEGEND = {js_legend};
    # """
    # --- FIX 1: Safely inject variables using json.dumps to prevent JS crashes ---
    js_data = f"""
    const API_BASE = {json.dumps(API_BASE)};
    const REPO_NAME = {json.dumps(st.session_state.active_repo)};
    const TARGET_PATH = {json.dumps(st.session_state.target_path)};
    const RAW_NODES = {js_nodes};
    const RAW_EDGES = {js_edges};
    const LEGEND = {js_legend};
    """

    # --- FIX 2: Deduplicated and pristine logic ---
    js_logic = """
    function esc(s) {
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
    }

    const nodesDS = new vis.DataSet(RAW_NODES.map(n => ({
        id: n.id, label: n.label, size: n.size, font: n.font, title: n.title, shape: n.shape,
        _community: n.community, _community_name: n.community_name, _file_type: n._file_type,
        _is_pending: n._is_pending,
        color: n._is_pending ? { background: n.color.background, border: '#F28E2B' } : n.color,
        borderWidth: n._is_pending ? 3 : 1.5,
        shapeProperties: { borderDashes: n._is_pending ? [4, 4] : false }
    })));

    const edgesDS = new vis.DataSet(RAW_EDGES.map((e, i) => ({
        id: i, from: e.from, to: e.to, label: e.label,
        width: e.width, color: e.color,
        arrows: { to: { enabled: true, scaleFactor: 1 } },
    })));

    const container = document.getElementById('graph');
    const network = new vis.Network(container, { nodes: nodesDS, edges: edgesDS }, {
        """ + js_physics_config + """
        interaction: { hover: true, tooltipDelay: 100, hideEdgesOnDrag: true },
        nodes: { borderWidth: 1.5 },
        edges: { smooth: { type: 'continuous', roundness: 0.2 }, selectionWidth: 3 },
    });

    // --- THE LOADING SCREEN FIX ---
    function freezeAndShow() {
        if (network.physics) {
            network.physics.stopSimulation(); // 1. Halt the calculation loop immediately
        }
        network.setOptions({ physics: false });   // 2. Erase the physics configuration permanently
        
        const overlay = document.getElementById('loading-overlay');
        if (overlay) {
            overlay.style.opacity = '0';
            setTimeout(() => overlay.style.display = 'none', 300);
        }
    }

    // 3. Catch ALL possible stabilization events to guarantee shutdown
    network.once('stabilizationIterationsDone', freezeAndShow);
    network.once('stabilized', freezeAndShow);
    setTimeout(freezeAndShow, 1500); // Failsafe guarantees loader dies after 1.5s

    // --- SEARCH DEBOUNCER ---
    let searchTimeout = null;
    const searchInput = document.getElementById('search');
    const searchResults = document.getElementById('search-results');

    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
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
        }, 250); 
    });

    document.addEventListener('click', e => {
        if (!searchResults.contains(e.target) && e.target !== searchInput) searchResults.style.display = 'none';
    });

    // --- ISOLATION & CAMERA ---
    let currentSelectedNode = null;
    const hiddenCommunities = new Set();

    function applyIsolation() {
        const isolate = document.getElementById('isolate-cb').checked;
        if (isolate && currentSelectedNode) {
        const neighbors = network.getConnectedNodes(currentSelectedNode);
        const visibleNodes = [currentSelectedNode, ...neighbors];
        const visibleSet = new Set(visibleNodes);
        
        const updates = RAW_NODES.map(n => ({
            id: n.id, hidden: hiddenCommunities.has(n.community) || !visibleSet.has(n.id)
        }));
        nodesDS.update(updates);
        setTimeout(() => { network.fit({ nodes: visibleNodes, animation: true, padding: 50 }); }, 50);
        } else {
        const updates = RAW_NODES.map(n => ({
            id: n.id, hidden: hiddenCommunities.has(n.community)
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

    // --- NODE SELECTION & UI ---
    function showInfo(nodeId) {
        const n = nodesDS.get(nodeId);
        if (!n) return;
        const neighborIds = network.getConnectedNodes(nodeId);
        const neighborItems = neighborIds.map(nid => {
        const nb = nodesDS.get(nid);
        const color = nb ? (nb._is_pending ? '#F28E2B' : nb.color.background) : '#555';
        return `<span class="neighbor-link" style="border-left-color:${esc(color)}" onclick="focusNode(${JSON.stringify(nid)})">${esc(nb ? nb.label : nid)}</span>`;
        }).join('');
        
        const pendingWarning = n._is_pending 
        ? `<div style="background: rgba(242, 142, 43, 0.1); border: 1px solid #F28E2B; color: #F28E2B; padding: 6px; border-radius: 4px; margin-bottom: 8px; font-weight: bold; font-size: 11px;">⚠️ Pending LLM Summarization</div>` 
        : '';

        document.getElementById('info-content').innerHTML = `
        ${pendingWarning}
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
        applyIsolation(); 
        
        const n = nodesDS.get(nodeId);
        const warningElement = document.getElementById('node-chat-pending-warning');
        
        if (n && n._is_pending) {
        warningElement.style.display = 'block';
        warningElement.innerHTML = "⏳ LLM summarization pending for this component...";
        } else {
        warningElement.style.display = 'none';
        }
        
        chatWrap.style.display = 'flex';
        chatHistory.innerHTML = '';
    }

    network.on('hoverNode', params => { container.style.cursor = 'pointer'; });
    network.on('blurNode', () => { container.style.cursor = 'default'; });

    network.on('selectNode', params => {
        currentSelectedNode = params.nodes[0];
        showInfo(currentSelectedNode);
        applyIsolation();
        
        const n = nodesDS.get(currentSelectedNode);
        const warningElement = document.getElementById('node-chat-pending-warning');
        
        if (n && n._is_pending) {
        warningElement.style.display = 'block';
        warningElement.innerHTML = "⏳ LLM summarization pending for this component...";
        } else {
        warningElement.style.display = 'none';
        }
        
        chatWrap.style.display = 'flex';
        chatHistory.innerHTML = '';
    });

    network.on('deselectNode', () => {
        currentSelectedNode = null;
        document.getElementById('info-content').innerHTML = '<span class="empty">Click a node to inspect it</span>';
        applyIsolation();
        chatWrap.style.display = 'none';
    });

    // --- CHAT STREAMING ---
    const chatWrap = document.getElementById('node-chat-wrap');
    const chatHistory = document.getElementById('node-chat-history');
    const chatInput = document.getElementById('node-chat-input');

    chatInput.addEventListener('keypress', async function(e) {
        if (e.key === 'Enter' && chatInput.value.trim() !== '') {
            const question = chatInput.value.trim();
            chatInput.value = '';
            
            chatHistory.innerHTML += `<div style="color: #F6E05E; margin-bottom: 6px;"><b>You:</b> ${esc(question)}</div>`;
            chatHistory.scrollTop = chatHistory.scrollHeight;
            
            const msgId = 'ai-msg-' + Date.now();
            chatHistory.innerHTML += `<div style="color: #e0e0e0; margin-bottom: 12px;"><b>AI:</b> <span id="${msgId}" style="color: #aaa; font-style: italic;">Thinking...</span></div>`;
            chatHistory.scrollTop = chatHistory.scrollHeight;
            
            const aiContainer = document.getElementById(msgId);
            let fullMarkdown = "";
            let isFirstChunk = true;

            try {
                const response = await fetch(`${API_BASE}/query/node/${REPO_NAME}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ node_id: currentSelectedNode, question: question, target_path: TARGET_PATH })
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
                    
                    if (isFirstChunk) {
                        aiContainer.innerHTML = ""; 
                        aiContainer.style.fontStyle = "normal";
                        aiContainer.classList.add("md-content");
                        isFirstChunk = false;
                    }
                    
                    const chunkText = decoder.decode(value, { stream: true });
                    fullMarkdown += chunkText;
                    
                    aiContainer.innerHTML = marked.parse(fullMarkdown);
                    chatHistory.scrollTop = chatHistory.scrollHeight;
                }
            } catch (error) {
                aiContainer.innerHTML = `<span style="color: #E15759;">Connection lost.</span>`;
            }
        }
    });

    // --- LEGEND LOGIC ---
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
    return html_head + js_data + js_logic + html_foot