from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from agents.state import GraphRAGState

# from agents.tools import search_architecture_graph
from intelligence_layer.query_engine import GraphQueryEngine
from config import settings

# 1. Initialize your local LLM connection
# LangChain treats local llama.cpp / LM Studio servers exactly like OpenAI
llm = ChatOpenAI(
    base_url=settings.MODEL_ENDPOINT, 
    api_key="not-needed-for-local", 
    temperature=0, # Router needs to be highly deterministic
)

async def router_node(state: GraphRAGState):
    """
    The Traffic Cop: Looks at the state and decides the intent.
    """
    user_query = state["user_query"]
    chat_history = state.get("chat_history", "")
    
    # 2. Define the routing instructions
    system_prompt = """You are an elite, high-speed routing engine for a local repository AI assistant.
    Your sole job is to classify the user's latest input into one of two routing destinations:

    1. 'CONVERSATIONAL': Choose this ONLY if the user is greeting you, making small talk, or asking meta-questions about the chat history itself.
    2. 'CODEBASE': Choose this for anything else. 
    **CRITICAL OVERRIDE:** If the user asks an explanatory question like "How does X work?", "Why do we use Y?", you MUST route to CODEBASE.

    Respond with EXACTLY one word, either 'CONVERSATIONAL' or 'CODEBASE'. Do not include punctuation or markdown.
    """
    
    # 3. Build and execute the prompt chain
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("user", "Chat History:\n{chat_history}\n\nLatest Input: {user_query}")
    ])
    
    # The LangChain "|" syntax binds the prompt to the LLM
    chain = prompt | llm 
    
    try:
        response = await chain.ainvoke({"chat_history": chat_history, "user_query": user_query})
        decision_text = response.content.strip().upper()
        
        intent = "CONVERSATIONAL" if "CONVERSATIONAL" in decision_text else "CODEBASE"
        
    except Exception as e:
        print(f"Routing failed, defaulting to CODEBASE. Error: {e}")
        intent = "CODEBASE"
        
    # 4. Write back to the whiteboard!
    # LangGraph will automatically take this dictionary and update state["intent"]
    return {"intent": intent}


async def graph_agent_node(state: GraphRAGState):
    """
    The Architect: Directly triggers the vector/graph database 
    and writes the structural context to the whiteboard.
    """
    repo_name = state["repo_name"]
    target_path = state["target_repo_path"]
    user_query = state["user_query"]
    chat_history = state.get("chat_history", "")
    
    # Instantiate the engine dynamically for this specific request
    engine = GraphQueryEngine(repo_name=repo_name, target_repo_path=target_path)
    
    # Execute the bulletproof search
    context = await engine._build_context_payload(
        user_query=user_query, 
        chat_history=chat_history
    )
    # Write it to the whiteboard! 
    # Because we used operator.add in the State, this safely appends to the list.
    return {"structural_context": [context]}


async def synthesizer_node(state: GraphRAGState):
    """
    The Writer: Reads the whiteboard context and drafts the final markdown answer.
    """
    user_query = state["user_query"]
    
    # Pull all context written by any agents on the whiteboard
    structural = "\n\n".join(state.get("structural_context", []))
    temporal = "\n\n".join(state.get("temporal_context", [])) # Empty for now!
    
    combined_context = f"--- STRUCTURAL CONTEXT ---\n{structural}\n\n--- TEMPORAL CONTEXT ---\n{temporal}"
    
    system_prompt = """You are an elite Staff Software Engineer assisting a teammate with their codebase. 
    Use the provided Context to answer their question. 
    
    RULES:
    - Be concise, direct, and highly technical.
    - If the context contains raw source code, format your code snippets beautifully.
    - If the context does not contain the answer, politely state that the information is missing. Do not guess.
    """
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("user", "Context:\n{context}\n\nUser Question: {question}")
    ])
    
    # Bind the prompt to the global 'llm' we defined at the top of the file
    chain = prompt | llm 
    
    # Generate the final answer
    response = await chain.ainvoke({
        "context": combined_context, 
        "question": user_query
    })
    
    # Write the final answer to the whiteboard
    return {"final_response": response.content}

async def conversational_node(state: GraphRAGState):
    """Handles pure small talk, bypassing the codebase completely."""
    user_query = state["user_query"]
    chat_history = state.get("chat_history", "")
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a friendly AI assistant. Use the chat history to respond to the user naturally."),
        ("user", "Chat History:\n{chat_history}\n\nUser: {user_query}")
    ])
    chain = prompt | llm 
    response = await chain.ainvoke({"chat_history": chat_history, "user_query": user_query})
    
    return {"final_response": response.content}