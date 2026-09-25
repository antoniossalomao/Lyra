# Política de segurança

Projeto pessoal, single-user, roda local (127.0.0.1). Sem superfície pública
exposta por padrão.

## Reportar vulnerabilidade

Encontrou uma falha de segurança (vazamento de chave, bypass de auth,
injeção, etc)? Reporte direto, não abra Issue pública:

antonio.assuino.salomao@gmail.com

Inclua: passos pra reproduzir, impacto, versão/commit afetado. Resposta e
correção não têm SLA formal — projeto sem equipe dedicada.

## Escopo

- Não versionamos `.env`, chaves de API, ou credenciais OAuth (ver `.gitignore`).
- Serviços internos (Qdrant, SurrealDB, Ollama, embed_service) assumem rede
  confiável (localhost) — não foram hardened pra exposição na internet.
