from semantic_kernel.connectors.ai.open_ai import OpenAIChatPromptExecutionSettings
import json
import asyncio
from pydantic import ValidationError
from semantic_kernel.functions import KernelArguments
from tenacity import retry, wait_exponential, stop_after_attempt

from config import settings
# from intelligence_layer.prompts import FILE_PROMPT
from core.librarian import Librarian
from core.assembler import ContextAssembler
from intelligence_layer.kernel_client import LocalKernelFactory
from intelligence_layer.prompts import CODE_ANALYSIS_PROMPT
from models.llm_output import ModuleAnalysis
from utils.helper import timeit
from utils.logger import get_logger

logger = get_logger()

class GraphAnalyst:
    def __init__(self, librarian: Librarian, target_repo_path: str, modified_files: set[str] | None = None):
        self.librarian = librarian
        self.target_repo_path = target_repo_path
        self.assembler = ContextAssembler(self.librarian.graph, self.target_repo_path)
        self.kernel = LocalKernelFactory.create_kernel()
        self.modified_files = modified_files or set()
        self.save_lock = asyncio.Lock()

    def _needs_analysis(self, batch_data: dict) -> bool:
        """
        Analyze if:
        1. File was modified
        2. File node itself lacks an architectural summary
        3. Any contained node is not marked complete
        """
        file_path = batch_data["file_path"]

        # Modified file always needs re-analysis
        if file_path in self.modified_files:
            return True

        # Check if the file node itself lacks an architectural summary
        file_node_id = f"file::{file_path}"
        file_node_data = self.librarian.graph.nodes.get(file_node_id, {})
        
        # if file_node_data.get("_is_pending") or file_node_data.get("analysis_status") != "complete":
            # return True
        
        f_summary = file_node_data.get("summary", "")
        if not f_summary or f_summary in ["No summary available.", "pending"]:
            return True

        # Check if any contained node is missing intelligence
        for node_id in batch_data["contained_nodes"]:
            node_data = self.librarian.graph.nodes.get(node_id, {})
            status = node_data.get("analysis_status")
            summary = node_data.get("summary", "")
            
            # --- FIX: Re-analyze if not complete, OR if summary is empty/pending ---
            if status != "complete" or not summary or summary in ["No summary available.", "pending"]:
                return True

        return False
   
   
    def _clean_json_response(self, text: str) -> str:
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()

    # --- NEW: Tenacity Retry Wrapper ---
    @retry(
        wait=wait_exponential(multiplier=2, min=4, max=15),
        stop=stop_after_attempt(3),
        reraise=True
    )
    async def _invoke_llm_with_retries(self, arguments: KernelArguments):
        """Wraps the LLM call with exponential backoff (e.g., waits 4s, 8s, 15s)."""
        logger.debug("Sending prompt to LLM inference engine...")
        return await self.kernel.invoke_prompt(
            prompt=CODE_ANALYSIS_PROMPT,
            arguments=arguments
        )
       
       
    @timeit
    async def analyze_and_update(self, progress_callback=None):
        logger.info("--- Starting Phase 2 LLM Analysis ---")

        global_symbols = self.assembler.get_global_symbol_list()
        all_batches = self.assembler.build_module_batches()
        logger.info(f"[DIAG] all_batches count: {len(all_batches)} | modified_files: {sorted(self.modified_files)[:10]}... (total {len(self.modified_files)})")


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
        
        # Concurrency limit for local/remote LLM calls
        sem = asyncio.Semaphore(5)

        async def analyze_single_batch(file_node, batch_data):
            nonlocal completed_batches
            # --- Announce the file BEFORE waiting for the LLM! ---
            if progress_callback:
                progress_callback(
                    completed_batches, 
                    total_batches, 
                    batch_data['file_path'] # Send just the path, since app.py adds "Analyzing:"
                )
            async with sem:
                logger.info(f"Analyzing Module: {batch_data['file_path']}")
                
                # ==========================================
                # FILE-LEVEL ARCHITECTURAL SUMMARIZATION
                # ==========================================
                file_node_data = self.librarian.graph.nodes.get(file_node, {})
               
                # Only summarize if it doesn't already have one
                if not file_node_data.get("summary") or file_node_data.get("summary") == "No summary available.":
                    logger.info(f"Generating architectural summary for file: {batch_data['file_path']}")
                    
                    if batch_data["is_spaghetti"]:
                        file_prompt = f"""You are a Senior Software Architect analyzing an unstructured, procedural script.
                            Read the following Python file and write a highly concise, 2-3 sentence summary of its 
                            execution flow, core data transformations, and side-effects. 
                            Append a list of 5-7 important keywords/tags that will be useful for semantic vector search.
                            Do NOT output JSON, just the raw text summary.

                            File: {batch_data['file_path']}
                            Code:
                            {batch_data['raw_code']}"""
                    else:                   
                        # Direct, simple prompt for the file overview (Cleaned up for IDE compatibility)
                        file_prompt = f"""You are a Senior Software Architect. Read the following Python file and write
                        a highly concise, 2-3 sentence summary of its overarching purpose, what it is responsible for,
                        and its role in the broader architecture. Do NOT output JSON, just the raw text summary.

                        File: {batch_data['file_path']}
                        Code:
                        {batch_data['raw_code']}
                    """
                    try:
                        # Execute Inference for the File summary
                        file_result = await self.kernel.invoke_prompt(prompt=file_prompt)
                       
                        # Save the generated text directly to the file node in the graph
                        self.librarian.graph.nodes[file_node]["summary"] = str(file_result).strip()
                        logger.debug(f"File summary successfully generated for {file_node}")
                       
                    except Exception as e:
                        logger.warning(f"Could not generate summary for file {batch_data['file_path']}: {e}")

                # ==========================================
                # FUNCTIONS/CLASSES EXTRACTION
                # ==========================================
                target_node_ids = batch_data["contained_nodes"]
                if target_node_ids:
                    arguments = KernelArguments(
                        target_nodes=json.dumps(
                            target_node_ids,
                            indent=2
                        ),
                        global_symbol_list=json.dumps(
                            global_symbols,
                            indent=2
                        ),
                        raw_code=batch_data["raw_code"],
                        settings=OpenAIChatPromptExecutionSettings(max_tokens=8192)
                    )

                    try:
                        # 1. Execute Inference for Functions/Classes
                        result = await self._invoke_llm_with_retries(
                            arguments
                        )

                        raw_response = self._clean_json_response(
                            str(result)
                        )

                        # 2. Validate Schema
                        parsed_data = (
                            ModuleAnalysis
                            .model_validate_json(raw_response)
                        )

                        logger.info(
                            f"Successfully parsed "
                            f"{len(parsed_data.analyzed_nodes)} nodes for {batch_data['file_path']}."
                        )

                        # 3. Inject Intelligence
                        processed_nodes = set() # Track what the LLM actually returns
                        
                        for node_data in parsed_data.analyzed_nodes:
                            node_id = node_data.node_id
                            processed_nodes.add(node_id) # Log it as processed
                            
                            if node_id in self.librarian.graph:
                                self.librarian.graph.nodes[node_id]["summary"] = node_data.summary
                                self.librarian.graph.nodes[node_id]["analysis_status"] = "complete"

                            for edge in node_data.dependencies:
                                target_id = edge.target_id
                                if target_id in self.librarian.graph:
                                    self.librarian.graph.add_edge(
                                        node_id, target_id, relation=edge.relation
                                    )

                        # --- Catch LLM Laziness/Omissions ---
                        omitted_nodes = set(target_node_ids) - processed_nodes
                        for missing_id in omitted_nodes:
                            if missing_id in self.librarian.graph:
                                # Mark omitted nodes as failed so they are retried next time
                                self.librarian.graph.nodes[missing_id]["analysis_status"] = "failed_validation"
                                logger.warning(f"LLM omitted {missing_id}. Marked for retry.")
                        

                        # Persist successful module safely in helper thread behind the lock
                        async with self.save_lock:
                            await asyncio.to_thread(self.librarian.save_graph)

                    except ValidationError as e:
                        logger.error(
                            f"Schema Validation Error on "
                            f"{batch_data['file_path']}: {e}"
                        )

                        for node_id in target_node_ids:
                            if node_id in self.librarian.graph:
                               self.librarian.graph.nodes[node_id][
                                    "analysis_status"
                                ] = "failed_validation"

                        async with self.save_lock:
                            await asyncio.to_thread(self.librarian.save_graph)

                    except Exception as e:
                        logger.error(
                            f"Execution Error on "
                            f"{batch_data['file_path']}: {e}"
                        )

                        for node_id in target_node_ids:
                            if node_id in self.librarian.graph:
                                self.librarian.graph.nodes[node_id][
                                    "analysis_status"
                                ] = "failed_runtime"

                        async with self.save_lock:
                            await asyncio.to_thread(self.librarian.save_graph)
                        raise
                else:
                    # If file has no contained functions/classes, save file summary status
                    async with self.save_lock:
                        await asyncio.to_thread(self.librarian.save_graph)
                
                # Progress update callback
                async with progress_lock:
                    completed_batches += 1
                    if progress_callback:
                        progress_callback(
                            completed_batches,
                            total_batches,
                            batch_data['file_path']
                            # f"Analyzed {batch_data['file_path']}"
                        )

        # Build list of concurrent tasks
        tasks = [
            analyze_single_batch(file_node, batch_data)
            for file_node, batch_data in batches.items()
        ]
        
        # Run tasks concurrently
        await asyncio.gather(*tasks)

        logger.info("--- Final Graph Flush ---")
        async with self.save_lock:
            await asyncio.to_thread(self.librarian.save_graph)

        logger.info("Phase 2 Complete!")
