import json
import networkx as nx
from semantic_kernel.functions import KernelArguments
from tenacity import retry, wait_exponential, stop_after_attempt
from semantic_kernel.connectors.ai.open_ai import OpenAIChatPromptExecutionSettings

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
        
    def _get_relevant_subgraph(self, G: nx.Graph, query: str, top_k: int = 5) -> nx.Graph:
        """
        Retrieves the most relevant nodes based on keyword overlap, 
        plus their immediate neighbors for structural context.
        """
        # 1. Simple Keyword Extraction (ignore tiny words)
        query_terms = {word.lower() for word in query.split() if len(word) > 3}
        
        node_scores = {}
        for node, data in G.nodes(data=True):
            score = 0
            text_to_search = f"{node} {data.get('summary', '')}".lower()
            for term in query_terms:
                if term in text_to_search:
                    score += 1
            if score > 0:
                node_scores[node] = score
                
        # 2. Fallback: If no keywords match, return the whole graph
        if not node_scores:
            logger.info("No direct keyword matches found. Falling back to full graph context.")
            return G
            
        # 3. Get Top-K highest scoring nodes
        top_nodes = sorted(node_scores, key=node_scores.get, reverse=True)[:top_k]
        
        # 4. Context Expansion: Add their 1-hop neighbors
        subgraph_nodes = set(top_nodes)
        for node in top_nodes:
            # If the graph is directed, use list(G.successors(node)) + list(G.predecessors(node))
            # If undirected, use G.neighbors(node)
            try:
                subgraph_nodes.update(G.successors(node))
                subgraph_nodes.update(G.predecessors(node))
            except AttributeError:
                subgraph_nodes.update(G.neighbors(node))
            
        logger.info(f"Extracted subgraph with {len(subgraph_nodes)} nodes based on query.")
        return G.subgraph(subgraph_nodes)

    @timeit
    def _build_context_payload(self, user_query: str) -> str:
        """Serializes the dynamically filtered NetworkX graph for the LLM."""
        try:
            G = nx.read_graphml(self.graph_path, node_type=str)
        except Exception as e:
            logger.error(f"Failed to load graph database: {e}")
            raise FileNotFoundError("Graph database not found.")

        # --- RETRIEVAL PHASE ---
        filtered_G = self._get_relevant_subgraph(G, user_query)

        context_lines = ["# Codebase Semantic Map\n", "## Components & Logic"]
        for node_id, data in filtered_G.nodes(data=True):
            if summary := data.get("summary", ""):
                context_lines.append(f"- [{data.get('type', 'unknown').upper()}] {node_id}: {summary}")

        context_lines.append("\n## Structural Relationships")
        for source, target, data in filtered_G.edges(data=True):
            context_lines.append(f"- {source} explicitly {data.get('relation', 'unknown')} {target}")

        return "\n".join(context_lines)
    # @timeit
    # def _build_context_payload(self) -> str:
    #     """Serializes the NetworkX graph for the LLM."""
    #     try:
    #         G = nx.read_graphml(self.graph_path, node_type=str)
    #     except Exception as e:
    #         logger.error(f"Failed to load graph database: {e}")
    #         raise FileNotFoundError("Graph database not found. Please run ingestion first.")

    #     context_lines = ["# Codebase Semantic Map\n", "## Components & Logic"]
    #     for node_id, data in G.nodes(data=True):
    #         if summary := data.get("summary", ""):
    #             context_lines.append(f"- [{data.get('type', 'unknown').upper()}] {node_id}: {summary}")

    #     context_lines.append("\n## Structural Relationships")
    #     for source, target, data in G.edges(data=True):
    #         context_lines.append(f"- {source} explicitly {data.get('relation', 'unknown')} {target}")

    #     return "\n".join(context_lines)

    @retry(wait=wait_exponential(multiplier=2, min=2, max=10), stop=stop_after_attempt(3), reraise=True)
    async def answer_question_stream(self, user_query: str, max_tokens: int = None):
        """Streams JSONL chunks, applies max_token limits, and captures telemetry."""
        logger.info(f"Assembling graph context for query: '{user_query}'")
        graph_context = self._build_context_payload(user_query=user_query)
        
        # Configure Dynamic Limits
        execution_settings = OpenAIChatPromptExecutionSettings(
            max_tokens=max_tokens if max_tokens and max_tokens > 0 else 4096
        )
        
        arguments = KernelArguments(
            graph_context=graph_context,
            user_query=user_query,
            settings=execution_settings)
        
        logger.info("Routing streaming query to local Gemma 4 instance...")
        
        try:
            # The ONE and ONLY inference loop
            async for chunks in self.kernel.invoke_prompt_stream(
                prompt=GRAPH_RAG_PROMPT, 
                arguments=arguments
            ):
                chunk = chunks[0] if isinstance(chunks, list) else chunks
                
                # 1. LOG AND YIELD JSON CHUNK
                if chunk.content:
                    # --- NEW: PRINT DIRECTLY TO TERMINAL ---
                    # print(f"RAW: [{chunk.content}]", flush=True)
                    
                    yield json.dumps({"type": "chunk", "content": chunk.content}) + "\n"
                    
                # 2. Dynamic Telemetry Extraction Strategy
                try:
                    metadata = getattr(chunk, 'metadata', {})
                    
                    timings = None
                    if hasattr(chunk, 'timings') and chunk.timings:
                        timings = chunk.timings
                    elif hasattr(chunk, 'inner_content') and chunk.inner_content:
                        timings = getattr(chunk.inner_content, 'timings', None)
                        if not timings and isinstance(chunk.inner_content, dict):
                            timings = chunk.inner_content.get('timings')
                    elif metadata and 'timings' in metadata:
                        timings = metadata['timings']

                    if timings:
                        tps = timings.get('predicted_per_second', 0) if isinstance(timings, dict) else getattr(timings, 'predicted_per_second', 0)
                        
                        prompt_n = timings.get('prompt_n', 0) if isinstance(timings, dict) else getattr(timings, 'prompt_n', 0)
                        predicted_n = timings.get('predicted_n', 0) if isinstance(timings, dict) else getattr(timings, 'predicted_n', 0)
                        total_tokens = prompt_n + predicted_n
                        
                        time_taken = total_tokens / tps if tps > 0 else 0
                                
                        logger.info(f"[TELEMETRY] Query complete | Time Taken: {time_taken:.2f} | Speed: {tps:.2f} tokens/sec | Total Tokens: {total_tokens} ({prompt_n} prompt + {predicted_n} generated)")
                        
                        telemetry_payload = {
                            "type": "telemetry",
                            "time_taken": round(time_taken, 2),
                            "tps": round(tps, 2),
                            "total_tokens": total_tokens,
                            "prompt_n": prompt_n,
                            "predicted_n": predicted_n
                        }
                        yield json.dumps(telemetry_payload) + "\n"
                        
                except Exception as e:
                    logger.warning(f"Could not parse telemetry from chunk: {e}")

        except Exception as e:
            logger.error(f"Streaming inference failed: {e}", exc_info=True)
            raise e
    # @retry(wait=wait_exponential(multiplier=2, min=2, max=10), stop=stop_after_attempt(3), reraise=True)
    # async def answer_question_stream(self, user_query: str):
    #     """
    #     Assembles context and returns an AsyncGenerator yielding pure text chunks.
    #     Intercepts internal metadata to log tokens/sec.
    #     """
    #     logger.info(f"Assembling graph context for query: '{user_query}'")
    #     graph_context = self._build_context_payload()
        
    #     arguments = KernelArguments(graph_context=graph_context, user_query=user_query)
    #     logger.info("Routing streaming query to local Gemma 4 instance...")
        
    #     try:
    #         async for chunks in self.kernel.invoke_prompt_stream(
    #             prompt=GRAPH_RAG_PROMPT, 
    #             arguments=arguments
    #         ):
    #             # Semantic Kernel usually yields a list of choices. Grab the first one.
    #             chunk = chunks[0] if isinstance(chunks, list) else chunks
                
    #             # 1. Yield ONLY the pure text content to the HTTP stream
    #             if chunk.content:
    #                 yield chunk.content
                    
    #             # 2. Dynamic Telemetry Extraction Strategy
    #             try:
    #                 metadata = getattr(chunk, 'metadata', {})
                    
    #                 # Probe for timings dictionary (Direct attribute -> inner_content -> metadata)
    #                 timings = None
    #                 if hasattr(chunk, 'timings') and chunk.timings:
    #                     timings = chunk.timings
    #                 elif hasattr(chunk, 'inner_content') and chunk.inner_content:
    #                     timings = getattr(chunk.inner_content, 'timings', None)
    #                     if not timings and isinstance(chunk.inner_content, dict):
    #                         timings = chunk.inner_content.get('timings')
    #                 elif metadata and 'timings' in metadata:
    #                     timings = metadata['timings']

    #                 # If timings metrics are located, extract and log throughput
    #                 if timings:
    #                     # Handle both dictionary and object access styles
    #                     tps = timings.get('predicted_per_second', 0) if isinstance(timings, dict) else getattr(timings, 'predicted_per_second', 0)
                        
    #                     # Extract exact token counts directly from llama-server's internal engine
    #                     prompt_n = timings.get('prompt_n', 0) if isinstance(timings, dict) else getattr(timings, 'prompt_n', 0)
    #                     predicted_n = timings.get('predicted_n', 0) if isinstance(timings, dict) else getattr(timings, 'predicted_n', 0)
    #                     total_tokens = prompt_n + predicted_n
                                
    #                     logger.info(f"[TELEMETRY] Query complete | Time Taken: {total_tokens/tps:.2f} | Speed: {tps:.2f} tokens/sec | Total Tokens: {total_tokens} ({prompt_n} prompt + {predicted_n} generated)")
    #             except Exception as e:
    #                 logger.warning(f"Could not parse telemetry from chunk: {e}")

    #     except Exception as e:
    #         logger.error(f"Streaming inference failed: {e}", exc_info=True)
    #         raise e