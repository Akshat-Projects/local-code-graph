import networkx as nx
from pathlib import Path
import json
# import threading

# 1. Import Tree-sitter and Language Bindings
import tree_sitter
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjavascript
import tree_sitter_java as tsjava
import tree_sitter_rust as tsrust
import tree_sitter_html as tshtml
import tree_sitter_css as tscss
import tree_sitter_go as tsgo
import tree_sitter_php as tsphp
import tree_sitter_c as tsc
import tree_sitter_cpp as tscpp
import tree_sitter_c_sharp as tscsharp
import tree_sitter_typescript as tstypescript
import tree_sitter_ruby as tsruby
import tree_sitter_swift as tsswift
import tree_sitter_kotlin as tskotlin
# import tree_sitter_r as tsr

from core.config_extractor import ConfigExtractor
from utils.logger import get_logger


logger = get_logger()


# --- Version-Safe Tree-sitter Loader ---
def get_ts_language(module, language_name=None):
    """Safely loads grammars whether you are on tree-sitter v0.21 or v0.22+"""
    if hasattr(module, "LANGUAGE"):
        return module.LANGUAGE
    # Some modules (like typescript) expose multiple languages (typescript vs tsx)
    if language_name and hasattr(module, f"language_{language_name}"):
        func = getattr(module, f"language_{language_name}")
        return tree_sitter.Language(func())
    return tree_sitter.Language(module.language())

# 2. Map Extensions to their Grammars
LANGUAGE_CONFIG = {
    ".py": {"lang": get_ts_language(tspython), "type": "python"},
    ".ipynb": {"lang": get_ts_language(tspython), "type": "python"},
    ".js": {"lang": get_ts_language(tsjavascript), "type": "javascript"},
    ".jsx": {"lang": get_ts_language(tsjavascript), "type": "javascript"},
    ".java": {"lang": get_ts_language(tsjava), "type": "java"},
    ".rs": {"lang": get_ts_language(tsrust), "type": "rust"},
    ".html": {"lang": get_ts_language(tshtml), "type": "html"},
    ".css": {"lang": get_ts_language(tscss), "type": "css"},
    
    ".go": {"lang": get_ts_language(tsgo), "type": "go"},
    ".php": {"lang": get_ts_language(tsphp, "php"), "type": "php"},
    ".c": {"lang": get_ts_language(tsc), "type": "c"},
    ".h": {"lang": get_ts_language(tsc), "type": "c"},
    ".cpp": {"lang": get_ts_language(tscpp), "type": "cpp"},
    ".hpp": {"lang": get_ts_language(tscpp), "type": "cpp"},
    ".cs": {"lang": get_ts_language(tscsharp), "type": "c_sharp"},
    ".rb": {"lang": get_ts_language(tsruby), "type": "ruby"},
    ".swift": {"lang": get_ts_language(tsswift), "type": "swift"},
    ".kt": {"lang": get_ts_language(tskotlin), "type": "kotlin"},
    # ".r": {"lang": get_ts_language(tsr), "type": "r"},
    
    # TypeScript handles .ts and .tsx differently
    ".ts": {"lang": get_ts_language(tstypescript, "typescript"), "type": "typescript"},
    ".tsx": {"lang": get_ts_language(tstypescript, "tsx"), "type": "tsx"},

    # Database & Configs (No structural extraction, just treated as file nodes)
    ".sql": {"lang": None, "type": "sql"},
    ".toml": {"type": "config"},
    ".txt": {"type": "config"},
    ".json": {"type": "config"},
    ".yaml": {"type": "config"},
    ".yml": {"type": "config"}
}

