# puya-odoo-mcp

MCP server for Odoo 16 with role-based access control (RBAC).

## Setup

### Prerequisites

- Python 3.10+
- Odoo module `puya_mcp_access` installed (adds `x_mcp_role` field to users)
- Odoo API key for the user

### Install

```bash
git clone git@github.com:puya-tech/puya-odoo-mcp.git
cd puya-odoo-mcp
pip install -e .
```

### Configure credentials

Create the credentials file (keeps the API key hidden from Claude Code):

```bash
mkdir -p ~/.config/puya-odoo-mcp
cat > ~/.config/puya-odoo-mcp/credentials << 'EOF'
ODOO_URL=https://cmcorpcl-puyacentro.odoo.com
ODOO_DB=cmcorpcl-costasurmat-main-7982838
ODOO_API_KEY=your-api-key-here
EOF
chmod 600 ~/.config/puya-odoo-mcp/credentials
```

The credentials file is read by the MCP server at startup. Claude Code never sees the API key.

Alternatively, env vars (`ODOO_URL`, `ODOO_DB`, `ODOO_API_KEY`) work as fallback.

### Configure in Claude Code

The project's `.claude/settings.json` already has the MCP server configured. Just install the package and set up credentials.

## Security

Two layers of protection:

1. **Hidden credentials**: API key lives in `~/.config/puya-odoo-mcp/credentials` (not in env vars), so Claude Code cannot access it directly
2. **Odoo native permissions**: Each user's Odoo account has restricted groups/permissions as a second layer, so even if the MCP is bypassed, the API key can only do what Odoo allows

## Roles

| Role | Read | Write/Create | Methods | Delete |
|------|------|-------------|---------|--------|
| vendedor | Own records only | No | No | No |
| administrativo | All allowed models | Yes | Whitelisted | No |
| developer | All models | Yes | All | Yes |

Roles are configured in `permissions.yaml`. Assign roles in Odoo at Settings > Users > MCP Role (debug mode).

## Tools

- `odoo_search` - Search records with domain filters
- `odoo_count` - Count matching records
- `odoo_read` - Read records by ID
- `odoo_fields` - Inspect model field definitions
- `odoo_write` - Update records (admin/dev)
- `odoo_create` - Create records (admin/dev)
- `odoo_execute` - Call model methods (admin/dev)
- `odoo_delete` - Delete records (dev only)

## Tests

```bash
pip install -e ".[dev]"
pytest
```
