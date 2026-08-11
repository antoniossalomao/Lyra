"""
lyra_telegram.py — Bot Telegram bidirecional para a Lyra.

Recebe mensagens do Telegram e encaminha para o cerebro_maestro.py (:8000/chat),
coletando os chunks SSE e devolvendo a resposta completa.

SETUP:
  1. Fale com @BotFather no Telegram → /newbot → copie o token
  2. Adicione ao .env:  TELEGRAM_BOT_TOKEN=<seu_token>
  3. Rode: python lyra_telegram.py
  4. Procure seu bot no Telegram e envie /start

FUNCIONALIDADES:
  - /start — mensagem de boas-vindas
  - Qualquer texto → resposta da Lyra
  - Foto/imagem → enviada para analisar_imagem (Gemini Vision)
  - "🎤" indicador de processamento enquanto Lyra pensa

MODOS DE SEGURANÇA:
  - TELEGRAM_ALLOWED_USERS: IDs separados por vírgula (OBRIGATÓRIO — vazio = bot recusa iniciar, default-deny desde 03/08/2026)
"""

import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import asyncio
import json
import os
import tempfile
import urllib.request
import urllib.error

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

LYRA_URL      = "http://127.0.0.1:8000"
BOT_TOKEN     = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USERS = set(
    int(x.strip()) for x in os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")
    if x.strip().isdigit()
)


# ── Comunicação com a Lyra ───────────────────────────────────────────────────

def _lyra_chat_sync(texto: str, modelo: str = "auto") -> str:
    """Chama /chat (SSE streaming) e coleta todos os chunks."""
    payload = json.dumps({"texto": texto, "modelo": modelo}).encode()
    req = urllib.request.Request(
        f"{LYRA_URL}/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    chunks = []
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n\r")
                if line.startswith("data: "):
                    chunk = line[6:]
                    if chunk not in ("[DONE]", ""):
                        chunks.append(chunk)
    except Exception as e:
        return f"[Erro ao contactar Lyra: {e}]"
    return "".join(chunks).strip() or "[Lyra não respondeu]"


def _lyra_tool_sync(nome: str, args: dict) -> dict:
    """Chama /tool/<nome> diretamente."""
    payload = json.dumps(args).encode()
    req = urllib.request.Request(
        f"{LYRA_URL}/tool/{nome}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"erro": str(e)}


# ── Handlers ─────────────────────────────────────────────────────────────────

async def cmd_start(update, context):
    await update.message.reply_text(
        "Oi! Sou a Lyra, sua IA pessoal. 🌟\n"
        "Pode me mandar mensagens de texto ou fotos aqui que respondo normalmente.\n"
        "Dúvidas? É só perguntar."
    )


async def handle_text(update, context):
    user_id = update.effective_user.id
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await update.message.reply_text("Acesso não autorizado.")
        return

    texto = update.message.text or ""
    if not texto.strip():
        return

    msg_aguarde = await update.message.reply_text("⏳ Pensando...")

    loop = asyncio.get_event_loop()
    resposta = await loop.run_in_executor(None, _lyra_chat_sync, texto)

    await msg_aguarde.delete()

    # Telegram tem limite de 4096 chars por mensagem
    for i in range(0, len(resposta), 4000):
        await update.message.reply_text(resposta[i:i+4000])


async def handle_photo(update, context):
    user_id = update.effective_user.id
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await update.message.reply_text("Acesso não autorizado.")
        return

    msg_aguarde = await update.message.reply_text("📷 Analisando imagem...")

    # Baixa a maior versão da foto
    foto = update.message.photo[-1]
    file = await context.bot.get_file(foto.file_id)

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name

    await file.download_to_drive(tmp_path)

    legenda = update.message.caption or "Descreva detalhadamente o que aparece nesta imagem."

    loop = asyncio.get_event_loop()
    resultado = await loop.run_in_executor(
        None, lambda: _lyra_tool_sync("analisar_imagem", {"path": tmp_path, "pergunta": legenda})
    )

    await msg_aguarde.delete()

    if resultado.get("ok"):
        resposta = resultado.get("descricao", "[sem descrição]")
    else:
        resposta = f"Erro ao analisar imagem: {resultado.get('erro', 'desconhecido')}"

    await update.message.reply_text(resposta[:4000])

    try:
        os.unlink(tmp_path)
    except Exception:
        pass


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        print("[ERRO] TELEGRAM_BOT_TOKEN não definido no .env")
        print("  1. Fale com @BotFather no Telegram → /newbot → copie o token")
        print("  2. Adicione ao .env:  TELEGRAM_BOT_TOKEN=<token>")
        return

    from telegram.ext import Application, CommandHandler, MessageHandler, filters

    print(f"[Lyra Telegram] Iniciando bot (polling)...")
    print(f"[Lyra Telegram] Lyra URL: {LYRA_URL}")
    if ALLOWED_USERS:
        print(f"[Lyra Telegram] Usuários permitidos: {ALLOWED_USERS}")
    else:
        # Default-deny (03/08/2026): antes o allowlist vazio liberava QUALQUER
        # usuário do Telegram — bastava achar o bot pra comandar a Lyra com
        # todas as ferramentas (executar_comando incluso). Agora recusa subir.
        print("[ERRO] TELEGRAM_ALLOWED_USERS vazio — o bot NÃO vai iniciar.")
        print("  Sem allowlist, qualquer pessoa que achar o bot comanda a Lyra.")
        print("  1. Mande /start pro seu bot e veja seu ID em @userinfobot")
        print("  2. Adicione ao .env:  TELEGRAM_ALLOWED_USERS=<seu_id>")
        return

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("[Lyra Telegram] Bot rodando. Ctrl+C para parar.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
