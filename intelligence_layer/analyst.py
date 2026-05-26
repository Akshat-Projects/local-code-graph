import os
import json
import asyncio
from pydantic import ValidationError
from semantic_kernel.functions import KernelArguments
from tenacity import retry, wait_exponential, stop_after_attempt

from config import settings
from core.librarian import Librarian
from core.assembler import ContextAssembler
from intelligence_layer.kernel_client import LocalKernelFactory
from intelligence_layer.prompts import CODE_ANALYSIS_PROMPT
from models.llm_output import ModuleAnalysis
from utils.helper import timeit
from utils.logger import get_logger

logger = get_logger()

class GraphAnalyst:
    def __init__(self, librarian: Librarian, target_repo_path: str):
        self.librarian = librarian
        self.target_repo_path = target_repo_path
        self.assembler = ContextAssembler(self.librarian.graph, self.target_repo_path)
        self.kernel = LocalKernelFactory.create_kernel()

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
    async def analyze_and_update(self):
        logger.info("--- Starting Phase 2 LLM Analysis ---")
        global_symbols = self.assembler.get_global_symbol_list()
        batches = self.assembler.build_module_batches()
        
        if not batches:
            logger.info("No modules found to analyze. Graph is up to date.")
            return

        for file_node, batch_data in batches.items():
            logger.info(f"Analyzing Module: {batch_data['file_path']}")
            
            target_node_ids = batch_data["contained_nodes"]
            arguments = KernelArguments(
                target_nodes=json.dumps(target_node_ids, indent=2),
                global_symbol_list=json.dumps(global_symbols, indent=2),
                raw_code=batch_data["raw_code"]
            )
            
            try:
                # 1. Execute Inference Loop (Now protected by Tenacity)
                result = await self._invoke_llm_with_retries(arguments)
                raw_response = self._clean_json_response(str(result))
                
                # 2. Enforce Pydantic Schema
                parsed_data = ModuleAnalysis.model_validate_json(raw_response)
                logger.info(f"Successfully parsed {len(parsed_data.analyzed_nodes)} nodes.")
                
                # 3. Inject Intelligence into NetworkX
                for node_data in parsed_data.analyzed_nodes:
                    node_id = node_data.node_id
                    if node_id in self.librarian.graph:
                        self.librarian.graph.nodes[node_id]["summary"] = node_data.summary
                    
                    for edge in node_data.dependencies:
                        target_id = edge.target_id
                        if target_id in self.librarian.graph:
                            self.librarian.graph.add_edge(node_id, target_id, relation=edge.relation)
                            logger.debug(f"Added explicit edge: {node_id} --({edge.relation})--> {target_id}")

            except ValidationError as e:
                logger.error(f"Schema Validation Error on {batch_data['file_path']}: {e}")
                raise Exception(f"LLM Output Schema Validation Failed: {e}") 
            except Exception as e:
                logger.error(f"Execution Error on {batch_data['file_path']}: {e}")
                # We raise the exception so ingest.py knows the pipeline completely failed!
                raise e
                
        # 4. Save the enriched graph ONLY if no exceptions were raised
        logger.info("--- Saving Enriched Graph ---")
        self.librarian.save_graph()
        logger.info("Phase 2 Complete!")
        
# import json
# import asyncio
# from pydantic import ValidationError
# import os
# from utils.logger import get_logger

# from semantic_kernel.functions import KernelArguments

# from core.librarian import Librarian
# from core.assembler import ContextAssembler
# from intelligence_layer.kernel_client import LocalKernelFactory
# from intelligence_layer.prompts import CODE_ANALYSIS_PROMPT
# from models.llm_output import ModuleAnalysis

# logger = get_logger()

# class GraphAnalyst:
#     def __init__(self, librarian: Librarian, target_repo_path: str):
#         """
#         Orchestrates the LLM analysis loop, enriching the structural graph
#         with semantic summaries and implicit execution edges.
#         """
#         self.librarian = librarian
#         self.target_repo_path = target_repo_path
#         self.assembler = ContextAssembler(self.librarian.graph, self.target_repo_path)
#         self.kernel = LocalKernelFactory.create_kernel()

