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
    <script src="https://unpkg.com/3d-force-graph"></script>
    <style>
        html, body {
            margin: 0 !important; padding: 0 !important;
            width: 100vw !important; height: 100vh !important;
            overflow: hidden !important; 
        }
        
        div.vis-tooltip {
            position: fixed !important;
            transform: translate(15px, 15px); 
            max-width: 350px;
            white-space: normal !important;
            word-wrap: break-word !important;
            background-color: #2D3748 !important;
            color: #E2E8F0 !important;
            border: 1px solid #4A5568 !important;
            border-radius: 6px !important;
            padding: 10px !important;
            z-index: 99999 !important;
            pointer-events: none !important; 
        }
        
        .custom-cb { accent-color: #4E79A7 !important; width: 16px; height: 16px; cursor: pointer; vertical-align: middle; margin-right: 6px; }
        .control-panel label { color: #E2E8F0; font-family: sans-serif; font-size: 14px; display: flex; align-items: center; }
        
        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: #1a1a2e; border-radius: 10px; }
        ::-webkit-scrollbar-thumb { background: #3a3a5e; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #4E79A7; }
        * { scrollbar-width: thin; scrollbar-color: #3a3a5e #1a1a2e; box-sizing: border-box; margin: 0; padding: 0; }
        
        body { background: #0f0f1a; color: #e0e0e0; font-family: -apple-system, sans-serif; display: flex; height: 100vh; overflow: hidden; position: relative; }
        
        #canvas-container { flex: 1; position: relative; overflow: hidden; }
        #graph { position: absolute; top: 0; left: 0; width: 100%; height: 100%; }
        #graph-3d { position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: none; }
        
        #sidebar { width: 280px; background: #1a1a2e; border-left: 1px solid #2a2a4e; display: flex; flex-direction: column; overflow-y: auto; z-index: 10; }
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
        
        .md-content p { margin-bottom: 6px; }
        .md-content code { background: #2a2a4e; padding: 2px 4px; border-radius: 3px; font-family: monospace; font-size: 11px; color: #F6E05E; }
        .md-content pre { background: #0f0f1a; padding: 8px; border-radius: 4px; overflow-x: auto; margin-bottom: 6px; border: 1px solid #3a3a5e; }
        .md-content pre code { background: transparent; color: #e0e0e0; padding: 0; }
        .md-content ul, .md-content ol { padding-left: 20px; margin-bottom: 6px; }
        
        .neighbor-link { display: block; padding: 2px 6px; margin: 2px 0; border-radius: 3px; cursor: pointer; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; border-left: 3px solid #333; }
        .neighbor-link:hover { background: #2a2a4e; }
        #neighbors-list { max-height: 160px; overflow-y: auto; margin-top: 4px; }
        #legend-wrap { flex: none; padding: 12px; }
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

        #node-chat-section {
            display: none;
            flex-direction: column;
        }
        #node-chat-section.popped-out {
            position: absolute !important;
            top: 20px;
            left: 20px;
            width: 360px;
            height: 480px;
            max-height: 80vh;
            border: 1px solid #4E79A7;
            border-radius: 8px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.6);
            z-index: 999;
            background: #1a1a2e;
            display: flex !important;
            flex-direction: column;
            overflow: hidden;
        }
        #node-chat-section.popped-out #node-chat-content {
            flex: 1 !important;
            height: calc(100% - 38px) !important;
            display: flex !important;
            flex-direction: column;
            border-bottom: none;
            padding: 14px;
        }
        #node-chat-section.popped-out #node-chat-history {
            max-height: none !important;
            flex: 1 !important;
            overflow-y: auto;
        }
        .chat-header-container { display: flex; justify-content: space-between; align-items: center; }
        .popout-btn { background: transparent; border: none; color: #aaa; cursor: pointer; font-size: 14px; display: flex; align-items: center; padding: 2px; border-radius: 4px; font-weight: bold; }
        .popout-btn:hover { color: #4E79A7; background: #2a2a4e; }

        #sidebar-toggle-btn {
            position: absolute;
            top: 14px;
            right: 14px;
            background: #1a1a2e;
            border: 1px solid #3a3a5e;
            color: #e0e0e0;
            padding: 8px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 600;
            z-index: 100;
            transition: all 0.2s ease;
            user-select: none;
        }
        #sidebar-toggle-btn:hover {
            background: #252547;
            border-color: #4E79A7;
            color: #fff;
        }

        #sidebar > div {
            flex-shrink: 0 !important;
        }
        .sidebar-section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 14px;
            background: #1a1a2e;
            border-bottom: 1px solid #2a2a4e;
            cursor: pointer;
            user-select: none;
        }
        .sidebar-section-header h3 {
            font-size: 11.5px !important;
            color: #a0aec0 !important;
            margin: 0 !important;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-weight: 600;
        }
        .sidebar-section-header:hover {
            background: #252547;
        }
        .sidebar-section-header:hover h3 {
            color: #e2e8f0 !important;
        }
        .sidebar-section-content {
            border-bottom: 1px solid #2a2a4e;
        }
        .section-arrow {
            font-size: 9px;
            color: #718096;
            transition: transform 0.2s ease;
        }
        .section-collapsed .section-arrow {
            transform: rotate(-90deg);
        }
        .section-collapsed .sidebar-section-content {
            display: none !important;
        }
    </style>
    </head>
    <body>
    <div id="canvas-container">
        <div id="loading-overlay">
            <div class="spinner"></div>
            <div style="font-size: 14px; font-weight: bold; letter-spacing: 1px;">CALCULATING TOPOGRAPHY</div>
            <div style="font-size: 11px; color: #aaa; margin-top: 8px;">Applying physics parameters...</div>
        </div>
        <button id="sidebar-toggle-btn">Hide Panel ➔</button>
        <div id="graph"></div>
        <div id="graph-3d"></div>
    </div>
    
    <div id="sidebar">
        <div id="search-wrap">
            <input id="search" type="text" placeholder="Search nodes..." autocomplete="off">
            <div style="display: flex; flex-direction: column; gap: 10px; margin-top: 14px; padding-bottom: 4px;">
                <label style="color:#E2E8F0; font-size:13px; cursor:pointer; display:flex; align-items:center;">
                    <input type="checkbox" id="isolate-cb" class="custom-cb"> Isolate Focus (1-Hop)
                </label>
                <label style="color:#E2E8F0; font-size:13px; cursor:pointer; display:flex; align-items:center;">
                    <input type="checkbox" id="config-cb" class="custom-cb" checked> Show Infrastructure & Libs
                </label>
                <label style="color:#E2E8F0; font-size:13px; cursor:pointer; display:flex; align-items:center;">
                    <input type="checkbox" id="toggle-3d-cb" class="custom-cb"> 🌌 Enable 3D Hyperspace
                </label>
            </div>
            <div id="search-results"></div>
        </div>
        
        <!-- Section 2: Node Info -->
        <div id="info-section">
            <div class="sidebar-section-header" onclick="toggleSection('info-section', 'info-content')">
                <h3>Node Info</h3>
                <span class="section-arrow">▼</span>
            </div>
            <div id="info-content" class="sidebar-section-content" style="padding: 14px; min-height: 120px;">
                <div id="info-content-inner"><span class="empty">Click a node to inspect it</span></div>
            </div>
        </div>
        
        <!-- Section 3 Placeholder when popped out -->
        <div id="node-chat-placeholder" style="display: none; flex-direction: column;">
            <div class="sidebar-section-header" onclick="restorePopoutDefault()" style="cursor: pointer; display: flex; justify-content: space-between; align-items: center;">
                <h3>Ask this Node (Popped Out)</h3>
                <span style="font-size: 11px; color: #4E79A7; text-decoration: underline; font-weight: bold;">Recenter Card</span>
            </div>
        </div>
        
        <!-- Section 3: Ask this Node -->
        <div id="node-chat-section" style="display: none; flex-direction: column;">
            <div class="sidebar-section-header" onclick="toggleSection('node-chat-section', 'node-chat-content')">
                <h3>Ask this Node</h3>
                <div style="display: flex; align-items: center; gap: 8px;">
                    <button id="chat-popout-toggle" class="popout-btn" title="Toggle Pop-out Mode" onclick="event.stopPropagation();">⤢</button>
                    <span class="section-arrow">▼</span>
                </div>
            </div>
            <div id="node-chat-content" class="sidebar-section-content" style="padding: 14px; display: flex; flex-direction: column; gap: 8px; background: #1a1a2e; transition: all 0.2s ease;">
                <div id="node-chat-pending-warning" style="display: none; font-size: 11px; color: #BAB0AC; font-style: italic; margin-bottom: 4px;"></div>
                <div id="node-chat-history" style="max-height: 150px; overflow-y: auto; font-size: 12px; color: #ccc; display: flex; flex-direction: column; gap: 6px;"></div>
                <input id="node-chat-input" type="text" placeholder="e.g. What does this function do?" autocomplete="off" style="width: 100%; background: #0f0f1a; border: 1px solid #3a3a5e; color: #e0e0e0; padding: 7px 10px; border-radius: 6px; font-size: 12px; outline: none;">
            </div>
        </div>

        <!-- Section 4: Communities -->
        <div id="legend-section">
            <div class="sidebar-section-header" onclick="toggleSection('legend-section', 'legend-content')">
                <h3>Communities</h3>
                <span class="section-arrow">▼</span>
            </div>
            <div id="legend-content" class="sidebar-section-content" style="padding: 12px;">
                <div id="legend-controls">
                    <label><input type="checkbox" id="select-all-cb" checked onchange="toggleAllCommunities(!this.checked)">Select All</label>
                </div>
                <div id="legend"></div>
            </div>
        </div>
        <div id="stats-footer" style="padding: 12px; border-top: 1px solid #2a2a4e; font-size: 11.5px; color: #a0aec0; text-align: center; background: #141424; font-family: sans-serif; letter-spacing: 0.3px;">
            <span id="stats-text">0 nodes · 0 edges · 0 communities</span>
        </div>
    </div>
    <script>
    """

    safe_js_nodes = js_nodes.replace("</script>", r"<\/script>")
    safe_js_edges = js_edges.replace("</script>", r"<\/script>")
    safe_js_legend = js_legend.replace("</script>", r"<\/script>")

    js_data = f"""
    const API_BASE = {json.dumps(API_BASE)};
    const REPO_NAME = {json.dumps(repo_name)};
    const TARGET_PATH = {json.dumps(target_path)};
    const RAW_NODES = {safe_js_nodes};
    const RAW_EDGES = {safe_js_edges};
    const LEGEND = {safe_js_legend};
    """
    
    js_logic = """
    function esc(s) {
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
    }

    const nodeChatHistories = {};

    const nodesDS = new vis.DataSet(RAW_NODES.map(n => {
        let bg = '#4E79A7';
        let bd = '#4E79A7';
        if (n && n.color) {
            bg = n.color.background || n.color || bg;
            bd = n.color.border || bd;
        }
        
        let tooltipEl = null;
        if (n.title) {
            tooltipEl = document.createElement('div');
            tooltipEl.innerHTML = n.title;
        }
        
        return {
            id: n.id, label: n.label, size: n.size, font: n.font, title: tooltipEl || n.title, shape: n.shape,
            // group: n.group, 
            _community: n.community, _community_name: n.community_name, _file_type: n._file_type,
            _is_pending: n._is_pending,
            summary: n.summary || '',
            color: n._is_pending ? { background: bg, border: '#F28E2B' } : { background: bg, border: bd },
            borderWidth: n._is_pending ? 3 : 1.5,
            shapeProperties: { borderDashes: n._is_pending ? [4, 4] : false }
        };
    }));

    const edgesDS = new vis.DataSet(RAW_EDGES.map((e, i) => ({
        id: i,
        from: e.from,
        to: e.to,
        label: e.label,
        title: e.title,
        width: e.width || 0.4,
        color: e.color || '#4a5568',
        dashes: e.dashes || false,
        arrows: e.arrows || { to: { enabled: true, scaleFactor: 1 } }
    })));

    const container = document.getElementById('graph');
    const network = new vis.Network(container, { nodes: nodesDS, edges: edgesDS }, {
        autoResize: true,
        """ + js_physics_config + """
        interaction: { hover: true, tooltipDelay: 100, hideEdgesOnDrag: true },
        nodes: { borderWidth: 1.5 },
        edges: { smooth: { type: 'continuous', roundness: 0.2 }, selectionWidth: 3 },
    });

    function freezeAndShow() {
        if (network.physics) { network.physics.stopSimulation(); }
        network.setOptions({ physics: false }); 
        const overlay = document.getElementById('loading-overlay');
        if (overlay) {
            overlay.style.opacity = '0';
            setTimeout(() => overlay.style.display = 'none', 300);
        }
    }

    network.once('stabilizationIterationsDone', freezeAndShow);
    network.once('stabilized', freezeAndShow);
    setTimeout(freezeAndShow, 1500); 

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
                let sc = '#4E79A7';
                if (n.color) sc = n.color.background || n.color || sc;
                
                el.style.borderLeft = `3px solid ${sc}`; el.style.paddingLeft = '8px';
                el.onclick = () => { 
                    focusNode(n.id); 
                    searchResults.style.display = 'none'; 
                };
                searchResults.appendChild(el);
            });
        }, 250); 
    });

    document.addEventListener('click', e => {
        if (!searchResults.contains(e.target) && e.target !== searchInput) searchResults.style.display = 'none';
    });

    let currentSelectedNode = null;
    const hiddenCommunities = new Set();

    // --- SHARED DESELECT FUNCTION (WITH 2D RECENTERING) ---
    function deselectNode() {
        currentSelectedNode = null;
        network.unselectAll(); 
        const infoContent = document.getElementById('info-content');
        if (infoContent) {
            infoContent.innerHTML = '<div id="info-content-inner"><span class="empty">Click a node to inspect it</span></div>';
        }
        applyIsolation();
        document.getElementById('node-chat-section').style.display = 'none';
        const placeholder = document.getElementById('node-chat-placeholder');
        if (placeholder) placeholder.style.display = 'none';
        
        const toggle3D = document.getElementById('toggle-3d-cb');
        if (toggle3D.checked && Graph3D) {
            Graph3D.zoomToFit(1000, 50);
        } else {
            // Smoothly fly back to see the whole graph in 2D
            network.fit({ animation: { duration: 1000, easingFunction: 'easeInOutQuad' } });
        }
    }

    // --- BULLETPROOF 3D ENGINE ---
    let Graph3D = null;
    const container2D = document.getElementById('graph');
    const container3D = document.getElementById('graph-3d');
    const toggle3D = document.getElementById('toggle-3d-cb');

    function init3D() {
        if (!Graph3D) {
            const containerParent = container3D.parentElement;
            const w = containerParent ? containerParent.clientWidth : (document.body.clientWidth - 280);
            const h = containerParent ? containerParent.clientHeight : document.body.clientHeight;
            container3D.addEventListener('contextmenu', event => event.preventDefault());

            Graph3D = ForceGraph3D({
                controlType: 'orbit',
                rendererConfig: {
                    antialias: false,
                    powerPreference: "high-performance",
                    precision: "mediump"
                }
            })(container3D)
                .width(w)
                .height(h)
                .backgroundColor('#0f0f1a')
                .nodeResolution(6)
                .linkResolution(4)
                // ── RESTORED visuals ──────────────────────────────────
                .linkDirectionalParticles(1)
                .linkDirectionalParticleSpeed(0.006)
                .linkDirectionalParticleWidth(1.0)
                .linkCurvature(0.12)
                .linkWidth(0.6)
                // ─────────────────────────────────────────────────────
                .nodeLabel(node => {
                    const originalNode = RAW_NODES.find(n => String(n.id) === String(node.id));
                    return originalNode && originalNode.title ? `<div style="background:rgba(15,15,26,0.95);padding:10px;border:1px solid #3a3a5e;border-radius:6px;max-width:300px;font-family:sans-serif;box-shadow: 0 4px 12px rgba(0,0,0,0.5);">${originalNode.title}</div>` : `<div style="background:rgba(15,15,26,0.9);padding:6px 10px;border:1px solid #3a3a5e;border-radius:4px;color:#e0e0e0;font-size:12px;font-family:sans-serif;">${esc(node.name)}</div>`;
                })
                .nodeColor('color')
                .nodeVal('val')
                .linkColor(link => link.color || '#3a3a5e')
                // ── THE ACTUAL FIX ────────────────────────────────────
                // After simulation converges, stop the render loop entirely.
                // GPU usage drops to ~0. Resume on any interaction.
                .onEngineStop(() => {
                    Graph3D.pauseAnimation();

                    if (currentSelectedNode) {
                        const n3d = Graph3D.graphData().nodes.find(
                            node => String(node.id) === String(currentSelectedNode)
                        );
                        if (n3d && n3d.x !== undefined && !Number.isNaN(n3d.x)) {
                            const distance = 120;
                            const hypo = Math.hypot(n3d.x, n3d.y, n3d.z);
                            let camPos = { x: n3d.x, y: n3d.y, z: n3d.z + distance };
                            if (hypo > 0.1) {
                                const r = 1 + distance / hypo;
                                camPos = { x: n3d.x * r, y: n3d.y * r, z: n3d.z * r };
                            }
                            // resumeAnimation for the camera flight, then pause again
                            Graph3D.resumeAnimation();
                            Graph3D.cameraPosition(camPos, n3d, 1500);
                            setTimeout(() => Graph3D.pauseAnimation(), 8000);
                        }
                    } else {
                        Graph3D.resumeAnimation();
                        Graph3D.zoomToFit(1000, 50);
                        setTimeout(() => Graph3D.pauseAnimation(), 8000);
                    }
                })
                .onNodeClick(node => {
                    Graph3D.resumeAnimation();
                    focusNode(node.id);
                })
                .onBackgroundClick(() => {
                    Graph3D.resumeAnimation();
                    deselectNode();
                });

            // Resume on orbit controls (mouse drag/scroll on the 3D canvas)
            // 3d-force-graph exposes the underlying three.js renderer controls
            container3D.addEventListener('mousedown', () => {
                if (Graph3D) Graph3D.resumeAnimation();
            });
            container3D.addEventListener('wheel', () => {
                if (Graph3D) Graph3D.resumeAnimation();
            }, { passive: true });

            // Pause again after orbit interaction ends
            let orbitPauseTimer = null;
            container3D.addEventListener('mouseup', () => {
                clearTimeout(orbitPauseTimer);
                orbitPauseTimer = setTimeout(() => {
                    if (Graph3D) Graph3D.pauseAnimation();
                }, 4000); // 4 seconds after releasing mouse — enough for inertia to settle
            });

            const validNodeIds = new Set(RAW_NODES.map(n => String(n.id)));

            const nodes3D = RAW_NODES.map(n => {
                let c = '#4E79A7';
                if (n.color) {
                    if (typeof n.color === 'string') c = n.color;
                    else if (n.color.background) c = n.color.background;
                }
                return {
                    id: String(n.id),
                    name: n.label,
                    color: c,
                    val: Math.max(1, (n.size || 15) / 3)
                };
            });

            const links3D = RAW_EDGES
                .filter(e => validNodeIds.has(String(e.from)) && validNodeIds.has(String(e.to)))
                .map(e => ({
                    source: String(e.from),
                    target: String(e.to),
                    color: e.color
                }));

            Graph3D.graphData({ nodes: nodes3D, links: links3D });

            window.addEventListener('resize', () => {
                if (Graph3D && container3D && container3D.parentElement) {
                    const rw = container3D.parentElement.clientWidth;
                    const rh = container3D.parentElement.clientHeight;
                    Graph3D.width(rw).height(rh);
                }
            });
        }
    }

    function applyIsolation() {
        const isolate = document.getElementById('isolate-cb').checked;
        const showConfigs = document.getElementById('config-cb').checked;

        let visibleSet = null;
        if (isolate && currentSelectedNode) {
            const neighbors = network.getConnectedNodes(currentSelectedNode);
            visibleSet = new Set([currentSelectedNode, ...neighbors]);
        }

        const visibleNodeIds = new Set(); 

        const updates = RAW_NODES.map(n => {
            let isHidden = hiddenCommunities.has(n.community);
            const fileType = n._file_type || '';
            const isConfig = fileType === 'library' || fileType === 'infrastructure' || (fileType === 'file' && n.label.match(/\\.(json|yaml|yml|toml|txt)$/i));
            
            if (!showConfigs && isConfig) isHidden = true;
            if (visibleSet && !visibleSet.has(n.id)) isHidden = true;
            if (!isHidden) visibleNodeIds.add(String(n.id)); 
            
            return { id: n.id, hidden: isHidden };
        });

        nodesDS.update(updates);

        if (toggle3D.checked) {
            init3D();
            Graph3D.nodeVisibility(node => visibleNodeIds.has(String(node.id)));
            Graph3D.linkVisibility(link => {
                const s = typeof link.source === 'object' ? link.source.id : link.source;
                const t = typeof link.target === 'object' ? link.target.id : link.target;
                return visibleNodeIds.has(String(s)) && visibleNodeIds.has(String(t));
            });
        }
    }

    document.getElementById('isolate-cb').addEventListener('change', () => {
        applyIsolation();
        // Trigger camera flight if a node is currently selected when flipping the toggle
        if(currentSelectedNode) focusNode(currentSelectedNode);
    });
    
    document.getElementById('config-cb').addEventListener('change', applyIsolation);
    
    toggle3D.addEventListener('change', (e) => {
        if (e.target.checked) {
            container2D.style.display = 'none';
            container3D.style.display = 'block';
            applyIsolation();
            
            // --- FIX: 2D to 3D Handoff ---
            setTimeout(() => { 
                if (Graph3D) {
                    if (currentSelectedNode) {
                        // If a node is selected, fly directly to it in 3D!
                        focusNode(currentSelectedNode); 
                    } else {
                        // Otherwise, frame the whole graph
                        Graph3D.zoomToFit(1000, 50); 
                    }
                } 
            }, 100);
            
        } else {
            container3D.style.display = 'none';
            container2D.style.display = 'block';
            applyIsolation(); 
            
            // --- FIX: 3D to 2D Handoff ---
            setTimeout(() => {
                if (currentSelectedNode) {
                    // If a node is selected, frame it perfectly in 2D!
                    focusNode(currentSelectedNode);
                } else {
                    // Otherwise, smoothly zoom out to the whole graph
                    network.fit({ animation: { duration: 1000, easingFunction: 'easeInOutQuad' } });
                }
            }, 50);
        }
    });

    const sidebar = document.getElementById('sidebar');
    const toggleBtn = document.getElementById('sidebar-toggle-btn');
    
    toggleBtn.addEventListener('click', () => {
        const isHidden = sidebar.style.display === 'none';
        if (isHidden) {
            sidebar.style.display = 'flex';
            toggleBtn.innerHTML = 'Hide Panel ➔';
        } else {
            sidebar.style.display = 'none';
            toggleBtn.innerHTML = '⬅ Show Panel';
        }
        
        // Handle 3D resize
        if (Graph3D && container3D && container3D.parentElement) {
            const w = container3D.parentElement.clientWidth;
            const h = container3D.parentElement.clientHeight;
            Graph3D.width(w).height(h);
        }
        // Handle 2D resize/fit
        setTimeout(() => {
            network.setSize('100%', '100%');
            network.redraw();
        }, 50);
    });

    applyIsolation(); 

    function showInfo(nodeId) {
        const n = nodesDS.get(nodeId);
        if (!n) return;
        const neighborIds = network.getConnectedNodes(nodeId);
        const neighborItems = neighborIds.map(nid => {
            const nb = nodesDS.get(nid);
            let sc = '#555';
            if (nb) {
                if (nb._is_pending) sc = '#F28E2B';
                else if (nb.color && nb.color.background) sc = nb.color.background;
                else if (typeof nb.color === 'string') sc = nb.color;
            }
            return `<span class="neighbor-link" style="border-left-color:${esc(sc)}" onclick="focusNode(${JSON.stringify(nid)})">${esc(nb ? nb.label : nid)}</span>`;
        }).join('');
        
        const pendingWarning = n._is_pending 
        ? `<div style="background: rgba(242, 142, 43, 0.1); border: 1px solid #F28E2B; color: #F28E2B; padding: 6px; border-radius: 4px; margin-bottom: 8px; font-weight: bold; font-size: 11px;">⚠️ Pending LLM Summarization</div>` 
        : '';

        const summaryHtml = n._is_pending
            ? ''
            : `<div class="field" style="margin-top: 10px;"><b>Summary:</b><br><span style="font-size:12px;color:#cbd5e0;line-height:1.4;display:block;margin-top:4px;white-space:pre-wrap;">${esc(n.summary || 'No summary available.')}</span></div>`;

        document.getElementById('info-content').innerHTML = `
        ${pendingWarning}
        <div class="field"><b>${esc(n.label)}</b></div>
        <div class="field">Type: ${esc(n._file_type || 'unknown')}</div>
        <div class="field">Community: ${esc(n._community_name)}</div>
        ${summaryHtml}
        ${neighborIds.length ? `<div class="field" style="margin-top:8px;color:#aaa;font-size:11px">Neighbors (${neighborIds.length})<br><span style="font-size: 10px; color: #666; font-style: italic;">*In 3D mode, Right-Click + Drag to Pan*</span></div><div id="neighbors-list">${neighborItems}</div>` : ''}
        `;
    }

    const chatSection = document.getElementById('node-chat-section');
    const chatWrap = document.getElementById('node-chat-content');
    const chatHistory = document.getElementById('node-chat-history');
    const chatInput = document.getElementById('node-chat-input');
    const popoutToggle = document.getElementById('chat-popout-toggle');

    function toggleSection(sectionId, contentId) {
        const section = document.getElementById(sectionId);
        const content = document.getElementById(contentId);
        if (!section || !content) return;
        
        const isCollapsed = section.classList.toggle('section-collapsed');
        if (isCollapsed) {
            content.style.setProperty('display', 'none', 'important');
        } else {
            if (contentId === 'node-chat-content') {
                content.style.display = 'flex';
            } else {
                content.style.display = 'block';
            }
        }
    }

    function focusNode(nodeId) {
        const originalNode = RAW_NODES.find(n => String(n.id) === String(nodeId));
        if (originalNode) nodeId = originalNode.id;

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
        
        chatSection.style.display = 'flex';
        // Auto-expand section if collapsed
        chatSection.classList.remove('section-collapsed');
        chatWrap.style.display = 'flex';
        const placeholder = document.getElementById('node-chat-placeholder');
        if (placeholder) {
            placeholder.style.display = chatSection.classList.contains('popped-out') ? 'flex' : 'none';
        }
        
        if (!nodeChatHistories[nodeId]) {
            const wrapper = document.createElement('div');
            wrapper.style.display = 'flex';
            wrapper.style.flexDirection = 'column';
            wrapper.style.gap = '6px';
            wrapper.innerHTML = `<div style="color: #A0AEC0; font-style: italic;">Connected to <b>${esc(nodeId)}</b>. Ask a question!</div>`;
            nodeChatHistories[nodeId] = wrapper;
        }
        chatHistory.innerHTML = '';
        chatHistory.appendChild(nodeChatHistories[nodeId]);
        chatHistory.scrollTop = chatHistory.scrollHeight;

        // --- THE CINEMATIC CAMERA SYSTEM ---
        const isolate = document.getElementById('isolate-cb').checked;
        
        if (toggle3D.checked && Graph3D) {
            // 3D Camera Flight
            const n3d = Graph3D.graphData().nodes.find(node => String(node.id) === String(nodeId));
            if (n3d && n3d.x !== undefined && !Number.isNaN(n3d.x)) {
                const distance = 120;
                const hypo = Math.hypot(n3d.x, n3d.y, n3d.z);
                let camPos = { x: n3d.x, y: n3d.y, z: n3d.z + distance }; 
                if (hypo > 0.1) {
                    const distRatio = 1 + distance/hypo;
                    camPos = { x: n3d.x * distRatio, y: n3d.y * distRatio, z: n3d.z * distRatio };
                }
                Graph3D.cameraPosition(camPos, n3d, 1500);
            }
        } else {
            // 2D Camera Flight
            if (isolate) {
                // Smoothly zoom to perfectly fit the node and its neighbors
                const neighbors = network.getConnectedNodes(nodeId);
                network.fit({
                    nodes: [nodeId, ...neighbors],
                    animation: { duration: 1000, easingFunction: "easeInOutQuad" }
                });
            } else {
                // Smoothly focus tightly on just the selected node
                network.focus(nodeId, {
                    scale: 1.2,
                    animation: { duration: 1000, easingFunction: "easeInOutQuad" }
                });
            }
        }
    }

    network.on('hoverNode', params => { container2D.style.cursor = 'pointer'; });
    network.on('blurNode', () => { container2D.style.cursor = 'default'; });
    
    // Using select instead of selectNode to ensure we catch background clicks properly
    network.on('select', params => {
        if (params.nodes.length > 0) {
            focusNode(params.nodes[0]);
        } else {
            deselectNode();
        }
    });

    let isDragging = false;
    let dragStartX = 0;
    let dragStartY = 0;
    let initialLeft = 0;
    let initialTop = 0;

    const chatHeader = document.querySelector('#node-chat-section .sidebar-section-header');
    if (chatHeader) {
        chatHeader.style.cursor = 'move';
        chatHeader.addEventListener('mousedown', onMouseDown);
    }

    const onMouseMove = (e) => {
        if (!isDragging) return;
        const dx = e.clientX - dragStartX;
        const dy = e.clientY - dragStartY;
        chatSection.style.left = (initialLeft + dx) + 'px';
        chatSection.style.top = (initialTop + dy) + 'px';
    };

    const onMouseUp = () => {
        isDragging = false;
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
    };

    function onMouseDown(e) {
        if (!chatSection.classList.contains('popped-out')) return;
        if (e.target.closest('button') || e.target.closest('input')) return;
        
        isDragging = true;
        dragStartX = e.clientX;
        dragStartY = e.clientY;
        
        const rect = chatSection.getBoundingClientRect();
        initialLeft = rect.left;
        initialTop = rect.top;
        
        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
        e.preventDefault();
    }

    window.restorePopoutDefault = function() {
        if (chatSection) {
            chatSection.style.left = '20px';
            chatSection.style.top = '20px';
            chatSection.style.display = 'flex';
        }
    };

    if (popoutToggle) {
        popoutToggle.addEventListener('click', () => {
            const isPoppedOut = chatSection.classList.toggle('popped-out');
            const placeholder = document.getElementById('node-chat-placeholder');
            if (isPoppedOut) {
                document.body.appendChild(chatSection);
                if (placeholder) placeholder.style.display = 'flex';
                popoutToggle.innerText = '✖'; 
                popoutToggle.title = 'Minimize to Sidebar';
            } else {
                const legendSection = document.getElementById('legend-section');
                document.getElementById('sidebar').insertBefore(chatSection, legendSection);
                if (placeholder) placeholder.style.display = 'none';
                popoutToggle.innerText = '⤢';
                popoutToggle.title = 'Toggle Pop-out Mode';
                chatSection.style.left = '';
                chatSection.style.top = '';
            }
        });
    }

    chatInput.addEventListener('keypress', async function(e) {
        if (e.key === 'Enter' && chatInput.value.trim() !== '') {
            const question = chatInput.value.trim();
            chatInput.value = '';
            const activeNode = currentSelectedNode;
            const activeWrapper = nodeChatHistories[activeNode];
            
            activeWrapper.insertAdjacentHTML('beforeend', `<div style="color: #F6E05E; margin-bottom: 6px;"><b>You:</b> ${esc(question)}</div>`);
            const msgId = 'ai-msg-' + Date.now();
            activeWrapper.insertAdjacentHTML('beforeend', `<div style="color: #e0e0e0; margin-bottom: 12px;"><b>AI:</b> <span id="${msgId}" style="color: #aaa; font-style: italic;">Thinking...</span></div>`);
            
            if (currentSelectedNode === activeNode) chatHistory.scrollTop = chatHistory.scrollHeight;
            
            const aiContainer = activeWrapper.querySelector('#' + msgId);
            let fullMarkdown = "";
            let isFirstChunk = true;

            try {
                const response = await fetch(`${API_BASE}/query/node/${REPO_NAME}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ node_id: activeNode, question: question, target_path: TARGET_PATH })
                });
                
                if (!response.ok) { aiContainer.innerHTML = `<span style="color: #E15759;">Error: ${response.statusText}</span>`; return; }

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
                    fullMarkdown += decoder.decode(value, { stream: true });
                    aiContainer.innerHTML = marked.parse(fullMarkdown);
                    if (currentSelectedNode === activeNode) chatHistory.scrollTop = chatHistory.scrollHeight;
                }
            } catch (error) { aiContainer.innerHTML = `<span style="color: #E15759;">Connection lost.</span>`; }
        }
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
    
    document.getElementById('stats-text').textContent = `${RAW_NODES.length} nodes · ${RAW_EDGES.length} edges · ${LEGEND.length} communities`;
    """

    html_foot = """
    </script>
    </body>
    </html>
    """
    return html_head + js_data + js_logic + html_foot