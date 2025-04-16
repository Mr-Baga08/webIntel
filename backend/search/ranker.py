import logging
from typing import List, Dict, Any
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sentence_transformers import SentenceTransformer, util

from .vector_store import get_vector_store

logger = logging.getLogger(__name__)

class Ranker:
    """
    Ranker for scoring and sorting search results by relevance.
    Combines TF-IDF keyword matching with semantic similarity.
    """
    
    def __init__(self, model_name="all-MiniLM-L6-v2"):
        """
        Initialize the ranker.
        
        Args:
            model_name: Name of the sentence transformer model to use
        """
        self.model_name = model_name
        self.vector_store = get_vector_store(model_name=model_name)
        self.tfidf = TfidfVectorizer(stop_words='english')
        
    def rank_results(self, query: str, results: List[Dict[str, Any]], 
                    hybrid_alpha: float = 0.7) -> List[Dict[str, Any]]:
        """
        Rank search results by relevance to the query.
        
        Args:
            query: Search query
            results: List of search result dictionaries
            hybrid_alpha: Weight for semantic search (vs. keyword matching)
            
        Returns:
            list: Ranked search results
        """
        if not results:
            return []
            
        # Extract texts for scoring
        texts = [result.get('text', result.get('snippet', '')) for result in results]
        
        # Combine scores from multiple methods
        semantic_scores = self._semantic_similarity(query, texts)
        keyword_scores = self._keyword_similarity(query, texts)
        
        # Calculate hybrid scores
        hybrid_scores = hybrid_alpha * np.array(semantic_scores) + (1 - hybrid_alpha) * np.array(keyword_scores)
        
        # Add scores to results
        for i, result in enumerate(results):
            result['relevance_score'] = float(hybrid_scores[i])
            result['semantic_score'] = float(semantic_scores[i])
            result['keyword_score'] = float(keyword_scores[i])
            
        # Sort by relevance score
        ranked_results = sorted(results, key=lambda x: x['relevance_score'], reverse=True)
        
        return ranked_results
        
    def _semantic_similarity(self, query: str, texts: List[str]) -> List[float]:
        """
        Calculate semantic similarity scores using sentence transformers.
        
        Args:
            query: Search query
            texts: List of texts to compare with the query
            
        Returns:
            list: Semantic similarity scores (0-1)
        """
        if not texts:
            return []
            
        # Embed query
        query_embedding = self.vector_store.embed_text(query)
        
        # Embed texts
        text_embeddings = self.vector_store.embed_batch(texts)
        
        # Calculate cosine similarities
        scores = []
        for embedding in text_embeddings:
            similarity = util.cos_sim(query_embedding, embedding)[0][0].item()
            scores.append(similarity)
            
        return scores
        
    def _keyword_similarity(self, query: str, texts: List[str]) -> List[float]:
        """
        Calculate keyword similarity scores using TF-IDF.
        
        Args:
            query: Search query
            texts: List of texts to compare with the query
            
        Returns:
            list: Keyword similarity scores (0-1)
        """
        if not texts:
            return []
            
        # Add query to corpus for vectorization
        corpus = [query] + texts
        
        try:
            # Create TF-IDF matrix
            tfidf_matrix = self.tfidf.fit_transform(corpus)
            
            # Calculate cosine similarities
            query_vector = tfidf_matrix[0:1]
            text_vectors = tfidf_matrix[1:]
            
            # Compute cosine similarity between query and each text
            scores = []
            for i in range(text_vectors.shape[0]):
                text_vector = text_vectors[i:i+1]
                similarity = (query_vector.dot(text_vector.T) / 
                             (np.sqrt(query_vector.dot(query_vector.T)) * 
                              np.sqrt(text_vector.dot(text_vector.T))))
                scores.append(similarity[0, 0])
                
            return scores
            
        except Exception as e:
            logger.error(f"Error calculating keyword similarity: {str(e)}")
            return [0.0] * len(texts)

# Helper function to rank results
def rank_search_results(query: str, results: List[Dict[str, Any]], 
                        model_name: str = "all-MiniLM-L6-v2",
                        hybrid_alpha: float = 0.7) -> List[Dict[str, Any]]:
    """
    Helper function to rank search results without creating a Ranker instance.
    
    Args:
        query: Search query
        results: List of search result dictionaries
        model_name: Name of the sentence transformer model to use
        hybrid_alpha: Weight for semantic search (vs. keyword matching)
        
    Returns:
        list: Ranked search results
    """
    ranker = Ranker(model_name=model_name)
    return ranker.rank_results(query, results, hybrid_alpha=hybrid_alpha)