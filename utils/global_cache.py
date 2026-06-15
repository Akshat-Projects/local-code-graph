import os
import asyncio
import networkx as nx
from utils.logger import get_logger

logger = get_logger()

GRAPH_CACHE = {}
GRAPH_MTIME = {}

async def load_graph_cached(graph_path: str | os.PathLike) -> nx.MultiDiGraph:
    """Loads a NetworkX graph from a GraphML file with global in-memory caching."""
    graph_path_str = str(graph_path)
    current_mtime = os.path.getmtime(graph_path_str)
    
    if (
        graph_path_str not in GRAPH_CACHE
        or GRAPH_MTIME[graph_path_str] != current_mtime
    ):
        logger.info(f"Reloading graph cache for {graph_path_str}...")
        G = await asyncio.to_thread(nx.read_graphml, graph_path_str, node_type=str)
        GRAPH_CACHE[graph_path_str] = G
        GRAPH_MTIME[graph_path_str] = current_mtime
        
    return GRAPH_CACHE[graph_path_str]