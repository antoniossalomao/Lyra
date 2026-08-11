# LYRA IDE — Plano Completo
> Criado em 10/08/2026. Decisão tomada com o Antônio: base = Eclipse Theia.

---

## 1. Objetivo

Transformar a Lyra num app desktop no formato IDE, visualmente e funcionalmente o mais parecido possível com o VSCode, com suporte ao máximo de extensões úteis pra programador. A Lyra deixa de ser só um chat flutuante (pywebview) e passa a viver dentro da IDE como painel/assistente nativo, com acesso ao editor, arquivos do projeto aberto, terminal, etc.

---

## 2. Decisão de arquitetura

**Escolhido: Eclipse Theia** (Apache/EPL, open source), rodando em target Electron.

Motivo (comparado com as 3 opções avaliadas):

| Opção | Prós | Contras | Veredito |
|---|---|---|---|
| **Eclipse Theia** | Framework feito exatamente pra isso — clona UI/UX do VSCode, usa Monaco (mesmo editor), extension host compatível com VSIX via Open VSX Registry, target Electron pronto | Não é 100% idêntico ao VSCode em edge cases raros de extensão | **Escolhida** — menor esforço, licença sem risco, manutenção viável por 1 pessoa |
| Fork Code-OSS | Compatibilidade de extensão 100% idêntica ao VSCode real | Sincronizar com upstream constante, injetar UI da Lyra vira atrito em cada merge, extensões da MS Marketplace (C/C++, Python oficial) proíbem uso fora do VSCode/VS real por EULA | Descartada |
| Electron + Monaco do zero | Controle total | Reimplementar file tree, terminal, debug adapter protocol, command palette, extension host inteiro — meses de trabalho só pra igualar o que o Theia já entrega pronto | Descartada |

---

## 3. Princípios que se aplicam (Ring 0, já existentes no projeto)

- **100% offline por padrão continua valendo.** Única exceção nova pedida por este plano: acesso ao **Open VSX Registry** (marketplace de extensões) — mesmo espírito da exceção já aprovada pra cascata cloud (Groq→Gemini→Claude) em `LYRA_NUCLEO.md` §3. **Precisa aprovação explícita e formal do Antônio antes de ligar essa chamada de rede em produção.**
- Telemetria/update-checker padrão do Theia (se apontar pra fora) deve ser desligada — mesma regra de zero envio de dados sem aprovação.
- Toda auto-modificação de código da própria Lyra continua exigindo aprovação (não muda com a IDE).
- `core.py` continua somente leitura — a IDE não altera esse arquivo nem esse princípio.

---

## 4. Estrutura de diretórios proposta

```
C:\Lyra_Project\
├── Lyra_Ollama\              (backend Python, intocado)
├── Lyra_Core\
│   ├── Front_end_Lyra\       (v1 pywebview, intocado até troca final)
│   ├── Front_end_Lyra_v2\    (chat React standalone, vira base dos widgets da IDE)
│   └── Lyra_IDE\             (NOVO — projeto Theia)
│       ├── browser-app\      (build browser, opcional/debug)
│       ├── electron-app\     (build desktop — o entregável final)
│       └── extensions\
│           └── lyra-ide-core\  (extensão custom: painéis Lyra dentro da IDE)
```

---

## 5. Fases de implementação

### Fase A — Protótipo (validação do motor)
**Objetivo:** confirmar que Theia levanta como app desktop na máquina do Antônio e que extensões reais instalam.

