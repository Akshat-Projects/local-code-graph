import networkx as nx
from config import settings
from utils.logger import get_logger

logger = get_logger()

def inspect_graph():
    # 1. Resolve the path to your active graph file
    graph_path = f"/home/akshat_ubuntu/project/local-code-graph/.localgraph/storage/Latest/graph.graphml"
    
    logger.info(f"Loading enriched graph from: {graph_path}\n")
    
    try:
        # Load the graph
        G = nx.read_graphml(graph_path, node_type=str)
    except Exception as e:
        logger.error(f"Could not load graph: {e}")
        return

    logger.info("=== EXTRACTED SUMMARIES ===")
    for node_id, data in G.nodes(data=True):
        # Only print nodes that actually have a summary populated
        summary = data.get("summary", "")
        if summary:
            logger.info(f"[{data.get('type').upper()}] {node_id}")
            logger.info(f" -> {summary}\n")

    logger.info("=== INFERRED DEPENDENCIES (EDGES) ===")
    edges = list(G.edges(data=True))
    if not edges:
        logger.warning("No edges found.")
    else:
        for source, target, data in edges:
            relation = data.get("relation", "unknown")
            logger.info(f"{source} --({relation})--> {target}")

if __name__ == "__main__":
    inspect_graph()