# CLAUDE.md - Puya Odoo MCP

## Que es este proyecto

MCP server que conecta Claude Code con Odoo 16. Actua como middleware de seguridad: controla que puede hacer cada usuario segun su rol, muestra previews antes de ejecutar cambios, audita todo, y envia acciones masivas a Telegram para aprobacion.

## Onboarding — Guia para nuevos usuarios

Si alguien te pide ayuda para instalar el MCP, guialo con estos pasos:

### Paso 1: Instalar el paquete

```bash
git clone git@github.com:puya-tech/puya-odoo-mcp.git
cd puya-odoo-mcp
pip install -e .
```

### Paso 2: Generar API key en Odoo

Indicale al usuario que vaya a:
1. Odoo > Ajustes > Usuarios > su usuario > Preferencias
2. Sección "Claves API" > "Nueva clave API"
3. Nombre: "Claude Code" o similar
4. Copiar la clave generada (se muestra una sola vez)

### Paso 3: Crear archivo de credenciales

Los valores publicos (URL de Odoo, DB, Supabase URL, Telegram chat ID) ya vienen en `config/shared.env` dentro del repo. El usuario solo necesita agregar sus secretos:

```bash
mkdir -p ~/.config/puya-odoo-mcp
cat > ~/.config/puya-odoo-mcp/credentials << 'EOF'
ODOO_LOGIN=<EMAIL_DEL_USUARIO>
ODOO_API_KEY=<API_KEY_GENERADA_EN_PASO_2>
SUPABASE_SERVICE_KEY=<PEDIR_A_ADMIN>
TELEGRAM_BOT_TOKEN=<PEDIR_A_ADMIN>
EOF
chmod 600 ~/.config/puya-odoo-mcp/credentials
```

**El usuario debe reemplazar** los valores entre `<>`. Las credenciales de Supabase y Telegram son compartidas — pedirlas al admin del proyecto.

### Paso 4: Configurar en Claude Code

Agregar en `~/.mcp.json`:

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

### Paso 5: Verificar

Reiniciar Claude Code o correr `/mcp` para reconectar. Luego probar: "busca los ultimos 5 pedidos de venta".

### Problemas comunes

- **"Not authenticated"** — API key incorrecta o email incorrecto
- **"Missing config"** — falta alguna variable en el archivo de credenciales
- **"Permission denied"** — el usuario no tiene rol asignado en Odoo (pedir al admin que lo asigne)

---

## Stack tecnico

- Python 3.10+
- FastMCP (mcp >= 1.0.0)
- Odoo 16 via XML-RPC
- Supabase para audit trail y pending actions
- Telegram Bot API para notificaciones de aprobacion

## Estructura del proyecto

```
src/puya_odoo_mcp/
  server.py      — Registro de tools, flujo preview/confirm, logica principal
  rbac.py        — Motor de permisos (roles, modelos, operaciones, blocklist)
  audit.py       — Audit trail en Supabase (mutations + pending actions)
  config.py      — Lectura de credenciales (archivo > env vars)
  odoo_client.py — Cliente XML-RPC para Odoo
  telegram.py    — Envio de notificaciones a Telegram
  __main__.py    — Entry point (stdio transport)

permissions.yaml — Configuracion de roles, modelos, operaciones, threshold masivo
tests/           — Tests unitarios (88 tests)
```

## Donde se configura cada cosa

| Que | Donde | Quien puede cambiar |
|-----|-------|---------------------|
| Rol de un usuario | Odoo UI: Ajustes > Usuarios > MCP Role | Solo admin humano en Odoo |
| Modelos permitidos por rol | `permissions.yaml` | Developer con acceso al repo |
| Modelos de infra bloqueados | `rbac.py` > `INFRA_BLOCKED_MODELS` | Solo cambiando codigo |
| Campos protegidos | `rbac.py` > `PROTECTED_FIELDS` | Solo cambiando codigo |
| Threshold de masivas | `permissions.yaml` > `settings.massive_threshold` | Developer con acceso al repo |
| Credenciales de usuario | `~/.config/puya-odoo-mcp/credentials` | Cada usuario en su maquina |

## Comandos utiles

```bash
# Correr tests
pip install -e ".[dev]"
pytest

# Verificar sintaxis
python -m py_compile src/puya_odoo_mcp/server.py

# Probar conexion manual
python -c "from puya_odoo_mcp.config import Config; c = Config(); print(f'URL: {c.odoo_url}')"
```

## Convenciones

- **Commits:** `tipo(scope): descripcion` (feat, fix, refactor, docs, chore)
- **Tests:** Siempre correr `pytest` antes de push
- **Seguridad:** Nunca commitear credenciales. El archivo credentials tiene chmod 600 y esta en .gitignore
