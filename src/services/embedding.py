from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
import numpy as np

from ..models.swap_models import Product

class EmbeddingService:
    
    def __init__(self, db: Session):
        self.db = db
        self.model = None
        self._init_model()
    
    def _init_model(self):
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer('all-MiniLM-L6-v2')
        except ImportError:
            print("sentence-transformers not available, embeddings disabled")
            self.model = None
    
    def generate_product_embedding(self, product: Product) -> Optional[np.ndarray]:
        if not self.model:
            return None
        
        text_representation = f"{product.name} {product.category} ${product.price}"
        if product.attributes:
            attrs_text = " ".join([f"{k}:{v}" for k, v in product.attributes.items()])
            text_representation += f" {attrs_text}"
        
        embedding = self.model.encode(text_representation)
        return embedding
    
    def update_product_embedding(self, product_id: int) -> bool:
        product = self.db.query(Product).filter(Product.id == product_id).first()
        if not product:
            return False
        
        embedding = self.generate_product_embedding(product)
        if embedding is not None:
            product.embedding = embedding.tolist()
            self.db.commit()
            return True
        return False
    
    def update_all_embeddings(self) -> Dict[str, Any]:
        products = self.db.query(Product).all()
        updated = 0
        failed = 0
        
        for product in products:
            embedding = self.generate_product_embedding(product)
            if embedding is not None:
                product.embedding = embedding.tolist()
                updated += 1
            else:
                failed += 1
        
        self.db.commit()
        return {'updated': updated, 'failed': failed, 'total': len(products)}
    
    def find_similar_products(self, product: Product, limit: int = 5) -> List[Product]:
        if not self.model or not product.embedding:
            return []
        
        try:
            query_embedding = product.embedding if isinstance(product.embedding, list) else self.generate_product_embedding(product)
            if query_embedding is None:
                return []
            
            query_embedding = np.array(query_embedding, dtype=float)
            
            all_products = self.db.query(Product).filter(
                Product.id != product.id,
                Product.availability == True,
                Product.embedding.isnot(None)
            ).all()
            
            similarities = []
            for candidate in all_products:
                if candidate.embedding:
                    try:
                        candidate_emb = np.array(candidate.embedding, dtype=float)
                        similarity = self._cosine_similarity(query_embedding, candidate_emb)
                        similarities.append((candidate, similarity))
                    except (ValueError, TypeError):
                        continue
            
            similarities.sort(key=lambda x: x[1], reverse=True)
            return [prod for prod, _ in similarities[:limit]]
        except Exception as e:
            print(f"Error in find_similar_products: {e}")
            return []
    
    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot_product / (norm1 * norm2)
