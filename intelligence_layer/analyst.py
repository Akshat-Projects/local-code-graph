import os
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

        # If the file itself lacks an architectural summary, analyze it
        file_node_id = f"file::{file_path}"
        file_node_data = self.librarian.graph.nodes.get(file_node_id, {})
        if not file_node_data.get("summary") or file_node_data.get("summary") == "No summary available.":
            return True

        # Check if any node is missing intelligence
        for node_id in batch_data["contained_nodes"]:
            node_data = self.librarian.graph.nodes.get(
                node_id,
                {}
            )
            if node_data.get("analysis_status") != "complete":
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

        batches = {
            file_node: batch
            for file_node, batch in all_batches.items()
            if self._needs_analysis(batch)
        }

        if not batches:
            logger.info("No modules found to analyze. Graph is up to date.")
            return

        total_batches = len(batches)
        current = 0

        for file_node, batch_data in batches.items():
            current += 1

            if progress_callback:
                progress_callback(
                    current,
                    total_batches,
                    f"Analyzing {batch_data['file_path']}..."
                )

            logger.info(f"Analyzing Module: {batch_data['file_path']}")
           
            # ==========================================
            # NEW: FILE-LEVEL ARCHITECTURAL SUMMARIZATION
            # ==========================================
            file_node_data = self.librarian.graph.nodes.get(file_node, {})
           
            # Only summarize if it doesn't already have one
            if not file_node_data.get("summary") or file_node_data.get("summary") == "No summary available.":
                logger.info(f"Generating architectural summary for file: {batch_data['file_path']}")
               
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

            target_node_ids = batch_data["contained_nodes"]
            if not target_node_ids:
                self.librarian.save_graph()
                continue

            arguments = KernelArguments(
                target_nodes=json.dumps(
                    target_node_ids,
                    indent=2
                ),
                global_symbol_list=json.dumps(
                    global_symbols,
                    indent=2
                ),
                raw_code=batch_data["raw_code"]
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
                    f"{len(parsed_data.analyzed_nodes)} nodes."
                )

                # 3. Inject Intelligence
                for node_data in parsed_data.analyzed_nodes:

                    node_id = node_data.node_id

                    if node_id in self.librarian.graph:
                        self.librarian.graph.nodes[node_id][
                            "summary"
                        ] = node_data.summary

                        self.librarian.graph.nodes[node_id][
                            "analysis_status"
                        ] = "complete"

                    for edge in node_data.dependencies:
                        target_id = edge.target_id

                        if target_id in self.librarian.graph:
                            self.librarian.graph.add_edge(
                                node_id,
                                target_id,
                                relation=edge.relation
                            )

                            logger.debug(
                                f"Added explicit edge: "
                                f"{node_id} "
                                f"--({edge.relation})--> "
                                f"{target_id}"
                            )

                # Persist successful module immediately
                self.librarian.save_graph()

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

                self.librarian.save_graph()
                continue

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

                self.librarian.save_graph()
                raise

        logger.info("--- Final Graph Flush ---")
        self.librarian.save_graph()

        logger.info("Phase 2 Complete!")
# import os
# import json
# import asyncio
# from pydantic import ValidationError
# from semantic_kernel.functions import KernelArguments
# from tenacity import retry, wait_exponential, stop_after_attempt

# from config import settings
# # from intelligence_layer.prompts import FILE_PROMPT
# from core.librarian import Librarian
# from core.assembler import ContextAssembler
# from intelligence_layer.kernel_client import LocalKernelFactory
# from intelligence_layer.prompts import CODE_ANALYSIS_PROMPT
# from models.llm_output import ModuleAnalysis
# from utils.helper import timeit
# from utils.logger import get_logger

# logger = get_logger()

# class GraphAnalyst:
#     def __init__(self, librarian: Librarian, target_repo_path: str, modified_files: set[str] | None = None):
#         self.librarian = librarian
#         self.target_repo_path = target_repo_path
#         self.assembler = ContextAssembler(self.librarian.graph, self.target_repo_path)
#         self.kernel = LocalKernelFactory.create_kernel()
#         self.modified_files = modified_files or set()

