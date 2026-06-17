import os
import json
import numpy as np
import faiss
import bm25s
from llama_cpp import Llama
from typing import List, Dict, Tuple
from utils.logger import get_logger

logger = get_logger()

class HybridVectorStore:
    def __init__(self, repo_name: str, persist_directory: str = "./data/vector_store"):
        self.repo_name = repo_name
        self.persist_dir = os.path.join(persist_directory, repo_name)
        os.makedirs(self.persist_dir, exist_ok=True)
        
        logger.info("Pulling EmbeddingGemma-300m GGUF (~300MB)...")

        # 1 & 2. Download and Initialize the lightweight C++ backend directly
        self.encoder = Llama.from_pretrained(
            repo_id="ggml-org/embeddinggemma-300M-GGUF",
            filename="embeddinggemma-300M-Q8_0.gguf",
            embedding=True, # CRITICAL: Tells llama.cpp to return vectors, not text
            n_ctx=2048,
            verbose=False
        )
        
        # 3. Our chosen Matryoshka dimension
        self.dimension = 256 
        
        self.faiss_path = os.path.join(self.persist_dir, "dense.index")
        self.metadata_path = os.path.join(self.persist_dir, "metadata.json")
        self.bm25_dir = os.path.join(self.persist_dir, "bm25")
        
        self.index = None          
        self.bm25_retriever = None 
        self.metadata = []         
        
        self._load_indices()

    def _load_indices(self):
        """Loads FAISS, BM25, and Metadata from disk if they exist."""
        if os.path.exists(self.faiss_path) and os.path.exists(self.metadata_path):
            self.index = faiss.read_index(self.faiss_path)
            with open(self.metadata_path, "r") as f:
                self.metadata = json.load(f)
            logger.info(f"Loaded FAISS index with {self.index.ntotal} vectors.")
        else:
            # Create an L2 distance FAISS index
            self.index = faiss.IndexFlatL2(self.dimension)
            logger.info("Initialized empty FAISS index.")
            
        if os.path.exists(self.bm25_dir):
            try:
                self.bm25_retriever = bm25s.BM25.load(self.bm25_dir, load_corpus=True)
                logger.info("Loaded BM25 sparse index.")
            except Exception as e:
                logger.warning(f"Failed to load BM25, will rebuild on next upsert: {e}")


    def _reciprocal_rank_fusion(self, dense_results, sparse_results, k=60) -> List[Tuple[str, float]]:
        """
        The mathematical heart of Hybrid Search.
        Fuses ranks from two separate lists. High rank in both = top result.
        """
        fused_scores = {}
        
        # Score Dense Results (rank is the index + 1)
        for rank, node_id in enumerate(dense_results):
            fused_scores[node_id] = fused_scores.get(node_id, 0.0) + (1.0 / (k + rank + 1))
            
        # Score Sparse Results
        for rank, node_id in enumerate(sparse_results):
            fused_scores[node_id] = fused_scores.get(node_id, 0.0) + (1.0 / (k + rank + 1))
            
        # Sort by fused score descending
        sorted_fused = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_fused

    def build_indexes(self, nodes_data: List[Dict]):
        if not nodes_data:
            return
            
        self.metadata = []
        texts_for_bm25 = []
        dense_documents = []
        
        for data in nodes_data:
            summary = data.get("summary", "")
            if not summary or summary == "No summary available.":
                continue
                
            self.metadata.append({"node_id": data["node_id"]})
            texts_for_bm25.append(summary)
            
            # Asymmetric Document Format
            formatted_doc = f"title: {data['node_id']} | text: {summary}"
            dense_documents.append(formatted_doc)
            
        if not dense_documents:
            return

        # --- THE LITE-WEIGHT ENCODE ---
        response = self.encoder.create_embedding(dense_documents)
        
        # Extract the native 768-dimension vectors into a float32 array
        embeddings = np.array([item["embedding"] for item in response["data"]], dtype=np.float32)

        # --- MANUAL MATRYOSHKA TRUNCATION ---
        # We simply chop off the end of the array to get our 256 dimensions!
        embeddings = embeddings[:, :self.dimension] 
        embeddings = np.ascontiguousarray(embeddings[:, :self.dimension], dtype=np.float32)
        
        faiss.normalize_L2(embeddings)
        self.index = faiss.IndexFlatL2(self.dimension)
        self.index.add(embeddings)
        
        faiss.write_index(self.index, self.faiss_path)
        with open(self.metadata_path, "w") as f:
            json.dump(self.metadata, f)
            
        corpus_tokens = bm25s.tokenize(texts_for_bm25)
        self.bm25_retriever = bm25s.BM25()
        self.bm25_retriever.index(corpus_tokens)
        self.bm25_retriever.save(self.bm25_dir, corpus=texts_for_bm25)
        
        
    def search(self, query: str, top_k: int = 15) -> List[str]:
        if not self.metadata:
            return []

        # Asymmetric Query Format
        formatted_query = f"task: search result | query: {query}"
        
        # Run inference via llama.cpp
        response = self.encoder.create_embedding([formatted_query])
        query_vector = np.array([response["data"][0]["embedding"]], dtype=np.float32)
        
        # --- MANUAL MATRYOSHKA TRUNCATION ---
        query_vector = np.ascontiguousarray(query_vector[:, :self.dimension], dtype=np.float32)
        faiss.normalize_L2(query_vector)
        
        # 🚀 THE FIX: Massively expand the pre-fusion candidate pool
        # We fetch a large pool so RRF has enough deep data to find the overlaps
        fetch_k = min(top_k * 10, len(self.metadata)) 
        
        _, dense_indices = self.index.search(query_vector, fetch_k)
        
        dense_node_ids = []
        for idx in dense_indices[0]:
            if idx != -1 and idx < len(self.metadata):
                dense_node_ids.append(self.metadata[idx]["node_id"])

        # --- 2. Sparse Search (BM25) ---
        sparse_node_ids = []
        if self.bm25_retriever:
            query_tokens = bm25s.tokenize([query])
            sparse_indices, _ = self.bm25_retriever.retrieve(query_tokens, k=fetch_k)
            
            for item in sparse_indices[0]:
                idx = item["id"] if isinstance(item, dict) else getattr(item, "id", item)
                if isinstance(idx, int) and idx < len(self.metadata):
                    sparse_node_ids.append(self.metadata[idx]["node_id"])

        # 3. Fuse the massive lists using mathematical rank overlap
        fused_results = self._reciprocal_rank_fusion(dense_node_ids, sparse_node_ids)
        
        # 4. Return only the highly-vetted top_k request
        return [node_id for node_id, score in fused_results[:top_k]]

    # def search(self, query: str, top_k: int = 5) -> List[str]:
    #     if not self.metadata:
    #         return []

    #     # Asymmetric Query Format
    #     formatted_query = f"task: search result | query: {query}"
        
    #     # Run inference via llama.cpp
    #     response = self.encoder.create_embedding([formatted_query])
    #     query_vector = np.array([response["data"][0]["embedding"]], dtype=np.float32)
        
    #     # --- MANUAL MATRYOSHKA TRUNCATION ---
    #     # Ensure the query vector is also C-contiguous before passing to FAISS
    #     query_vector = np.ascontiguousarray(query_vector[:, :self.dimension], dtype=np.float32)
    #     faiss.normalize_L2(query_vector)
        
    #     _, dense_indices = self.index.search(query_vector, min(top_k * 2, len(self.metadata)))
        
    #     dense_node_ids = []
    #     for idx in dense_indices[0]:
    #         if idx != -1 and idx < len(self.metadata):
    #             dense_node_ids.append(self.metadata[idx]["node_id"])

    #     # --- 2. Sparse Search (BM25) ---
    #     sparse_node_ids = []
    #     if self.bm25_retriever:
    #         query_tokens = bm25s.tokenize([query])
    #         sparse_indices, _ = self.bm25_retriever.retrieve(query_tokens, k=min(top_k * 2, len(self.metadata)))
            
    #         for item in sparse_indices[0]:
    #             # Safely extract the integer ID whether bm25s returns a dict, an object, or a raw int
    #             idx = item["id"] if isinstance(item, dict) else getattr(item, "id", item)
                
    #             # Now safely compare the integer
    #             if isinstance(idx, int) and idx < len(self.metadata):
    #                 sparse_node_ids.append(self.metadata[idx]["node_id"])

    #     fused_results = self._reciprocal_rank_fusion(dense_node_ids, sparse_node_ids)
    #     return [node_id for node_id, score in fused_results[:top_k]]