Passos:
1. `yarn create theia-app` (ou clonar o `theia-cli` yeoman generator) dentro de `Lyra_Core\Lyra_IDE\`.
2. Gerar target `electron-app` (não só `browser-app`).
3. `yarn theia:electron` — subir localmente, confirmar boot.
4. Testar instalação de 1 extensão real via Open VSX (ex: `ms-python.python` equivalente aberto, ou `esbenp.prettier-vscode`) — confirmar que ativa e funciona (autocomplete, formatação).
5. Confirmar de fábrica: editor Monaco, file explorer, terminal integrado (via node-pty), busca global, painel git, command palette (Ctrl+Shift+P) — todos vêm prontos no Theia, só validar que sobem sem erro no Windows.

**Critério de sucesso:** app `.exe`/janela Electron abre, edita um arquivo `.py` com highlight correto, terminal integrado roda `python --version`, 1 extensão de teste instalada e ativa.

**Risco conhecido a testar:** node-pty e alguns módulos nativos do Theia às vezes têm fricção de build no Windows (node-gyp, Visual Studio Build Tools). Se acontecer, documentar o fix aqui mesmo.

---

### Fase B — Branding
**Objetivo:** a IDE parece da Lyra, não um Theia genérico.

Passos:
1. Trocar `applicationName`, ícone (`.ico`), splash screen no `package.json` raiz do Theia app.
2. Aplicar tema dark neon reaproveitando os tokens já validados no frontend v2 (`--neon: #00DDFF`, `--danger: #FF4466`, família Inter 200/300/500) — Theia suporta tema via VSCode theme JSON (`contributes.themes`), então dá pra portar direto.
3. Desligar/remover: update-checker padrão (aponta pra registry do Eclipse), qualquer telemetry endpoint default, links "About" que apontam pra Theia/Eclipse Foundation.
4. Nome do produto: decidir com o Antônio (ex: "Lyra IDE", "Lyra Studio") — placeholder até definição.

**Critério de sucesso:** janela abre com ícone/nome/tema da Lyra, nenhuma chamada de rede não aprovada disparada no boot (validar com captura de tráfego, mesmo teste headless já usado nas auditorias do frontend v2).

---

### Fase C — Ponte com o backend Lyra
**Objetivo:** a Lyra (chat, memória, voz) vive dentro da IDE como painel nativo, não mais só no pywebview separado.

Passos:
1. Criar extensão custom `extensions/lyra-ide-core/` seguindo o padrão de extensão Theia (`@theia/core` como peer dependency, contribui `WidgetFactory` + `FrontendApplicationContribution`).
2. Portar componentes React já prontos e validados do `Front_end_Lyra_v2` (`Chat.tsx`, `Sidebar.tsx`, `RightPanel.tsx`) — Theia usa React internamente pra widgets (via `ReactWidget` de `@theia/core/lib/browser`), então o componente em si não muda, só o wrapper de montagem.
3. Reaproveitar `api.ts` já existente (chamadas pro backend :8000) sem reescrever — mesmos endpoints:
   - `POST /chat` (SSE streaming)
   - `GET /historico`, `GET/PATCH/DELETE /sessoes`
   - `GET /metrics`, `GET /stats` (poll 4s)
   - `GET /buscar`
   - `GET /grafo/completo`
   - `POST /tts/mudo`, `POST /tts/falar`
   - `GET /integracoes`
   - `GET /exportar`
4. Registrar o painel de chat da Lyra como `ViewContainer` dockável (lateral direita ou esquerda, configurável pelo usuário como qualquer painel nativo do VSCode).
5. CORS do backend: já libera `http://127.0.0.1:5173` (Vite dev) — adicionar a origem do Electron app do Theia quando definida (Electron roda como `file://` ou origem custom, checar em runtime e ajustar `cerebro_maestro.py`).

**Critério de sucesso:** painel da Lyra abre dentro da IDE, manda mensagem, recebe streaming, histórico persiste — mesma funcionalidade do frontend v2 atual, só que embutida.

---

### Fase D — Features de IA na IDE (o que difere de só "ter o chat do lado")
**Objetivo:** a Lyra interage com o código que está aberto, não só conversa isolada.

Passos:
1. **Completion inline no editor** — Monaco expõe `registerInlineCompletionsProvider`; ligar num endpoint novo ou reusar `/chat` com prompt de completion, contexto = conteúdo do arquivo aberto + posição do cursor. Cascata Groq→Gemini→Claude→local já existe, só muda o prompt template.
2. **Menu de contexto "Perguntar à Lyra sobre isto"** — comando Theia registrado no menu de seleção do editor, manda a seleção de texto + linguagem detectada pro `/chat` ou `/agente` com prompt de análise.
3. **Botão de voz na toolbar** — Voice Live (`/ws/voice`, já implementado e validado) vira um `StatusBarItem` ou botão fixo na IDE, mesmo fluxo já testado no frontend v2.
4. **Painel do Grafo de Memória 3D** — portar como aba extra dockável, reaproveitando o código já validado (`3d-force-graph` + Three.js, vendorizado offline).
5. **Ação "Explicar erro"** — se o painel de Problems do Theia detectar erro de lint/build, botão que manda o erro + trecho de código pro `/agente` pedir explicação/fix sugerido (não aplica automaticamente — mostra sugestão, usuário aplica manualmente, respeita Ring 0 §5 de não auto-modificar sem aprovação).