# 3. Define S-Expression Queries per Language
CALL_QUERIES = {
    # High confidence — stable, widely tested grammars
    "python": "(call function: (attribute attribute: (identifier) @call_name))",
    "javascript": "(call_expression function: (member_expression property: (property_identifier) @call_name))",
    "typescript": "(call_expression function: (member_expression property: (property_identifier) @call_name))",
    "tsx": "(call_expression function: (member_expression property: (property_identifier) @call_name))",
    "java": "(method_invocation name: (identifier) @call_name)",
    "go": "(call_expression function: (selector_expression field: (field_identifier) @call_name))",
    "c_sharp": "(invocation_expression function: (member_access_expression name: (identifier) @call_name))",

    # Medium confidence — validate with a test file before production use
    "rust": "(call_expression function: (field_expression field: (field_identifier) @call_name))",
    "cpp": "(call_expression function: (field_expression field: (field_identifier) @call_name))",
    "php": "(member_call_expression name: (name) @call_name)",
    "ruby": "(call method: (identifier) @call_name)",
    "swift": "(call_expression function: (explicit_member_expression name: (simple_identifier) @call_name))",
    "kotlin": "(call_expression callee: (navigation_expression (simple_identifier) @call_name))",

    # C has no method calls — capture plain function calls instead
    "c": "(call_expression function: (identifier) @call_name)",

    # No meaningful call semantics to capture
    "html": "",
    "css":  "",
    "sql":  "",
}
QUERIES = {
    "python": "(class_definition name: (identifier) @class) (function_definition name: (identifier) @function)",
    "javascript": "(class_declaration name: (identifier) @class) (function_declaration name: (identifier) @function) (lexical_declaration (variable_declarator name: (identifier) @function value: (arrow_function))) (method_definition name: (property_identifier) @function)",
    "typescript": "(class_declaration name: (type_identifier) @class) (interface_declaration name: (type_identifier) @class) (function_declaration name: (identifier) @function) (method_definition name: (property_identifier) @function)",
    "tsx": "(class_declaration name: (type_identifier) @class) (function_declaration name: (identifier) @function) (lexical_declaration (variable_declarator name: (identifier) @function value: (arrow_function)))",
    "java": "(class_declaration name: (identifier) @class) (method_declaration name: (identifier) @function)",
    "rust": "(struct_item name: (type_identifier) @class) (impl_item type: (type_identifier) @class) (function_item name: (identifier) @function)",
    "go": "(type_spec name: (type_identifier) @class) (function_declaration name: (identifier) @function) (method_declaration name: (field_identifier) @function)",
    "php": "(class_declaration name: (name) @class) (method_declaration name: (name) @function) (function_declaration name: (name) @function)",
    "c": "(struct_specifier name: (type_identifier) @class) (function_definition declarator: (function_declarator declarator: (identifier) @function))",
    "cpp": "(class_specifier name: (type_identifier) @class) (struct_specifier name: (type_identifier) @class) (function_definition declarator: (function_declarator declarator: (identifier) @function))",
    "c_sharp": "(class_declaration name: (identifier) @class) (method_declaration name: (identifier) @function)",
    "ruby": "(class name: (constant) @class) (method name: (identifier) @function)",
    "swift": "(class_declaration name: (type_identifier) @class) (struct_declaration name: (type_identifier) @class) (function_declaration name: (identifier) @function)",
    "kotlin": "(class_declaration (simple_identifier) @class) (function_declaration (simple_identifier) @function)",
    # "r": "(function_definition) @function",
    "css": "(class_selector (class_name) @class) (id_selector (id_name) @function)",
    "html": "", "sql": "", "json": "", "yaml": ""
}

