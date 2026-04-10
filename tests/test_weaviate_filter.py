import os
import sys

# Mock Weaviate Vector Store
class MockWeaviateVectorStore:
    def __init__(self, client, index_name, text_key, embedding):
        self.client = client
        self.index_name = index_name
        self.text_key = text_key
        self.embedding = embedding

    def similarity_search(self, query, k, vector, filters, **kwargs):
        print(f"Called similarity_search with filters: {filters}")
        return filters

# Mock Weaviate Filter
class MockFilter:
    def __init__(self, prop=None):
        self.prop = prop
        self.val = None
        self.op = None
        self.filters = None

    @classmethod
    def by_property(cls, prop):
        return cls(prop)

    def equal(self, val):
        self.val = val
        self.op = "equal"
        return self

    @classmethod
    def all_of(cls, filters):
        obj = cls()
        obj.filters = filters
        obj.op = "all_of"
        return obj

    def __repr__(self):
        if self.op == "all_of":
            return f"Filter.all_of({self.filters})"
        return f"Filter.by_property('{self.prop}').equal('{self.val}')"

class Mem0CompatibleWeaviate(MockWeaviateVectorStore):
    def similarity_search_by_vector(self, embedding, k=4, filter=None, **kwargs):
        weaviate_filter = None
        
        if isinstance(filter, dict) and filter:
            filters_list = []
            for key, value in filter.items():
                filters_list.append(MockFilter.by_property(key).equal(value))
                
            if len(filters_list) == 1:
                weaviate_filter = filters_list[0]
            elif len(filters_list) > 1:
                weaviate_filter = MockFilter.all_of(filters_list)
        else:
            weaviate_filter = filter

        return self.similarity_search(
            query=None, 
            k=k, 
            vector=embedding, 
            filters=weaviate_filter, 
            **kwargs
        )

# Test the filter translation
vector_store = Mem0CompatibleWeaviate(None, "TestIndex", "text", None)

print("Test 1: Single filter")
f1 = vector_store.similarity_search_by_vector([0.1, 0.2], k=4, filter={"user_id": "123"})
assert f1.prop == "user_id" and f1.val == "123"

print("\nTest 2: Multiple filters")
f2 = vector_store.similarity_search_by_vector([0.1, 0.2], k=4, filter={"user_id": "123", "domain": "MAINTENANCE"})
assert f2.op == "all_of" and len(f2.filters) == 2
assert f2.filters[0].prop == "user_id" and f2.filters[0].val == "123"
assert f2.filters[1].prop == "domain" and f2.filters[1].val == "MAINTENANCE"

print("\nTest 3: No filter")
f3 = vector_store.similarity_search_by_vector([0.1, 0.2], k=4, filter=None)
assert f3 is None

print("\nAll tests passed successfully!")
