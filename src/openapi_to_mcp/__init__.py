"""openapi_to_mcp: generate MCP servers from OpenAPI documents.

The package has three layers:

* discovery (:mod:`openapi_to_mcp.discovery`) turns an OpenAPI document into a
  :class:`~openapi_to_mcp.model.Service` of MCP tool definitions;
* generation (:mod:`openapi_to_mcp.generator`) writes a standalone MCP server
  project: a ``tools.json`` manifest plus a vendored copy of the runtime;
* runtime (:mod:`openapi_to_mcp.runtime`) serves that manifest over MCP stdio.
"""

from openapi_to_mcp.model import Service, Tool

__all__ = ["Service", "Tool", "__version__"]

__version__ = "0.1.0"
