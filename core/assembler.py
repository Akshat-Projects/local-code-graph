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
        """
        Groups nodes by file and extracts the raw source code.
        Instead of sending 1 function at a time, we send the whole file module
        to maximize Gemma 4's 128k context window.
        """
        batches = {}
        
        # 1. Find all file nodes in the graph
        file_nodes = [
            n for n, d in self.graph.nodes(data=True) 
            if d.get("type") == "file"
        ]
        
        for file_node in file_nodes:
            file_path = self.graph.nodes[file_node]["file_path"]
            absolute_path = os.path.join(self.target_repo_path, file_path)
            
            # 2. Find all functions, classes, and class methods contained in this file
            # NetworkX successors of a file node are its classes and module-level functions
            internal_nodes = list(self.graph.successors(file_node))
            
            # Also retrieve class methods (successors of class nodes)
            method_nodes = []
            for node in internal_nodes:
                if self.graph.nodes[node].get("type") == "class":
                    method_nodes.extend(self.graph.successors(node))
            internal_nodes.extend(method_nodes)
            
            # 3. Read the raw source code
            try:
                with open(absolute_path, "r", encoding="utf-8") as f:
                    raw_code = f.read()
            except Exception as e:
                logger.warning(f"Warning: Could not read {absolute_path}: {e}")
                continue
                
            batches[file_node] = {
                "file_path": file_path,
                "raw_code": raw_code,
                "contained_nodes": internal_nodes
            }
            
        return batches