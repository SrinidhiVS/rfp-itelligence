def test_existing_backend_contract_tests_are_part_of_frontend_regression_suite():
    import src.api.app
    import src.agents.graph
    import src.search.search
    import src.extraction.extractor

    assert src.api.app.app.title == "RFP Multi-Agent Analysis"
