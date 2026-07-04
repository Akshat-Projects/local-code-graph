"""
Provides utility classes to assemble code files and dependencies into cohesive context modules,
forming ingestion batches and structural symbol lists for analysis.
"""

import os
import networkx as nx
from typing import Dict, List, Any
from utils.logger import get_logger

logger = get_logger()

class ContextAssembler:
    def __init__(self, graph: nx.MultiDiGraph, target_repo_path: str):
        """
        Prepares raw code blocks and structural context from the Phase 1 graph
        to feed into Gemma 4's context window.
        """
        self.graph = graph
        self.target_repo_path = target_repo_path

    def get_global_symbol_list(self) -> List[str]:
        """
        Creates a flat list of every known class and function in the codebase.
        Gemma 4 will use this as a 'dictionary' to accurately map dependencies.
        """
        symbols = []
        for node_id, data in self.graph.nodes(data=True):
            if data.get("type") in ["function", "class"]:
                symbols.append(node_id)
        return symbols

    def build_module_batches(self, token_budget: int = 2000) -> Dict[str, Dict[str, Any]]:
        batches = {}
        file_nodes = [n for n, d in self.graph.nodes(data=True) if d.get("type") == "file"]
        
        # Self-heal graph by pruning directory paths registered as files
        invalid_file_nodes = []
        for file_node in file_nodes:
            file_path = self.graph.nodes[file_node].get("file_path", "")
            if file_path:
                absolute_path = os.path.join(self.target_repo_path, file_path)
                if os.path.isdir(absolute_path):
                    invalid_file_nodes.append(file_node)
                    
        if invalid_file_nodes:
            for file_node in invalid_file_nodes:
                logger.info(f"Pruning invalid directory node from graph: {file_node}")
                try:
                    self.graph.remove_node(file_node)
                except Exception as e:
                    logger.warning(f"Failed to prune node {file_node}: {e}")
            # Re-fetch file nodes
            file_nodes = [n for n, d in self.graph.nodes(data=True) if d.get("type") == "file"]

        logger.info(f"[DIAG] Total nodes in graph: {self.graph.number_of_nodes()} | File-type nodes found: {len(file_nodes)}")
        if file_nodes:
            logger.info(f"[DIAG] Sample file node: {file_nodes[0]} -> {self.graph.nodes[file_nodes[0]]}")
        logger.info(f"[DIAG] target_repo_path = {self.target_repo_path} | token_budget = {token_budget}")
        
        for file_node in file_nodes:
            file_path = self.graph.nodes[file_node]["file_path"]
            if file_path.lower().endswith(".md"):
                continue
            absolute_path = os.path.join(self.target_repo_path, file_path)
            
            internal_nodes = [
                node for node, ndata in self.graph.nodes(data=True)
                if ndata.get("file_path") == file_path and ndata.get("type") in ["class", "function"]
            ]
            
            try:
                with open(absolute_path, "r", encoding="utf-8") as f:
                    raw_code = f.read()
            except Exception as e:
                logger.warning(f"[DIAG] Warning: Could not read {absolute_path}: {e}")
                continue
                
            # --- Spaghetti Detection ---
            line_count = len(raw_code.splitlines())
            is_spaghetti = False
            if line_count > 300 and not internal_nodes:
                logger.warning(f"Spaghetti code detected in {file_path}. Flagging for deep analysis.")
                is_spaghetti = True

            # Estimate tokens as len(raw_code) // 4
            estimated_tokens = len(raw_code) // 4
            
            # Check if we need to chunk this file
            is_python = file_path.endswith((".py", ".ipynb"))
            if estimated_tokens > token_budget and is_python:
                logger.info(f"Chunking {file_path} (estimated tokens: {estimated_tokens} > budget: {token_budget})")
                chunks = self._chunk_python_code(raw_code, token_budget)
                
                current_line = 1
                for i, chunk_code in enumerate(chunks):
                    chunk_line_count = len(chunk_code.splitlines())
                    start_line = current_line
                    end_line = current_line + chunk_line_count - 1
                    current_line = end_line + 1
                    
                    # Filter internal nodes that belong to this chunk's line range
                    chunk_nodes = []
                    for node in internal_nodes:
                        node_data = self.graph.nodes[node]
                        line_start = node_data.get("line_start")
                        if line_start is not None and start_line <= line_start <= end_line:
                            chunk_nodes.append(node)
                            
                    batch_key = f"{file_node}::chunk_{i}"
                    batches[batch_key] = {
                        "file_node": file_node,
                        "file_path": file_path,
                        "raw_code": chunk_code,
                        "contained_nodes": chunk_nodes,
                        "is_spaghetti": is_spaghetti
                    }
            else:
                batches[file_node] = {
                    "file_node": file_node,
                    "file_path": file_path,
                    "raw_code": raw_code,
                    "contained_nodes": internal_nodes,
                    "is_spaghetti": is_spaghetti
                }
            
        return batches

    def _chunk_python_code(self, raw_code: str, token_budget: int) -> List[str]:
        import ast
        try:
            tree = ast.parse(raw_code)
        except Exception:
            return [raw_code]
            
        statements = tree.body
        if not statements:
            return [raw_code]
            
        lines = raw_code.splitlines()
        chunks = []
        
        statement_ranges = []
        prev_end = 0
        for stmt in statements:
            start = stmt.lineno - 1
            end = stmt.end_lineno
            statement_ranges.append((prev_end, end))
            prev_end = end
            
        if prev_end < len(lines):
            if statement_ranges:
                start, _ = statement_ranges[-1]
                statement_ranges[-1] = (start, len(lines))
            else:
                statement_ranges.append((0, len(lines)))
                
        current_chunk_lines = []
        current_chunk_len = 0
        
        for start, end in statement_ranges:
            stmt_code = "\n".join(lines[start:end])
            stmt_len = len(stmt_code)
            
            # If adding this statement exceeds token budget and we already have some code, flush
            if current_chunk_len > 0 and (current_chunk_len + stmt_len) // 4 > token_budget:
                chunks.append("\n".join(current_chunk_lines))
                current_chunk_lines = []
                current_chunk_len = 0
                
            current_chunk_lines.extend(lines[start:end])
            current_chunk_len += stmt_len
            
        if current_chunk_lines:
            chunks.append("\n".join(current_chunk_lines))
            
        return chunks
