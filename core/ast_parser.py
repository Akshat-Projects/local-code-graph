import ast
import networkx as nx
from utils.logger import get_logger

logger = get_logger()

class CodebaseASTParser:
    def __init__(self, graph: nx.MultiDiGraph):
        """
        Processes raw source code into structured structural nodes 
        inside the shared NetworkX graph instance.
        """
        self.graph = graph

    def clear_file_nodes(self, relative_path: str):
        """
        Removes all existing structural nodes belonging to a file before re-parsing.
        This prevents stale code artifacts from lingering when a file is updated.
        """
        # Find all nodes matching this file path property
        nodes_to_remove = [
            node_id for node_id, data in self.graph.nodes(data=True)
            if data.get("file_path") == relative_path
        ]
        for node_id in nodes_to_remove:
            self.graph.remove_node(node_id)

    def parse_file(self, absolute_path: str, relative_path: str, file_hash: str):
        """
        Parses a python file, extracts class and function signatures, 
        and maps them as unique nodes in the graph.
        """
        try:
            with open(absolute_path, "r", encoding="utf-8") as f:
                source_code = f.read()
            tree = ast.parse(source_code, filename=absolute_path)
        except Exception as e:
            logger.error(f"Failed to parse AST for {relative_path}: {e}")
            return

        # 1. Clear old entry data for this specific file path to handle clean upserting
        self.clear_file_nodes(relative_path)

        # 2. Upsert the overarching tracking file node itself containing the new hash
        file_node_id = f"file::{relative_path}"
        self.graph.add_node(
            file_node_id,
            type="file",
            file_path=relative_path,
            hash=file_hash
        )

        # 3. Walk the tree to harvest structural classes and functions
        for child in ast.walk(tree):
            if isinstance(child, ast.ClassDef):
                node_id = f"{relative_path}::{child.name}"
                self.graph.add_node(
                    node_id,
                    type="class",
                    name=child.name,
                    file_path=relative_path,
                    line_start=child.lineno,
                    line_end=getattr(child, "end_lineno", child.lineno),
                    summary=""  # Initial empty string slot for Gemma 4 to fill later
                )
                # Connect structural dependency: File contains Class
                self.graph.add_edge(file_node_id, node_id, relation="contains")

            elif isinstance(child, ast.FunctionDef):
                node_id = f"{relative_path}::{child.name}"
                args = [arg.arg for arg in child.args.args]
                signature = f"def {child.name}({', '.join(args)}):"
                
                self.graph.add_node(
                    node_id,
                    type="function",
                    name=child.name,
                    file_path=relative_path,
                    line_start=child.lineno,
                    line_end=getattr(child, "end_lineno", child.lineno),
                    signature=signature,
                    summary=""  # Initial empty string slot for Gemma 4 to fill later
                )
                # Connect structural dependency: File contains Function
                self.graph.add_edge(file_node_id, node_id, relation="contains")