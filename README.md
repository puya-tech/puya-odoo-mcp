# puya-odoo-mcp

MCP server para Odoo 16 con control de acceso por roles (RBAC), audit trail centralizado en Supabase y proteccion contra escalacion de privilegios.

## Como funciona

Cada trabajador se conecta a Odoo a traves de este MCP usando sus propias credenciales. El MCP:

1. Autentica al usuario con su API key de Odoo
2. Lee el campo `x_mcp_role` del usuario en Odoo para determinar su rol
3. Registra solo los tools que ese rol puede usar
4. Aplica filtros de dominio, campos denegados y blocklists por cada operacion
5. Guarda un registro de auditoria en Supabase por cada accion de escritura (before/after)

```
Trabajador instala MCP
    -> Ingresa SU api key de Odoo
    -> MCP lee x_mcp_role de SU usuario
    -> Solo ve los tools que su rol permite
    -> No puede cambiar su propio rol (campo protegido)
    -> No puede acceder a modelos de infraestructura
    -> Cada write queda registrado con snapshot before/after
```

## Instalacion

### Requisitos

- Python 3.10+
- Modulo de Odoo `puya_mcp_access` instalado (agrega el campo `x_mcp_role` a usuarios)
- API key de Odoo del usuario
- (Opcional) Supabase para audit trail centralizado

### Instalar el paquete

```bash
git clone git@github.com:puya-tech/puya-odoo-mcp.git
cd puya-odoo-mcp
pip install -e .
```

### Configurar credenciales

Crear el archivo de credenciales (mantiene el API key oculto de Claude Code):

```bash
mkdir -p ~/.config/puya-odoo-mcp
cat > ~/.config/puya-odoo-mcp/credentials << 'EOF'
ODOO_URL=https://cmcorpcl-puyacentro.odoo.com
ODOO_DB=cmcorpcl-costasurmat-main-7982838
ODOO_LOGIN=tu-email@empresa.cl
ODOO_API_KEY=tu-api-key-aqui

# Opcional: audit trail centralizado
SUPABASE_URL=https://lozdcwaeynloidrkeqfn.supabase.co
SUPABASE_SERVICE_KEY=tu-service-key-aqui
EOF
chmod 600 ~/.config/puya-odoo-mcp/credentials
```

El archivo de credenciales se lee al iniciar el MCP. Claude Code nunca ve el API key.

Variables de entorno (`ODOO_URL`, `ODOO_DB`, `ODOO_LOGIN`, `ODOO_API_KEY`) funcionan como fallback si no existe el archivo.

### Configurar en Claude Code

Agregar en `.mcp.json` (global o de proyecto):

```json
{
  "mcpServers": {
    "odoo": {
      "command": "python",
      "args": ["-m", "puya_odoo_mcp"]
    }
  }
}
```

## Roles

Los roles se asignan en Odoo por un admin humano: **Ajustes > Usuarios > campo MCP Role** (requiere modo debug). El campo `x_mcp_role` no se puede modificar via MCP — esta protegido en codigo.

### vendedor (lectura propia)

Solo puede leer registros que le pertenecen. No puede escribir, crear ni ejecutar metodos.

| Modelo | Operaciones | Restricciones |
|--------|------------|---------------|
| res.partner | search, read | Solo sus clientes (`user_id = uid`). No ve: credit_limit, payment_terms |
| sale.order | search, read | Solo sus ordenes (`user_id = uid`) |
| sale.order.line | search, read | Sin restriccion de dominio |
| product.product | search, read | No ve: standard_price, seller_ids |
| product.template | search, read | No ve: standard_price, seller_ids |
| account.move | search, read | Solo sus facturas (`invoice_user_id = uid`) |

### administrativo (lectura + escritura controlada)

Puede leer y escribir en modelos de negocio. Puede ejecutar metodos especificos (confirmar ventas, publicar facturas).

| Modelo | Operaciones | Restricciones |
|--------|------------|---------------|
| res.partner | search, read, write, create | Sin restriccion de dominio |
| sale.order | search, read, write, create | - |
| sale.order.line | search, read, write, create | - |
| account.move | search, read, write, create | - |
| account.payment | search, read, write, create | - |
| stock.picking | search, read, write | No puede crear |
| stock.move | search, read | Solo lectura |
| stock.quant | search, read | Solo lectura |
| product.product | search, read, write | No ve/escribe: standard_price |
| product.template | search, read, write | No ve/escribe: standard_price |
| purchase.order | search, read | Solo lectura |

**Metodos permitidos:**
- `sale.order:action_confirm` (confirmar venta)
- `account.move:action_post` (publicar factura)
- `account.payment:action_post` (publicar pago)

