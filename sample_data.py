import requests
import json

BASE_URL = "http://localhost:5000"

def create_sample_products():
    products = [
        {
            "sku": "LAPTOP-001",
            "name": "Dell XPS 13 Laptop",
            "category": "electronics",
            "price": 999.99,
            "retailer_id": "retailer_1",
            "availability": True,
            "attributes": {"brand": "Dell", "screen_size": 13, "ram": 16}
        },
        {
            "sku": "LAPTOP-002",
            "name": "HP Spectre x360",
            "category": "electronics",
            "price": 1099.99,
            "retailer_id": "retailer_1",
            "availability": True,
            "attributes": {"brand": "HP", "screen_size": 13, "ram": 16}
        },
        {
            "sku": "LAPTOP-003",
            "name": "Lenovo ThinkPad X1",
            "category": "electronics",
            "price": 1199.99,
            "retailer_id": "retailer_1",
            "availability": False,
            "attributes": {"brand": "Lenovo", "screen_size": 14, "ram": 16}
        },
        {
            "sku": "PHONE-001",
            "name": "iPhone 15 Pro",
            "category": "mobile",
            "price": 999.99,
            "retailer_id": "retailer_2",
            "availability": True,
            "attributes": {"brand": "Apple", "storage": 256}
        },
        {
            "sku": "PHONE-002",
            "name": "Samsung Galaxy S24",
            "category": "mobile",
            "price": 899.99,
            "retailer_id": "retailer_2",
            "availability": True,
            "attributes": {"brand": "Samsung", "storage": 256}
        }
    ]
    
    created_products = []
    for product in products:
        response = requests.post(f"{BASE_URL}/api/products", json=product)
        if response.status_code == 200:
            created_products.append(response.json())
            print(f"Created product: {product['name']}")
    
    return created_products

def create_sample_rules():
    rules = [
        {
            "name": "Out of Stock Laptop Swap",
            "description": "Automatically suggest alternative laptops when a product is out of stock",
            "priority": 10,
            "active": True,
            "conditions": {
                "category": ["electronics"],
                "availability": False,
                "attributes": {"screen_size": 13}
            },
            "target_criteria": {
                "category": ["electronics"],
                "price_range": {"min": 800, "max": 1300},
                "max_price_diff": 200
            },
            "auto_swap_enabled": False
        },
        {
            "name": "Price-Based Mobile Swap",
            "description": "Suggest cheaper alternatives for mobile phones",
            "priority": 5,
            "active": True,
            "conditions": {
                "category": ["mobile"],
                "price_range": {"min": 900, "max": 1500}
            },
            "target_criteria": {
                "category": ["mobile"],
                "price_range": {"min": 700, "max": 950}
            },
            "auto_swap_enabled": False
        }
    ]
    
    created_rules = []
    for rule in rules:
        response = requests.post(f"{BASE_URL}/api/rules", json=rule)
        if response.status_code == 200:
            created_rules.append(response.json())
            print(f"Created rule: {rule['name']}")
    
    return created_rules

def test_swap_suggestions():
    products_response = requests.get(f"{BASE_URL}/api/products")
    products = products_response.json()
    
    if products:
        test_product = products[0]
        print(f"\nGetting swap suggestions for: {test_product['name']}")
        
        suggestions_response = requests.post(
            f"{BASE_URL}/api/suggestions",
            json={
                "product_id": test_product['id'],
                "context": "Looking for a similar laptop within $200 price range"
            }
        )
        
        if suggestions_response.status_code == 200:
            suggestions = suggestions_response.json()
            print(f"Received {len(suggestions.get('suggestions', []))} suggestions")
            print(json.dumps(suggestions, indent=2))

if __name__ == "__main__":
    print("Creating sample data for Smart Swap AI System...\n")
    
    print("Step 1: Creating sample products")
    products = create_sample_products()
    
    print("\nStep 2: Creating sample rules")
    rules = create_sample_rules()
    
    print("\nStep 3: Testing swap suggestions")
    test_swap_suggestions()
    
    print("\n✅ Sample data created successfully!")
    print("Visit http://localhost:5000 to explore the system")
    print("API Documentation: http://localhost:5000/docs")
