from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from datetime import datetime
import json

from ..models.swap_models import Product, SwapRule, SwapExecution

class RuleEngine:
    
    def __init__(self, db: Session):
        self.db = db
    
    def evaluate_swap_rules(self, product: Product) -> List[Dict[str, Any]]:
        active_rules = self.db.query(SwapRule).filter(
            SwapRule.active == True
        ).order_by(SwapRule.priority.desc()).all()
        
        matching_rules = []
        for rule in active_rules:
            if self._evaluate_conditions(product, rule.conditions):
                matching_rules.append({
                    'rule': rule,
                    'confidence': 1.0,
                    'reason': 'deterministic_match'
                })
        
        return matching_rules
    
    def _evaluate_conditions(self, product: Product, conditions: Dict[str, Any]) -> bool:
        if 'category' in conditions:
            category_value = conditions['category']
            if isinstance(category_value, str):
                if product.category != category_value:
                    return False
            else:
                if product.category not in category_value:
                    return False
        
        if 'price_range' in conditions:
            min_price = conditions['price_range'].get('min', 0)
            max_price = conditions['price_range'].get('max', float('inf'))
            if not (min_price <= product.price <= max_price):
                return False
        
        if 'availability' in conditions:
            if product.availability != conditions['availability']:
                return False
        
        if 'attributes' in conditions:
            for key, value in conditions['attributes'].items():
                if product.attributes.get(key) != value:
                    return False
        
        return True
    
    def find_swap_candidates(self, product: Product, criteria: Dict[str, Any]) -> List[Product]:
        query = self.db.query(Product).filter(
            Product.id != product.id,
            Product.availability == True
        )
        
        if 'category' in criteria:
            category_value = criteria['category']
            if isinstance(category_value, str):
                query = query.filter(Product.category == category_value)
            else:
                query = query.filter(Product.category.in_(category_value))
        
        if 'price_range' in criteria:
            min_price = criteria['price_range'].get('min', 0)
            max_price = criteria['price_range'].get('max', float('inf'))
            query = query.filter(
                Product.price >= min_price,
                Product.price <= max_price
            )
        
        if 'max_price_diff' in criteria:
            max_diff = criteria['max_price_diff']
            query = query.filter(
                Product.price >= product.price - max_diff,
                Product.price <= product.price + max_diff
            )
        
        candidates = query.limit(10).all()
        
        # Filter by same_attributes if specified
        if 'same_attributes' in criteria:
            same_attrs = criteria['same_attributes']
            filtered_candidates = []
            for candidate in candidates:
                match = True
                for attr_key in same_attrs:
                    if product.attributes.get(attr_key) != candidate.attributes.get(attr_key):
                        match = False
                        break
                if match:
                    filtered_candidates.append(candidate)
            candidates = filtered_candidates
        
        return candidates
    
    def execute_swap(
        self,
        rule: SwapRule,
        original_product: Product,
        swap_product: Product,
        execution_type: str = "auto",
        confidence: float = 1.0,
        justification: Dict[str, Any] = None
    ) -> SwapExecution:
        if justification is None:
            justification = {
                'rule_name': rule.name,
                'rule_version': rule.version,
                'execution_time': datetime.utcnow().isoformat(),
                'confidence': confidence
            }
        
        execution = SwapExecution(
            rule_id=rule.id,
            original_product_id=original_product.id,
            swap_product_id=swap_product.id,
            execution_type=execution_type,
            confidence_score=confidence,
            justification=justification,
            status="executed" if rule.auto_swap_enabled else "pending_approval",
            executed_by="system" if execution_type == "auto" else "agent"
        )
        
        self.db.add(execution)
        self.db.commit()
        self.db.refresh(execution)
        
        return execution
    
    def get_swap_history(self, product_id: Optional[int] = None, limit: int = 100) -> List[SwapExecution]:
        query = self.db.query(SwapExecution).order_by(SwapExecution.executed_at.desc())
        
        if product_id:
            query = query.filter(
                (SwapExecution.original_product_id == product_id) |
                (SwapExecution.swap_product_id == product_id)
            )
        
        return query.limit(limit).all()