### developer (acceso total)

Acceso a todos los modelos y metodos. Unico rol que puede eliminar registros y consultar el audit log de todos los usuarios.

## Seguridad

### Capas de proteccion

| Capa | Que protege | Como |
|------|------------|------|
| **Credenciales ocultas** | API key no expuesta a Claude | Archivo con permisos 600, no en env vars |
| **RBAC en codigo** | Acciones restringidas por rol | `permissions.yaml` + `INFRA_BLOCKED_MODELS` hardcodeado |
| **Modelos de infraestructura bloqueados** | No se puede tocar la seguridad de Odoo | `res.users`, `res.groups`, `ir.config_parameter`, `ir.rule`, `ir.model.access`, `ir.module.module`, `ir.cron`, `base.automation` — bloqueados para todo rol que no sea developer |
| **Campo de rol protegido** | No se puede escalar privilegios | `x_mcp_role` esta en `PROTECTED_FIELDS` — ningun rol puede escribirlo via MCP |
| **Ownership en lectura** | Vendedor no lee registros ajenos | `odoo_read` valida que los IDs pertenezcan al usuario si hay domain_filter |
| **Permisos nativos de Odoo** | Segunda barrera independiente | Aunque se bypasee el MCP, el API key solo puede lo que Odoo permite |
| **Audit trail** | Trazabilidad y rollback | Cada write/create/delete/execute queda en Supabase con before/after |

### Que NO se puede hacer via MCP

- Cambiar el rol de ningun usuario (`x_mcp_role` protegido)
- Acceder a `res.users`, `ir.config_parameter`, etc. (salvo developer)
- Un vendedor no puede leer registros de otros vendedores, ni por search ni por ID directo
- Un administrativo no puede eliminar registros
- Ningun rol puede ejecutar metodos que no esten en su whitelist

## Audit trail

Cada operacion de escritura (write, create, delete, execute) se registra en la tabla `mcp_audit_log` de Supabase con:

| Campo | Contenido |
|-------|-----------|
| id | ID auto-incremental |
| created_at | Timestamp |
| user_login | Email del usuario que hizo la accion |
| role | Rol del usuario al momento de la accion |
| action | write, create, unlink, execute |
| model | Modelo de Odoo afectado |
| record_ids | IDs de registros tocados |
| old_values | Snapshot ANTES del cambio (JSON) |
| new_values | Lo que se escribio (JSON) |
| duration_ms | Duracion de la operacion |
| reverted | Si la accion fue revertida |

### Consultar el audit log

El tool `odoo_audit_log` permite consultar el historial:

- **Vendedor/administrativo**: solo ven sus propias acciones
- **Developer**: ve las acciones de todos, puede filtrar por usuario

```
odoo_audit_log(model="res.partner")           # ultimos writes a partners
odoo_audit_log(action="unlink")               # ultimos deletes
odoo_audit_log(audit_id=42)                   # entrada especifica con before/after
odoo_audit_log(user_login="juan@empresa.cl")  # acciones de un usuario (solo developer)
```

### Rollback

Con el audit log se puede revertir cualquier write:

1. Consultar la entrada: `odoo_audit_log(audit_id=15)`
2. Leer `old_values` para ver el estado anterior
3. Aplicar los valores originales: `odoo_write(model, ids, old_values)`

## Tools disponibles

| Tool | Roles | Descripcion |
|------|-------|-------------|
| `odoo_search` | todos | Buscar registros con filtros |
| `odoo_count` | todos | Contar registros |
| `odoo_read` | todos | Leer registros por ID (con ownership check) |
| `odoo_fields` | todos | Inspeccionar campos de un modelo |
| `odoo_write` | admin, dev | Actualizar registros (con audit before/after) |
| `odoo_create` | admin, dev | Crear registros (con audit) |
| `odoo_execute` | admin, dev | Ejecutar metodos del modelo (whitelist) |
| `odoo_delete` | dev | Eliminar registros (con snapshot previo) |
| `odoo_audit_log` | todos (scoped) | Consultar historial de acciones |

## Tests

```bash
pip install -e ".[dev]"
pytest
```

## Configuracion de roles

Los permisos por rol se configuran en `permissions.yaml`. Para agregar un modelo o metodo:

```yaml
roles:
  administrativo:
    models:
      nuevo.modelo:
        operations: [search_read, write]
        fields_denied: [campo_sensible]
    methods_allowed:
      - "nuevo.modelo:action_something"
```

Los modelos de infraestructura (`INFRA_BLOCKED_MODELS`) estan hardcodeados en `rbac.py` y no se pueden desbloquear desde el YAML para roles que no sean developer.
