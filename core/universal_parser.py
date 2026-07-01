"""
Parses target codebase source files (Python, Javascript, TypeScript, C++, etc.) using Tree-sitter AST,
extracting function definitions, class structural nodes, imports, and caller linkages.
"""

import networkx as nx
from pathlib import Path
import json
import re
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


def resolve_python_import(target_repo_path: str, current_relative_path: str, import_module: str, relative_dots: str = "") -> str | None:
    base_dir = Path(target_repo_path).resolve()
    current_dir = (base_dir / current_relative_path).parent
    
    if relative_dots:
        num_dots = len(relative_dots)
        for _ in range(num_dots - 1):
            if current_dir != base_dir:
                current_dir = current_dir.parent
        resolved_path = (current_dir / import_module.replace(".", "/")).resolve()
    else:
        resolved_path = (base_dir / import_module.replace(".", "/")).resolve()
        
    try:
        possible_py = resolved_path.with_suffix(".py")
        if possible_py.is_file():
            return str(possible_py.relative_to(base_dir))
            
        possible_init = resolved_path / "__init__.py"
        if possible_init.is_file():
            return str(possible_init.relative_to(base_dir))
            
    except Exception:
        pass
    return None


def resolve_js_import(target_repo_path: str, current_relative_path: str, import_path_str: str) -> str | None:
    if not (import_path_str.startswith(".") or import_path_str.startswith("/")):
        return None
        
    base_dir = Path(target_repo_path).resolve()
    current_dir = (base_dir / current_relative_path).parent
    resolved_path = (current_dir / import_path_str).resolve()
    
    extensions = [".js", ".jsx", ".ts", ".tsx"]
    for ext in extensions:
        possible_file = resolved_path.with_suffix(ext)
        try:
            if possible_file.is_file():
                return str(possible_file.relative_to(base_dir))
        except Exception:
            pass
            
    for ext in extensions:
        possible_index = resolved_path / f"index{ext}"
        try:
            if possible_index.is_file():
                return str(possible_index.relative_to(base_dir))
        except Exception:
            pass
    return None


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
    "python": "(call function: [(identifier) @call_name (attribute attribute: (identifier) @call_name)])",
    "javascript": "(call_expression function: [(identifier) @call_name (member_expression property: (property_identifier) @call_name)])",
    "typescript": "(call_expression function: [(identifier) @call_name (member_expression property: (property_identifier) @call_name)])",
    "tsx": "(call_expression function: [(identifier) @call_name (member_expression property: (property_identifier) @call_name)])",
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
        self.parsed_files = {}
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

    def _extract_imports(self, tree, ext, source_bytes, relative_path, target_repo_path):
        import_map = {}
        file_node_id = f"file::{relative_path}"
        lang_type = LANGUAGE_CONFIG[ext]["type"]
        
        if lang_type == "python":
            query_str = """
                (import_statement) @import
                (import_from_statement) @import_from
            """
        elif lang_type in ["javascript", "typescript", "tsx"]:
            query_str = """
                (import_statement) @import
                (call_expression
                    function: (identifier) @name
                    arguments: (arguments (string) @path)
                    (#eq? @name "require")) @require_call
            """
        else:
            return import_map
            
        try:
            language_obj = LANGUAGE_CONFIG[ext]["lang"]
            query = language_obj.query(query_str)
            
            captures = []
            if hasattr(query, "captures"):
                raw = query.captures(tree.root_node)
                for item in raw:
                    captures.append((item[0], item[1]))
            else:
                from tree_sitter import QueryCursor
                cursor = QueryCursor(query)
                raw = cursor.captures(tree.root_node)
                if isinstance(raw, dict):
                    for name, nodes in raw.items():
                        for node in nodes:
                            captures.append((node, name))
                elif isinstance(raw, list):
                    for item in raw:
                        if hasattr(item[0], "start_byte"):
                            captures.append((item[0], item[1]))
                        else:
                            captures.append((item[1], item[0]))
                            
            for node, capture_name in captures:
                node_text = source_bytes[node.start_byte:node.end_byte].decode("utf-8").strip()
                
                if lang_type == "python":
                    if capture_name == "import":
                        parts = node_text.replace("import", "").split(",")
                        for part in parts:
                            part = part.strip()
                            if " as " in part:
                                orig, alias = part.split(" as ")
                                orig = orig.strip()
                                alias = alias.strip()
                                import_map[alias] = {"module": orig, "resolved": resolve_python_import(target_repo_path, relative_path, orig)}
                            else:
                                import_map[part] = {"module": part, "resolved": resolve_python_import(target_repo_path, relative_path, part)}
                    elif capture_name == "import_from":
                        match = re.match(r"from\s+(\.+)?(\S+)\s+import\s+(.+)", node_text, re.DOTALL)
                        if match:
                            dots = match.group(1) or ""
                            mod = match.group(2)
                            imports_part = match.group(3).strip()
                            
                            resolved_module_file = resolve_python_import(target_repo_path, relative_path, mod, dots)
                            
                            imports_part = imports_part.replace("(", "").replace(")", "")
                            parts = imports_part.split(",")
                            for part in parts:
                                part = part.strip()
                                if not part:
                                    continue
                                if " as " in part:
                                    orig, alias = part.split(" as ")
                                    orig = orig.strip()
                                    alias = alias.strip()
                                    import_map[alias] = {"module": f"{mod}.{orig}", "resolved": resolved_module_file}
                                else:
                                    import_map[part] = {"module": f"{mod}.{part}", "resolved": resolved_module_file}
                                    
                elif lang_type in ["javascript", "typescript", "tsx"]:
                    if capture_name == "import":
                        match = re.match(r"import\s+(.*?)\s+from\s+['\"](.*?)['\"]", node_text, re.DOTALL)
                        if match:
                            imports_part = match.group(1).strip()
                            import_path = match.group(2).strip()
                            resolved_file = resolve_js_import(target_repo_path, relative_path, import_path)
                            
                            imports_part = imports_part.replace("{", "").replace("}", "")
                            parts = imports_part.split(",")
                            for part in parts:
                                part = part.strip()
                                if not part:
                                    continue
                                if " as " in part:
                                    orig, alias = part.split(" as ")
                                    orig = orig.strip()
                                    alias = alias.strip()
                                    import_map[alias] = {"module": orig, "resolved": resolved_file}
                                elif "*" in part:
                                    if " as " in part:
                                        _, alias = part.split(" as ")
                                        import_map[alias.strip()] = {"module": "*", "resolved": resolved_file}
                                else:
                                    import_map[part] = {"module": part, "resolved": resolved_file}
                                    
                    elif capture_name == "require_call":
                        match = re.match(r"(?:const|let|var)\s+(.*?)\s*=\s*require\s*\(['\"](.*?)['\"]\)", node_text)
                        if match:
                            imports_part = match.group(1).strip()
                            import_path = match.group(2).strip()
                            resolved_file = resolve_js_import(target_repo_path, relative_path, import_path)
                            
                            imports_part = imports_part.replace("{", "").replace("}", "")
                            parts = imports_part.split(",")
                            for part in parts:
                                part = part.strip()
                                if not part:
                                    continue
                                if ":" in part:
                                    orig, alias = part.split(":")
                                    import_map[alias.strip()] = {"module": orig.strip(), "resolved": resolved_file}
                                else:
                                    import_map[part] = {"module": part, "resolved": resolved_file}
            
            for name, info in import_map.items():
                resolved_file = info["resolved"]
                if resolved_file:
                    target_file_node_id = f"file::{resolved_file}"
                    if target_file_node_id not in self.graph:
                        self.graph.add_node(target_file_node_id, type="file", file_path=resolved_file)
                    if not self.graph.has_edge(file_node_id, target_file_node_id):
                        self.graph.add_edge(file_node_id, target_file_node_id, relation="depends_on", confidence="EXTRACTED", confidence_score=1.0)
                        
        except Exception as e:
            logger.warning(f"Failed to parse imports for {relative_path}: {e}")
            
        return import_map


    def parse_file(self, absolute_path: str, relative_path: str, file_hash: str):
        ext = Path(absolute_path).suffix
        file_ext = Path(absolute_path).suffix.lower()
        filename = Path(absolute_path).name.lower()

        target_configs = [
            "package.json", "requirements.txt",
            "docker-compose.yml", "docker-compose.yaml", "pyproject.toml"
        ]
        if filename in target_configs:
            file_node_id = self._register_file_node(relative_path, file_hash)
            self.config_extractor.extract(absolute_path, relative_path, file_node_id)
            self.graph.nodes[file_node_id]["summary"] = "Configuration/Documentation file."
            self.graph.nodes[file_node_id]["_is_pending"] = False
            self.graph.nodes[file_node_id]["analysis_status"] = "complete"
            return

        if ext not in LANGUAGE_CONFIG or "lang" not in LANGUAGE_CONFIG[ext]:
            file_node_id = self._register_file_node(relative_path, file_hash)
            self.graph.nodes[file_node_id]["summary"] = "Configuration/Documentation file."
            self.graph.nodes[file_node_id]["_is_pending"] = False
            self.graph.nodes[file_node_id]["analysis_status"] = "complete"
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

        self.clear_file_nodes(relative_path)
        file_node_id = self._register_file_node(relative_path, file_hash)

        if lang_type == "html":
            self.graph.nodes[file_node_id]["summary"] = "HTML file."
            self.graph.nodes[file_node_id]["_is_pending"] = False
            self.graph.nodes[file_node_id]["analysis_status"] = "complete"
            return

        # Determine target repo path from absolute & relative path
        abs_path_normalized = Path(absolute_path).resolve()
        rel_path_normalized = Path(relative_path)
        project_root = abs_path_normalized
        for _ in range(len(rel_path_normalized.parts)):
            project_root = project_root.parent
        target_repo_path = str(project_root)

        language_obj = LANGUAGE_CONFIG[ext]["lang"]
        query = language_obj.query(QUERIES[lang_type])
        
        captures = []
        if hasattr(query, "captures"):
            raw = query.captures(tree.root_node)
            for item in raw:
                captures.append((item[0], item[1]))
        else:
            from tree_sitter import QueryCursor
            cursor = QueryCursor(query)
            raw = cursor.captures(tree.root_node)
            
            if isinstance(raw, dict):
                for name, nodes in raw.items():
                    for node in nodes:
                        captures.append((node, name))
            elif isinstance(raw, list):
                for item in raw:
                    if hasattr(item[0], "start_byte"):
                        captures.append((item[0], item[1]))
                    else:
                        captures.append((item[1], item[0]))
                        
        captures.sort(key=lambda x: x[0].start_byte)

        classes = {}
        registered_ranges = {}

        for node, capture_name in captures:
            node_name = source_bytes[node.start_byte:node.end_byte].decode('utf8')
            body_node = node.parent
            start_line = body_node.start_point[0] + 1
            end_line   = body_node.end_point[0] + 1

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

        # Store for Pass 2 (Static call and import linking)
        self.parsed_files[relative_path] = {
            "tree": tree,
            "ext": ext,
            "source_bytes": source_bytes,
            "file_node_id": file_node_id,
            "target_repo_path": target_repo_path,
            "registered_ranges": registered_ranges,
            "lang_type": lang_type
        }

    def resolve_all_calls(self):
        """Pass 2 of static call linking. Runs after all files have been parsed."""
        logger.info(f"Pass 2: Resolving static calls and linkages across {len(self.parsed_files)} parsed files...")
        for rel_path, data in self.parsed_files.items():
            tree = data["tree"]
            ext = data["ext"]
            source_bytes = data["source_bytes"]
            file_node_id = data["file_node_id"]
            target_repo_path = data["target_repo_path"]
            registered_ranges = data["registered_ranges"]
            lang_type = data["lang_type"]

            import_map = self._extract_imports(tree, ext, source_bytes, rel_path, target_repo_path)
            language_obj = LANGUAGE_CONFIG[ext]["lang"]

            call_query_str = CALL_QUERIES.get(lang_type, "")
            if call_query_str:
                try:
                    call_query = language_obj.query(call_query_str)
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

                    # Deterministic static call linking:
                    try:
                        for scope_node_id, calls in api_calls_by_scope.items():
                            for call in calls:
                                parts = call.split(".")
                                prefix = parts[0]
                                
                                target_class_or_func = None
                                target_file = None
                                
                                if prefix in import_map:
                                    target_file = import_map[prefix]["resolved"]
                                    imported_module_path = import_map[prefix]["module"]
                                    symbol_name = imported_module_path.split(".")[-1]
                                    target_class_or_func = symbol_name
                                else:
                                    target_file = rel_path
                                    target_class_or_func = prefix
                                    
                                if target_file and target_class_or_func:
                                    possible_ids = [
                                        f"{target_file}::{target_class_or_func}"
                                    ]
                                    if len(parts) > 1:
                                        method_name = parts[1]
                                        for node_id in self.graph.nodes:
                                            if node_id.startswith(f"{target_file}::") and node_id.endswith(f"::{method_name}"):
                                                possible_ids.append(node_id)
                                                
                                    for candidate_id in possible_ids:
                                        if candidate_id in self.graph:
                                            if not self.graph.has_edge(scope_node_id, candidate_id):
                                                self.graph.add_edge(
                                                    scope_node_id,
                                                    candidate_id,
                                                    relation="calls",
                                                    confidence="STATIC_RESOLVED",
                                                    confidence_score=1.0
                                                )
                                                
                                            # Roll up to class-to-class call edge
                                            caller_class = self.graph.nodes[scope_node_id].get("parent_class", "")
                                            callee_class = self.graph.nodes[candidate_id].get("parent_class", "")
                                            
                                            # Target class node ID: callee_class if callee is a method, or candidate_id if callee is the class itself
                                            target_class_id = callee_class if callee_class else (candidate_id if self.graph.nodes[candidate_id].get("type") == "class" else None)
                                            
                                            if caller_class and target_class_id and caller_class != target_class_id:
                                                if not self.graph.has_edge(caller_class, target_class_id):
                                                    self.graph.add_edge(
                                                        caller_class,
                                                        target_class_id,
                                                        relation="calls",
                                                        confidence="STATIC_RESOLVED",
                                                        confidence_score=1.0
                                                    )
                    except Exception as e:
                        logger.warning(f"Static call linking failed for {rel_path}: {e}")

                except Exception as e:
                    logger.warning(
                        f"Call capture failed for {rel_path} "
                        f"(lang={lang_type}): {e}"
                    )
        
       
    
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
        exists = False
        if self.graph.has_edge(file_id, class_node_id):
            if self.graph.is_multigraph():
                for existing_attrs in self.graph[file_id][class_node_id].values():
                    if existing_attrs.get("relation") == "contains":
                        exists = True
                        break
            else:
                existing_attrs = self.graph[file_id][class_node_id]
                if existing_attrs.get("relation") == "contains":
                    exists = True
        if not exists:
            self.graph.add_edge(file_id, class_node_id, relation="contains", confidence="EXTRACTED", confidence_score=1.0)

    def _register_function(self, func_node_id, name, path, file_id, parent_class_id, start, end):
        self.graph.add_node(
            func_node_id, type="function", name=name, file_path=path,
            parent_class=parent_class_id or "", 
            line_start=start, line_end=end, 
            signature=f"{name}()", summary="", analysis_status="pending"
        )
        if parent_class_id:
            exists = False
            if self.graph.has_edge(parent_class_id, func_node_id):
                if self.graph.is_multigraph():
                    for existing_attrs in self.graph[parent_class_id][func_node_id].values():
                        if existing_attrs.get("relation") == "defines":
                            exists = True
                            break
                else:
                    existing_attrs = self.graph[parent_class_id][func_node_id]
                    if existing_attrs.get("relation") == "defines":
                        exists = True
            if not exists:
                self.graph.add_edge(parent_class_id, func_node_id, relation="defines", confidence="EXTRACTED", confidence_score=1.0)
        else:
            exists = False
            if self.graph.has_edge(file_id, func_node_id):
                if self.graph.is_multigraph():
                    for existing_attrs in self.graph[file_id][func_node_id].values():
                        if existing_attrs.get("relation") == "contains":
                            exists = True
                            break
                else:
                    existing_attrs = self.graph[file_id][func_node_id]
                    if existing_attrs.get("relation") == "contains":
                        exists = True
            if not exists:
                self.graph.add_edge(file_id, func_node_id, relation="contains", confidence="EXTRACTED", confidence_score=1.0)