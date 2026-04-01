# puya-odoo-mcp

MCP server para Odoo 16 con control de acceso por roles (RBAC), audit trail centralizado en Supabase, previews de confirmacion y aprobaciones externas via Telegram.

## Como funciona

Cada trabajador se conecta a Odoo a traves de este MCP usando sus propias credenciales. El MCP actua como middleware de seguridad entre Claude Code y Odoo.

```
Trabajador instala Claude Code + MCP
    -> Ingresa SUS credenciales de Odoo (archivo local, no visible para Claude)
    -> MCP lee x_mcp_role de SU usuario en Odoo
    -> Solo ve los tools que su rol permite
    -> No puede cambiar su propio rol (campo protegido en codigo)
    -> No puede acceder a modelos de infraestructura de Odoo
    -> Todo write muestra un preview antes de ejecutar
    -> Acciones masivas (>10 registros) se bloquean y van a Telegram para aprobacion
    -> Cada accion de escritura queda registrada con snapshot before/after
```

---

## Instalacion paso a paso

### 1. Requisitos previos

- Python 3.10+
- Claude Code instalado
- Modulo `puya_mcp_access` instalado en Odoo (agrega campo `x_mcp_role` a usuarios)
- API key de Odoo del usuario (Ajustes > Usuarios > Preferencias > Claves API)

### 2. Clonar e instalar

```bash
git clone git@github.com:puya-tech/puya-odoo-mcp.git
cd puya-odoo-mcp
pip install -e .
```

### 3. Configurar credenciales

Cada usuario crea su propio archivo de credenciales:

```bash
mkdir -p ~/.config/puya-odoo-mcp
cat > ~/.config/puya-odoo-mcp/credentials << 'EOF'
ODOO_URL=https://cmcorpcl-puyacentro.odoo.com
ODOO_DB=cmcorpcl-costasurmat-main-7982838
ODOO_LOGIN=tu-email@empresa.cl
ODOO_API_KEY=tu-api-key-de-odoo

# Audit trail centralizado (pedir a admin)
SUPABASE_URL=https://lozdcwaeynloidrkeqfn.supabase.co
SUPABASE_SERVICE_KEY=la-service-key-de-supabase

# Notificaciones de aprobacion (pedir a admin)
TELEGRAM_BOT_TOKEN=token-del-bot
TELEGRAM_CHAT_ID=id-del-grupo
EOF
chmod 600 ~/.config/puya-odoo-mcp/credentials
```

**Importante:** El archivo tiene permisos 600 (solo el usuario puede leerlo). Claude Code nunca ve el API key ni las credenciales.

### 4. Configurar en Claude Code

Agregar en `~/.mcp.json` (global) o en `.mcp.json` del proyecto:

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

### 5. Verificar

Abrir Claude Code y preguntar algo como "busca los ultimos 5 pedidos de venta". Si el MCP esta bien configurado, Claude usara `odoo_search` automaticamente.

---

## Roles

Los roles se asignan en Odoo por un admin humano: **Ajustes > Usuarios > campo MCP Role** (requiere modo debug/desarrollador). El campo `x_mcp_role` no se puede modificar via MCP — esta protegido en codigo.

Si un usuario no tiene rol asignado, se le asigna `vendedor` por defecto (el mas restrictivo).

### vendedor

Solo lectura de sus propios registros. No puede escribir, crear, eliminar ni ejecutar metodos.

| Modelo | Puede hacer | Restricciones |
|--------|------------|---------------|
| res.partner | Buscar, leer | Solo sus clientes (`user_id = uid`). No ve: credit_limit, payment_terms |
| sale.order | Buscar, leer | Solo sus ordenes (`user_id = uid`) |
| sale.order.line | Buscar, leer | — |
| product.product | Buscar, leer | No ve: standard_price (costo), seller_ids (proveedores) |
| product.template | Buscar, leer | No ve: standard_price, seller_ids |
| account.move | Buscar, leer | Solo sus facturas (`invoice_user_id = uid`) |
| Cualquier otro modelo | Nada | Acceso denegado |

