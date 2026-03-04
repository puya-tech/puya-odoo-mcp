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

### Environment variables

```bash
export ODOO_URL="https://costasurmat.odoo.com"
export ODOO_DB="costasurmat-main-12345678"
export ODOO_API_KEY="your-api-key-here"
```

### Configure in Claude Code

Add to your project's `.claude/settings.json`:

```json
{
  "mcpServers": {
    "odoo": {
      "command": "python",
      "args": ["-m", "puya_odoo_mcp"],
      "env": {
        "ODOO_URL": "https://costasurmat.odoo.com",
        "ODOO_DB": ""
      }
    }
  }
}
```

Set `ODOO_API_KEY` and `ODOO_DB` as system environment variables.

## Roles

| Role | Read | Write/Create | Methods | Delete |
|------|------|-------------|---------|--------|
| vendedor | Own records only | No | No | No |
| administrativo | All allowed models | Yes | Whitelisted | No |
| developer | All models | Yes | All | Yes |

Roles are configured in `permissions.yaml`. Assign roles in Odoo at Settings > Users > MCP Role.

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
