from src.search.search import SearchService


def test_existing_search_service_still_constructs_without_vector_index():
    service = SearchService([])
    assert service.vector_search is None
