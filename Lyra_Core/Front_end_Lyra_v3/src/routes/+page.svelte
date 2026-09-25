<script lang="ts">
	import { api } from '$lib/api';
	import Chat from '$lib/components/Chat.svelte';

	type Tela = 'carregando' | 'setup' | 'login' | 'logado' | 'erro_conexao';

	let tela = $state<Tela>('carregando');
	let username = $state('');
	let senha = $state('');
	let erro = $state('');
	let enviando = $state(false);

	async function carregar() {
		try {
			const status = await api.authStatus();
			tela = status.setup_necessario ? 'setup' : 'login';
		} catch {
			// Backend fora do ar ou CORS bloqueando (dev cross-origin) — ver api.ts.
			tela = 'erro_conexao';
		}
	}
	carregar();

	async function enviar() {
		erro = '';
		enviando = true;
		try {
			if (tela === 'setup') {
				await api.authSetup(username, senha);
			} else if (tela === 'login') {
				await api.authLogin(username, senha);
			}
			tela = 'logado';
		} catch (e) {
			erro = e instanceof Error ? e.message : 'Falha desconhecida.';
		} finally {
			enviando = false;
		}
	}
</script>

{#if tela === 'logado'}
	<Chat />
{:else}
<main>
	{#if tela === 'carregando'}
		<p class="dim">Conectando ao núcleo...</p>
	{:else if tela === 'erro_conexao'}
		<p class="dim">Não foi possível falar com o backend (cerebro_maestro :8000).</p>
	{:else}
		<form onsubmit={(e) => { e.preventDefault(); enviar(); }}>
			<h1>{tela === 'setup' ? 'Criar conta admin' : 'Entrar'}</h1>
			<p class="dim">
				{tela === 'setup'
					? 'Primeiro acesso — essa conta protege o app.'
					: 'Lyra — acesso protegido.'}
			</p>

			<label>
				Usuário
				<input bind:value={username} autocomplete="username" required />
			</label>

			<label>
				Senha
				<input type="password" bind:value={senha} autocomplete={tela === 'setup' ? 'new-password' : 'current-password'} required minlength={tela === 'setup' ? 8 : undefined} />
			</label>

			{#if erro}
				<p class="erro">{erro}</p>
			{/if}

			<button type="submit" disabled={enviando}>
				{enviando ? '...' : tela === 'setup' ? 'Criar conta' : 'Entrar'}
			</button>
		</form>
	{/if}
</main>
{/if}

<style>
	main {
		min-height: 100vh;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 24px;
	}

	form {
		width: 100%;
		max-width: 320px;
		display: flex;
		flex-direction: column;
		gap: 14px;
	}

	h1 {
		font-weight: 400;
		font-size: 1.4rem;
		margin: 0;
	}

	.dim {
		color: var(--text-dim);
		margin: 0 0 8px;
	}

	label {
		display: flex;
		flex-direction: column;
		gap: 6px;
		font-size: 0.85rem;
		color: var(--text-dim);
	}

	input {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		color: var(--text);
		padding: 10px 12px;
		outline: none;
		transition: border-color 0.15s var(--ease);
	}

	input:focus {
		border-color: var(--accent);
	}

	button {
		margin-top: 8px;
		background: var(--accent-dim);
		border: 1px solid var(--accent);
		color: var(--accent);
		border-radius: var(--radius);
		padding: 10px 12px;
		cursor: pointer;
		transition: background 0.15s var(--ease);
	}

	button:hover:not(:disabled) {
		background: var(--accent);
		color: var(--bg);
	}

	button:disabled {
		opacity: 0.5;
		cursor: default;
	}

	.erro {
		color: var(--danger);
		font-size: 0.85rem;
		margin: 0;
	}
</style>