### administrativo

Lectura y escritura en modelos de negocio. Puede ejecutar metodos especificos.

| Modelo | Puede hacer | Restricciones |
|--------|------------|---------------|
| res.partner | Buscar, leer, escribir, crear | — |
| sale.order | Buscar, leer, escribir, crear | — |
| sale.order.line | Buscar, leer, escribir, crear | — |
| account.move | Buscar, leer, escribir, crear | — |
| account.payment | Buscar, leer, escribir, crear | — |
| stock.picking | Buscar, leer, escribir | No puede crear |
| stock.move | Buscar, leer | Solo lectura |
| stock.quant | Buscar, leer | Solo lectura |
| product.product | Buscar, leer, escribir | No ve/escribe: standard_price |
| product.template | Buscar, leer, escribir | No ve/escribe: standard_price |
| purchase.order | Buscar, leer | Solo lectura |

**Metodos permitidos:**
- `sale.order:action_confirm` — confirmar venta
- `account.move:action_post` — publicar factura
- `account.payment:action_post` — publicar pago

**Acciones masivas (>10 registros):** Se bloquean y se envian a Telegram para aprobacion.

### developer

Acceso completo a todos los modelos y metodos. Unico rol que puede eliminar registros. Puede confirmar acciones masivas sin aprobacion externa. Puede consultar el audit log de todos los usuarios.

---

## Tools (comandos disponibles)

### Lectura (todos los roles)

#### `odoo_search`
Busca registros con filtros. Respeta domain_filter del rol (vendedor solo ve lo suyo).

```
"busca clientes que sean empresa"
→ odoo_search(model="res.partner", domain=[["is_company","=",true]])
```

Parametros:
- `model` — nombre del modelo (ej: `res.partner`, `sale.order`)
- `domain` — filtro de busqueda estilo Odoo (ej: `[["state","=","sale"]]`)
- `fields` — campos a devolver (ej: `["name","email"]`). Vacio = todos los permitidos
- `limit` — maximo de registros (default 80, max 200)
- `offset` — saltar N registros (paginacion)
- `order` — ordenamiento (ej: `"create_date desc"`)

#### `odoo_count`
Cuenta registros que cumplen un filtro. Util para saber cuantos hay antes de buscar.

```
"cuantos pedidos hay en estado borrador?"
→ odoo_count(model="sale.order", domain=[["state","=","draft"]])
```

#### `odoo_read`
Lee registros especificos por ID. Si el rol tiene domain_filter, valida que los IDs pertenezcan al usuario.

```
"lee los datos del partner 1234"
→ odoo_read(model="res.partner", ids=[1234], fields=["name","email","phone"])
```

#### `odoo_fields`
Inspecciona los campos de un modelo. Util para saber que campos existen antes de buscar o escribir.

```
"que campos tiene el modelo sale.order?"
→ odoo_fields(model="sale.order")
```

Devuelve: nombre del campo, tipo, si es requerido, si es readonly.

### Escritura (administrativo y developer)

**Todas las acciones de escritura usan el flujo de dos fases: preview → confirmacion.**

#### `odoo_write`
Actualiza registros. Primero muestra un preview con los cambios propuestos (valor actual → valor nuevo). No se ejecuta hasta que se confirma.

```
"cambia el email del cliente 1234 a nuevo@email.com"
→ odoo_write(model="res.partner", ids=[1234], values={"email":"nuevo@email.com"})

Respuesta (NO se ejecuto aun):
  Cambios en res.partner (1 registro):
    Registro #1234 (ACME Corp):
      email: viejo@email.com -> nuevo@email.com

  pending_id: 42

→ Usuario dice "ok" → odoo_confirm(pending_id=42) → se ejecuta
```

