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

    def build_module_batches(self) -> Dict[str, Dict[str, Any]]:
        batches = {}
        file_nodes = [n for n, d in self.graph.nodes(data=True) if d.get("type") == "file"]
        
        logger.info(f"[DIAG] Total nodes in graph: {self.graph.number_of_nodes()} | File-type nodes found: {len(file_nodes)}")
        if file_nodes:
            logger.info(f"[DIAG] Sample file node: {file_nodes[0]} -> {self.graph.nodes[file_nodes[0]]}")
        logger.info(f"[DIAG] target_repo_path = {self.target_repo_path}")
        
        for file_node in file_nodes:
            file_path = self.graph.nodes[file_node]["file_path"]
            absolute_path = os.path.join(self.target_repo_path, file_path)
            
            internal_nodes = list(self.graph.successors(file_node))
            method_nodes = []
            for node in internal_nodes:
                if self.graph.nodes[node].get("type") == "class":
                    method_nodes.extend(self.graph.successors(node))
            internal_nodes.extend(method_nodes)
            
            try:
                with open(absolute_path, "r", encoding="utf-8") as f:
                    raw_code = f.read()
            except Exception as e:
                logger.warning(f"[DIAG] Warning: Could not read {absolute_path}: {e}")
                continue
                
            # --- NEW: Spaghetti Detection ---
            # If a file is huge but contains zero cleanly parsed functions/classes
            line_count = len(raw_code.splitlines())
            is_spaghetti = False
            if line_count > 300 and not internal_nodes:
                logger.warning(f"Spaghetti code detected in {file_path}. Flagging for deep analysis.")
                is_spaghetti = True
                
            batches[file_node] = {
                "file_path": file_path,
                "raw_code": raw_code,
                "contained_nodes": internal_nodes,
                "is_spaghetti": is_spaghetti # The Analyst can check this flag!
            }
            
        return batches
