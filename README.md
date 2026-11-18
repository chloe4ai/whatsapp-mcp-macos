# whatsapp-mcp-macos

An MCP server that lets Claude read and send **your own personal WhatsApp** on macOS, without an unofficial protocol client.

- **Reading** opens WhatsApp Desktop's local SQLite store read-only. It is not encrypted on disk, so there is no key extraction step.
- **Sending** goes through the official app with its `whatsapp://send` URL scheme. By default it only types a draft; you press Return.

中文简介见[文末](#中文简介)。

> **Status: v0.1, early.** The test suite runs against a synthetic database built from WhatsApp's known table layout. It has not yet been confirmed against a live WhatsApp Desktop store.

## Why not the existing options

| Option | What it is | Why it didn't fit |
|---|---|---|
| Meta's WhatsApp Business Tools MCP (Sept 2026) | Official. Phone onboarding, templates, webhooks, test messages for the Business Platform | Business accounts and developer setup only. It can't read a personal account's chats |
| Community servers on whatsmeow / Baileys | Register as a linked device and speak the WhatsApp Web protocol | Unofficial client, against WhatsApp's terms, and accounts do get restricted |
| **This** | Reads what the official desktop app already stored; sends through that app | Only sees what the desktop app has synced; macOS only |

## Tools

| Tool | What it does |
|---|---|
| `get_status` | Is the database readable, how many chats/messages, newest message time |
| `list_chats` | Chats by recent activity, optional name filter |
| `list_groups` | Group chats only |
| `read_messages` | One chat by name, phone or JID, with optional `since` / `until` |
| `search` | Text search across all chats or one |
| `check_new` | Incoming messages since the last call (checkpoint in `~/.whatsapp-mcp/state.json`) |
| `send` | Draft a message to one person; `confirm_send=true` also presses Return |

## Setup

1. Install **WhatsApp** from the Mac App Store, link it to your phone, and let it sync.
2. Grant **Full Disk Access** to the app that will launch the server (Claude, or your terminal): System Settings > Privacy & Security > Full Disk Access. Quit and reopen that app afterwards. The database lives in another app's group container, and macOS blocks that even for root.
3. Only if you want `confirm_send=true`: grant the same app **Accessibility**, so it can press Return.
4. Register the server. From a clone of this repo:

```bash
pipx install .
```

Then in `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "whatsapp": { "command": "/Users/YOU/.local/bin/whatsapp-mcp-macos" }
  }
}
```

Or for Claude Code:

```bash
claude mcp add whatsapp -- whatsapp-mcp-macos
```

Ask Claude to run `get_status` first. If it says macOS blocked the read, step 2 isn't in effect yet.

## Limits

- **History depth.** The desktop app only holds what it synced from the phone, and only receives new messages while it is running.
- **No group sending.** The URL scheme addresses a phone number, nothing else. Contacts WhatsApp only knows by a privacy ID (`@lid`) need their number passed explicitly.
- **Media** shows up as `[image] caption`, `[voice] 12s` and so on. Files are not returned.
- **Schema.** Table and column names (`ZWACHATSESSION`, `ZWAMESSAGE`, ...) are WhatsApp's Core Data store and can change between app versions. The server checks which columns exist, but a larger change would need an update here.
- **Sent confirmation.** After `confirm_send=true` the tool reports that Return was pressed, not that WhatsApp delivered. Read the chat back to confirm.

## Tests

The suite builds a synthetic database, so it needs no WhatsApp data:

```bash
uv run --with pytest pytest
```

## 中文简介

让 Claude 读、发你自己的个人 WhatsApp（仅 macOS）。读消息是只读打开 WhatsApp 桌面版的本地数据库（未加密，不用提取密钥）；发消息走官方 App 的 `whatsapp://send`，默认只把草稿填进输入框，由你自己按回车，传 `confirm_send=true` 才会代按。

不走非官方协议，所以没有封号风险；代价是只能看到桌面版已经同步下来的消息，且不能往群里发。使用前需要给启动它的 App（Claude 或终端）开「完全磁盘访问权限」，要代按回车的话再开「辅助功能」。

## License

MIT
