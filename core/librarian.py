import os
import hashlib
import re
import networkx as nx
from pathlib import Path

from utils.constants import AllowedTypes
from utils.logger import get_logger

logger = get_logger()

class Librarian:
    def __init__(self, workspace_root: str, repo_name: str):
        """
        Manages file discovery, change verification, and graph storage 
        for an isolated repository workspace.
        """
        # Defend against malicious names (like ../../etc, foo/bar, foo\bar, foo;rm -rf)
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", repo_name):
            raise ValueError("Invalid repository name")

        base_storage = (
            Path(workspace_root)
            / ".localgraph"
            / "storage"
        ).resolve()

        storage_dir = (base_storage / repo_name).resolve()
        # Defend against malicious path manipulation (like ../../etc)
        try:
            storage_dir.relative_to(base_storage)
        except ValueError:
            raise ValueError(
                "Path traversal attempt detected"
            )

        self.storage_dir = storage_dir

        self.repo_name = repo_name
        # Set up isolated storage layout: .localgraph/storage/[repo_name]/
        # self.storage_dir = os.path.join(workspace_root, ".localgraph", "storage", repo_name)
        os.makedirs(self.storage_dir, exist_ok=True)
        
        # self.graph_path = os.path.join(self.storage_dir, "graph.graphml")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.graph_path = (self.storage_dir / "graph.graphml")
        self.graph = self._load_or_create_graph()

    def _load_or_create_graph(self) -> nx.MultiDiGraph:
        """Loads an existing GraphML file or initializes a fresh MultiDiGraph."""
        if os.path.exists(self.graph_path):
            try:
                # GraphML natively reads properties back as string/bool/numeric types
                return nx.read_graphml(self.graph_path, node_type=str)
            except Exception as e:
                logger.warning(f"Warning: Failed to read existing graph layout ({e}). Initializing fresh.")
        return nx.MultiDiGraph()

    def save_graph(self):
        """Serializes the current in-memory NetworkX graph to the isolated storage path."""
        nx.write_graphml(self.graph, self.graph_path)

    @staticmethod
    def calculate_file_hash(absolute_path: str) -> str:
        """Computes the SHA-256 hash of a file to check for structural changes."""
        hasher = hashlib.sha256()
        try:
            with open(absolute_path, "rb") as f:
                while chunk := f.read(8192):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            logger.error(f"Error hashing file {absolute_path}: {e}")
            return ""

    def scan_repository(self, target_repo_path: str, valid_files: list[Path] = None) -> dict:
        """
        Walks the codebase, filters out non-relevant files, and classifies 
        files into 'modified' (needs parsing) or 'unchanged' states.
        """
        target_dir = Path(target_repo_path)
        file_manifest = {}
        
        # If the pipeline handed us a safe list, use it. Otherwise, scan everything.
        files_to_scan = valid_files if valid_files is not None else [f for f in target_dir.rglob("*") if f.is_file()]
        
        for file_path in files_to_scan:
            # We only want to parse Python files (preserving your original logic)
            if file_path.suffix not in AllowedTypes.SUPPORTED_EXTENSIONS:
                continue
                
            # Convert Path objects to strings for compatibility with the rest of your app
            full_path = str(file_path.absolute())
            relative_path = str(file_path.relative_to(target_dir))
            
            current_hash = self.calculate_file_hash(full_path)
            
            # Read the historical hash directly out of the graph's file nodes if it exists
            file_node_id = f"file::{relative_path}"
            old_hash = self.graph.nodes.get(file_node_id, {}).get("hash", "")
            
            status = "modified" if current_hash != old_hash else "unchanged"
            
            file_manifest[relative_path] = {
                "absolute_path": full_path,
                "hash": current_hash,
                "status": status
            }
                
        return file_manifest
