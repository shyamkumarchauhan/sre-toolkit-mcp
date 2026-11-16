# SRE Toolkit MCP server

A small, read-only [Model Context Protocol](https://modelcontextprotocol.io) server for
on-call engineers. Connect it to Claude Code, Claude Desktop, VS Code or any other MCP
client and the assistant can run a few safe checks during an incident.

| Primitive | Name | What it does |
|---|---|---|
| Tool | `http_check` | One request to a URL: status code and latency |
| Tool | `tls_expiry` | Certificate expiry date and days left |
| Tool | `dns_lookup` | IPv4 and IPv6 addresses for a hostname |
| Tool | `error_budget` | Budget minutes, spent and remaining, for an availability SLO |
| Tool | `burn_rate` | Burn rate against the SLO, and whether it should page |
| Resource | `runbook://{service}` | A first-response runbook template |
| Prompt | `incident_summary` | Stakeholder update from an incident timeline |

## Safety

- Nothing in this server changes a system. Every tool is a read or a calculation.
- Network tools only reach hosts listed in `ALLOWED_HOSTS`. Redirects are reported, not
  followed, so a 30x cannot lead outside the list.
- Expected failures are raised as `ToolError`, so the model sees a useful message. Any
  other exception is reported to the client as a generic error and logged on the server.

## Run it

Needs Python 3.10+ and the MCP Python SDK 2.x.

```powershell
git clone https://github.com/shyamkumarchauhan/sre-toolkit-mcp.git
cd sre-toolkit-mcp
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

### Claude Code

```powershell
claude mcp add sre-toolkit --env ALLOWED_HOSTS=example.com,status.example.com -- python C:\path\to\sre-toolkit-mcp\server.py
```

### Claude Desktop, VS Code and other clients (`mcpServers` JSON)

```json
{
  "mcpServers": {
    "sre-toolkit": {
      "command": "python",
      "args": ["C:/path/to/sre-toolkit-mcp/server.py"],
      "env": { "ALLOWED_HOSTS": "example.com,status.example.com" }
    }
  }
}
```

### As a remote server (Streamable HTTP)

```powershell
python server.py --http          # listens on http://127.0.0.1:8000/mcp
claude mcp add --transport http sre-toolkit http://127.0.0.1:8000/mcp
```

Put authentication in front of it before exposing it beyond your machine.

## Test it

The MCP Inspector lists the tools and lets you call them by hand:

```powershell
npx @modelcontextprotocol/inspector python server.py
```

## Extend it

Add a function with a docstring and type hints, decorate it with `@mcp.tool()`, and
restart the client. Keep new tools read-only unless a person approves each call.

## About

Built by [Shyamkumar L Chauhan](https://shyamkumarchauhan.com/mcp.html). More on MCP for operations teams, and a directory of MCP server repos, on the MCP hub page. Released under the MIT License.
