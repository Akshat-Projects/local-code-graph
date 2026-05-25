import networkx as nx
from semantic_kernel.functions import KernelArguments
from tenacity import retry, wait_exponential, stop_after_attempt

from config import settings
from utils.logger import get_logger
from utils.helper import timeit
from intelligence_layer.kernel_client import LocalKernelFactory
from intelligence_layer.prompts import GRAPH_RAG_PROMPT

logger = get_logger()

class GraphQueryEngine:
    def __init__(self, repo_name: str):
        self.repo_name = repo_name
        self.graph_path = f".localgraph/storage/{repo_name}/graph.graphml"
        self.kernel = LocalKernelFactory.create_kernel()

    @timeit
    def _build_context_payload(self) -> str:
        """Serializes the NetworkX graph for the LLM."""
        try:
            G = nx.read_graphml(self.graph_path, node_type=str)
        except Exception as e:
            logger.error(f"Failed to load graph database: {e}")
            raise FileNotFoundError("Graph database not found. Please run ingestion first.")

        context_lines = ["# Codebase Semantic Map\n", "## Components & Logic"]
        for node_id, data in G.nodes(data=True):
            if summary := data.get("summary", ""):
                context_lines.append(f"- [{data.get('type', 'unknown').upper()}] {node_id}: {summary}")

        context_lines.append("\n## Structural Relationships")
        for source, target, data in G.edges(data=True):
            context_lines.append(f"- {source} explicitly {data.get('relation', 'unknown')} {target}")

        return "\n".join(context_lines)

    @retry(wait=wait_exponential(multiplier=2, min=2, max=10), stop=stop_after_attempt(3), reraise=True)
    async def answer_question_stream(self, user_query: str):
        """
        Assembles context and returns an AsyncGenerator yielding pure text chunks.
        Intercepts internal metadata to log tokens/sec.
        """
        logger.info(f"Assembling graph context for query: '{user_query}'")
        graph_context = self._build_context_payload()
        
        arguments = KernelArguments(graph_context=graph_context, user_query=user_query)
        logger.info("Routing streaming query to local Gemma 4 instance...")
        
        try:
            async for chunks in self.kernel.invoke_prompt_stream(
                prompt=GRAPH_RAG_PROMPT, 
                arguments=arguments
            ):
                # Semantic Kernel usually yields a list of choices. Grab the first one.
                chunk = chunks[0] if isinstance(chunks, list) else chunks
                
               # 1. Yield ONLY the pure text content to the HTTP stream
                if chunk.content:
                    yield chunk.content
                    
                # 2. Intercept the final chunk's metadata for our telemetry logger
                try:
                    metadata = getattr(chunk, 'metadata', {})
                    if metadata and 'timings' in metadata:
                        timings = metadata['timings']
                        tps = timings.get('predicted_per_second', 0)
                        
                        # Usage is usually an object inside the metadata dict
                        usage_obj = metadata.get('usage')
                        total_tokens = 0
                        if usage_obj:
                            # Handle both object and dict access just in case
                            total_tokens = getattr(usage_obj, 'total_tokens', 0) if hasattr(usage_obj, 'total_tokens') else usage_obj.get('total_tokens', 0)
                            
                        logger.info(f"[TELEMETRY] Query complete | Speed: {tps:.2f} tokens/sec | Total Tokens: {total_tokens}")
                except Exception as e:
                    # Log the error as a warning so we don't fail silently anymore!
                    logger.warning(f"Could not parse telemetry from chunk: {e}")

        except Exception as e:
            logger.error(f"Streaming inference failed: {e}", exc_info=True)
            raise e
        
# import networkx as nx
# from semantic_kernel.functions import KernelArguments
# from tenacity import retry, wait_exponential, stop_after_attempt

# from config import settings
# from utils.logger import get_logger
# from utils.helper import timeit
# from intelligence_layer.kernel_client import LocalKernelFactory
# from intelligence_layer.prompts import GRAPH_RAG_PROMPT

# logger = get_logger()

# class GraphQueryEngine:
#     def __init__(self, repo_name: str):
#         self.repo_name = repo_name
#         self.graph_path = f".localgraph/storage/{repo_name}/graph.graphml"
#         self.kernel = LocalKernelFactory.create_kernel()

