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
                    
                # 2. Dynamic Telemetry Extraction Strategy
                try:
                    metadata = getattr(chunk, 'metadata', {})
                    
                    # Probe for timings dictionary (Direct attribute -> inner_content -> metadata)
                    timings = None
                    if hasattr(chunk, 'timings') and chunk.timings:
                        timings = chunk.timings
                    elif hasattr(chunk, 'inner_content') and chunk.inner_content:
                        timings = getattr(chunk.inner_content, 'timings', None)
                        if not timings and isinstance(chunk.inner_content, dict):
                            timings = chunk.inner_content.get('timings')
                    elif metadata and 'timings' in metadata:
                        timings = metadata['timings']

                    # If timings metrics are located, extract and log throughput
                    if timings:
                        # Handle both dictionary and object access styles
                        tps = timings.get('predicted_per_second', 0) if isinstance(timings, dict) else getattr(timings, 'predicted_per_second', 0)
                        
                        # Extract exact token counts directly from llama-server's internal engine
                        prompt_n = timings.get('prompt_n', 0) if isinstance(timings, dict) else getattr(timings, 'prompt_n', 0)
                        predicted_n = timings.get('predicted_n', 0) if isinstance(timings, dict) else getattr(timings, 'predicted_n', 0)
                        total_tokens = prompt_n + predicted_n
                                
                        logger.info(f"[TELEMETRY] Query complete | Time Taken: {total_tokens/tps:.2f} | Speed: {tps:.2f} tokens/sec | Total Tokens: {total_tokens} ({prompt_n} prompt + {predicted_n} generated)")
                except Exception as e:
                    logger.warning(f"Could not parse telemetry from chunk: {e}")

        except Exception as e:
            logger.error(f"Streaming inference failed: {e}", exc_info=True)
            raise e