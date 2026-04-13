import json

def test_memory_extraction(past_memories_response):
    if isinstance(past_memories_response, dict):
        past_memories = past_memories_response.get("results", [])
    else:
        past_memories = past_memories_response
        
    if past_memories:
        memory_strings = "\n".join([f"- {mem.get('memory', mem.get('text', ''))}" for mem in past_memories if isinstance(mem, dict)])
        return memory_strings
    return ""

# Test Case 1: New mem0 format (dict with 'results' and 'memory' key)
new_format = {"results": [{"id": "1", "memory": "User likes Python", "score": 0.9}]}
print("Test 1 (New Format):")
print(test_memory_extraction(new_format))

# Test Case 2: Old mem0 format (list of dicts with 'text' key)
old_format = [{"id": "2", "text": "User works with Neo4j"}]
print("\nTest 2 (Old Format):")
print(test_memory_extraction(old_format))

# Test Case 3: Empty results dict
empty_dict = {"results": []}
print("\nTest 3 (Empty Dict):")
print(test_memory_extraction(empty_dict))

# Test Case 4: Empty list
empty_list = []
print("\nTest 4 (Empty List):")
print(test_memory_extraction(empty_list))