**Critério de sucesso:** completar código com sugestão da Lyra funciona num arquivo `.py` real; perguntar sobre uma seleção de código retorna resposta coerente; grafo de memória abre dentro da IDE sem quebrar.

---

### Fase E — Empacotamento
**Objetivo:** instalador `.exe` Windows, pronto pra uso diário no PC do Antônio.

Passos:
1. Configurar `electron-builder` no `electron-app/` (target `nsis` pra Windows, ícone, nome, versão).
2. Testar build de produção (`yarn theia build && electron-builder`), instalar numa pasta limpa, confirmar boot sem dependência do ambiente de dev.
3. Auditoria de rede no build final (mesmo padrão da auditoria de segurança já feita no frontend v2 — captura de tráfego no boot): única chamada externa aceitável = Open VSX, só quando o usuário abrir o marketplace manualmente (não no boot automático).
4. Documentar processo de update (Theia/Electron não tem auto-update ligado por padrão — decisão: manual por enquanto, igual ao resto do projeto que já é 100% local).

**Critério de sucesso:** instalador roda em máquina limpa, app abre, conecta no backend Lyra (que já está rodando via `lyra_boot.vbs`), nenhuma chamada de rede fora do aprovado.

---

### Fase F — Curadoria de extensões pra programador
**Objetivo:** lista concreta de extensões recomendadas/pré-instaladas, cobrindo o que um programador usa no dia a dia.

| Categoria | Extensão (Open VSX) | Observação |
|---|---|---|
| Python | `ms-python.python` (checar EULA) ou alternativa `pylance`-like aberta | risco de licença, ver §6 |
| C/C++ | `llvm-vs-code-extensions.vscode-clangd` | alternativa aberta ao `ms-vscode.cpptools` |
| Lint/Format | `dbaeumer.vscode-eslint`, `esbenp.prettier-vscode` | sem risco de licença |
| Git | `eamodio.gitlens` | verificar versão compatível com Open VSX |
| Docker | `ms-azuretools.vscode-docker` (checar EULA) | mesma categoria de risco do Python/C++ |
| YAML/JSON | `redhat.vscode-yaml` | sem risco |
| Rust | `rust-lang.rust-analyzer` | sem risco, oficial já é aberto |
| Ícones | `pkief.material-icon-theme` | sem risco |
| REST/API | `humao.rest-client` | sem risco |
| Live preview | `ritwickdey.liveserver` (ou equivalente Open VSX) | sem risco |

**Decisão pendente:** extensões da própria Microsoft (Python, C/C++, Docker) têm EULA que tecnicamente restringe uso fora do VSCode/VS real — usar mesmo assim (risco baixo, uso pessoal) ou substituir por alternativas 100% abertas (`clangd` em vez de `cpptools`, etc.)? **Perguntar ao Antônio antes de empacotar essas extensões por padrão** — dá pra deixar como recomendação manual (usuário instala se quiser) em vez de pré-empacotado, evitando a questão de licença de vez.

---

## 6. Riscos e decisões abertas (resumo)

1. **Exceção de rede pro Open VSX** — precisa aprovação formal do Antônio (Ring 0 §3), igual foi feito pra cascata cloud.
2. **Licença de extensões MS-proprietárias** — decidir: usar mesmo assim, trocar por alternativa aberta, ou deixar como instalação manual opcional (recomendado, menor risco).
3. **Fricção de build nativo no Windows** (node-pty/node-gyp) — só se confirma na Fase A; se acontecer, documentar fix aqui.
4. **CORS do Electron app** — origem exata do Electron precisa ser descoberta em runtime na Fase C e adicionada ao `cerebro_maestro.py`.
5. **Nome final do produto** — placeholder "Lyra IDE", decidir com o Antônio na Fase B.
6. **Front_end_Lyra_v2 fica obsoleto ou continua paralelo?** — decisão futura: a IDE substitui o frontend de chat standalone, ou os dois convivem (chat rápido via pywebview + IDE completa pra quando for programar)? Não decidido — não bloqueia as Fases A-C, mas afeta se vale a pena continuar investindo no v2 standalone em paralelo.

