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