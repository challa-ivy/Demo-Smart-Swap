from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from ..models.database import get_db
from ..models.swap_models import Product, SwapRule, SwapExecution, RetailerFeedback
from ..services.rule_engine import RuleEngine
from ..services.orchestration import SwapOrchestrator
from ..services.embedding import EmbeddingService
from ..services.product_validator import ProductValidator

router = APIRouter()

class ProductCreate(BaseModel):
    sku: str
    name: str
    category: str
    price: float
    retailer_id: str
    availability: bool = True
    attributes: dict = {}

class SwapRuleCreate(BaseModel):
    name: str
    description: str
    priority: int = 0
    active: bool = True
    conditions: dict
    target_criteria: dict
    auto_swap_enabled: bool = False

class SwapSuggestionRequest(BaseModel):
    product_id: Optional[int] = None
    context: Optional[str] = None

class FeedbackRequest(BaseModel):
    execution_id: int
    accepted: bool
    feedback_text: Optional[str] = None

class FeedbackUpdate(BaseModel):
    accepted: Optional[bool] = None
    feedback_text: Optional[str] = None

class SwapExecutionRequest(BaseModel):
    rule_id: int
    original_product_id: int
    swap_product_id: int

class SwapExecutionUpdate(BaseModel):
    status: Optional[str] = None
    confidence_score: Optional[float] = None
    justification: Optional[dict] = None

@router.post("/api/products")
async def create_product(product: ProductCreate, db: Session = Depends(get_db)):
    # Validate product before adding
    validator = ProductValidator(db)
    is_valid, decision, warnings = validator.validate_product(
        sku=product.sku,
        name=product.name,
        category=product.category,
        price=product.price,
        retailer_id=product.retailer_id,
        attributes=product.attributes
    )
    
    if not is_valid:
        raise HTTPException(status_code=400, detail={
            "error": "Product validation failed",
            "decision": decision,
            "warnings": warnings
        })
    
    # Create product
    db_product = Product(**product.dict())
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    
    # Return product with validation info
    return {
        "product": db_product,
        "validation": {
            "decision": decision,
            "warnings": warnings
        }
    }

@router.post("/api/products/bulk")
async def create_products_bulk(products: List[ProductCreate], db: Session = Depends(get_db)):
    validator = ProductValidator(db)
    created_products = []
    validation_results = []
    failed_products = []
    
    for idx, product in enumerate(products):
        # Validate each product
        is_valid, decision, warnings = validator.validate_product(
            sku=product.sku,
            name=product.name,
            category=product.category,
            price=product.price,
            retailer_id=product.retailer_id,
            attributes=product.attributes
        )
        
        if not is_valid:
            failed_products.append({
                "index": idx,
                "product": product.dict(),
                "reason": decision,
                "warnings": warnings
            })
            continue
        
        # Create product if valid
        db_product = Product(**product.dict())
        db.add(db_product)
        db.flush()
        db.refresh(db_product)
        created_products.append(db_product)
        validation_results.append({
            "product_id": db_product.id,
            "decision": decision,
            "warnings": warnings
        })
    
    db.commit()
    
    return {
        "message": f"Successfully created {len(created_products)}/{len(products)} products",
        "created_products": created_products,
        "validation_results": validation_results,
        "failed_products": failed_products
    }