Parametros:
- `model` — modelo a modificar
- `ids` — lista de IDs a actualizar
- `values` — diccionario campo:valor
- `reason` — razon del cambio (requerido para acciones masivas)

#### `odoo_create`
Crea un nuevo registro. Muestra preview antes de crear.

```
"crea un nuevo contacto llamado Juan Perez"
→ odoo_create(model="res.partner", values={"name":"Juan Perez","email":"juan@email.com"})
```

#### `odoo_execute`
Ejecuta un metodo de un modelo (solo metodos en la whitelist del rol). Muestra preview antes.

```
"confirma el pedido S00456"
→ odoo_execute(model="sale.order", method="action_confirm", args=[[456]])
```

#### `odoo_delete` (solo developer)
Elimina registros. Guarda snapshot completo del registro antes de eliminar.

### Control de flujo

#### `odoo_confirm`
Confirma y ejecuta una accion pendiente despues de que el usuario aprobo el preview.

```
odoo_confirm(pending_id=42)
```

- Si la accion es masiva y el usuario no es developer: **rechazada** (requiere aprobacion via Telegram)
- Si ya fue confirmada o cancelada: informa el estado actual
- Solo el usuario que creo la accion puede confirmarla

#### `odoo_cancel`
Cancela una accion pendiente. Usarlo si el usuario dice "no" al preview.

```
odoo_cancel(pending_id=42)
```

### Auditoria

#### `odoo_audit_log`
Consulta el historial de acciones. Cada rol solo ve sus propias acciones (developer ve todas).

```
"que cambios se hicieron hoy?"
→ odoo_audit_log(limit=20)

"que writes se hicieron a productos?"
→ odoo_audit_log(model="product.template", action="write")

"dame el detalle del audit #7"
→ odoo_audit_log(audit_id=7)

"que hizo juan@empresa.cl?" (solo developer)
→ odoo_audit_log(user_login="juan@empresa.cl")
```

---

## Flujo de dos fases (preview → confirm)

Toda accion de escritura (write, create, execute, delete) pasa por este flujo:

```
1. Claude llama odoo_write/create/execute/delete
   → NO se ejecuta. Se genera un preview legible.

2. Claude muestra el preview al usuario:
   "Se va a cambiar el email de ACME Corp de viejo@x.com a nuevo@x.com"

3. El usuario decide:
   → "Si, dale" → Claude llama odoo_confirm(pending_id) → Se ejecuta + audit trail
   → "No" → Claude llama odoo_cancel(pending_id) → Se cancela
```

Esto permite que el usuario siempre vea exactamente que se va a hacer antes de que pase.

---

## Acciones masivas

Si una accion afecta mas de 10 registros (configurable en `permissions.yaml`):

**Para developer:** Preview normal, puede confirmar directamente.

**Para administrativo:** La accion se bloquea y se envia una solicitud de aprobacion al grupo de Telegram.

```
1. Administrativo pide "actualiza el precio de todos los productos de la marca X"
2. MCP genera preview + guarda pending_action en Supabase
3. MCP envia notificacion a Telegram con preview + botones Aprobar/Rechazar
4. Claude le dice al usuario: "Tu solicitud fue enviada para aprobacion"

5. Aprobador en Telegram ve el mensaje con detalle y clickea:
   → "Aprobar" → Se ejecuta automaticamente contra Odoo → Mensaje actualizado
   → "Rechazar" → Se cancela → Mensaje actualizado
```

El usuario puede cerrar Claude Code tranquilo — la ejecucion la hace el agente centralizado en Vercel cuando se aprueba.

El threshold de 10 registros se configura en `permissions.yaml`:
```yaml
settings:
  massive_threshold: 10
```

---

## Seguridad

### Capas de proteccion

