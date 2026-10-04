def test_frontend_modules_import_without_replacing_backend():
    from src.api.app import app
    from src.frontend.client import FrontendClient
    from src.frontend.app import main

    assert app.title == "RFP Multi-Agent Analysis"
    assert callable(main)
    assert FrontendClient
