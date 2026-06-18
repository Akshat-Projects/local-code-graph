from typing import TypedDict, Annotated, List
import operator

class GraphRAGState(TypedDict):
    repo_name: str
    target_repo_path: str
    # The original question from the user
    user_query: str
    
    # The conversation history
    chat_history: str
    
    # The routing decision (e.g., 'CONVERSATIONAL' or 'CODEBASE')
    intent: str
    
    # We use Annotated and operator.add so that if multiple agents 
    # find context, they add to the list instead of overwriting each other!
    structural_context: Annotated[List[str], operator.add]
    temporal_context: Annotated[List[str], operator.add]
    
    telemetry: dict | None
    elapsed_seconds: float
    
    # The final markdown output to stream to the UI
    final_response: str