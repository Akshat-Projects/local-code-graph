from typing import Any, Mapping
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from agents.state import GraphRAGState
import langchain_openai.chat_models.base as langchain_openai_base

# from agents.tools import search_architecture_graph
from intelligence_layer.query_engine import GraphQueryEngine
from utils.helper import timeit
from config import settings
from utils.logger import get_logger

logger = get_logger()

# 1. Patch _convert_delta_to_message_chunk
if hasattr(langchain_openai_base, "_convert_delta_to_message_chunk"):
    original_convert = langchain_openai_base._convert_delta_to_message_chunk
    
    def patched_convert(_dict, default_class):
        # logger.info(f"[DIAG] patched _convert_delta_to_message_chunk fired. keys={list(_dict.keys()) if hasattr(_dict, 'keys') else type(_dict)}")
        chunk = original_convert(_dict, default_class)
        
        reasoning = None
        if hasattr(_dict, "get"):
            reasoning = _dict.get("reasoning_content")
        else:
            reasoning = getattr(_dict, "reasoning_content", None)
            
        # logger.info(f"[DIAG] reasoning_content found: {reasoning is not None}")
        if reasoning:
            chunk.additional_kwargs["reasoning_content"] = reasoning
        return chunk
        
    langchain_openai_base._convert_delta_to_message_chunk = patched_convert
    logger.info("Successfully monkeypatched langchain_openai._convert_delta_to_message_chunk")
else:
    logger.warning("Could not find _convert_delta_to_message_chunk in langchain_openai.chat_models.base")

# 2. Patch _convert_dict_to_message
if hasattr(langchain_openai_base, "_convert_dict_to_message"):
    original_convert_dict = langchain_openai_base._convert_dict_to_message
    
    def patched_convert_dict(_dict):
        # logger.info(f"[DIAG] patched _convert_dict_to_message fired. keys={list(_dict.keys()) if hasattr(_dict, 'keys') else type(_dict)}")
        message = original_convert_dict(_dict)
        reasoning = _dict.get("reasoning_content")
        if reasoning:
            message.additional_kwargs["reasoning_content"] = reasoning
        return message
        
    langchain_openai_base._convert_dict_to_message = patched_convert_dict
    logger.info("Successfully monkeypatched langchain_openai._convert_dict_to_message")
else:
    logger.warning("Could not find _convert_dict_to_message in langchain_openai.chat_models.base")

# 1. Initialize your local LLM connection
# LangChain treats local llama.cpp / LM Studio servers exactly like OpenAI
llm = ChatOpenAI(
    base_url=settings.MODEL_ENDPOINT, 
    api_key=settings.OPENAI_API_KEY, 
    temperature=0, # Router needs to be highly deterministic
    stream_usage=True
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
    **CRITICAL OVERRIDE:** If the user asks an explanatory question like "How does X work?", "Why do we use Y?", "Why this doesn't work?", you MUST route to CODEBASE.

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


@timeit(attach_as="elapsed_seconds")
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
    
    telemetry = None
    usage = getattr(response, "usage_metadata", None)
    if usage:
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        telemetry = {
            "prompt_n": input_tokens,
            "predicted_n": output_tokens,
            "total_tokens": usage.get("total_tokens", input_tokens + output_tokens),
        }
    else:
        # Fallback estimation (approx. 4 characters per token)
        input_len = len(combined_context)
        output_len = len(response.content) if response.content else 0
        prompt_tokens = max(1, input_len // 4)
        predicted_tokens = max(1, output_len // 4)
        telemetry = {
            "prompt_n": prompt_tokens,
            "predicted_n": predicted_tokens,
            "total_tokens": prompt_tokens + predicted_tokens,
        }
    
    # Write the final answer to the whiteboard
    return {"final_response": response.content, "telemetry": telemetry}

@timeit(attach_as="elapsed_seconds")
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
    
    telemetry = None
    usage = getattr(response, "usage_metadata", None)
    if usage:
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        telemetry = {
            "prompt_n": input_tokens,
            "predicted_n": output_tokens,
            "total_tokens": usage.get("total_tokens", input_tokens + output_tokens),
        }
    else:
        # Fallback estimation
        input_len = len(chat_history) + len(user_query)
        output_len = len(response.content) if response.content else 0
        prompt_tokens = max(1, input_len // 4)
        predicted_tokens = max(1, output_len // 4)
        telemetry = {
            "prompt_n": prompt_tokens,
            "predicted_n": predicted_tokens,
            "total_tokens": prompt_tokens + predicted_tokens,
        }
        
    return {"final_response": response.content, "telemetry": telemetry}