"""
Orchestrates Phase 2 LLM analysis for architectural mapping, building module ingestion batches,
invoking local inference with retries, and updating the code graph with parsed intelligence summaries.
"""

from semantic_kernel.connectors.ai.open_ai import OpenAIChatPromptExecutionSettings
import json
import asyncio
from pydantic import ValidationError
from semantic_kernel.functions import KernelArguments
from tenacity import retry, wait_exponential, stop_after_attempt

from config import settings
from core.librarian import Librarian
from core.assembler import ContextAssembler
from intelligence_layer.kernel_client import LocalKernelFactory
from intelligence_layer.prompts import (
    CODE_ANALYSIS_PROMPT,
    STANDARD_CODE_ANALYSIS_PROMPT,
    SPAGHETTI_CODE_ANALYSIS_PROMPT
)
from models.llm_output import ModuleAnalysis
from utils.helper import timeit
from utils.logger import get_logger

logger = get_logger()


class GraphAnalyst:
    """
    Analyzes the codebase structure using local LLMs to map relationships,
    generate component summaries, and enrich the NetworkX code graph.
    """
    def __init__(self, librarian: Librarian, target_repo_path: str, modified_files: set[str] | None = None):
        self.librarian = librarian
        self.target_repo_path = target_repo_path
        self.assembler = ContextAssembler(self.librarian.graph, self.target_repo_path)
        self.kernel = LocalKernelFactory.create_kernel()
        self.modified_files = modified_files or set()
        self.save_lock = asyncio.Lock()

    def _needs_analysis(self, batch_data: dict) -> bool:
        """
        Determines if a code file needs LLM re-analysis based on modification status 
        or lack of architectural intelligence summaries in the graph database.
        """
        file_path = batch_data["file_path"]

        # Modified file always needs re-analysis
        if file_path in self.modified_files:
            return True

        # Check if the file node itself lacks an architectural summary
        file_node_id = f"file::{file_path}"
        file_node_data = self.librarian.graph.nodes.get(file_node_id, {})
        
        f_summary = file_node_data.get("summary", "")
        if not f_summary or f_summary in ["No summary available.", "pending"]:
            return True

        # Check if any contained node is missing intelligence
        for node_id in batch_data["contained_nodes"]:
            node_data = self.librarian.graph.nodes.get(node_id, {})
            status = node_data.get("analysis_status")
            summary = node_data.get("summary", "")
            
            if status != "complete" or not summary or summary in ["No summary available.", "pending"]:
                return True

        return False
   
   
    def _clean_json_response(self, text: str) -> str:
        """Cleans markdown ticks and formatting noise from LLM JSON responses."""
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()

    @retry(
        wait=wait_exponential(multiplier=2, min=4, max=15),
        stop=stop_after_attempt(3),
        reraise=True
    )
    async def _invoke_llm_with_retries(self, arguments: KernelArguments) -> str:
        """Wraps the LLM call and schema validation with exponential backoff retries."""
        logger.debug("Sending prompt to LLM inference engine...")
        result = await self.kernel.invoke_prompt(
            prompt=CODE_ANALYSIS_PROMPT,
            arguments=arguments
        )
        raw_response = self._clean_json_response(str(result))
        # Validate raw response matches the Pydantic schema before returning
        ModuleAnalysis.model_validate_json(raw_response)
        return raw_response
       
       
    def _filter_global_symbols(self, global_symbols: list[str], raw_code: str) -> list[str]:
        """Filters global symbol list to contain only candidate symbols mentioned inside raw_code."""
        import re
        words = set(re.findall(r'\b[a-zA-Z_]\w*\b', raw_code))
        
        filtered = []
        for symbol in global_symbols:
            parts = symbol.split("::")
            if len(parts) >= 2:
                # E.g. "path/to/file.py::ClassName::method_name"
                # Check class or method/function name
                base_names = parts[1:]
                if any(name in words for name in base_names):
                    filtered.append(symbol)
            else:
                if symbol in words:
                    filtered.append(symbol)
        return filtered

    async def _analyze_module(self, batch_data: dict, global_symbols: list[str]) -> None:
        """Extracts detailed module file summary, target node summaries, and dependencies via a single LLM call."""
        file_path = batch_data["file_path"]
        file_node_id = f"file::{file_path}"
        target_node_ids = batch_data["contained_nodes"]

        # Run reference pruning on global_symbols for this file's raw_code
        pruned_symbols = self._filter_global_symbols(global_symbols, batch_data["raw_code"])

        arguments = KernelArguments(
            target_nodes=json.dumps(target_node_ids, indent=2),
            global_symbol_list=json.dumps(pruned_symbols, indent=2),
            raw_code=batch_data["raw_code"],
            settings=OpenAIChatPromptExecutionSettings(max_tokens=8192)
        )

        try:
            logger.info(f"Generating semantic analysis for module: {file_path}")
            raw_response = await self._invoke_llm_with_retries(arguments)
            self._process_llm_response(raw_response, batch_data)

        except ValidationError as e:
            logger.error(f"Schema Validation Error on {file_path} after retries: {e}")
            for node_id in target_node_ids:
                if node_id in self.librarian.graph:
                   self.librarian.graph.nodes[node_id]["analysis_status"] = "failed_validation"
            if file_node_id in self.librarian.graph:
                self.librarian.graph.nodes[file_node_id]["analysis_status"] = "failed_validation"

            async with self.save_lock:
                graph_copy = self.librarian.graph.copy()
                await asyncio.to_thread(self.librarian.save_graph, graph_copy)

        except Exception as e:
            logger.error(f"Execution Error on {file_path} after retries: {e}")
            for node_id in target_node_ids:
                if node_id in self.librarian.graph:
                    self.librarian.graph.nodes[node_id]["analysis_status"] = "failed_runtime"
            if file_node_id in self.librarian.graph:
                self.librarian.graph.nodes[file_node_id]["analysis_status"] = "failed_runtime"

            async with self.save_lock:
                graph_copy = self.librarian.graph.copy()
                await asyncio.to_thread(self.librarian.save_graph, graph_copy)
            raise

    def _process_llm_response(self, raw_response: str, batch_data: dict) -> None:
        """Parses and validates LLM analysis, injecting summaries and dependency edges into the graph."""
        parsed_data = ModuleAnalysis.model_validate_json(raw_response)
        logger.info(f"Successfully parsed {len(parsed_data.analyzed_nodes)} nodes for {batch_data['file_path']}.")
        
        file_path = batch_data["file_path"]
        file_node_id = f"file::{file_path}"
        
        # 1. Update the file-level summary
        if file_node_id in self.librarian.graph:
            self.librarian.graph.nodes[file_node_id]["summary"] = parsed_data.file_summary
            self.librarian.graph.nodes[file_node_id]["analysis_status"] = "complete"

        # 2. Update target nodes
        target_node_ids = batch_data["contained_nodes"]
        processed_nodes = set()
        for node_data in parsed_data.analyzed_nodes:
            node_id = node_data.node_id
            processed_nodes.add(node_id)
            
            if node_id in self.librarian.graph:
                self.librarian.graph.nodes[node_id]["summary"] = node_data.summary
                self.librarian.graph.nodes[node_id]["analysis_status"] = "complete"

            for edge in node_data.dependencies:
                target_id = edge.target_id
                if target_id in self.librarian.graph:
                    exists = False
                    if self.librarian.graph.has_edge(node_id, target_id):
                        if self.librarian.graph.is_multigraph():
                            for existing_attrs in self.librarian.graph[node_id][target_id].values():
                                if existing_attrs.get("relation") == edge.relation:
                                    exists = True
                                    break
                        else:
                            existing_attrs = self.librarian.graph[node_id][target_id]
                            if existing_attrs.get("relation") == edge.relation:
                                exists = True
                    if not exists:
                        self.librarian.graph.add_edge(
                            node_id,
                            target_id,
                            relation=edge.relation,
                            confidence=edge.confidence,
                            confidence_score=edge.confidence_score
                        )

        omitted_nodes = set(target_node_ids) - processed_nodes
        if omitted_nodes:
            logger.info(
                f"[DIAG Ingest] File: {batch_data['file_path']} | "
                f"Target Nodes: {target_node_ids} | "
                f"Returned Nodes: {list(processed_nodes)} | "
                f"Raw Response: {raw_response}"
            )
            for missing_id in omitted_nodes:
                if missing_id in self.librarian.graph:
                    self.librarian.graph.nodes[missing_id]["analysis_status"] = "failed_validation"
                    logger.warning(f"LLM omitted {missing_id}. Marked for retry.")

        async def save_pipeline():
            async with self.save_lock:
                graph_copy = self.librarian.graph.copy()
                await asyncio.to_thread(self.librarian.save_graph, graph_copy)

            file_hash = self.librarian.graph.nodes.get(file_node_id, {}).get("hash", "")
            if file_hash:
                file_nodes = [
                    nid for nid, ndata in self.librarian.graph.nodes(data=True)
                    if ndata.get("file_path") == batch_data['file_path'] and nid != file_node_id
                ]
                all_complete = all(
                    self.librarian.graph.nodes[nid].get("analysis_status") == "complete"
                    for nid in file_nodes
                )
                if all_complete:
                    self.librarian.write_to_cache(batch_data['file_path'], file_hash)

        asyncio.create_task(save_pipeline())

    @timeit
    async def analyze_and_update(self, progress_callback=None):
        """Orchestrates Phase 2 codebase LLM analysis across batches concurrently."""
        logger.info("--- Starting Phase 2 LLM Analysis ---")

        global_symbols = self.assembler.get_global_symbol_list()
        all_batches = self.assembler.build_module_batches()
        logger.info(f"[DIAG] all_batches count: {len(all_batches)} | modified_files count: {len(self.modified_files)}")

        batches = {
            file_node: batch
            for file_node, batch in all_batches.items()
            if self._needs_analysis(batch)
        }
        logger.info(f"[DIAG] batches after _needs_analysis filter: {len(batches)}")

        if not batches:
            logger.info("No modules found to analyze. Graph is up to date.")
            return

        # Concurrency resolution (Dynamic vs. Configured Limit)
        concurrency = settings.MAX_CONCURRENT_INGESTION_TASKS
        if concurrency is None:
            endpoint = settings.MODEL_ENDPOINT.lower()
            if any(local_host in endpoint for local_host in ["localhost", "127.0.0.1", "0.0.0.0"]):
                concurrency = 4
                logger.info("Local deployment detected. Defaulting concurrency semaphore to 4.")
            else:
                concurrency = 15
                logger.info("Cloud deployment detected. Defaulting concurrency semaphore to 15.")
        else:
            logger.info(f"Using user-configured concurrency limit: {concurrency}")

        total_batches = len(batches)
        completed_batches = 0
        progress_lock = asyncio.Lock()
        sem = asyncio.Semaphore(concurrency)

        async def analyze_single_batch(batch_key, batch_data):
            nonlocal completed_batches
            if progress_callback:
                progress_callback(
                    completed_batches, 
                    total_batches, 
                    batch_data['file_path']
                )
            async with sem:
                logger.info(f"Analyzing Module: {batch_data['file_path']}")
                
                # Combined LLM Module Analysis (overarching summary + node details)
                await self._analyze_module(batch_data, global_symbols)
                
                async with progress_lock:
                    completed_batches += 1
                    if progress_callback:
                        progress_callback(
                            completed_batches,
                            total_batches,
                            batch_data['file_path']
                        )

        tasks = [
            analyze_single_batch(batch_key, batch_data)
            for batch_key, batch_data in batches.items()
        ]
        
        await asyncio.gather(*tasks)

        logger.info("--- Final Graph Flush ---")
        async with self.save_lock:
            graph_copy = self.librarian.graph.copy()
            await asyncio.to_thread(self.librarian.save_graph, graph_copy)

        logger.info("Phase 2 Complete!")
