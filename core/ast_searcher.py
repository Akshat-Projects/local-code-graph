"""
Provides AST structural search capabilities across multiple programming languages
using Tree-sitter tree matching queries and filters.
"""

import os
import networkx as nx
from pathlib import Path
import tree_sitter
from utils.logger import get_logger
from utils.helper import get_ignore_spec

# Re-use the language config mapping from core/universal_parser.py
from core.universal_parser import LANGUAGE_CONFIG

logger = get_logger()

# Predefined AST Search Templates
AST_SEARCH_TEMPLATES = {
    "python": {
        "exception_handlers": "(except_clause) @match",
        "decorators": "(decorator) @match",
        "async_functions": "(function_definition (async) @async) @match",
        "class_inheritance": "(class_definition superclasses: (argument_list) @superclasses) @match"
    },
    "javascript": {
        "async_functions": "(arrow_function (async) @async) @match (function_declaration (async) @async) @match",
        "arrow_functions": "(arrow_function) @match",
        "try_catch": "(try_statement) @match"
    },
    "typescript": {
        "interfaces": "(interface_declaration) @match",
        "async_functions": "(function_declaration (async) @async) @match (method_definition (async) @async) @match"
    }
}

class ASTSearcher:
    def __init__(self, graph: nx.MultiDiGraph = None):
        self.graph = graph

    def query_graph_structure(self, filters: dict) -> list:
        """
        Queries the pre-built NetworkX graph based on structural criteria.
        Supported filters:
          - node_type: 'file', 'class', 'function'
          - name: exact or partial string matching
          - inherits: searches for inherits_from edges targeting this symbol
          - calls: searches for calls/defines edges targeting this symbol
        """
        if not self.graph:
            return []
            
        results = []
        node_type = filters.get("node_type")
        name_query = filters.get("name")
        inherits_query = filters.get("inherits")
        calls_query = filters.get("calls")
        
        for node_id, data in self.graph.nodes(data=True):
            # 1. Filter by node type
            if node_type and data.get("type") != node_type:
                continue
                
            # 2. Filter by name (case-insensitive)
            node_name = data.get("name", str(node_id).split("::")[-1])
            if name_query and name_query.lower() not in node_name.lower():
                continue
                
            # 3. Filter by inheritance
            if inherits_query:
                # Check incoming inheritance edges
                has_inheritance = False
                for u, v, k, edata in self.graph.edges(keys=True, data=True):
                    if v == node_id and edata.get("relation") in ["inherits", "inherits_from"]:
                        if inherits_query.lower() in str(u).lower():
                            has_inheritance = True
                            break
                if not has_inheritance:
                    continue
                    
            # 4. Filter by calls
            if calls_query:
                has_calls = False
                for u, v, k, edata in self.graph.edges(keys=True, data=True):
                    if u == node_id and edata.get("relation") == "calls":
                        if calls_query.lower() in str(v).lower():
                            has_calls = True
                            break
                if not has_calls:
                    continue
                    
            results.append({
                "id": str(node_id),
                "type": data.get("type", "unknown"),
                "name": node_name,
                "file_path": data.get("file_path", ""),
                "line_start": data.get("line_start", 0),
                "line_end": data.get("line_end", 0),
                "summary": data.get("summary", "")
            })
            
        return results

    def search_tree_sitter_pattern(self, target_repo_path: str, query_str: str, language_ext: str) -> list:
        """
        Performs a dynamic on-the-fly AST search across files matching the extension
        using a custom S-expression query.
        """
        results = []
        if language_ext not in LANGUAGE_CONFIG or "lang" not in LANGUAGE_CONFIG[language_ext]:
            logger.warning(f"Unsupported extension for AST search: {language_ext}")
            return results
            
        lang_config = LANGUAGE_CONFIG[language_ext]
        lang_obj = lang_config["lang"]
        
        try:
            query = lang_obj.query(query_str)
        except Exception as e:
            logger.error(f"Failed to compile tree-sitter query: {e}")
            raise ValueError(f"Invalid query S-expression: {e}")
            
        target_dir = Path(target_repo_path)
        ignore_spec = get_ignore_spec(target_dir)
        
        # Build parser
        parser = tree_sitter.Parser()
        parser.language = lang_obj
        
        # Walk directories
        for root, dirs, files in os.walk(target_repo_path):
            # Prune ignored dirs in-place
            dirs[:] = [d for d in dirs if not ignore_spec.match_file(str(Path(root) / d))]
            
            for file in files:
                file_path = Path(root) / file
                rel_path = str(file_path.relative_to(target_dir))
                
                if ignore_spec.match_file(rel_path):
                    continue
                    
                if file_path.suffix.lower() == language_ext.lower():
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            source_code = f.read()
                            
                        source_bytes = source_code.encode("utf-8")
                        tree = parser.parse(source_bytes)
                        
                        # Execute query version-safely
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
                            start_line = node.start_point[0] + 1
                            end_line = node.end_point[0] + 1
                            code_snippet = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
                            
                            # Limit snippet to first few lines if it is too long
                            lines = code_snippet.splitlines()
                            if len(lines) > 8:
                                code_snippet = "\n".join(lines[:8]) + "\n... (truncated)"
                                
                            results.append({
                                "file_path": rel_path,
                                "start_line": start_line,
                                "end_line": end_line,
                                "snippet": code_snippet,
                                "capture_name": capture_name
                            })
                    except Exception as e:
                        logger.warning(f"Failed to scan AST for file {rel_path}: {e}")
                        
        return results
