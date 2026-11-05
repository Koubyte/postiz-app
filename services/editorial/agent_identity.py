"""Per-request agent identity, propagated to synchronous MCP tool handlers."""
from contextvars import ContextVar

current_identity = ContextVar('editorial_agent_identity', default=None)


def independent_key_id():
    """Existing legacy and internal calls keep their original upload behavior."""
    identity = current_identity.get()
    return identity.get('key_id') if identity and identity.get('key_id') != 'legacy' else None
