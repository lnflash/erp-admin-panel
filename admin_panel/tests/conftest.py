"""Suite-wide fixtures.

``fake`` (an in-memory frappe stand-in, see ``idv_stubs``) is registered
here rather than imported by name into each test module, so the modules can
take it as a parameter without shadowing an import.
"""

from idv_stubs import fake

__all__ = ["fake"]
