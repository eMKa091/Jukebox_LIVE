"""Domain logic: the rules of the product.

Nothing in this package imports from app.web. Every rule the application
enforces is testable without an HTTP client -- which is the thing the legacy
codebase could not do, because its rules were interleaved with st.button()
calls.
"""
