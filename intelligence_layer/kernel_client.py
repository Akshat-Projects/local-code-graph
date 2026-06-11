import os
from openai import AsyncOpenAI
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion
from semantic_kernel.functions import kernel_function
from typing import Annotated

from config import settings
from utils.logger import get_logger

logger = get_logger()

class LocalKernelFactory:
    """
    Initializes a Semantic Kernel instance configured to route all 
    inference requests to the local llama-server instance.
    """
    
    @staticmethod
    def create_kernel() -> Kernel:
        # Initialize the core kernel
        kernel = Kernel()
        
        # Configure the connector to point to llama-server
        # llama-server runs on port 8080 by default and mimics the OpenAI v1 API
        local_endpoint = settings.LOCAL_ENDPOINT
        
        # llama-server doesn't require a real API key, but the OpenAI SDK 
        # requires the variable to be populated with something.
        # dummy_api_key = settings.OPENAI_API_KEY
        
        # Define the AI Service
        # We use the generic OpenAIChatCompletion but rewrite its destination
        client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.LOCAL_ENDPOINT,
        )

        chat_service = OpenAIChatCompletion(
            ai_model_id=settings.AI_MODEL_ID,
            async_client=client,
        )
        # chat_service = OpenAIChatCompletion(
        #     ai_model_id=settings.AI_MODEL_ID, # The name doesn't strictly matter for llama-server, but good for logs
        #     api_key=dummy_api_key,
        #     base_url=local_endpoint
        # )
        
        # Register the local service with Semantic Kernel as the default text generator
        kernel.add_service(chat_service)
        
        logger.info(f"Semantic Kernel initialized. Routing to local engine at {local_endpoint}")
        return kernel
    
    


class CodebaseSearchPlugin:
    def __init__(self, engine_instance):
        self.engine = engine_instance

    @kernel_function(
        name="search_codebase",
        description="""Searches the local codebase graph for architectural context, code snippets, and structural relationships.
                        ALWAYS use this tool if the user asks about how the code works, where things are, or specific algorithms."""
    )
    async def search_codebase(
        self,
        query: Annotated[str, "The search query to find relevant code context in the codebase."]
    ) -> Annotated[str, "The retrieved codebase context"]:
        
        logger.info(f"[AGENT] LLM autonomously called search_codebase for: '{query}'")
        # Call your existing powerhouse function!
        return await self.engine._build_context_payload(user_query=query, chat_history="")

# Quick test execution
if __name__ == "__main__":
    import asyncio
    
    async def test_connection():
        logger.info(f"Starting test for App: {settings.APP_NAME}")
        kernel = LocalKernelFactory.create_kernel()
        
        # Simple health check prompt
        prompt = "Hello! Are you running locally?"
        try:
            response = await kernel.invoke_prompt(prompt)
            logger.info(f"Gemma 4 Response: {response}")
        except Exception as e:
            logger.error(f"Connection failed: {e}\nIs llama-server running on port 8080?")
            
    asyncio.run(test_connection())