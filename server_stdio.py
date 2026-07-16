"""Entry point for Glama build: runs the MCP server with stdio transport."""
import server  # registers all tools and middleware

server.mcp.run(transport="stdio")
