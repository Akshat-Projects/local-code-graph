import os
import asyncio
import json
import networkx as nx
from semantic_kernel.functions import KernelArguments
from pathlib import Path
from tenacity import retry, wait_exponential, stop_after_attempt
from semantic_kernel.connectors.ai.open_ai import OpenAIChatPromptExecutionSettings

from config import settings
from utils.logger import get_logger
from utils.helper import timeit, validate_ingestion_path
from intelligence_layer.kernel_client import LocalKernelFactory
from utils.global_cache import GRAPH_CACHE, GRAPH_MTIME
from intelligence_layer.prompts import GRAPH_RAG_PROMPT

logger = get_logger()

class GraphQueryEngine:
    def __init__(self, repo_name: str, target_repo_path: str):
        self.repo_name = repo_name
        self.graph_path = f".localgraph/storage/{repo_name}/graph.graphml"
        self.kernel = LocalKernelFactory.create_kernel()
        # self.target_repo_path = target_repo_path
        self.target_repo_path = str(validate_ingestion_path(target_repo_path))
        # Enable caching for faster query result
        self._graph_cache = None
        self._graph_mtime = None
        
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
    
    
    # def _load_graph(self):
    #     current_mtime = os.path.getmtime(
    #         self.graph_path
    #     )
    #     if (self._graph_cache is None or self._graph_mtime != current_mtime):
    #         logger.info("Reloading graph cache...")
    #         self._graph_cache = nx.read_graphml(
    #             self.graph_path,
    #             node_type=str
    #         )
    #         self._graph_mtime = current_mtime

    #     return self._graph_cache
    def _load_graph(self):
        current_mtime = os.path.getmtime(self.graph_path)
        if (
            self.graph_path not in GRAPH_CACHE
            or GRAPH_MTIME[self.graph_path]
            != current_mtime
        ):
            logger.info("Reloading graph cache...")
            GRAPH_CACHE[self.graph_path] = (
                nx.read_graphml(
                    self.graph_path,
                    node_type=str
                )
            )
            GRAPH_MTIME[self.graph_path] = (
                current_mtime
            )
        return GRAPH_CACHE[self.graph_path]
    
    @timeit
    async def _build_context_payload(self, user_query: str) -> str:
        try:
            # G = nx.read_graphml(self.graph_path, node_type=str)
            # G = self._load_graph()
            G = await asyncio.to_thread(
                    self._load_graph
                )
        except Exception as e:
            logger.error(f"Failed to load graph database: {e}")
            raise FileNotFoundError("Graph database not found.")

        filtered_G = self._get_relevant_subgraph(G, user_query)

        context_lines = ["# Codebase Semantic Map\n", "## Components & Logic"]
        
        # 1. Add the Semantic Summaries
        for node_id, data in filtered_G.nodes(data=True):
            if summary := data.get("summary", ""):
                context_lines.append(f"- [{data.get('type', 'unknown').upper()}] {node_id}: {summary}")

        context_lines.append("\n## Structural Relationships")
        for source, target, data in filtered_G.edges(data=True):
            context_lines.append(f"- {source} explicitly {data.get('relation', 'unknown')} {target}")

        # --- NEW: DYNAMIC FILE INJECTION ---
        context_lines.append("\n## Relevant Raw Source Code")
        
        # Find all unique files associated with our highly relevant subgraph
        file_scores = {}
        for _, node_data in filtered_G.nodes(data=True):

            file_path = node_data.get("file_path")

            if not file_path:
                continue

            file_scores[file_path] = (
                file_scores.get(file_path, 0)
                + 1
            )

        top_files = sorted(file_scores, key=file_scores.get, reverse=True)[:3]


        for rel_path in top_files: # Cap at top 3 files to save GPU memory
            full_path = os.path.join(self.target_repo_path, rel_path)
            if os.path.exists(full_path):
                try:
                    # with open(full_path, "r", encoding="utf-8") as f:
                        # code_content = f.read()
                    code_content = await asyncio.to_thread(
                            Path(full_path).read_text,
                            encoding="utf-8"
                        )
                    context_lines.append(f"\n### File: {rel_path}\n```python\n{code_content}\n```")
                except Exception as e:
                    logger.warning(f"Could not read source file {full_path}: {e}")
                # with open(full_path, "r", encoding="utf-8") as f:
                #     code_content = f.read()
                #     context_lines.append(f"\n### File: {rel_path}\n```python\n{code_content}\n```")

        return "\n".join(context_lines)


    @retry(wait=wait_exponential(multiplier=2, min=2, max=10), stop=stop_after_attempt(3), reraise=True)
    async def answer_question_stream(self, user_query: str, max_tokens: int = None):
        """Streams JSONL chunks, applies max_token limits, and captures telemetry."""
        logger.info(f"Assembling graph context for query: '{user_query}'")
        graph_context = await self._build_context_payload(user_query=user_query)
        
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
                    try:
                        delta = getattr(chunk.inner_content.choices[0], "delta", None)
                        if delta:
                            # Handle both Pydantic model attribute and raw dictionary
                            reasoning = getattr(delta, "reasoning_content", None)
                            if not reasoning and isinstance(delta, dict):
                                reasoning = delta.get("reasoning_content")
                                
                            if reasoning:
                                # Stream it to the UI under a specific "thought" type
                                yield json.dumps({"type": "thought", "content": reasoning}) + "\n"
                    except Exception:
                        pass
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
        