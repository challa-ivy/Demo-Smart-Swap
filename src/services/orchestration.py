from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
import os

from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain.tools import Tool
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.schema import HumanMessage, SystemMessage

from ..models.swap_models import Product, SwapRule, SwapExecution, RetailerFeedback
from .rule_engine import RuleEngine
try:
    from .embedding import EmbeddingService
    HAS_EMBEDDINGS = True
except ImportError:
    HAS_EMBEDDINGS = False
    EmbeddingService = None

class SwapOrchestrator:
    
    def __init__(self, db: Session):
        self.db = db
        self.rule_engine = RuleEngine(db)
        self.embedding_service = EmbeddingService(db) if HAS_EMBEDDINGS else None
        
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if openai_api_key:
            self.llm = ChatOpenAI(
                model="gpt-4",
                temperature=0.7,
                openai_api_key=openai_api_key
            )
        else:
            self.llm = None
    
    def suggest_swap(self, product: Product, context: Optional[str] = None) -> Dict[str, Any]:
        rule_matches = self.rule_engine.evaluate_swap_rules(product)
        
        suggestions = []
        seen_product_ids = set()
        
        for match in rule_matches:
            rule = match['rule']
            candidates = self.rule_engine.find_swap_candidates(product, rule.target_criteria)
            
            for candidate in candidates:
                if candidate.id not in seen_product_ids:
                    seen_product_ids.add(candidate.id)
                    
                    # Get stats for this specific swap pair combination
                    swap_stats = self._get_swap_pair_stats(product.id, candidate.id)
                    confidence_score = swap_stats['confidence']
                    
                    # Build reasoning with swap-specific history
                    if swap_stats['swap_count'] == 0:
                        adjustment_note = " (No swap history - try it to build confidence)"
                    else:
                        adjustment_note = f" (This exact swap done {swap_stats['swap_count']} time{'s' if swap_stats['swap_count'] != 1 else ''} before"
                        if swap_stats['boost_percentage'] > 0:
                            adjustment_note += f", {swap_stats['boost_percentage']}% confidence"
                        if swap_stats['accepted_count'] > 0:
                            adjustment_note += f", {swap_stats['accepted_count']} accepted"
                        adjustment_note += ")"
                    
                    suggestion = {
                        'original_product': self._product_to_dict(product),
                        'swap_candidate': self._product_to_dict(candidate),
                        'rule_name': rule.name,
                        'confidence': confidence_score,
                        'reasoning': f"Rule-based match: {rule.description}{adjustment_note}",
                        'type': 'deterministic',
                        'swap_history_count': swap_stats['swap_count']
                    }
                    suggestions.append(suggestion)
        
        if self.embedding_service:
            embedding_suggestions = self._get_embedding_suggestions(product)
            for emb_sug in embedding_suggestions:
                if emb_sug['swap_candidate']['id'] not in seen_product_ids:
                    seen_product_ids.add(emb_sug['swap_candidate']['id'])
                    suggestions.append(emb_sug)
        
        if self.llm and context:
            llm_suggestions = self._get_llm_suggestions(product, context)
            for llm_sug in llm_suggestions:
                if llm_sug['swap_candidate']['id'] not in seen_product_ids:
                    seen_product_ids.add(llm_sug['swap_candidate']['id'])
                    suggestions.append(llm_sug)
        
        suggestions.sort(key=lambda x: x['confidence'], reverse=True)
        return {'suggestions': suggestions[:5]}
    
    def suggest_swap_by_context(self, context: str) -> Dict[str, Any]:
        """Generate product suggestions based purely on context using LLM"""
        if not self.llm:
            raise ValueError("LLM is not configured. Please set OPENAI_API_KEY environment variable.")
        
        if not context:
            raise ValueError("Context is required for context-based suggestions.")
        
        import json
        
        # Get all available products
        all_products = self.db.query(Product).filter(
            Product.availability == True
        ).limit(30).all()
        
        if not all_products:
            return {'suggestions': []}
        
        product_list = "\n".join([
            f"- {p.name} (SKU: {p.sku}, Price: ${p.price}, Category: {p.category}, Attributes: {p.attributes})"
            for p in all_products
        ])
        
        prompt = f"""You are a smart product recommendation system. Based on the following context, suggest the most suitable products from the available inventory.

Context: {context}

Available products:
{product_list}

Please suggest the top 5 most suitable products that match the context and explain your reasoning.
Consider factors like category, price, attributes, and how well they match the customer's needs described in the context.

Respond with a JSON array of objects, each with: "sku" (string), "reasoning" (string), "confidence" (number 0-1).
Example: [{{"sku": "SOAP-001", "reasoning": "Gentle formula suitable for sensitive skin", "confidence": 0.85}}]"""
        
        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            response_text = str(response.content).strip()
            
            if not response_text:
                print(f"Warning: Empty response from LLM")
                return {'suggestions': []}
            
            # Clean up response text
            if '```json' in response_text:
                response_text = response_text.split('```json')[1].split('```')[0].strip()
            elif '```' in response_text:
                response_text = response_text.split('```')[1].split('```')[0].strip()
            
            if not response_text:
                print(f"Warning: Response text empty after cleanup")
                return {'suggestions': []}
            
            try:
                parsed_suggestions = json.loads(response_text)
            except json.JSONDecodeError as je:
                print(f"JSON parsing error: {je}")
                print(f"Response text was: {response_text[:500]}")
                return {'suggestions': [], 'error': f"Invalid JSON response from LLM: {str(je)}"}
            
            suggestions = []
            for suggestion in parsed_suggestions:
                sku = suggestion.get('sku')
                reasoning = suggestion.get('reasoning', 'LLM recommendation based on context')
                confidence = float(suggestion.get('confidence', 0.7))
                
                candidate_product = self.db.query(Product).filter(Product.sku == sku).first()
                
                if candidate_product:
                    suggestions.append({
                        'swap_candidate': self._product_to_dict(candidate_product),
                        'confidence': confidence,
                        'reasoning': f"🤖 AI Recommendation: {reasoning}",
                        'type': 'llm_suggested',
                        'context_based': True
                    })
            
            suggestions.sort(key=lambda x: x['confidence'], reverse=True)
            return {'suggestions': suggestions[:5]}
        except json.JSONDecodeError as je:
            print(f"JSON decode error: {je}")
            return {'suggestions': [], 'error': f"Invalid JSON from LLM: {str(je)}"}
        except Exception as e:
            print(f"Error generating context-based suggestions: {e}")
            import traceback
            traceback.print_exc()
            return {'suggestions': [], 'error': f"Error: {str(e)}"}
    
    def _get_llm_suggestions(self, product: Product, context: str) -> List[Dict[str, Any]]:
        import json
        
        all_products = self.db.query(Product).filter(
            Product.id != product.id,
            Product.availability == True
        ).limit(20).all()
        
        product_list = "\n".join([
            f"- {p.name} (SKU: {p.sku}, Price: ${p.price}, Category: {p.category})"
            for p in all_products
        ])
        
        prompt = f"""Given the following product that needs a swap:
Product: {product.name}
SKU: {product.sku}
Price: ${product.price}
Category: {product.category}

Context: {context}

Available products for swapping:
{product_list}

Please suggest the top 3 most suitable product swaps and explain your reasoning.
Consider factors like category similarity, price range, and the given context.

Respond with a JSON array of objects, each with: "sku" (string), "reasoning" (string), "confidence" (number 0-1).
Example: [{{"sku": "LAPTOP-002", "reasoning": "Similar specs, better price", "confidence": 0.85}}]"""
        
        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            response_text = response.content.strip()
            
            if response_text.startswith('```json'):
                response_text = response_text.split('```json')[1].split('```')[0].strip()
            elif response_text.startswith('```'):
                response_text = response_text.split('```')[1].split('```')[0].strip()
            
            parsed_suggestions = json.loads(response_text)
            
            llm_suggestions = []
            for suggestion in parsed_suggestions:
                sku = suggestion.get('sku')
                reasoning = suggestion.get('reasoning', 'LLM recommendation')
                confidence = float(suggestion.get('confidence', 0.7))
                
                candidate_product = self.db.query(Product).filter(Product.sku == sku).first()
                
                if candidate_product:
                    # Apply learning feedback to LLM suggestions
                    swap_stats = self._get_swap_pair_stats(product.id, candidate_product.id)
                    
                    # Use learned confidence if available, otherwise use LLM's confidence
                    learned_confidence = swap_stats['confidence']
                    
                    # Build reasoning with swap history
                    if swap_stats['swap_count'] == 0:
                        adjustment_note = " [No swap history - AI suggestion]"
                    else:
                        adjustment_note = f" [This swap done {swap_stats['swap_count']} time{'s' if swap_stats['swap_count'] != 1 else ''} before, {swap_stats['boost_percentage']}% learned confidence"
                        if swap_stats['accepted_count'] > 0:
                            adjustment_note += f", {swap_stats['accepted_count']} accepted"
                        adjustment_note += "]"
                    
                    llm_suggestions.append({
                        'original_product': self._product_to_dict(product),
                        'swap_candidate': self._product_to_dict(candidate_product),
                        'confidence': learned_confidence,
                        'reasoning': f"AI: {reasoning}{adjustment_note}",
                        'type': 'llm_suggested',
                        'swap_history_count': swap_stats['swap_count']
                    })
            
            return llm_suggestions
        except Exception as e:
            print(f"Error parsing LLM suggestions: {e}")
            return []
    
    def _get_embedding_suggestions(self, product: Product) -> List[Dict[str, Any]]:
        if not self.embedding_service:
            return []
        
        similar_products = self.embedding_service.find_similar_products(product, limit=3)
        
        suggestions = []
        for similar_product in similar_products:
            # Apply learning feedback to embedding suggestions
            swap_stats = self._get_swap_pair_stats(product.id, similar_product.id)
            learned_confidence = swap_stats['confidence']
            
            # Build reasoning with swap history
            if swap_stats['swap_count'] == 0:
                adjustment_note = " [No swap history - try it to build confidence]"
            else:
                adjustment_note = f" [This swap done {swap_stats['swap_count']} time{'s' if swap_stats['swap_count'] != 1 else ''} before, {swap_stats['boost_percentage']}% learned confidence"
                if swap_stats['accepted_count'] > 0:
                    adjustment_note += f", {swap_stats['accepted_count']} accepted"
                adjustment_note += "]"
            
            suggestions.append({
                'original_product': self._product_to_dict(product),
                'swap_candidate': self._product_to_dict(similar_product),
                'confidence': learned_confidence,
                'reasoning': f'Semantic similarity match{adjustment_note}',
                'type': 'embedding_based',
                'swap_history_count': swap_stats['swap_count']
            })
        
        return suggestions
    
    def _get_swap_pair_stats(self, original_product_id: int, swap_product_id: int) -> Dict[str, Any]:
        # Count how many times this specific swap combination has been executed
        swap_history = self.db.query(SwapExecution).filter(
            SwapExecution.original_product_id == original_product_id,
            SwapExecution.swap_product_id == swap_product_id
        ).all()
        
        swap_count = len(swap_history)
        
        # Get feedback for this specific swap pair
        feedback_records = []
        for execution in swap_history:
            if execution.feedback:
                feedback_records.append(execution.feedback)
        
        accepted_count = sum(1 for f in feedback_records if f.accepted) if feedback_records else 0
        
        # Calculate confidence score starting from 0 and building up based on swap history
        confidence_score = 0.0
        boost_percentage = 0
        
        if swap_count == 0:
            # No history, confidence is 0
            confidence_score = 0.0
            boost_percentage = 0
        elif swap_count == 1:
            # First swap, minimal confidence
            confidence_score = 0.05
            boost_percentage = 5
        elif swap_count >= 10:
            # 10+ swaps, high confidence
            confidence_score = 0.30
            boost_percentage = 30
        elif swap_count >= 5:
            # 5-9 swaps, good confidence
            confidence_score = 0.20
            boost_percentage = 20
        elif swap_count >= 2:
            # 2-4 swaps, growing confidence
            confidence_score = 0.10
            boost_percentage = 10
        
        # Further adjust based on feedback acceptance rate
        if feedback_records:
            acceptance_rate = accepted_count / len(feedback_records)
            if acceptance_rate > 0.8:
                confidence_score += 0.10
                boost_percentage += 10
            elif acceptance_rate < 0.3:
                confidence_score -= 0.10
                boost_percentage -= 10
        
        # Cap confidence at 1.0 (100%)
        confidence_score = min(max(confidence_score, 0.0), 1.0)
        
        return {
            'confidence': confidence_score,
            'swap_count': swap_count,
            'accepted_count': accepted_count,
            'boost_percentage': boost_percentage
        }
    
    def learn_from_feedback(self, execution_id: int, accepted: bool, feedback_text: Optional[str] = None):
        execution = self.db.query(SwapExecution).filter(SwapExecution.id == execution_id).first()
        if not execution:
            return {'error': 'Execution not found'}
        
        feedback = RetailerFeedback(
            execution_id=execution_id,
            retailer_id=execution.original_product.retailer_id,
            accepted=accepted,
            feedback_text=feedback_text,
            feedback_metadata={'confidence_score': execution.confidence_score}
        )
        
        self.db.add(feedback)
        self.db.commit()
        
        return {'status': 'feedback_recorded', 'accepted': accepted}
    
    def get_retailer_acceptance_stats(self, retailer_id: Optional[str] = None) -> Dict[str, Any]:
        query = self.db.query(RetailerFeedback)
        
        if retailer_id:
            query = query.filter(RetailerFeedback.retailer_id == retailer_id)
        
        all_feedback = query.all()
        
        if not all_feedback:
            return {'total': 0, 'accepted': 0, 'rejected': 0, 'acceptance_rate': 0.0}
        
        total = len(all_feedback)
        accepted = sum(1 for f in all_feedback if f.accepted)
        rejected = total - accepted
        
        return {
            'total': total,
            'accepted': accepted,
            'rejected': rejected,
            'acceptance_rate': accepted / total if total > 0 else 0.0
        }
    
    def _product_to_dict(self, product: Product) -> Dict[str, Any]:
        return {
            'id': product.id,
            'sku': product.sku,
            'name': product.name,
            'category': product.category,
            'price': product.price,
            'retailer_id': product.retailer_id
        }
