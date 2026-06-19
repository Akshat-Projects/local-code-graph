import os
import asyncio
import re
import shutil
import subprocess
import json
import networkx as nx
from semantic_kernel.functions import KernelArguments
from pathlib import Path
from tenacity import retry, wait_exponential, stop_after_attempt
from semantic_kernel.connectors.ai.open_ai import OpenAIChatPromptExecutionSettings

from config import settings
from utils.logger import get_logger
from utils.helper import timeit, validate_ingestion_path, secure_path_join
from intelligence_layer.kernel_client import LocalKernelFactory
from core.vector_operations import HybridVectorStore
from intelligence_layer.kernel_client import CodebaseSearchPlugin
from utils.global_cache import load_graph_cached
from utils.helper import get_ignore_spec
from intelligence_layer.prompts import GRAPH_RAG_PROMPT, AGENT_PROMPT

logger = get_logger()

class GraphQueryEngine:
    def __init__(self, repo_name: str, target_repo_path: str):
        self.repo_name = repo_name
        self.graph_path = f".localgraph/storage/{repo_name}/graph.graphml"
        self.kernel = LocalKernelFactory.create_kernel()
        self.kernel.add_plugin(CodebaseSearchPlugin(self), plugin_name="Codebase")
        self.vector_store = HybridVectorStore(repo_name)
        self.target_repo_path = str(validate_ingestion_path(target_repo_path))
        
        # Enable caching for faster query result
        self._graph_cache = None
        self._graph_mtime = None
   
   
    def _exact_match_search(
        self,
        query: str,
        target_dir: Path,
        ignore_spec,
    ) -> dict:
        """
        Extracts code-like tokens from the natural language query and
        searches for them literally across the workspace.
        Returns {relative_path: [line_numbers]}.
        Respects the same ignore spec as ingestion — no new filtering logic.
        Language-agnostic: operates on raw file bytes regardless of language.
        """
        # Common English stop words to filter out from natural language queries
        stopwords = {
            "why", "is", "my", "chatbot", "not", "find", "any", "mentions", "of", 
            "despite", "me", "adding", "regex", "search", "in", "whole", "code", 
            "base", "can", "you", "see", "where", "the", "does", "do", "how", "what", 
            "which", "who", "whom", "this", "that", "these", "those", "am", "are", 
            "was", "were", "be", "been", "being", "have", "has", "had", "having", 
            "a", "an", "and", "but", "if", "or", "because", "as", "until", "while", 
            "at", "by", "for", "with", "about", "against", "between", "into", "through", 
            "during", "before", "after", "above", "below", "to", "from", "up", "down", 
            "on", "off", "over", "under", "again", "further", "then", "once", "here", 
            "there", "when", "all", "both", "each", "few", "more", "most", "other", 
            "some", "such", "no", "nor", "only", "own", "same", "so", "than", "too", 
            "very", "will", "just", "should", "now", "us", "use", "used", "using"
        }

        # 1. First, extract code-specific patterns (CamelCase, snake_case, dotted names)
        code_tokens = re.findall(
            r'\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b'     # CamelCase
            r'|\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b'      # snake_case
            r'|\b[a-zA-Z_]\w+\.[a-zA-Z_]\w+\b',         # dotted
            query
        )

        # 2. As a fallback, extract any alphanumeric word that isn't a stopword or too short
        all_words = re.findall(r'\b[a-zA-Z_]\w*\b', query)
        fallback_tokens = [w for w in all_words if w.lower() not in stopwords and len(w) > 2]

        tokens = list(set(code_tokens + fallback_tokens))

        if not tokens:
            return {}

        has_rg  = shutil.which("rg") is not None
        results = {}

        for token in tokens:
            matched_lines = []

            if has_rg:
                try:
                    # Run ripgrep case-insensitively (-i) and literally (-F)
                    out = subprocess.check_output(
                        ["rg", "-in", "--no-heading", "-F", token, str(target_dir)],
                        text=True,
                        timeout=5,
                        stderr=subprocess.DEVNULL
                    )
                    matched_lines = out.strip().splitlines()
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    matched_lines = []
            else:
                # Pure-Python fallback — case-insensitive match
                token_lower = token.lower()
                for file_path in target_dir.rglob("*"):
                    if not file_path.is_file():
                        continue
                    try:
                        rel = str(file_path.relative_to(target_dir))
                    except ValueError:
                        continue
                    if ignore_spec.match_file(rel):
                        continue
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        for i, line in enumerate(content.splitlines(), 1):
                            if token_lower in line.lower():
                                matched_lines.append(f"{file_path}:{i}:{line}")
                    except Exception:
                        continue

            for raw in matched_lines:
                parts = raw.split(":", 2)
                if len(parts) < 2:
                    continue
                try:
                    abs_path = Path(parts[0])
                    line_no  = int(parts[1])
                    rel_path = str(abs_path.relative_to(target_dir))
                except (ValueError, Exception):
                    continue
                if ignore_spec.match_file(rel_path):
                    continue
                results.setdefault(rel_path, []).append(line_no)

        return results
        
    def _get_relevant_subgraph(self, G: nx.Graph, query: str, chat_history: str = "", top_k: int = 15) -> tuple[nx.Graph, dict]:
        search_query = query
        if chat_history:
            context_anchor = chat_history[-150:].replace('\n', ' ')
            search_query = f"{context_anchor} {query}"
            logger.info(f"Enriched Vector Search Query: {search_query}")

        # 1. True Hybrid Search (RRF handles the exact-match heavy lifting now!)
        top_semantic_nodes = self.vector_store.search(search_query, top_k=top_k)
        
        seed_nodes = {}
        for rank, node_id in enumerate(top_semantic_nodes):
            # The #1 result gets highest score, scaling down linearly
            seed_nodes[node_id] = float(len(top_semantic_nodes) - rank)

        if not seed_nodes:
            logger.info("No direct matches found. Extracting central architectural hubs.")
            hub_nodes = sorted(G.degree, key=lambda x: x[1], reverse=True)[:top_k]
            subgraph_nodes = {node for node, _ in hub_nodes}
            scores = {node: float(deg) for node, deg in hub_nodes}
            for node in list(subgraph_nodes):
                neighbors = (set(G.successors(node)) | set(G.predecessors(node))) if G.is_directed() else set(G.neighbors(node))
                subgraph_nodes.update(neighbors)
                for n in neighbors:
                    scores.setdefault(n, 1.0)
            return G.subgraph(subgraph_nodes), scores

        total_score = sum(seed_nodes.values())
        personalization = {node: score / total_score for node, score in seed_nodes.items()}

        try:
            calc_graph = nx.DiGraph(G) if G.is_directed() else nx.Graph(G) if G.is_multigraph() else G
            pr_scores = nx.pagerank(calc_graph, alpha=0.85, personalization=personalization, max_iter=100)

            target_expansion_limit = top_k * 3
            top_structural_nodes = sorted(pr_scores, key=pr_scores.get, reverse=True)[:target_expansion_limit]
            subgraph_nodes = set(top_structural_nodes)
            scores = {n: pr_scores.get(n, 0) for n in subgraph_nodes}
            
            logger.info(f"Successfully generated structural PPR subgraph with {len(subgraph_nodes)} nodes.")
            return G.subgraph(subgraph_nodes), scores

        except Exception as e:
            logger.warning(f"PageRank computation failed or bypassed: {e}. Falling back to 1-hop neighborhood.")
            top_nodes = sorted(seed_nodes, key=seed_nodes.get, reverse=True)[:top_k]
            subgraph_nodes = set(top_nodes)
            scores = {n: seed_nodes.get(n, 0) for n in top_nodes}
            for node in top_nodes:
                neighbors = (set(G.successors(node)) | set(G.predecessors(node))) if G.is_directed() else set(G.neighbors(node))
                subgraph_nodes.update(neighbors)
                for n in neighbors:
                    scores.setdefault(n, 0.1)
            return G.subgraph(subgraph_nodes), scores
        
        
    async def _load_graph(self):
        return await load_graph_cached(self.graph_path)
   
   
    @timeit
    async def _build_context_payload(self, user_query: str, chat_history: str = "") -> str:
        target_dir = Path(self.target_repo_path)
        
        try:
            G = await self._load_graph()
        except Exception as e:
            logger.error(f"Failed to load graph database: {e}")
            raise FileNotFoundError("Graph database not found.")

        # filtered_G = self._get_relevant_subgraph(G=G, query=user_query, chat_history=chat_history)
        filtered_G, relevance_scores = self._get_relevant_subgraph(G=G, query=user_query, chat_history=chat_history)

        context_lines = ["# Codebase Semantic Map\n", "## Components & Logic"]
       
        # 1. Add the Semantic Summaries
        for node_id, data in filtered_G.nodes(data=True):
            if summary := data.get("summary", ""):
                context_lines.append(f"- [{data.get('type', 'unknown').upper()}] {node_id}: {summary}")

        context_lines.append("\n## Structural Relationships")
        for source, target, data in filtered_G.edges(data=True):
            context_lines.append(f"- {source} explicitly {data.get('relation', 'unknown')} {target}")

        # --- DYNAMIC FILE INJECTION ---
        context_lines.append("\n## Relevant Raw Source Code")
       
        file_scores = {}
        for node_id, node_data in filtered_G.nodes(data=True):
            file_path = node_data.get("file_path")
            if not file_path:
                node_str = str(node_id)
                if node_str.startswith("file::"):
                    file_path = node_str.replace("file::", "")
                elif "::" in node_str:
                    file_path = node_str.split("::")[0]
            if not file_path:
                continue

            file_path = str(file_path).strip()
            relevance = relevance_scores.get(node_id, 0.0)
            exact_bonus = 50 if user_query.lower() in str(node_id).lower() else 0
            node_score = relevance + exact_bonus
            file_scores[file_path] = max(file_scores.get(file_path, 0), node_score)
            
        ignore_spec = get_ignore_spec(target_dir)
        grep_hits = self._exact_match_search(user_query, target_dir, ignore_spec)
        for rel_path in grep_hits:
            file_scores[rel_path] = file_scores.get(rel_path, 0) + 80

        # top_files = sorted(file_scores, key=file_scores.get, reverse=True)[:8]
        top_files = sorted(file_scores, key=file_scores.get, reverse=True)[:5]
        
        # --- CRITICAL LOGGING ---
        logger.info(f"Attempting to inject raw code for files: {top_files}")
        for rel_path in top_files:
            try:
                full_path = secure_path_join(self.target_repo_path, rel_path)
            except Exception as e:
                logger.error(f"Path verification failed for {rel_path}: {e}")
                continue

            if full_path.exists() and full_path.is_file():
                try:
                    code_content = await asyncio.to_thread(full_path.read_text, encoding="utf-8")
                    # context_lines.append(f"\n### File: {rel_path}\n```python\n{code_content}\n```")
                    ext = Path(rel_path).suffix.lstrip(".")  # "py", "js", "java", etc.
                    context_lines.append(f"\n### File: {rel_path}\n```{ext}\n{code_content}\n```")
                    logger.info(f"SUCCESS: Injected physical file: {full_path}")
                except Exception as e:
                    logger.error(f"FAIL: Could not read source file {full_path}: {e}")
            else:
                logger.error(f"FAIL: File not found on disk at absolute path: {full_path}")

        return "\n".join(context_lines)
    

    async def _route_query(self, user_query: str, chat_history: str) -> str:
        """
        The Traffic Cop: Decides if we need to search the graph or just chat.
        """
        router_prompt = f"""You are an elite, high-speed routing engine for a local repository AI assistant.
            Your sole job is to classify the user's latest input into one of two routing destinations:

            1. 'CONVERSATIONAL': Choose this ONLY if the user is greeting you, making small talk, or asking meta-questions about the chat history itself (e.g., "What did I just ask?").
            2. 'CODEBASE': Choose this for anything else. 
            **CRITICAL OVERRIDE:** If the user asks an explanatory question like "How does X work?", "Why do we use Y?", or "What advantage does Z provide?", you MUST route to CODEBASE so the agent can read the repository files to find the answer.

            ---
            FEW-SHOT EXAMPLES:

            Input: "Hi there" -> Destination: CONVERSATIONAL
            Input: "What questions did I ask you so far?" -> Destination: CONVERSATIONAL
            Input: "Can you tell what advantage Data Normalizer did provide?" -> Destination: CODEBASE
            Input: "Why are we using a median blur here?" -> Destination: CODEBASE
            Input: "process_data_frame" -> Destination: CODEBASE
            Input: "thanks for the help" -> Destination: CONVERSATIONAL
            Input: "where is the threshold setting?" -> Destination: CODEBASE
            ---

            Current Chat History:
            {chat_history}

            Latest User Input: "{user_query}"

            Respond with EXACTLY one word, either 'CONVERSATIONAL' or 'CODEBASE'. Do not include punctuation, explanation, or markdown formatting.

            Destination:"""
            
        try:
            # A blazing fast, non-streaming call to get the routing word
            decision = await self.kernel.invoke_prompt(prompt=router_prompt)
            decision_text = str(decision).strip().upper()
            
            if "CONVERSATIONAL" in decision_text:
                return "CONVERSATIONAL"
            return "CODEBASE"
        except Exception as e:
            logger.warning(f"Routing failed, defaulting to CODEBASE. Error: {e}")
            return "CODEBASE"
        
        
    @retry(wait=wait_exponential(multiplier=2, min=2, max=10), stop=stop_after_attempt(3), reraise=True)
    async def answer_question_stream(self, user_query: str, max_tokens: int = None, chat_history: str = ""):
        """Streams JSONL chunks, applies max_token limits, and captures telemetry."""
        # 1. Ask the Traffic Cop
        intent = await self._route_query(user_query, chat_history)
        
        execution_settings = OpenAIChatPromptExecutionSettings(
            max_tokens=max_tokens if max_tokens and max_tokens > 0 else 16384
        )

        # 2. Branch the Logic based on the Agent's decision
        if intent == "CONVERSATIONAL":
            logger.info("Agent routed query to Conversational Memory (Bypassing GraphRAG).")
            
            chat_prompt = f"""You are a helpful conversational AI assistant. 
            Below is the transcript of your conversation with the user so far:
            
            --- START CONVERSATION LOG ---
            {chat_history}
            --- END CONVERSATION LOG ---
            
            The user just said: "{user_query}"
            
            Respond directly to the user's latest message. Use the conversation log above as your personal memory to understand context.
            """
            
            arguments = KernelArguments(settings=execution_settings)
            final_prompt = chat_prompt
            
        else:
            logger.info(f"Agent routed query to GraphRAG Engine: '{user_query}'")
            
            # Trigger the heavy Vector Search + PageRank pipeline
            graph_context = await self._build_context_payload(user_query=user_query, chat_history=chat_history)
            
            arguments = KernelArguments(
                graph_context=graph_context,
                chat_history=chat_history,
                user_query=user_query,
                settings=execution_settings)
            final_prompt = GRAPH_RAG_PROMPT
        
       
        try:
            # The ONE and ONLY inference loop
            async for chunks in self.kernel.invoke_prompt_stream(
                prompt=final_prompt,
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
            # 1. Get a clean, stringified version of the error without the massive traceback
            error_str = str(e)
            
            # 2. Check if it's a connection-related death
            if "Connection error" in error_str or "ConnectError" in error_str or "Failed to connect" in error_str:
                logger.error("LLM Connection Refused: Ensure llama.cpp/Ollama/LM Studio is running and port is correct.")
                yield "\n\n🚨 **Connection Lost:** Cannot reach the local LLM server. Please check if your inference engine is running."
            else:
                # 3. Handle context window overflows or other generation errors cleanly
                logger.error(f"LLM Generation Error: {error_str}")
                yield f"\n\n⚠️ **Inference Error:** The LLM encountered an issue. Make sure your context window isn't overflowing."