#     def _clean_json_response(self, text: str) -> str:
#         """
#         Safety net: Local LLMs sometimes wrap JSON in markdown ticks 
#         despite strict prompt instructions. This strips them.
#         """
#         text = text.strip()
#         if text.startswith("```json"):
#             text = text[7:]
#         elif text.startswith("```"):
#             text = text[3:]
            
#         if text.endswith("```"):
#             text = text[:-3]
            
#         return text.strip()

#     async def analyze_and_update(self):
#         """
#         Executes the batch processing loop.
#         """
#         logger.info("--- Starting Phase 2 LLM Analysis ---")
#         global_symbols = self.assembler.get_global_symbol_list()
#         batches = self.assembler.build_module_batches()
        
#         if not batches:
#             logger.warning("No modules found to analyze.")
#             return

#         for file_node, batch_data in batches.items():
#             logger.info(f"\nAnalyzing Module: {batch_data['file_path']}")
            
#             # The exact function/class IDs we want the LLM to focus on
#             target_node_ids = batch_data["contained_nodes"]
            
#             # Prepare arguments for Semantic Kernel
#             arguments = KernelArguments(
#                 target_nodes=json.dumps(target_node_ids, indent=2),
#                 global_symbol_list=json.dumps(global_symbols, indent=2),
#                 raw_code=batch_data["raw_code"]
#             )
            
#             try:
#                 # 1. Execute Inference Loop
#                 result = await self.kernel.invoke_prompt(
#                     prompt=CODE_ANALYSIS_PROMPT, 
#                     arguments=arguments
#                 )
                
#                 raw_response = self._clean_json_response(str(result))
                
#                 # 2. Enforce Pydantic Schema
#                 parsed_data = ModuleAnalysis.model_validate_json(raw_response)
#                 logger.info(f" Successfully parsed {len(parsed_data.analyzed_nodes)} nodes.")
                
#                 # 3. Inject Intelligence into NetworkX
#                 for node_data in parsed_data.analyzed_nodes:
#                     node_id = node_data.node_id
                    
#                     # Update the node's summary
#                     if node_id in self.librarian.graph:
#                         self.librarian.graph.nodes[node_id]["summary"] = node_data.summary
                    
#                     # Inject explicit execution edges
#                     for edge in node_data.dependencies:
#                         target_id = edge.target_id
                        
#                         # Double-check it exists in the graph to prevent dead links
#                         if target_id in self.librarian.graph:
#                             self.librarian.graph.add_edge(
#                                 node_id, 
#                                 target_id, 
#                                 relation=edge.relation
#                             )
#                             logger.info(f"  -> Added edge: {node_id} --({edge.relation})--> {target_id}")

#             except ValidationError as e:
#                 logger.error(f" Schema Validation Error on {batch_data['file_path']}: {e}")
#             except Exception as e:
#                 logger.error(f" Execution Error on {batch_data['file_path']}: {e}")
                
#         # 4. Save the enriched graph
#         logger.info("\n--- Saving Enriched Graph ---")
#         self.librarian.save_graph()
#         logger.info("Phase 2 Complete!")

# ---------------------------------------------------------
# Test Runner
# ---------------------------------------------------------
if __name__ == "__main__":
    from config import settings
    
    async def run_phase_2():
        logger.debug(f"--- DEBUG DIAGNOSTICS ---")
        logger.debug(f"Target Repo Name: {settings.REPO_NAME}")
        logger.debug(f"Target Source Code Path: {settings.TARGET_REPO_PATH}")
        
        # Load the graph generated from Phase 1
        librarian = Librarian(
            workspace_root=".", 
            repo_name=settings.REPO_NAME
        )
        
        logger.debug(f"Graph DB Path: {os.path.abspath(librarian.graph_path)}")
        logger.debug(f"Nodes loaded in memory: {librarian.graph.number_of_nodes()}")
        logger.debug(f"-------------------------\n")
        
        if librarian.graph.number_of_nodes() == 0:
            logger.warning("ERROR: Graph is empty. You must run Phase 1 (run_test.py) first.")
            return
        
        analyst = GraphAnalyst(
            librarian=librarian,
            target_repo_path=settings.TARGET_REPO_PATH
        )
        
        await analyst.analyze_and_update()
        
    asyncio.run(run_phase_2())