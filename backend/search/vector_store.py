import logging
import os
import numpy as np
import faiss
import pickle
from typing import List, Dict, Any, Optional, Tuple
from sentence_transformers import SentenceTransformer
import threading

logger = logging.getLogger(__name__)

class VectorStore:
    """
    Vector store using FAISS for efficient similarity search.
    Includes sentence transformer model for text embedding.
    """
    
    def __init__(self, model_name="all-MiniLM-L6-v2", dimension=384, index_path=None):
        """
        Initialize the vector store.
        
        Args:
            model_name: Sentence transformer model name
            dimension: Embedding dimension (must match model output)
            index_path: Path to load existing index from
        """
        self.model_name = model_name
        self.dimension = dimension
        self.index_path = index_path
        
        # Lazy-load model to save memory
        self._model = None
        self._model_lock = threading.Lock()
        
        # Initialize or load FAISS index
        if index_path and os.path.exists(index_path):
            logger.info(f"Loading FAISS index from {index_path}")
            self.index = self._load_index(index_path)
        else:
            logger.info(f"Creating new FAISS index with dimension {dimension}")
            self.index = faiss.IndexFlatL2(dimension)
            
        # Maps FAISS IDs to document IDs
        self.id_mapping = {}
        self.next_id = 0
        
        # Maps document IDs to metadata
        self.metadata = {}
        
    @property
    def model(self):
        """Lazy-load the model when first needed."""
        with self._model_lock:
            if self._model is None:
                logger.info(f"Loading sentence transformer model: {self.model_name}")
                self._model = SentenceTransformer(self.model_name)
        return self._model
        
    def embed_text(self, text: str) -> np.ndarray:
        """
        Convert text to embedding vector.
        
        Args:
            text: Text to embed
            
        Returns:
            np.ndarray: Embedding vector
        """
        if not text or len(text.strip()) == 0:
            # Return zero vector for empty text
            return np.zeros(self.dimension, dtype=np.float32)
            
        # Embed text using sentence transformer
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.astype(np.float32)
        
    def embed_batch(self, texts: List[str]) -> np.ndarray:
        """
        Convert multiple texts to embedding vectors.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            np.ndarray: Batch of embedding vectors
        """
        # Filter out empty texts
        valid_texts = [text for text in texts if text and len(text.strip()) > 0]
        
        if not valid_texts:
            # Return empty batch
            return np.zeros((0, self.dimension), dtype=np.float32)
            
        # Embed batch using sentence transformer
        embeddings = self.model.encode(valid_texts, convert_to_numpy=True)
        return embeddings.astype(np.float32)
        
    def add(self, doc_id: str, text: str, metadata: Dict[str, Any] = None) -> int:
        """
        Add a document to the vector store.
        
        Args:
            doc_id: Document ID
            text: Text to embed and store
            metadata: Optional metadata to store with the document
            
        Returns:
            int: FAISS ID
        """
        # Embed the text
        embedding = self.embed_text(text)
        
        # Reshape for FAISS
        embedding = embedding.reshape(1, -1)
        
        # Add to FAISS index
        faiss_id = self.next_id
        self.index.add(embedding)
        
        # Update mappings
        self.id_mapping[faiss_id] = doc_id
        if metadata:
            self.metadata[doc_id] = metadata
            
        self.next_id += 1
        return faiss_id
        
    def add_batch(self, doc_ids: List[str], texts: List[str], metadatas: List[Dict[str, Any]] = None) -> List[int]:
        """
        Add multiple documents to the vector store.
        
        Args:
            doc_ids: List of document IDs
            texts: List of texts to embed and store
            metadatas: Optional list of metadata dictionaries
            
        Returns:
            List[int]: List of FAISS IDs
        """
        if len(doc_ids) != len(texts):
            raise ValueError("doc_ids and texts must have the same length")
            
        if metadatas and len(metadatas) != len(doc_ids):
            raise ValueError("metadatas must have the same length as doc_ids")
            
        # Embed the texts
        embeddings = self.embed_batch(texts)
        
        # Add to FAISS index
        faiss_ids = []
        for i, embedding in enumerate(embeddings):
            # Reshape for FAISS
            embedding = embedding.reshape(1, -1)
            
            # Add to FAISS index
            faiss_id = self.next_id
            self.index.add(embedding)
            
            # Update mappings
            self.id_mapping[faiss_id] = doc_ids[i]
            if metadatas:
                self.metadata[doc_ids[i]] = metadatas[i]
                
            faiss_ids.append(faiss_id)
            self.next_id += 1
            
        return faiss_ids
        
    def search(self, query_text: str, k: int = 5) -> List[Dict[str, Any]]:
        """
        Search for similar documents.
        
        Args:
            query_text: Query text
            k: Number of results to return
            
        Returns:
            List[Dict]: Search results with document IDs, scores, and metadata
        """
        # Embed the query
        query_embedding = self.embed_text(query_text)
        
        # Reshape for FAISS
        query_embedding = query_embedding.reshape(1, -1)
        
        # Search FAISS index
        distances, indices = self.index.search(query_embedding, k)
        
        # Format results
        results = []
        for i, idx in enumerate(indices[0]):
            if idx != -1 and idx in self.id_mapping:  # -1 means no result
                doc_id = self.id_mapping[idx]
                results.append({
                    'doc_id': doc_id,
                    'score': float(1.0 / (1.0 + distances[0][i])),  # Convert distance to similarity score
                    'metadata': self.metadata.get(doc_id, {})
                })
                
        return results
        
    def save(self, path: str = None) -> str:
        """
        Save the vector store to disk.
        
        Args:
            path: Path to save to, defaults to self.index_path
            
        Returns:
            str: Path where the index was saved
        """
        save_path = path or self.index_path
        
        if not save_path:
            raise ValueError("No save path specified")
            
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
        # Save FAISS index
        faiss.write_index(self.index, f"{save_path}.faiss")
        
        # Save mappings
        with open(f"{save_path}.mappings", 'wb') as f:
            pickle.dump({
                'id_mapping': self.id_mapping,
                'metadata': self.metadata,
                'next_id': self.next_id
            }, f)
            
        logger.info(f"Saved vector store to {save_path}")
        return save_path
        
    def _load_index(self, path: str) -> faiss.Index:
        """
        Load FAISS index and mappings from disk.
        
        Args:
            path: Path to load from
            
        Returns:
            faiss.Index: Loaded index
        """
        # Load FAISS index
        index = faiss.read_index(f"{path}.faiss")
        
        # Load mappings
        try:
            with open(f"{path}.mappings", 'rb') as f:
                mappings = pickle.load(f)
                self.id_mapping = mappings['id_mapping']
                self.metadata = mappings['metadata']
                self.next_id = mappings['next_id']
        except Exception as e:
            logger.warning(f"Failed to load mappings: {str(e)}")
            
        return index
        
    def clear(self):
        """Clear the vector store."""
        self.index = faiss.IndexFlatL2(self.dimension)
        self.id_mapping = {}
        self.metadata = {}
        self.next_id = 0

# Singleton instance for reuse
_vector_store = None

def get_vector_store(model_name="all-MiniLM-L6-v2", dimension=384, index_path=None):
    """Get the singleton vector store instance."""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore(model_name=model_name, dimension=dimension, index_path=index_path)
    return _vector_store