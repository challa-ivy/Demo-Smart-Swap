from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, JSON, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime

from .database import Base

class Product(Base):
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    category = Column(String, index=True)
    price = Column(Float, nullable=False)
    retailer_id = Column(String, index=True)
    availability = Column(Boolean, default=True)
    attributes = Column(JSON)
    embedding = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SwapRule(Base):
    __tablename__ = "swap_rules"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    priority = Column(Integer, default=0)
    active = Column(Boolean, default=True)
    conditions = Column(JSON, nullable=False)
    target_criteria = Column(JSON, nullable=False)
    auto_swap_enabled = Column(Boolean, default=False)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    executions = relationship("SwapExecution", back_populates="rule")

class SwapExecution(Base):
    __tablename__ = "swap_executions"
    
    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey("swap_rules.id"), nullable=False)
    original_product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    swap_product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    execution_type = Column(String, nullable=False)
    confidence_score = Column(Float)
    justification = Column(JSON, nullable=False)
    status = Column(String, default="pending")
    executed_by = Column(String)
    executed_at = Column(DateTime, default=datetime.utcnow)
    
    rule = relationship("SwapRule", back_populates="executions")
    original_product = relationship("Product", foreign_keys=[original_product_id])
    swap_product = relationship("Product", foreign_keys=[swap_product_id])
    feedback = relationship("RetailerFeedback", back_populates="execution", uselist=False)

class RetailerFeedback(Base):
    __tablename__ = "retailer_feedback"
    
    id = Column(Integer, primary_key=True, index=True)
    execution_id = Column(Integer, ForeignKey("swap_executions.id"), nullable=False)
    retailer_id = Column(String, nullable=False)
    accepted = Column(Boolean, nullable=False)
    feedback_text = Column(Text)
    feedback_metadata = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    execution = relationship("SwapExecution", back_populates="feedback")
