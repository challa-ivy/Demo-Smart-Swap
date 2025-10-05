import os
from typing import Tuple, List, Optional, Dict, Any
from sqlalchemy.orm import Session
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate

from ..models.swap_models import Product


class ProductValidator:
    """Validates products before they're added to the system using business rules and LLM intelligence."""
    
    def __init__(self, db: Session):
        self.db = db
        self.llm = None
        
        # Initialize LLM if API key is available
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            self.llm = ChatOpenAI(model="gpt-4", temperature=0.2)
    
    def validate_product(self, sku: str, name: str, category: str, price: float, 
                        retailer_id: str, attributes: Optional[Dict[str, Any]] = None) -> Tuple[bool, str, List[str]]:
        """
        Validates if a product should be added to the system.
        
        Returns:
            Tuple of (is_valid, decision, warnings)
            - is_valid: True if product passes all checks
            - decision: Explanation of the decision
            - warnings: List of warning messages (non-blocking issues)
        """
        warnings = []
        attributes = attributes or {}
        
        # 1. Basic data validation
        basic_valid, basic_msg = self._validate_basic_data(sku, name, category, price)
        if not basic_valid:
            return False, f"❌ Basic validation failed: {basic_msg}", []
        
        # 2. Check for duplicates
        duplicate_check, duplicate_msg = self._check_duplicates(sku, name, retailer_id)
        if duplicate_check == "reject":
            return False, f"❌ Duplicate detected: {duplicate_msg}", []
        elif duplicate_check == "warn":
            warnings.append(f"⚠️ {duplicate_msg}")
        
        # 3. LLM-based validation (if available)
        if self.llm:
            llm_valid, llm_msg, llm_warnings = self._llm_validate(
                sku, name, category, price, retailer_id, attributes
            )
            if not llm_valid:
                return False, f"❌ AI validation failed: {llm_msg}", warnings
            warnings.extend(llm_warnings)
        else:
            warnings.append("⚠️ LLM validation skipped (no API key configured)")
        
        # All checks passed
        return True, "✅ Product validation passed", warnings
    
    def _validate_basic_data(self, sku: str, name: str, category: str, price: float) -> Tuple[bool, str]:
        """Validates basic product data quality."""
        
        # Check required fields
        if not sku or not sku.strip():
            return False, "SKU is required"
        if not name or not name.strip():
            return False, "Product name is required"
        if not category or not category.strip():
            return False, "Category is required"
        
        # Validate SKU format (alphanumeric with dashes)
        if not sku.replace("-", "").replace("_", "").isalnum():
            return False, f"SKU '{sku}' contains invalid characters (use alphanumeric, dashes, underscores only)"
        
        # Validate price
        if price is None or price < 0:
            return False, f"Price must be non-negative (got: {price})"
        if price == 0:
            return False, "Price cannot be zero (products must have a value)"
        if price > 1000000:
            return False, f"Price seems unrealistic (${price}). Please verify."
        
        # Validate name length
        if len(name) < 3:
            return False, "Product name too short (minimum 3 characters)"
        if len(name) > 200:
            return False, "Product name too long (maximum 200 characters)"
        
        return True, "Basic validation passed"
    
    def _check_duplicates(self, sku: str, name: str, retailer_id: str) -> Tuple[str, str]:
        """
        Checks for duplicate products.
        
        Returns:
            Tuple of (action, message)
            - action: "reject", "warn", or "ok"
            - message: Explanation message
        """
        # Check for exact SKU match with same retailer
        existing = self.db.query(Product).filter(
            Product.sku == sku,
            Product.retailer_id == retailer_id
        ).first()
        
        if existing:
            return "reject", f"Product with SKU '{sku}' already exists for retailer '{retailer_id}' (ID: {existing.id})"
        
        # Check for very similar names (potential duplicates)
        name_lower = name.lower().strip()
        all_products = self.db.query(Product).filter(Product.retailer_id == retailer_id).all()
        
        for product in all_products:
            existing_name = product.name.lower().strip()
            
            # Simple similarity check (exact match or substring)
            if name_lower == existing_name:
                return "warn", f"Very similar product exists: '{product.name}' (SKU: {product.sku})"
            
            # Check if one is substring of the other
            if name_lower in existing_name or existing_name in name_lower:
                if len(name_lower) > 5 and len(existing_name) > 5:  # Only for non-trivial names
                    return "warn", f"Similar product name exists: '{product.name}' (SKU: {product.sku})"
        
        return "ok", "No duplicates found"
    
    def _llm_validate(self, sku: str, name: str, category: str, price: float, 
                     retailer_id: str, attributes: Dict[str, Any]) -> Tuple[bool, str, List[str]]:
        """Uses LLM to validate if the product seems legitimate and appropriate."""
        
        if not self.llm:
            return True, "LLM not available", []
        
        # Get existing categories for reference
        existing_categories = self.db.query(Product.category).distinct().all()
        existing_categories = [cat[0] for cat in existing_categories if cat[0]]
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a product validation expert. Your job is to validate if a product should be added to a retail inventory system.

Analyze the product and determine if it should be APPROVED or REJECTED.

REJECT if:
- Product seems fake, nonsensical, or inappropriate
- Product name doesn't match the category
- Price seems unrealistic for the product type
- SKU format seems suspicious or invalid
- Product appears to be test/dummy data

APPROVE if:
- Product seems like a real retail item
- Name, category, and price are consistent
- SKU follows a reasonable pattern

Also provide WARNINGS for non-blocking issues like:
- Category doesn't match existing categories (suggest better category)
- Price seems unusual but not impossible
- Attributes seem incomplete

Respond in this exact JSON format:
{{
    "decision": "APPROVED" or "REJECTED",
    "reasoning": "Brief explanation of your decision",
    "warnings": ["warning1", "warning2"] or []
}}"""),
            ("human", """Please validate this product:

SKU: {sku}
Name: {name}
Category: {category}
Price: ${price}
Retailer: {retailer_id}
Attributes: {attributes}

Existing categories in system: {existing_categories}

Should this product be added to the inventory?""")
        ])
        
        try:
            response = self.llm.invoke(prompt.format_messages(
                sku=sku,
                name=name,
                category=category,
                price=price,
                retailer_id=retailer_id,
                attributes=attributes,
                existing_categories=", ".join(existing_categories) if existing_categories else "None yet"
            ))
            
            # Parse LLM response
            import json
            content = str(response.content).strip()
            
            # Try to extract JSON from response
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            result = json.loads(content)
            
            decision = result.get("decision", "REJECTED").upper()
            reasoning = result.get("reasoning", "No reasoning provided")
            warnings = result.get("warnings", [])
            
            if decision == "APPROVED":
                return True, f"🤖 AI approved: {reasoning}", [f"🤖 {w}" for w in warnings]
            else:
                return False, f"🤖 AI rejected: {reasoning}", []
                
        except Exception as e:
            # If LLM validation fails, we'll allow the product but add a warning
            return True, "LLM validation encountered an error, proceeding with caution", [
                f"⚠️ LLM validation error: {str(e)}"
            ]