class UniversalParser:
    def __init__(self, graph: nx.MultiDiGraph):
        self.graph = graph
        self.parsers = {}
        self.config_extractor = ConfigExtractor(self.graph)
        # self._graph_lock = threading.Lock()
        
        # Pre-load parsers for efficiency
        for ext, config in LANGUAGE_CONFIG.items():
            # --- Skip building Tree-sitter parsers for config files ---
            if "lang" not in config:
                continue
                
            parser = tree_sitter.Parser()
            parser.language = config["lang"]
            self.parsers[ext] = parser

    def clear_file_nodes(self, relative_path: str):
        nodes_to_remove = [
            node_id for node_id, data in self.graph.nodes(data=True)
            if data.get("file_path") == relative_path
        ]
        for node_id in nodes_to_remove:
            self.graph.remove_node(node_id)

    def parse_file(self, absolute_path: str, relative_path: str, file_hash: str):
        ext = Path(absolute_path).suffix
        file_ext = Path(absolute_path).suffix.lower()
        filename = Path(absolute_path).name.lower()

        # --- Early exits: register file node HERE since clear_file_nodes is never called ---
        target_configs = [
            "package.json", "requirements.txt",
            "docker-compose.yml", "docker-compose.yaml", "pyproject.toml"
        ]
        if filename in target_configs:
            file_node_id = self._register_file_node(relative_path, file_hash)
            self.config_extractor.extract(absolute_path, relative_path, file_node_id)
            return

        if ext not in LANGUAGE_CONFIG:
            self._register_file_node(relative_path, file_hash)
            return

        lang_type = LANGUAGE_CONFIG[ext]["type"]
        parser = self.parsers[ext]

        try:
            with open(absolute_path, "r", encoding="utf-8") as f:
                source_code = f.read()

            if ext == ".ipynb":
                notebook = json.loads(source_code)
                virtual_code = []
                for cell in notebook.get("cells", []):
                    if cell.get("cell_type") == "code":
                        cell_source = cell.get("source", [])
                        if isinstance(cell_source, list):
                            virtual_code.append("".join(cell_source))
                        else:
                            virtual_code.append(cell_source)
                source_bytes = "\n\n".join(virtual_code).encode("utf8")
            else:
                source_bytes = source_code.encode("utf8")

            tree = parser.parse(source_bytes)
        except Exception as e:
            logger.error(f"Failed to parse AST for {relative_path}: {e}")
            return

        # FIX: clear OLD nodes first, THEN register the fresh file node.
        # Old order was reversed: _register_file_node ran first, then
        # clear_file_nodes deleted it (file node has file_path=relative_path),
        # then add_edge in _register_class/_register_function silently
        # re-created it with zero attributes — invisible to build_module_batches.
        self.clear_file_nodes(relative_path)
        file_node_id = self._register_file_node(relative_path, file_hash)  # ← MOVED HERE

        if lang_type == "html":
            return

        language_obj = LANGUAGE_CONFIG[ext]["lang"]
        query = language_obj.query(QUERIES[lang_type])
        
        # --- Version-Safe Capture Extraction (Tree-sitter 0.22+ compatibility) ---
        captures = []
        if hasattr(query, "captures"):
            # Older API (< 0.22): returns a list of tuples [(Node, capture_name), ...]
            raw = query.captures(tree.root_node)
            for item in raw:
                captures.append((item[0], item[1]))
        else:
            # Newer API (>= 0.22): uses QueryCursor
            from tree_sitter import QueryCursor
            cursor = QueryCursor(query)
            raw = cursor.captures(tree.root_node)
            
            # Depending on the exact minor version (0.22 vs 0.24), 
            # `raw` might be a Dictionary OR a List. We handle both!
            if isinstance(raw, dict):
                # Format: {"capture_name": [Node1, Node2, ...]}
                for name, nodes in raw.items():
                    for node in nodes:
                        captures.append((node, name))
            elif isinstance(raw, list):
                # Format: [(Node, "capture_name"), ...]
                for item in raw:
                    # Safety check in case the tuple order is flipped
                    if hasattr(item[0], "start_byte"):
                        captures.append((item[0], item[1]))
                    else:
                        captures.append((item[1], item[0]))
                        
        # Sort captures by their appearance in the file (top-to-bottom)
        # This guarantees we register a Class BEFORE we process its nested Methods!
        captures.sort(key=lambda x: x[0].start_byte)

        # Extract matches
        classes = {}
        
        registered_ranges = {}  # node_id -> (start_byte, end_byte) of full body

        for node, capture_name in captures:
            node_name = source_bytes[node.start_byte:node.end_byte].decode('utf8')
            body_node = node.parent  # full definition node, not just the name
            start_line = body_node.start_point[0] + 1  # FIXED
            end_line   = body_node.end_point[0] + 1    # FIXED

            if capture_name == "class":
                class_id = f"{relative_path}::{node_name}"
                self._register_class(class_id, node_name, relative_path, file_node_id, start_line, end_line)
                classes[node_name] = {"id": class_id, "ts_node": body_node}
                registered_ranges[class_id] = (body_node.start_byte, body_node.end_byte)

            elif capture_name == "function":
                parent_class_id = None
                for cls_name, cls_data in classes.items():
                    if self._is_descendant(node, cls_data["ts_node"]):
                        parent_class_id = cls_data["id"]
                        break
                func_id = f"{parent_class_id}::{node_name}" if parent_class_id else f"{relative_path}::{node_name}"
                self._register_function(func_id, node_name, relative_path, file_node_id, parent_class_id, start_line, end_line)
                registered_ranges[func_id] = (body_node.start_byte, body_node.end_byte)
                
        # After the main capture loop, before returning
        call_query_str = CALL_QUERIES.get(lang_type, "")
        if call_query_str:
            try:
                call_query = language_obj.query(call_query_str)

                # Version-safe extraction — identical pattern to your existing code
                call_captures = []
                if hasattr(call_query, "captures"):
                    raw = call_query.captures(tree.root_node)
                    for item in raw:
                        call_captures.append((item[0], item[1]))
                else:
                    from tree_sitter import QueryCursor
                    cursor = QueryCursor(call_query)
                    raw = cursor.captures(tree.root_node)
                    if isinstance(raw, dict):
                        for name, nodes in raw.items():
                            for n in nodes:
                                call_captures.append((n, name))
                    elif isinstance(raw, list):
                        for item in raw:
                            if hasattr(item[0], "start_byte"):
                                call_captures.append((item[0], item[1]))
                            else:
                                call_captures.append((item[1], item[0]))

                api_calls_by_scope: dict[str, set] = {}
                for call_node, _ in call_captures:
                    call_name = source_bytes[
                        call_node.start_byte:call_node.end_byte
                    ].decode("utf8").strip()
                    if not call_name or len(call_name) > 80:
                        continue
                    enclosing = self._find_enclosing_scope(call_node, registered_ranges)
                    scope_id  = enclosing if enclosing else file_node_id
                    api_calls_by_scope.setdefault(scope_id, set()).add(call_name)

                for scope_node_id, calls in api_calls_by_scope.items():
                    if scope_node_id in self.graph:
                        existing = self.graph.nodes[scope_node_id].get("api_calls", "")
                        prior    = set(existing.split(",")) if existing else set()
                        merged   = prior | calls
                        self.graph.nodes[scope_node_id]["api_calls"] = ",".join(
                            sorted(merged)
                        )

            except Exception as e:
                # A bad query string for one language must never break parsing
                logger.warning(
                    f"Call capture failed for {relative_path} "
                    f"(lang={lang_type}): {e}"
                )
        
        # for node, capture_name in captures:
        #     # Safely get the name using bytes
        #     node_name = source_bytes[node.start_byte:node.end_byte].decode('utf8')
        #     start_line = node.start_point[0] + 1
        #     end_line = node.end_point[0] + 1

        #     if capture_name == "class":
        #         class_id = f"{relative_path}::{node_name}"
        #         self._register_class(class_id, node_name, relative_path, file_node_id, start_line, end_line)
        #         classes[node_name] = {"id": class_id, "ts_node": node.parent} 
                
        #     elif capture_name == "function":
        #         # Determine if this function is inside a class we already found
        #         parent_class_id = None
        #         for cls_name, cls_data in classes.items():
        #             # If the function's AST node is a child of the class's AST node, it's a method!
        #             if self._is_descendant(node, cls_data["ts_node"]):
        #                 parent_class_id = cls_data["id"]
        #                 break
                
        #         func_id = f"{parent_class_id}::{node_name}" if parent_class_id else f"{relative_path}::{node_name}"
        #         self._register_function(func_id, node_name, relative_path, file_node_id, parent_class_id, start_line, end_line)

    
    def _find_enclosing_scope(
        self,
        node,
        registered_ranges: dict
    ) -> str | None:
        """
        Returns the node_id of the smallest registered scope
        (class or function) whose byte range contains this node.
        Falls back to None, which callers treat as file scope.
        Language-agnostic: uses byte offsets from Tree-sitter.
        """
        call_start = node.start_byte
        call_end   = node.end_byte

        best_id   = None
        best_size = float('inf')

        for node_id, (scope_start, scope_end) in registered_ranges.items():
            if scope_start <= call_start and call_end <= scope_end:
                size = scope_end - scope_start
                if size < best_size:
                    best_size = size
                    best_id   = node_id

        return best_id
    
    
    # ─────────────────────────────────────────────
    # Tree-sitter Helper
    # ─────────────────────────────────────────────
    def _is_descendant(self, node, potential_parent):
        """Checks if a node is nested inside another node."""
        current = node.parent
        while current:
            if current == potential_parent:
                return True
            current = current.parent
        return False

    # ─────────────────────────────────────────────
    # Graph Registration
    # ─────────────────────────────────────────────
    def _register_file_node(self, relative_path: str, file_hash: str) -> str:
        file_node_id = f"file::{relative_path}"
        self.graph.add_node(
            file_node_id, type="file", file_path=relative_path, hash=file_hash
        )
        return file_node_id

    def _register_class(self, class_node_id, name, path, file_id, start, end):
        self.graph.add_node(
            class_node_id, type="class", name=name, file_path=path,
            line_start=start, line_end=end, summary="", analysis_status="pending"
        )
        self.graph.add_edge(file_id, class_node_id, relation="contains")

    def _register_function(self, func_node_id, name, path, file_id, parent_class_id, start, end):
        self.graph.add_node(
            func_node_id, type="function", name=name, file_path=path,
            parent_class=parent_class_id or "", 
            line_start=start, line_end=end, 
            signature=f"{name}()", summary="", analysis_status="pending"
        )
        if parent_class_id:
            self.graph.add_edge(parent_class_id, func_node_id, relation="defines")
        else:
            self.graph.add_edge(file_id, func_node_id, relation="contains")