#     @timeit
#     def _build_context_payload(self) -> str:
#         """Serializes the NetworkX graph for the LLM."""
#         try:
#             G = nx.read_graphml(self.graph_path, node_type=str)
#         except Exception as e:
#             logger.error(f"Failed to load graph database: {e}")
#             raise FileNotFoundError("Graph database not found. Please run ingestion first.")

#         context_lines = ["# Codebase Semantic Map\n", "## Components & Logic"]
#         for node_id, data in G.nodes(data=True):
#             if summary := data.get("summary", ""):
#                 context_lines.append(f"- [{data.get('type', 'unknown').upper()}] {node_id}: {summary}")

#         context_lines.append("\n## Structural Relationships")
#         for source, target, data in G.edges(data=True):
#             context_lines.append(f"- {source} explicitly {data.get('relation', 'unknown')} {target}")

#         return "\n".join(context_lines)

#     @timeit
#     @retry(wait=wait_exponential(multiplier=2, min=2, max=10), stop=stop_after_attempt(3), reraise=True)
#     async def answer_question_stream(self, user_query: str):
#         """
#         Assembles context and returns an AsyncGenerator yielding text chunks.
#         """
#         logger.info(f"Assembling graph context for query: '{user_query}'")
#         graph_context = self._build_context_payload()
        
#         arguments = KernelArguments(graph_context=graph_context, user_query=user_query)
#         logger.info("Routing streaming query to local Gemma 4 instance...")
        
#         try:
#             # invoke_prompt_stream returns an async generator yielding string chunks
#             async for chunk in self.kernel.invoke_prompt_stream(
#                 prompt=GRAPH_RAG_PROMPT, 
#                 arguments=arguments
#             ):
#                 if chunk:
#                     # Semantic kernel chunk objects usually need to be cast to string
#                     yield str(chunk)
                    
#         except Exception as e:
#             logger.error(f"Streaming inference failed: {e}", exc_info=True)
#             raise e
# #-------------------------------------------------------------------------------------------------------        
# import networkx as nx
# from semantic_kernel.functions import KernelArguments

# from config import settings
# from utils.logger import get_logger
# from intelligence_layer.kernel_client import LocalKernelFactory
# from intelligence_layer.prompts import GRAPH_RAG_PROMPT

# logger = get_logger()

# class GraphQueryEngine:
#     def __init__(self, repo_name: str):
#         self.repo_name = repo_name
#         self.graph_path = f".localgraph/storage/{repo_name}/graph.graphml"
#         self.kernel = LocalKernelFactory.create_kernel()

#     def _build_context_payload(self) -> str:
#         """
#         Serializes the NetworkX graph into a highly compressed, token-efficient 
#         text document for the LLM to read.
#         """
#         try:
#             G = nx.read_graphml(self.graph_path, node_type=str)
#         except Exception as e:
#             logger.error(f"Failed to load graph database: {e}")
#             raise FileNotFoundError("Graph database not found. Please run ingestion first.")

#         context_lines = ["# Codebase Semantic Map\n"]
        
#         # 1. Add Node Summaries
#         context_lines.append("## Components & Logic")
#         for node_id, data in G.nodes(data=True):
#             summary = data.get("summary", "")
#             if summary:
#                 node_type = data.get("type", "unknown").upper()
#                 context_lines.append(f"- [{node_type}] {node_id}: {summary}")

#         # 2. Add Explicit Dependencies
#         context_lines.append("\n## Structural Relationships")
#         edges = list(G.edges(data=True))
#         for source, target, data in edges:
#             relation = data.get("relation", "unknown")
#             context_lines.append(f"- {source} explicitly {relation} {target}")

#         return "\n".join(context_lines)

#     async def answer_question(self, user_query: str) -> str:
#         """
#         Assembles the graph context and routes the question to Gemma 4.
#         """
#         logger.info(f"Assembling graph context for query: '{user_query}'")
#         graph_context = self._build_context_payload()
        
#         arguments = KernelArguments(
#             graph_context=graph_context,
#             user_query=user_query
#         )
        
#         logger.info("Routing query to local Gemma 4 instance...")
#         try:
#             result = await self.kernel.invoke_prompt(
#                 prompt=GRAPH_RAG_PROMPT, 
#                 arguments=arguments
#             )
#             return str(result)
#         except Exception as e:
#             logger.error(f"Inference failed: {e}", exc_info=True)
#             raise e