#     def _needs_analysis(self, batch_data: dict) -> bool:
#         """
#         Analyze if:
#         1. File was modified
#         2. Any contained node is not marked complete
#         """

#         file_path = batch_data["file_path"]

#         # Modified file always needs re-analysis
#         if file_path in self.modified_files:
#             return True

#         # Check if any node is missing intelligence
#         for node_id in batch_data["contained_nodes"]:

#             node_data = self.librarian.graph.nodes.get(
#                 node_id,
#                 {}
#             )

#             # if not node_data.get("summary"):
#             #     return True
#             if node_data.get("analysis_status") != "complete":
#                 return True

#         return False
    
    
#     def _clean_json_response(self, text: str) -> str:
#         text = text.strip()
#         if text.startswith("```json"):
#             text = text[7:]
#         elif text.startswith("```"):
#             text = text[3:]
#         if text.endswith("```"):
#             text = text[:-3]
#         return text.strip()

#     # --- NEW: Tenacity Retry Wrapper ---
#     @retry(
#         wait=wait_exponential(multiplier=2, min=4, max=15), 
#         stop=stop_after_attempt(3),
#         reraise=True
#     )
#     async def _invoke_llm_with_retries(self, arguments: KernelArguments):
#         """Wraps the LLM call with exponential backoff (e.g., waits 4s, 8s, 15s)."""
#         logger.debug("Sending prompt to LLM inference engine...")
#         return await self.kernel.invoke_prompt(
#             prompt=CODE_ANALYSIS_PROMPT, 
#             arguments=arguments
#         )
        
        
#     @timeit
#     async def analyze_and_update(self, progress_callback=None):
#         logger.info("--- Starting Phase 2 LLM Analysis ---")

#         global_symbols = self.assembler.get_global_symbol_list()
#         all_batches = self.assembler.build_module_batches()

#         batches = {
#             file_node: batch
#             for file_node, batch in all_batches.items()
#             if self._needs_analysis(batch)
#         }

#         if not batches:
#             logger.info("No modules found to analyze. Graph is up to date.")
#             return

#         total_batches = len(batches)
#         current = 0

#         for file_node, batch_data in batches.items():
#             current += 1

#             if progress_callback:
#                 progress_callback(
#                     current,
#                     total_batches,
#                     f"Analyzing {batch_data['file_path']}..."
#                 )

#             logger.info(f"Analyzing Module: {batch_data['file_path']}")
            
#             # ==========================================
#             # NEW: FILE-LEVEL ARCHITECTURAL SUMMARIZATION
#             # ==========================================
#             file_node_data = self.librarian.graph.nodes.get(file_node, {})
            
#             # Only summarize if it doesn't already have one
#             if not file_node_data.get("summary") or file_node_data.get("summary") == "No summary available.":
#                 logger.info(f"Generating architectural summary for file: {batch_data['file_path']}")
                
#                 # Direct, simple prompt for the file overview (Cleaned up for IDE compatibility)
#                 file_prompt = f"""You are a Senior Software Architect. Read the following Python file and write
#                 a highly concise, 2-3 sentence summary of its overarching purpose, what it is responsible for, 
#                 and its role in the broader architecture. Do NOT output JSON, just the raw text summary.

#                 File: {batch_data['file_path']}
#                 Code:
#                 {batch_data['raw_code']}
#                 """
#                 try:
#                     # Execute Inference for the File summary
#                     file_result = await self.kernel.invoke_prompt(prompt=file_prompt)
                    
#                     # Save the generated text directly to the file node in the graph
#                     self.librarian.graph.nodes[file_node]["summary"] = str(file_result).strip()
#                     logger.debug(f"File summary successfully generated for {file_node}")
                    
#                 except Exception as e:
#                     logger.warning(f"Could not generate summary for file {batch_data['file_path']}: {e}")
#             # ==========================================

#             target_node_ids = batch_data["contained_nodes"]

