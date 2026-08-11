# Instruções Manuais — Projeto Lyra

Coisas que precisam ser feitas manualmente (não podem ser automatizadas por segurança ou por precisar de browser/conta).

---

## 1. Telegram Bot

**O que é:** Bot bidirecional no Telegram — você manda mensagem pelo celular, a Lyra responde. Suporta texto e fotos.

**Como configurar:**

1. No Telegram, procure **@BotFather** e mande `/newbot`
2. Escolha um nome (ex: `Lyra Pessoal`) e um username (ex: `lyra_anton_bot`)
3. O BotFather vai te dar um token, tipo: `7123456789:AAGxxx...`
4. Abra o arquivo `.env` em `C:\Lyra_Project\Lyra_Ollama\.env` e preencha:
   ```
   TELEGRAM_BOT_TOKEN=7123456789:AAGxxx...
   ```
5. (Opcional) Para restringir o bot só ao seu usuário: no Telegram, mande uma mensagem para **@userinfobot** — ele retorna seu ID numérico. Cole em:
   ```
   TELEGRAM_ALLOWED_USERS=123456789
   ```

**Como iniciar:**
```
C:\Lyra_Project\bin\startup\start_telegram.bat
```
Ou direto no terminal:
```
python C:\Lyra_Project\Lyra_Ollama\lyra_telegram.py
```

---

## 2. Browser-use (Playwright Chromium) — ✅ FEITO (02/07/2026)

**O que é:** A ferramenta `navegar_web` da Lyra abre um Chromium real controlado por IA para sites que precisam de JS, login ou interação (coisa que `buscar_url` não alcança).

Chromium instalado e `lyra_browser.py` corrigido (API do `browser-use` tinha mudado + modelo Gemini sem quota) — ver `LYRA_TECNICO.md` seção 10.14 pra detalhes. Validado ao vivo, funcional.

---

## 3. Google Workspace (Gmail + Calendar)

**O que é:** Permite que a Lyra leia emails, crie rascunhos e veja/crie eventos no Google Calendar.

**Como configurar (uma vez só):**

1. Acesse [console.cloud.google.com](https://console.cloud.google.com/)
2. Crie um projeto novo (ou use um existente)
3. Ative as APIs:
   - **Gmail API**
   - **Google Calendar API**
4. Vá em **Credenciais → Criar credenciais → ID do cliente OAuth 2.0 → Aplicativo para computador**
5. Baixe o JSON gerado e salve em:
   ```
   C:\Lyra_Project\Lyra_Core\google_auth\credentials.json
   ```
6. Rode uma vez para autorizar (vai abrir o browser para login):
   ```
   python C:\Lyra_Project\Lyra_Ollama\lyra_google_workspace.py
   ```
   Isso gera o `token.json` automaticamente — depois nunca mais precisa repetir.

---

## 4. Screenpipe (gravação contínua de tela)

**O que é:** Grava tela e áudio continuamente em `D:\Lyra_Vault\Screenpipe\` para contexto histórico. Expõe MCP em `:3030`.

**Como instalar:**
```
npm install -g @screenpipe/cli
```

**Como iniciar:**
```
C:\Lyra_Project\bin\startup\start_screenpipe.bat
```

**Após instalar**, adicione a linha abaixo no `lyra_boot.vbs` (junto com os outros `Shell`):
```vbscript
Shell "C:\Lyra_Project\bin\startup\start_screenpipe.bat"
```

---

## 5. SurrealDB — Atualização

**O que é:** O banco de dados principal da Lyra. Tem uma versão nova disponível.

**Como atualizar (pare a Lyra antes):**

1. Feche tudo da Lyra (ou rode o stop_lyra se tiver)
2. Abra PowerShell como administrador e rode:
   ```
   winget upgrade SurrealDB.SurrealDB --accept-source-agreements --accept-package-agreements
   ```
3. Inicie a Lyra novamente normalmente

---

## 6. MCP no Claude Code (opcional)

**O que é:** Conecta o Claude Code (este assistente aqui) diretamente aos endpoints da Lyra como ferramentas MCP. Permite que eu consulte sua memória, busque RAG, etc.

**Como configurar:**

Abra as configurações do Claude Code (`~\.claude\settings.json`) e adicione:
```json
{
  "mcpServers": {
    "lyra": {
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

O MCP já está rodando em `http://127.0.0.1:8000/mcp` — só precisa registrar no cliente.

---

## 7. Telegram — Adicionar ao boot automático (após configurar)

Depois de testar e confirmar que o bot funciona, adicione ao `lyra_boot.vbs`:
```vbscript
Shell "C:\Lyra_Project\bin\startup\start_telegram.bat"
```

---

## Resumo rápido

| # | Tarefa | Urgente? |
|---|--------|----------|
| 1 | Criar bot no @BotFather + preencher `.env` | Sim (pra usar Telegram) |
| 2 | ~~`python -m playwright install chromium`~~ | ✅ Feito 02/07/2026 |
| 3 | Configurar OAuth Google + rodar `lyra_google_workspace.py` | Quando quiser usar Gmail/Calendar |
| 4 | `npm install -g @screenpipe/cli` | Quando quiser gravação contínua |
| 5 | Atualizar SurrealDB via winget | Quando puder reiniciar a Lyra |
| 6 | Registrar MCP no Claude Code settings.json | Quando quiser integração direta |
| 7 | Adicionar Telegram e Screenpipe ao lyra_boot.vbs | Após testar cada um |
