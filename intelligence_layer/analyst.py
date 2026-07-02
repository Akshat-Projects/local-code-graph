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
       
       
    async def _analyze_file_summary(self, batch_data: dict, file_node: str) -> None:
        """Generates and updates the high-level file summary for architectural context."""
        file_node_data = self.librarian.graph.nodes.get(file_node, {})
        
        if not file_node_data.get("summary") or file_node_data.get("summary") == "No summary available.":
            logger.info(f"Generating architectural summary for file: {batch_data['file_path']}")
            
            prompt_template = SPAGHETTI_CODE_ANALYSIS_PROMPT if batch_data["is_spaghetti"] else STANDARD_CODE_ANALYSIS_PROMPT
            
            arguments = KernelArguments(
                file_path=batch_data['file_path'],
                raw_code=batch_data['raw_code']
            )
            
            try:
                file_result = await self.kernel.invoke_prompt(prompt=prompt_template, arguments=arguments)
                self.librarian.graph.nodes[file_node]["summary"] = str(file_result).strip()
                logger.debug(f"File summary successfully generated for {file_node}")
            except Exception as e:
                logger.warning(f"Could not generate summary for file {batch_data['file_path']}: {e}")

    async def _analyze_node_details(self, batch_data: dict, global_symbols: list[str]) -> None:
        """Extracts detailed functions/classes summaries and dependencies via structural LLM call."""
        target_node_ids = batch_data["contained_nodes"]
        if not target_node_ids:
            async with self.save_lock:
                graph_copy = self.librarian.graph.copy()
                await asyncio.to_thread(self.librarian.save_graph, graph_copy)
            
            file_node_id = f"file::{batch_data['file_path']}"
            file_hash = self.librarian.graph.nodes.get(file_node_id, {}).get("hash", "")
            if file_hash:
                self.librarian.write_to_cache(batch_data['file_path'], file_hash)
            return

        arguments = KernelArguments(
            target_nodes=json.dumps(target_node_ids, indent=2),
            global_symbol_list=json.dumps(global_symbols, indent=2),
            raw_code=batch_data["raw_code"],
            settings=OpenAIChatPromptExecutionSettings(max_tokens=8192)
        )

        try:
            raw_response = await self._invoke_llm_with_retries(arguments)
            self._process_llm_response(raw_response, batch_data)

        except ValidationError as e:
            logger.error(f"Schema Validation Error on {batch_data['file_path']} after retries: {e}")
            for node_id in target_node_ids:
                if node_id in self.librarian.graph:
                   self.librarian.graph.nodes[node_id]["analysis_status"] = "failed_validation"

            async with self.save_lock:
                graph_copy = self.librarian.graph.copy()
                await asyncio.to_thread(self.librarian.save_graph, graph_copy)

        except Exception as e:
            logger.error(f"Execution Error on {batch_data['file_path']} after retries: {e}")
            for node_id in target_node_ids:
                if node_id in self.librarian.graph:
                    self.librarian.graph.nodes[node_id]["analysis_status"] = "failed_runtime"

            async with self.save_lock:
                graph_copy = self.librarian.graph.copy()
                await asyncio.to_thread(self.librarian.save_graph, graph_copy)
            raise

    def _process_llm_response(self, raw_response: str, batch_data: dict) -> None:
        """Parses and validates LLM analysis, injecting summaries and dependency edges into the graph."""
        parsed_data = ModuleAnalysis.model_validate_json(raw_response)
        logger.info(f"Successfully parsed {len(parsed_data.analyzed_nodes)} nodes for {batch_data['file_path']}.")
        
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

            file_node_id = f"file::{batch_data['file_path']}"
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

        total_batches = len(batches)
        completed_batches = 0
        progress_lock = asyncio.Lock()
        sem = asyncio.Semaphore(5)

        async def analyze_single_batch(batch_key, batch_data):
            nonlocal completed_batches
            file_node = batch_key.split("::chunk_")[0]
            if progress_callback:
                progress_callback(
                    completed_batches, 
                    total_batches, 
                    batch_data['file_path']
                )
            async with sem:
                logger.info(f"Analyzing Module: {batch_data['file_path']}")
                
                # Phase A: File summary overview
                await self._analyze_file_summary(batch_data, file_node)
                
                # Phase B: Detailed AST node functions/classes and dependencies
                await self._analyze_node_details(batch_data, global_symbols)
                
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