| Capa | Que protege |
|------|------------|
| **Credenciales ocultas** | API key en archivo 600, no visible para Claude |
| **RBAC por rol** | Cada rol solo ve los tools y modelos que le corresponden |
| **Modelos de infraestructura bloqueados** | `res.users`, `res.groups`, `ir.config_parameter`, `ir.rule`, `ir.model.access`, `ir.module.module`, `ir.cron`, `base.automation` — bloqueados para todo rol que no sea developer |
| **Campo de rol protegido** | `x_mcp_role` no se puede escribir via MCP, ni siquiera como developer |
| **Ownership en lectura** | Vendedor no puede leer registros ajenos ni por search ni por ID directo |
| **Preview obligatorio** | Todo write muestra que va a cambiar antes de ejecutar |
| **Bloqueo de masivas** | Acciones >10 registros requieren aprobacion externa para no-developer |
| **Permisos nativos de Odoo** | Segunda barrera: el API key solo puede lo que Odoo permite |
| **Audit trail** | Todo queda registrado con before/after para trazabilidad y rollback |

### Que NO se puede hacer via MCP

- Cambiar el rol de ningun usuario
- Acceder a configuracion interna de Odoo (salvo developer)
- Un vendedor no puede ver datos de otros vendedores
- Un administrativo no puede eliminar registros
- Nadie puede ejecutar metodos que no esten en su whitelist
- Acciones masivas no se pueden confirmar sin aprobacion (salvo developer)

---

## Audit trail

Cada write/create/delete/execute queda en `mcp_audit_log` (Supabase) con:

| Campo | Contenido |
|-------|-----------|
| user_login | Quien hizo la accion |
| role | Con que rol |
| action | write, create, unlink, execute |
| model | Modelo afectado |
| record_ids | IDs de registros tocados |
| old_values | Valores ANTES del cambio |
| new_values | Lo que se escribio |
| details | Metadata adicional (reason, approved_by, etc.) |

Para rollback: consultar `old_values` del audit entry y aplicarlos con `odoo_write`.

---

## Configuracion

### Agregar modelos o metodos a un rol

Editar `permissions.yaml`:

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

### Cambiar el threshold de acciones masivas

```yaml
settings:
  massive_threshold: 20  # ahora requiere >20 registros
```

### Asignar rol a un usuario

En Odoo: Ajustes > Usuarios > seleccionar usuario > campo "MCP Role" (requiere modo debug).

### Generar API key para un usuario

En Odoo: Ajustes > Usuarios > seleccionar usuario > Preferencias > Claves API > Nueva clave.

---

## Tests

```bash
pip install -e ".[dev]"
pytest
```

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│  Claude Code (local del usuario)                             │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  MCP Server (puya-odoo-mcp)                             │ │
│  │                                                          │ │
│  │  credentials → Config → OdooClient → Odoo XML-RPC       │ │
│  │                   ↓                                      │ │
│  │              RBACEngine → permissions.yaml               │ │
│  │                   ↓                                      │ │
│  │  Tools: search, count, read, fields                     │ │
│  │         write, create, execute, delete (preview+confirm)│ │
│  │         confirm, cancel, audit_log                      │ │
│  │                   ↓                                      │ │
│  │  AuditLogger → Supabase (mcp_audit_log)                 │ │
│  │  TelegramNotifier → Telegram API (acciones masivas)     │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Vercel (puya-chat) — agente centralizado                    │
│                                                               │
│  /api/approvals/telegram-callback                            │
│      ↓                                                        │
│  Inngest: approval/execute → Odoo JSON-RPC → mcp_audit_log  │
│  Inngest: approval/reject → cancela pending_action           │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Supabase — estado centralizado                              │
│                                                               │
│  mcp_audit_log — registro de todas las acciones con b/a     │
│  mcp_pending_actions — acciones pendientes de confirmacion   │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Telegram — grupo PuyaAppovals                               │
│                                                               │
│  Bot @AIPuyaBot envia solicitudes con botones                │
│  Aprobadores clickean → callback a Vercel → ejecuta          │
└─────────────────────────────────────────────────────────────┘
```
