import json
from models.llm_output import ModuleAnalysis

# Automatically generate the JSON Schema from Pydantic
EXPECTED_SCHEMA = json.dumps(ModuleAnalysis.model_json_schema(), indent=2)

CODE_ANALYSIS_PROMPT = f"""
You are an expert static analysis engine mapping a deep learning Python codebase.
Read the provided source code module, summarize its operational logic, and extract explicit structural dependencies.

### INPUTS PROVIDED:
1. TARGET NODES: The specific functions/classes inside this file to analyze.
2. GLOBAL SYMBOL LIST: Every valid internal node ID in the repository.
3. RAW CODE: The Python source code.

### INSTRUCTIONS:
1. SUMMARY: Write a concise `summary` for each target node. Focus on execution flow, tensor shapes, and inputs/outputs.
2. DEPENDENCIES: Cross-reference dependencies against the GLOBAL SYMBOL LIST. 
   - If a dependency is in the list, extract it.
   - If it is NOT in the list (e.g., `os`, `numpy`), IGNORE IT.
3. RELATION TYPE: Strictly categorize as `calls`, `instantiates`, or `inherits`.

### OUTPUT FORMAT:
You must output ONLY valid, parsable JSON matching the following schema. Do not use markdown formatting ticks.

{EXPECTED_SCHEMA}

---
### DYNAMIC PAYLOAD:
TARGET NODES: 
{{{{$target_nodes}}}}

GLOBAL SYMBOL LIST: 
{{{{$global_symbol_list}}}}

RAW CODE:
{{{{$raw_code}}}}
"""


GRAPH_RAG_PROMPT = """
You are an expert software architect and senior engineer.
You are helping a developer understand a codebase by answering questions based on a provided Semantic Graph Map.

### SEMANTIC GRAPH MAP:
{{$graph_context}}

### USER QUESTION:
{{$user_query}}

### INSTRUCTIONS:
1. Answer the user's question using ONLY the provided semantic graph map.
2. If the answer cannot be confidently derived from the context, state clearly that the information is not present in the current graph.
3. Be highly specific. Reference exact class names, function names, and file paths when explaining how data flows or how components interact.
4. Keep your explanation concise and technical.
"""