#             arguments = KernelArguments(
#                 target_nodes=json.dumps(
#                     target_node_ids,
#                     indent=2
#                 ),
#                 global_symbol_list=json.dumps(
#                     global_symbols,
#                     indent=2
#                 ),
#                 raw_code=batch_data["raw_code"]
#             )

#             try:
#                 # 1. Execute Inference for Functions/Classes
#                 result = await self._invoke_llm_with_retries(
#                     arguments
#                 )

#                 raw_response = self._clean_json_response(
#                     str(result)
#                 )

#                 # 2. Validate Schema
#                 parsed_data = (
#                     ModuleAnalysis
#                     .model_validate_json(raw_response)
#                 )

#                 logger.info(
#                     f"Successfully parsed "
#                     f"{len(parsed_data.analyzed_nodes)} nodes."
#                 )

#                 # 3. Inject Intelligence
#                 for node_data in parsed_data.analyzed_nodes:

#                     node_id = node_data.node_id

#                     if node_id in self.librarian.graph:
#                         self.librarian.graph.nodes[node_id][
#                             "summary"
#                         ] = node_data.summary

#                         self.librarian.graph.nodes[node_id][
#                             "analysis_status"
#                         ] = "complete"

#                     for edge in node_data.dependencies:
#                         target_id = edge.target_id

#                         if target_id in self.librarian.graph:
#                             self.librarian.graph.add_edge(
#                                 node_id,
#                                 target_id,
#                                 relation=edge.relation
#                             )

#                             logger.debug(
#                                 f"Added explicit edge: "
#                                 f"{node_id} "
#                                 f"--({edge.relation})--> "
#                                 f"{target_id}"
#                             )

#                 # Persist successful module immediately
#                 self.librarian.save_graph()

#             except ValidationError as e:
#                 logger.error(
#                     f"Schema Validation Error on "
#                     f"{batch_data['file_path']}: {e}"
#                 )

#                 for node_id in target_node_ids:
#                     if node_id in self.librarian.graph:
#                         self.librarian.graph.nodes[node_id][
#                             "analysis_status"
#                         ] = "failed_validation"

#                 self.librarian.save_graph()
#                 continue

#             except Exception as e:
#                 logger.error(
#                     f"Execution Error on "
#                     f"{batch_data['file_path']}: {e}"
#                 )

#                 for node_id in target_node_ids:
#                     if node_id in self.librarian.graph:
#                         self.librarian.graph.nodes[node_id][
#                             "analysis_status"
#                         ] = "failed_runtime"

#                 self.librarian.save_graph()
#                 raise

#         logger.info("--- Final Graph Flush ---")
#         self.librarian.save_graph()

#         logger.info("Phase 2 Complete!")
        
   
# # ---------------------------------------------------------
# # Test Runner
# # ---------------------------------------------------------
# if __name__ == "__main__":
#     from config import settings
    
#     async def run_phase_2():
#         logger.debug(f"--- DEBUG DIAGNOSTICS ---")
#         logger.debug(f"Target Repo Name: {settings.REPO_NAME}")
#         logger.debug(f"Target Source Code Path: {settings.TARGET_REPO_PATH}")
        
#         # Load the graph generated from Phase 1
#         librarian = Librarian(
#             workspace_root=".", 
#             repo_name=settings.REPO_NAME
#         )
        
#         logger.debug(f"Graph DB Path: {os.path.abspath(librarian.graph_path)}")
#         logger.debug(f"Nodes loaded in memory: {librarian.graph.number_of_nodes()}")
#         logger.debug(f"-------------------------\n")
        
#         if librarian.graph.number_of_nodes() == 0:
#             logger.warning("ERROR: Graph is empty. You must run Phase 1 (run_test.py) first.")
#             return
        
#         analyst = GraphAnalyst(
#             librarian=librarian,
#             target_repo_path=settings.TARGET_REPO_PATH
#         )
        
#         await analyst.analyze_and_update()
        
#     asyncio.run(run_phase_2())