---

## 7. Estimativa de esforço

Projeto multi-sessão, não é tarefa de uma sessão só. Ordem de grandeza (sessões de trabalho noturno como as já registradas no projeto, não horas-relógio):

- Fase A: 1 sessão (scaffold + validação).
- Fase B: 1 sessão (branding é mecânico, mas tem detalhe visual pra acertar).
- Fase C: 2-3 sessões (é o grosso — portar componentes React, resolver integração de widget, testar streaming dentro do Electron).
- Fase D: 2-3 sessões (cada feature de IA é um pedaço independente, dá pra fazer incremental).
- Fase E: 1 sessão (empacotamento + auditoria de rede).
- Fase F: contínuo, não bloqueia lançamento — pode ir crescendo depois que a IDE já está usável.

**Recomendação de execução:** tratar como projeto via skill `blueprint` quando começar de fato (Fase A), pra manter o fio entre sessões sem depender só deste documento estático.

---

## 8. Execução da Fase A — status (10/08/2026)

**Iniciada.** Progresso real:

1. ✅ Yarn instalado globalmente (`npm install -g yarn`, v1.22.22).
2. ✅ Theia Blueprint clonado em `Lyra_Core\Lyra_IDE\` (repo oficial `eclipse-theia/theia-blueprint`, template white-label pronto pra produto de marca própria — melhor encaixe que gerar do zero).
3. ❌→✅ `yarn install` falhou 2x por incompatibilidade de versão do Node: sistema tem Node v24.15.0 (rejeitado pelo `engines: node >=22` só na 2ª tentativa com v20, que é *menor* que o exigido — corrigido usando **Node v22.14.0 portátil** baixado em `Lyra_IDE\.toolchain\node22\` (não mexe no Node do sistema, isolado por projeto).
4. **🔴 Bloqueio real, confirmado como issue conhecida do próprio Theia no Windows** (GitHub #11981, #15029): módulos nativos `@theia/ffmpeg` (preview de mídia) e `node-pty` (terminal integrado) exigem compilação C++ via node-gyp — sem binário pré-compilado disponível pra nenhuma versão de Node testada. Precisa Visual Studio Build Tools (workload "Desktop development with C++") instalado no sistema.
5. **Aprovado pelo Antônio** (10/08/2026) instalar o Build Tools — mas a instalação via `winget` falhou (erro 1602) porque **a sessão de execução não tem privilégio de administrador** e o instalador precisa de elevação UAC, que não pode ser aprovada sem interação direta na máquina.

**Bloqueado em:** precisa o Antônio rodar, uma vez, num PowerShell **como Administrador**:
```
winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```
(ou instalador manual em visualstudio.microsoft.com, workload "Desenvolvimento para desktop com C++").

**Depois disso, retomar sozinho:** `cd Lyra_Core\Lyra_IDE`, adicionar `.toolchain\node22` no PATH da sessão, rodar `yarn install` de novo (o resto do pipeline — clone, yarn, Node 22 portátil — já está pronto e não precisa repetir).

## 9. Atualização — 10/08/2026 (tarde/noite): contornado `@theia/ffmpeg`, novo bloqueio pontual no rebuild pro Electron

**Resolvido sozinho, sem precisar de admin:** `@theia/ffmpeg` era o único módulo nativo sem fallback de binário pronto (todos os outros — `node-pty`, `keytar`, `drivelist`, `@parcel/watcher` — já tinham prebuild funcionando pro Node puro). Neutralizado via `patch-package` (patch salvo em `patches/@theia+ffmpeg+1.74.1.patch`, reaplica sozinho em todo `yarn install` futuro, graças ao `postinstall` que o próprio Theia Blueprint já tinha). `yarn install` completo rodou limpo depois disso (`Done in 93.09s`).

**Achado bônus:** a "Theia IDE" (Theia Blueprint) já vem com framework de IA embutido de fábrica — `@theia/ai-anthropic`, `@theia/ai-chat`, `@theia/ai-code-completion`, `@theia/ai-mcp`, providers plugáveis (Google/OpenAI/Ollama/Claude Code/etc.). Pode simplificar bastante a Fase C/D — talvez baste adicionar um provider "Lyra" em vez de construir o painel de chat do zero.

**Novo bloqueio, mais específico:** `yarn build` na Electron app roda `theia rebuild:electron`, que recompila os módulos nativos especificamente pro ABI do Electron (os prebuilds shipados só cobrem Node puro, não Electron). Isso expôs: `node-pty`, `keytar`, `native-keymap`, `drivelist` — nenhum tem prebuild pra Electron, todos exigem compilar de verdade. Dessa vez o MSBuild rodou (achou o compilador!) mas falhou com **MSB8040**: falta o componente específico "C++ Spectre-mitigated libraries" no VS Build Tools instalado.

**ID do componente confirmado** (via Microsoft Learn): `Microsoft.VisualStudio.Component.VC.Runtimes.x86.x64.Spectre`.

**Comando pronto pra quando o Antônio puder rodar** (PowerShell como Administrador):
```
& "C:\Program Files (x86)\Microsoft Visual Studio\Installer\setup.exe" modify --installPath "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools" --add Microsoft.VisualStudio.Component.VC.Runtimes.x86.x64.Spectre --quiet --wait --norestart
```

Depois disso, retomar: `cd Lyra_Core\Lyra_IDE\applications\electron`, PATH com `.toolchain\node22`, `yarn build` de novo.

## 10. Fase A — CONCLUÍDA via target browser (10/08/2026, mesma sessão, sem precisar do Antônio)

Enquanto o bloqueio do Electron (componente Spectre) esperava ação manual, segui pelo target **browser** (não precisa recompilar módulos nativos pro ABI do Electron — só reusa os que já compilaram/baixaram certo pro Node puro). Todos os critérios de sucesso da Fase A batidos:

1. **Extensões locais do workspace compiladas** — rodava `yarn build:extensions` antes de buildar a app (passo que faltava, não documentado explicitamente no fluxo do template).
2. **2º bloqueio pontual contornado sem admin:** o bundle do backend (`esbuild`) quebrava tentando resolver `@vscode/windows-ca-certs` (dependência opcional que falhou compilar, mesma classe do ffmpeg, mas sem fallback de `patch-package` fácil porque o pacote inteiro nem existia mais em `node_modules` — removido automaticamente após falha de build). Resolvido com **stub manual local**: recriado `node_modules/@vscode/windows-ca-certs/{package.json,index.js}` com uma classe `Crypt32` vazia (`next()`→undefined, `done()`→no-op) + arquivo `.node` vazio em `build/Release/crypt32.node` (o `@theia/esbuild-plugin` verifica a existência do binário nesse path específico antes de aceitar o módulo como resolvível). **Efeito colateral aceito conscientemente:** perde-se a leitura de certificados customizados da Windows Certificate Store (só relevante pra proxy HTTPS corporativo) — irrelevante pro uso offline-first da Lyra. **Não é persistente** — some se `node_modules` for apagado e reinstalado; precisa recriar os 3 arquivos (ou formalizar como patch depois).
3. **Build completo, 0 erros:** `yarn build` no target browser terminou limpo (`Done in 8.93s`).
4. **Boot confirmado ao vivo:** `theia start --hostname 127.0.0.1 --port 3000` → log mostrou `Theia app listening on http://127.0.0.1:3000`, `curl` retornou **HTTP 200** com HTML real (`<title>Theia IDE</title>` antes do branding).
5. **Extensão real via Open VSX — testado com o pipeline já configurado no `package.json` raiz** (`yarn download:plugins`): baixou **97 extensões reais, 445MB**, incluindo o bundle builtin completo (TypeScript, CSS, YAML, XML, git-base, etc. via GitHub release) + Java pack completo (`redhat.java`, `vscjava.vscode-java-debug/test/maven/gradle`) via Open VSX Registry direto. Confirma que a exceção de rede do §3/§6.1 funciona ponta a ponta.
6. **Branding mínimo aplicado e validado:** `applicationName`/`productName` trocados de "Theia IDE" pra **"Lyra IDE"** em `applications/browser/package.json` e `applications/electron/package.json`. Rebuild + restart confirmou ao vivo: `curl` retornou `<title>Lyra IDE</title>`.

