# Ingestion Fixtures

Real procurement PDF integration tests use the source documents already stored in the repository; tests should not copy or rewrite those source files.

- Bid1 tables: `Initial_docs/Bid1/JA-207652 Student and Staff Computing Devices FINAL.pdf`
- Bid2 tables: `Initial_docs/Bid2/PORFP_-_Dell_Laptop_Final.pdf`
- Bid3 tables: `Initial_docs/Bid3/PORFP_-_Dell_Laptop_Final.pdf`

Choose a small set of representative pages and manually verify expected headers, cells, and page numbers against the source PDFs. Treat PyMuPDF's detected table counts as coverage information, not correctness expectations. Synthetic PDF fixtures should cover blank/merged cells, continuation headers, false positives, and extraction failures without embedding full procurement documents in test fixtures.
