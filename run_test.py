# import os
# import networkx as nx
# from core.librarian import Librarian
# from core.ast_parser import CodebaseASTParser
# from config import settings
# from utils.logger import get_logger

# logger = get_logger()

# def execute_test():
#     # 1. Define configuration settings
#     test_repo_name = settings.REPO_NAME
#     # target_code_dir = r"my_mock_test"
#     target_code_dir = settings.TARGET_REPO_PATH
    
#     logger.info("--- Initializing Phase 1 Components ---")
#     librarian = Librarian(workspace_root=".", repo_name=test_repo_name)
    
#     # 2. Scan the mock folder
#     logger.info(f"\n--- Scanning directory: {target_code_dir} ---")
#     manifest = librarian.scan_repository(target_code_dir)
    
#     for relative_path, metadata in manifest.items():
#         logger.info(f"Discovered: {relative_path} | Hash: {metadata['hash'][:12]}... | Status: {metadata['status']}")
    
#     # 3. Parse AST tokens and map to graph
#     logger.info("\n--- Parsing AST Topography ---")
#     parser = CodebaseASTParser(librarian.graph)
    
#     for relative_path, metadata in manifest.items():
#         if metadata["status"] == "modified":
#             logger.info(f"Extracting tokens out of: {relative_path}")
#             parser.parse_file(
#                 absolute_path=metadata["absolute_path"],
#                 relative_path=relative_path,
#                 file_hash=metadata["hash"]
#             )
            
#     # 4. Save the GraphML file
#     librarian.save_graph()
    
#     # 5. Verify graph topology outputs
#     logger.info("\n--- Validating Generated Graph Layout ---")
#     generated_graph = librarian.graph
#     logger.info(f"Total nodes created: {generated_graph.number_of_nodes()}")
#     logger.info(f"Total edges created: {generated_graph.number_of_edges()}")
    
#     logger.info("\nExtracted Graph Nodes:")
#     for node_id, data in generated_graph.nodes(data=True):
#         logger.info(f" -> Node: [{node_id}] | Attributes: {data}")

# if __name__ == "__main__":
#     execute_test()