**Ainda pendente (Electron, precisa do Antônio):** o componente Spectre (§9) só afeta o target **electron** (empacotamento desktop final) — o `node-pty`/`keytar`/etc. recompilam especificamente pro ABI do Electron nesse rebuild, diferente do Node puro que já funciona no browser. Comando pronto continua o mesmo do §9.

**Achado que muda o plano:** com o browser target já funcionando de ponta a ponta, dá pra continuar boa parte da Fase C (integração com o backend Lyra, portar componentes React) usando o modo browser via `yarn start` — sem esperar o Electron destravar. O Electron só é estritamente necessário no fim, pra virar de fato um app desktop (Fase E). Ordem sugerida revisada: seguir Fase C/D no browser agora, resolver Electron (Spectre) em paralelo quando o Antônio puder, Fase E (empacotamento) só quando os dois estiverem prontos.

## 11. Fase A — TOTALMENTE CONCLUÍDA (10/08/2026, mesma sessão): target Electron também funcionando

O Antônio rodou o comando do componente Spectre (§9) — `isComplete: true` confirmado via `vswhere`. Retomado o build do Electron:

1. **2º bloqueio pontual do ffmpeg, específico do target Electron:** mesmo com o patch do §9/10 aplicado (instala neutralizado), o `theia build --app-target=electron` chama `checkFfmpeg()` em tempo de build — uma checagem de licenciamento de codec proprietário (verifica se o ffmpeg empacotado no Electron final não contém codecs como h264/aac, só relevante pra quem vai redistribuir comercialmente). Essa função exige o addon nativo `ffmpeg.node` pra rodar, que nunca foi compilado. **Resolvido:** patch adicional no `check-ffmpeg.js` (`checkFfmpeg` agora só `return` no início, skip total) — persistido no mesmo patch `patches/@theia+ffmpeg+1.74.1.patch` via `patch-package`.
2. **Build completo, 0 erros:** `yarn build` no target electron → `Done in 19.63s`.
3. **App desktop real aberto e confirmado na tela do Antônio:** título da janela **"Welcome - Lyra IDE"**. Backend interno subiu (`Theia app listening on http://127.0.0.1:56794`), 97 plugins sincronizados e carregados, layout restaurado.
4. **Bug de lançamento descoberto e contornado (ambiente desta sessão, não do Theia):** rodar `yarn start`/`electron ...` via Bash (Git Bash) resultava em crash (`TypeError: Cannot read properties of undefined (reading 'requestSingleInstanceLock')`) porque a variável de ambiente **`ELECTRON_RUN_AS_NODE=1`** estava setada nesta sessão (herdada do próprio Claude Code, que roda sobre Electron) — isso força qualquer Electron filho a rodar como Node puro, sem `app`/janela. **Fix:** remover a env var (`Remove-Item Env:\ELECTRON_RUN_AS_NODE`) e lançar `electron.exe` direto via PowerShell (não Bash) com caminho absoluto. **Isso é só uma pegadinha do ambiente de desenvolvimento desta sessão** — não afeta o usuário final abrindo o `.exe` instalado normalmente fora desse contexto.

