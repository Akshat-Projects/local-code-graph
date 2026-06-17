# from langchain_core.tools import tool
# from intelligence_layer.query_engine import GraphQueryEngine

# # Initialize your engine once so the tools can share it
# graph_engine = GraphQueryEngine(repo_name="YOUR_REPO", target_repo_path="YOUR_PATH")

# @tool
# async def search_architecture_graph(query: str, chat_history: str = "") -> str:
#     """
#     Searches the repository's 3D structural graph and vector database.
#     Use this tool EVERY TIME the user asks about how the code works, where a 
#     function is located, or what a specific file does. 
#     It returns the raw source code and architectural summaries.
#     """
#     # 1. We just call the bulletproof function you already wrote!
#     context_payload = await graph_engine._build_context_payload(
#         user_query=query, 
#         chat_history=chat_history
#     )
    
#     return context_payload