@router.get("/api/products")
async def list_products(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    products = db.query(Product).offset(skip).limit(limit).all()
    return products

@router.get("/api/products/{product_id}")
async def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@router.put("/api/products/{product_id}")
async def update_product(product_id: int, product_update: ProductCreate, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Update fields
    for key, value in product_update.dict().items():
        setattr(product, key, value)
    
    db.commit()
    db.refresh(product)
    return product

@router.delete("/api/products/{product_id}")
async def delete_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    db.delete(product)
    db.commit()
    return {"message": f"Product {product_id} deleted successfully"}

@router.post("/api/rules")
async def create_rule(rule: SwapRuleCreate, db: Session = Depends(get_db)):
    db_rule = SwapRule(**rule.dict())
    db.add(db_rule)
    db.commit()
    db.refresh(db_rule)
    return db_rule

@router.get("/api/rules")
async def list_rules(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    rules = db.query(SwapRule).offset(skip).limit(limit).all()
    return rules

@router.get("/api/rules/{rule_id}")
async def get_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(SwapRule).filter(SwapRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule

@router.put("/api/rules/{rule_id}")
async def update_rule(rule_id: int, rule_update: SwapRuleCreate, db: Session = Depends(get_db)):
    rule = db.query(SwapRule).filter(SwapRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    # Update fields
    for key, value in rule_update.dict().items():
        setattr(rule, key, value)
    
    db.commit()
    db.refresh(rule)
    return rule

@router.delete("/api/rules/{rule_id}")
async def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(SwapRule).filter(SwapRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    db.delete(rule)
    db.commit()
    return {"message": f"Rule {rule_id} deleted successfully"}

@router.post("/api/suggestions")
async def get_swap_suggestions(request: SwapSuggestionRequest, db: Session = Depends(get_db)):
    orchestrator = SwapOrchestrator(db)
    
    # Context-only suggestions (LLM-driven)
    if request.context and not request.product_id:
        suggestions = orchestrator.suggest_swap_by_context(request.context)
        return suggestions
    
    # Product-specific suggestions (traditional flow)
    if request.product_id:
        product = db.query(Product).filter(Product.id == request.product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        suggestions = orchestrator.suggest_swap(product, request.context)
        return suggestions
    
    # Neither product_id nor context provided
    raise HTTPException(status_code=400, detail="Either product_id or context must be provided")

@router.post("/api/swaps/execute")
async def execute_swap(request: SwapExecutionRequest, db: Session = Depends(get_db)):
    rule = db.query(SwapRule).filter(SwapRule.id == request.rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    original = db.query(Product).filter(Product.id == request.original_product_id).first()
    swap = db.query(Product).filter(Product.id == request.swap_product_id).first()
    
    if not original or not swap:
        raise HTTPException(status_code=404, detail="Product not found")
    
    engine = RuleEngine(db)
    execution = engine.execute_swap(rule, original, swap)
    return execution

@router.get("/api/swaps")
async def list_swaps(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    engine = RuleEngine(db)
    swaps = engine.get_swap_history(limit=limit)
    return swaps

@router.get("/api/swaps/{swap_id}")
async def get_swap(swap_id: int, db: Session = Depends(get_db)):
    swap = db.query(SwapExecution).filter(SwapExecution.id == swap_id).first()
    if not swap:
        raise HTTPException(status_code=404, detail="Swap execution not found")
    return swap

@router.put("/api/swaps/{swap_id}")
async def update_swap(swap_id: int, swap_update: SwapExecutionUpdate, db: Session = Depends(get_db)):
    swap = db.query(SwapExecution).filter(SwapExecution.id == swap_id).first()
    if not swap:
        raise HTTPException(status_code=404, detail="Swap execution not found")
    
    # Update fields
    for key, value in swap_update.dict(exclude_unset=True).items():
        setattr(swap, key, value)
    
    db.commit()
    db.refresh(swap)
    return swap

@router.delete("/api/swaps/{swap_id}")
async def delete_swap(swap_id: int, db: Session = Depends(get_db)):
    swap = db.query(SwapExecution).filter(SwapExecution.id == swap_id).first()
    if not swap:
        raise HTTPException(status_code=404, detail="Swap execution not found")
    
    db.delete(swap)
    db.commit()
    return {"message": f"Swap execution {swap_id} deleted successfully"}

@router.post("/api/feedback")
async def submit_feedback(feedback: FeedbackRequest, db: Session = Depends(get_db)):
    orchestrator = SwapOrchestrator(db)
    result = orchestrator.learn_from_feedback(
        feedback.execution_id,
        feedback.accepted,
        feedback.feedback_text
    )
    return result

@router.get("/api/feedback")
async def list_feedback(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    feedback = db.query(RetailerFeedback).offset(skip).limit(limit).all()
    return feedback

@router.get("/api/feedback/{feedback_id}")
async def get_feedback(feedback_id: int, db: Session = Depends(get_db)):
    feedback = db.query(RetailerFeedback).filter(RetailerFeedback.id == feedback_id).first()
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return feedback

@router.put("/api/feedback/{feedback_id}")
async def update_feedback(feedback_id: int, feedback_update: FeedbackUpdate, db: Session = Depends(get_db)):
    feedback = db.query(RetailerFeedback).filter(RetailerFeedback.id == feedback_id).first()
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")
    
    # Update fields
    for key, value in feedback_update.dict(exclude_unset=True).items():
        setattr(feedback, key, value)
    
    db.commit()
    db.refresh(feedback)
    return feedback

@router.delete("/api/feedback/{feedback_id}")
async def delete_feedback(feedback_id: int, db: Session = Depends(get_db)):
    feedback = db.query(RetailerFeedback).filter(RetailerFeedback.id == feedback_id).first()
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")
    
    db.delete(feedback)
    db.commit()
    return {"message": f"Feedback {feedback_id} deleted successfully"}

@router.get("/api/stats/retailer")
async def get_retailer_stats(retailer_id: Optional[str] = None, db: Session = Depends(get_db)):
    orchestrator = SwapOrchestrator(db)
    stats = orchestrator.get_retailer_acceptance_stats(retailer_id)
    return stats

@router.post("/api/embeddings/generate")
async def generate_embeddings(db: Session = Depends(get_db)):
    embedding_service = EmbeddingService(db)
    if not embedding_service.model:
        raise HTTPException(status_code=503, detail="Embedding service not available. sentence-transformers library may not be installed.")
    
    result = embedding_service.update_all_embeddings()
    return {
        "message": "Embeddings generated successfully",
        "details": result
    }