**Fase A 100% concluída — todos os critérios batidos nos dois targets (browser e electron):** app abre, edita com highlight (Monaco padrão), terminal integrado disponível, 97 extensões reais instaladas e ativas via Open VSX, branding "Lyra IDE" aplicado.

## 12. Fase B — CONCLUÍDA (10/08/2026, mesma sessão)

Reaproveitado o mark oficial da Lyra já existente (`Front_end_Lyra_v2/public/favicon.svg` — o raio roxo/azul) em vez de criar identidade nova. Sem ferramenta de conversão SVG→PNG instalada (`magick`/`inkscape`/`rsvg-convert` ausentes) — contornado renderizando via Edge headless (`msedge.exe --headless=new --screenshot=...`) + `Pillow` (Python) pra composição/matting/resize.

**Feito:**
1. **Ícone real gerado em todas as resoluções** (16 a 512px) a partir do SVG vetorial, com transparência verificada por pixel (não só visual). Aplicado em: `applications/electron/resources/icon.ico`, `resources/icons/WindowsLauncherIcons/TheiaIDE.ico` (o que o `electron-builder` realmente usa pro `.exe`/instalador), `resources/icons/WindowIcon/512-512.png` (fallback Linux), `applications/browser/ico/favicon.ico`.
2. **Wordmark "⚡ LYRA IDE"** gerado via HTML+Inter (fonte já vendorizada offline do projeto) renderizado no Edge headless, com **matting por diferença** (renderiza em preto e branco, reconstrói alpha real por pixel) — método mais preciso que chroma-key simples, que deixava franjas verdes visíveis nas bordas do texto/logo na 1ª tentativa. Substituiu `theia-extensions/product/src/browser/icons/{TheiaIDE,TheiaIDE-next,512-512,512-512-next}.png`.
3. **Splash screen novo** (`applications/electron/resources/TheiaIDESplash.svg`) — fundo preto, logo Lyra centralizado, texto "LYRA IDE", ponto cyan (mesma paleta `--neon` do frontend v2). Substituiu o splash genérico do Theia.
4. **Tema "Lyra Dark"** — editado `plugins/vscode.theme-defaults/extension/themes/dark_modern.json` (o tema "Default Dark Modern" já baixado): família de azul `#0078D4` trocada pro cyan neon `#00DDFF` (botões, activity bar, links, progress bar, tabs), fundos escurecidos pro preto/quase-preto da paleta Lyra (`#181818`→`#000000`, `#1F1F1F`→`#0a0a0f`, etc.). Definido como tema padrão explícito (`workbench.colorTheme: "Default Dark Modern"`) em `applications/{browser,electron}/package.json`. **Limitação conhecida:** editado direto dentro de `plugins/` (pasta de extensão baixada) — funciona perfeitamente agora, mas não sobrevive a um `yarn download:plugins` do zero (re-baixaria o original). Formalizar como extensão de tema própria (via `patch-package` ou pacote local) fica pra um polish futuro, não bloqueia nada agora.
5. **Update-checker desligado por padrão** — `updates.checkForUpdates` em `theia-extensions/updater/src/electron-browser/updater/theia-updater-preferences.ts` mudado de `true` pra `false` (Ring 0: sem chamada de rede não aprovada por padrão). URLs de publish do `download.eclipse.org` removidas do `electron-builder.yml` (não temos feed de release próprio).
6. **`electron-builder.yml`**: `productName` → `LyraIDE`, `appId` → `com.lyra.ide`, `copyright`/`vendor` → nome do Antônio.
7. **Header "Lyra IDE"** na Welcome page (`renderProductName()` em `branding-util.tsx`) — texto de marketing/ajuda mais profundo (links pro Open VSX, documentação Theia, etc.) mantido como está, deliberadamente — é conteúdo útil sobre a plataforma real por baixo, não é branding quebrado.

