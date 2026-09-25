import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},

			// adapter-auto only supports some environments, see https://svelte.dev/docs/kit/adapter-auto for a list.
			// If your environment is not supported, or you settled on a specific environment, switch out the adapter.
			// See https://svelte.dev/docs/kit/adapters for more information about adapters.
			adapter: adapter({ pages: 'build', assets: 'build', fallback: 'index.html' }),

				// BASE_PATH configuravel no build: vazio (padrao) pro cutover real em /ui;
				// '/ui-novo' quando buildado especificamente pra rodar lado a lado com o
				// /ui atual (preview, ver cerebro_maestro.py). Sem isso os assets referenciam
				// caminho absoluto "/_app/..." e quebram (tela branca) quando servidos de
				// um subpath - bug real encontrado testando no navegador de verdade.
				paths: {
					base: (process.env.BASE_PATH ?? '') as '' | `/${string}`
				}
		})
	]
});
