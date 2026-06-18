from langgraph.graph import StateGraph, END
from agents.state import GraphRAGState
from agents.nodes import router_node, graph_agent_node, synthesizer_node, conversational_node

# --- THE ROUTING LOGIC ---
def route_query(state: GraphRAGState):
    """Reads the whiteboard to decide which arrow to follow out of the Router."""
    if state.get("intent") == "CONVERSATIONAL":
        return "route_to_chat"
    return "route_to_codebase"

# 1. Bring in the Whiteboard
workflow = StateGraph(GraphRAGState)

# 2. Assign the Seats (Add Nodes)
workflow.add_node("router", router_node)
workflow.add_node("conversational", conversational_node)
workflow.add_node("graph_agent", graph_agent_node)
workflow.add_node("synthesizer", synthesizer_node)

# 3. Draw the Flowchart (Add Edges)
# Everyone always starts at the Router
workflow.set_entry_point("router")

# The Router has a fork in the road based on our `route_query` logic
workflow.add_conditional_edges(
    "router",
    route_query,
    {
        "route_to_chat": "conversational",
        "route_to_codebase": "graph_agent"
    }
)

# After the Graph Agent fetches data, it hands off to the Synthesizer
workflow.add_edge("graph_agent", "synthesizer")

# When the Synthesizer or Conversational node finishes, the process ends!
workflow.add_edge("synthesizer", END)
workflow.add_edge("conversational", END)

# 4. Compile the Application
agent_app = workflow.compile()