**Validado ao vivo:** rebuild completo (`build:extensions` + `yarn build` no electron), app aberto de novo, screenshot real da janela confirma: ícone na barra de título, wordmark limpo sem franjas, header "Lyra IDE", tema preto/cyan aplicado, título da janela "Welcome - Lyra_Project - Lyra IDE".

**Achado bônus:** a extensão real "Claude Code" (VS Code extension) já apareceu funcionando na sidebar direita do app, com as sessões desta própria conversa visíveis — confirma que a compatibilidade de extensões VSIX está genuinamente funcional, não é só teoria.

## 13. Fase B — correção e aprofundamento (10/08/2026, mesma sessão, pedido do Antônio)

**Erro cometido e corrigido:** o ícone usado inicialmente (o "raio" roxo/azul) veio de `Front_end_Lyra_v2/public/favicon.svg` — **não é o ícone oficial da Lyra**. O ícone real é `Front_end_Lyra/lyra.ico`: estrela/sparkle de 4 pontas em gradiente cyan sobre fundo quadrado arredondado escuro (paleta `--neon: #00DDFF`), já usado em produção no frontend v1. Antônio corrigiu ao vivo ("desde qdn o icone da lyra é esse raio ai? kkkkkkkkkkk"). Todos os ícones/wordmark/splash foram **regenerados do zero com o ícone certo**:

