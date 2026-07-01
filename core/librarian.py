"""
Manages the graph database state (saving/loading GraphML) and scans directories,
tracking modified files using MD5 hashes to optimize downstream parsing.
"""

import os
import hashlib
import re
import networkx as nx
from pathlib import Path
import tempfile

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
                loaded_g = nx.read_graphml(self.graph_path, node_type=str)
                return nx.MultiDiGraph(loaded_g)
            except Exception as e:
                logger.warning(f"Warning: Failed to read existing graph layout ({e}). Initializing fresh.")
        return nx.MultiDiGraph()


    def save_graph(self, G: nx.MultiDiGraph = None):
        """Saves the graph using an atomic write to prevent UI read-crashes."""
        graph_obj = G if G is not None else self.graph
        try:
            dir_name = os.path.dirname(self.graph_path)
            os.makedirs(dir_name, exist_ok=True)
            
            # 1. Write to a temporary file first
            fd, temp_path = tempfile.mkstemp(dir=dir_name, prefix=".tmp_", suffix=".graphml")
            with os.fdopen(fd, 'wb') as f:
                nx.write_graphml(graph_obj, f)
                
            # 2. Atomic rename (Instantly replaces the old file, zero chance of read corruption)
            os.replace(temp_path, self.graph_path)
            
        except Exception as e:
            logger.error(f"Failed to save graph atomically: {e}")


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
        files_to_scan = valid_files if valid_files is not None else [f for f in target_dir.rglob("*") if f.is_file()]

        cache_dir = self.storage_dir / "cache"   # scoped to this repo, not the whole workspace

        for file_path in files_to_scan:
            if file_path.suffix not in AllowedTypes.SUPPORTED_EXTENSIONS:
                continue

            full_path = str(file_path.absolute())
            relative_path = str(file_path.relative_to(target_dir))
            current_hash = self.calculate_file_hash(full_path)

            # Key on path + content, so identical-content files don't collide
            cache_key = hashlib.sha256(f"{relative_path}::{current_hash}".encode()).hexdigest()
            cache_file = cache_dir / f"v4_{cache_key}.json"

            if cache_file.exists():
                status = "unchanged"
                self.load_from_cache(cache_file)
            else:
                status = "modified"

            file_manifest[relative_path] = {
                "absolute_path": full_path,
                "hash": current_hash,
                "status": status,
            }

        return file_manifest


    def load_from_cache(self, cache_file_path: Path):
        import json
        try:
            with open(cache_file_path, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
            
            # Add nodes
            for node_data in cached_data.get("nodes", []):
                node_id = node_data["id"]
                attrs = node_data.get("attributes", {})
                self.graph.add_node(node_id, **attrs)
                
            # Add edges
            for edge_data in cached_data.get("edges", []):
                u = edge_data["source"]
                v = edge_data["target"]
                attrs = edge_data.get("attributes", {})
                
                # Deduplicate: check if an edge with the same relation already exists
                relation = attrs.get("relation")
                exists = False
                if self.graph.has_edge(u, v):
                    if self.graph.is_multigraph():
                        for existing_attrs in self.graph[u][v].values():
                            if existing_attrs.get("relation") == relation:
                                exists = True
                                break
                    else:
                        existing_attrs = self.graph[u][v]
                        if existing_attrs.get("relation") == relation:
                            exists = True
                if not exists:
                    self.graph.add_edge(u, v, **attrs)
                
            logger.info(f"Loaded cached structure from {cache_file_path}")
        except Exception as e:
            logger.error(f"Failed to load cache from {cache_file_path}: {e}")


    def write_to_cache(self, relative_path: str, file_hash: str):
        import json
        if not file_hash:
            return
        # workspace_root = self.storage_dir.parent.parent.parent
        cache_dir = self.storage_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_key = hashlib.sha256(f"{relative_path}::{file_hash}".encode()).hexdigest()
        cache_file = cache_dir / f"v4_{cache_key}.json"
            
        file_node_id = f"file::{relative_path}"
        nodes_to_cache = []
        edges_to_cache = []
        
        for node_id, data in self.graph.nodes(data=True):
            if data.get("file_path") == relative_path or node_id == file_node_id:
                nodes_to_cache.append({
                    "id": node_id,
                    "attributes": data
                })
                
        node_ids_set = {n["id"] for n in nodes_to_cache}
        for u, v, key, data in self.graph.edges(keys=True, data=True):
            if u in node_ids_set:
                edges_to_cache.append({
                    "source": u,
                    "target": v,
                    "attributes": data
                })
                
        cached_structure = {
            "hash": file_hash,
            "file_path": relative_path,
            "nodes": nodes_to_cache,
            "edges": edges_to_cache
        }
        
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cached_structure, f, indent=2)
            logger.info(f"Successfully cached structure for {relative_path} with hash {file_hash}")
        except Exception as e:
            logger.error(f"Failed to write cache for {relative_path}: {e}")
