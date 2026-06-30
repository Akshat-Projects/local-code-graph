"""
Defines Pydantic data schemas representing structural LLM extraction schemas
for modules, classes, functions, and relational linkages.
"""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from typing import List, Literal

class DependencyEdge(BaseModel):
    target_id: str = Field(
        ..., 
        description="Exact string matched from GLOBAL SYMBOL LIST. Ignore if not in list."
    )
    relation: Literal["calls", "instantiates", "inherits"] = Field(
        ..., 
        description="The strict categorization of the dependency."
    )
    confidence: Literal["EXTRACTED", "INFERRED"] = Field(
        "INFERRED",
        description="Confidence classification of the relationship"
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score from 0.0 to 1.0"
    )

class NodeAnalysis(BaseModel):
    node_id: str = Field(
        ..., 
        description="Exact string matched from TARGET NODES."
    )
    summary: str = Field(
        ..., 
        description="Concise 1-2 sentence technical summary of execution flow and data shapes."
    )
    dependencies: List[DependencyEdge] = Field(
        default_factory=list,
        description="List of explicitly identified structural dependencies."
    )

class ModuleAnalysis(BaseModel):
    analyzed_nodes: List[NodeAnalysis] = Field(
        ...,
        description="The array of analyzed functions and classes for the module."
    )


class ASTSearchRequest(BaseModel):
    repo_name: str
    target_path: str
    query_type: str  # "graph" or "tree-sitter"
    filters: Optional[Dict[str, Any]] = None
    pattern: Optional[str] = None
    language_ext: Optional[str] = None