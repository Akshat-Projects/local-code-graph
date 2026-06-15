import ast
import networkx as nx
from utils.logger import get_logger

logger = get_logger()

class CodebaseASTParser:
    def __init__(self, graph: nx.MultiDiGraph):
        self.graph = graph

    def clear_file_nodes(self, relative_path: str):
        nodes_to_remove = [
            node_id for node_id, data in self.graph.nodes(data=True)
            if data.get("file_path") == relative_path
        ]
        for node_id in nodes_to_remove:
            self.graph.remove_node(node_id)

    def parse_file(self, absolute_path: str, relative_path: str, file_hash: str):
        try:
            with open(absolute_path, "r", encoding="utf-8") as f:
                source_code = f.read()
            tree = ast.parse(source_code, filename=absolute_path)
        except Exception as e:
            logger.error(f"Failed to parse AST for {relative_path}: {e}")
            return

        self.clear_file_nodes(relative_path)

        file_node_id = f"file::{relative_path}"
        self.graph.add_node(
            file_node_id,
            type="file",
            file_path=relative_path,
            hash=file_hash
        )

        # ✅ Walk only the TOP-LEVEL children of the module
        # This lets us handle class bodies separately — preserving nesting
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                self._parse_class(node, file_node_id, relative_path)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._parse_function(node, file_node_id, relative_path)

    # ─────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────

    def _parse_class(self, node: ast.ClassDef, file_node_id: str, relative_path: str):
        """Registers a class node and recurses into its methods."""
        class_node_id = f"{relative_path}::{node.name}"

        self.graph.add_node(
            class_node_id,
            type="class",
            name=node.name,
            file_path=relative_path,
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno),
            summary="",
            analysis_status="pending"
        )
        # File → contains → Class  (same as before, query engine unaffected)
        self.graph.add_edge(file_node_id, class_node_id, relation="contains")

        # ✅ NEW: walk only the class body for methods
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._parse_method(child, class_node_id, file_node_id, relative_path)

    def _parse_method(
        self,
        node: ast.FunctionDef,
        class_node_id: str,
        file_node_id: str,
        relative_path: str
    ):
        """
        Registers a method node linked to its parent class.
        Also links to the file so query engine file_path lookups still work.
        """
        # Use class-scoped ID to avoid collision with module-level functions
        # e.g.  "models.py::MyModel::save"  instead of  "models.py::save"
        method_node_id = f"{class_node_id}::{node.name}"

        args = [arg.arg for arg in node.args.args]
        signature = f"def {node.name}({', '.join(args)}):"

        self.graph.add_node(
            method_node_id,
            type="function",          # ← kept as "function" so analyst/query engine treat it identically
            name=node.name,
            file_path=relative_path,  # ← kept so query engine file scoring still works
            parent_class=class_node_id,  # ← new field, ignored by existing code
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno),
            signature=signature,
            summary="",
            analysis_status="pending"
        )
        # ✅ NEW structural edge: Class → defines → method
        self.graph.add_edge(class_node_id, method_node_id, relation="defines")

        # File → contains → method edge deliberately omitted here:
        # the class→method edge already gives the query engine the path
        # file → class → method, which is richer context

    def _parse_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        file_node_id: str,
        relative_path: str
    ):
        """Registers a module-level function (unchanged behaviour)."""
        node_id = f"{relative_path}::{node.name}"
        args = [arg.arg for arg in node.args.args]
        signature = f"def {node.name}({', '.join(args)}):"

        self.graph.add_node(
            node_id,
            type="function",
            name=node.name,
            file_path=relative_path,
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno),
            signature=signature,
            summary="",
            analysis_status="pending"
        )
        self.graph.add_edge(file_node_id, node_id, relation="contains")