- `applications/electron/resources/icon.ico` e `resources/icons/WindowsLauncherIcons/TheiaIDE.ico` — cópia direta de `lyra.ico` (já vinha multi-resolução: 16/32/48/64/128/256px, não precisou re-renderizar).
- `resources/icons/WindowIcon/512-512.png`, `theia-extensions/product/src/browser/icons/{512-512,512-512-next}.png` — upscale Lanczos do frame 256px pra 512px.
- `applications/browser/ico/favicon.ico` — regenerado a partir da estrela.
- **Wordmark "⚡ LYRA IDE"** (`theia-extensions/product/src/browser/icons/{TheiaIDE,TheiaIDE-next}.png`) — recomposto com a estrela real + texto Inter, mesma técnica de matting por diferença (preto/branco) da 1ª tentativa, sem franjas.
- **Splash screen** (`TheiaIDESplash.svg`) — logo trocado pra estrela real.

**Ícone da barra de tarefas não aparecia (2º problema real reportado):** em modo dev (rodando `electron.exe` direto do `node_modules`, sem empacotar), o Windows usa o ícone genérico do Electron — só o `.exe` empacotado via `electron-builder` carrega o `.ico` customizado embutido. Corrigido em `theia-extensions/product/src/electron-main/icon-contribution.ts`: a lógica que já existia (seta `windowOptions.icon` em runtime) era **só pra Linux** — estendida pra `win32` também, com comentário explicando o motivo. Aplica o ícone tanto em dev quanto empacotado, sem depender só do embutido no `.exe`.

**Identidade visual aprofundada, além do que a Fase B original cobria** (pedido: "falta bastante coisa ainda pra ficar com a identidade da lyra"):

1. **Fonte Inter vendorizada e aplicada globalmente na UI** — `theia-extensions/product/src/browser/style/fonts/{inter-latin,inter-latin-ext}.woff2` (mesmos arquivos já usados no frontend v2, 100% offline). `@font-face` + `--theia-ui-font-family` sobrescrita em `theia-extensions/product/src/browser/style/index.css` (variável nativa do `@theia/core` que controla toda a fonte de UI — menus, sidebar, painéis; a fonte do editor de código continua monoespaçada, intocada, correto). Confirmado que o `esbuild` embute o `.woff2` como base64 inline no `bundle.css` (`loader: 'dataurl'` já configurado no `gen-esbuild.browser.mjs` pra `.woff2`/`.ttf`/`.eot` — mesmo mecanismo que já embutia os PNGs).
2. **`.gs-blue-header` corrigido** — o `<span>` "IDE" do header da Welcome page usava um azul hardcoded (`#5088e7`, resquício do tema Theia) mesmo depois do texto virar "Lyra IDE" — trocado pro cyan `#00DDFF`.
3. **Scrollbar com hover neon** — `::-webkit-scrollbar-thumb:hover { background: rgba(0,221,255,0.35); }`, mesmo padrão do frontend v2.
4. **Tema "Lyra Dark"** (§12) continua valendo — `focusBorder`/botões/tabs/activity bar já usam o cyan certo.

**Validado ao vivo, 2 rodadas de rebuild + screenshot real da janela** (não só teoria): 1ª rodada confirmou ícone/wordmark/tema; encontrado e corrigido o ícone errado; 2ª rodada confirmou ícone certo (zoom no wordmark mostra a estrela em miniatura ao lado de "LYRA IDE", renderizando corretamente — a olho nu em tamanho pequeno ela lembra um "+", mas é a estrela de 4 pontas mesmo, não é bug).

**O que ainda não foi tocado (deliberadamente, fora do escopo desta rodada):** ícones da activity bar (explorer/search/git/etc. continuam os padrão do VS Code — trocar exigiria um pacote de ícones customizado inteiro, tipo o `material-icon-theme` mas com tema Lyra, esforço grande à parte), efeitos de glassmorphism/blur/glow que o frontend v2 tem em profundidade (blur em camadas, glow ambiente nas animações) — precisam de CSS bem mais extenso por componente da IDE (painéis, tabs, barra de título), fica pra uma rodada futura de polish se o Antônio quiser ir mais fundo.

## 14. Próximo passo imediato

Fase B (+ aprofundamento) concluída e documentada. Próximo: **Fase C** — ponte com o backend Lyra (painel de chat embutido na IDE, endpoints `/chat`/`/historico`/`/metrics`/`/grafo` etc., reaproveitando componentes React do frontend v2). Avaliar se vale plugar a Lyra como provider do framework de IA já embutido no Theia (`@theia/ai-*`) em vez de construir painel do zero — decisão de arquitetura pra tomar no início da Fase C.
