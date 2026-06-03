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
You are a Senior Principal Software Engineer. You have been given a semantic graph map and the raw source code of the most relevant files in the user's repository.

Context Information:
{{$graph_context}}

User Query:
{{$user_query}}

Instructions:
1. Act as an active developer, not just a documentation reader.
2. If the user asks for existing code, find it in the "Relevant Raw Source Code" section and provide it in markdown blocks.
3. If the user asks you to write NEW code, modify existing code, or implement a requirement, DO IT. Use the provided context to ensure your new code seamlessly integrates with their existing architecture.
4. Always explain your logic briefly before writing the code. Be concise.
"""

# FILE_PROMPT = f"""
# You are a Senior Software Architect. Read the following Python file and write
#                 a highly concise, 2-3 sentence summary of its overarching purpose, what it is responsible for, 
#                 and its role in the broader architecture. Do NOT output JSON, just the raw text summary.

# File: {batch_data['file_path']}
# Code:
# {batch_data['raw_code']}
# """