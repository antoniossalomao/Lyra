// settings.ts — preferências persistidas em localStorage (paridade com o
// Front_end_Lyra_v2: modelo padrão, TTS, nome de exibição, tamanho de fonte,
// reduzir movimento). Singleton reativo (Svelte 5 runes) — qualquer
// componente importa `settings` e lê/escreve direto, sem prop-drilling.

export type TamanhoFonte = 'pequeno' | 'medio' | 'grande';

const CHAVES = {
	modelo: 'lyra_default_model',
	ttsMudo: 'lyra_tts_muted',
	nome: 'lyra_display_name',
	tamanhoFonte: 'lyra_font_size',
	reduzirMovimento: 'lyra_reduce_motion'
} as const;

function ler(chave: string, padrao: string): string {
	if (typeof localStorage === 'undefined') return padrao;
	return localStorage.getItem(chave) ?? padrao;
}

class Settings {
	modelo = $state(ler(CHAVES.modelo, 'auto'));
	ttsMudo = $state(ler(CHAVES.ttsMudo, '0') === '1');
	nome = $state(ler(CHAVES.nome, 'Antônio'));
	tamanhoFonte = $state(ler(CHAVES.tamanhoFonte, 'medio') as TamanhoFonte);
	reduzirMovimento = $state(ler(CHAVES.reduzirMovimento, '0') === '1');

	setModelo(v: string) {
		this.modelo = v;
		localStorage.setItem(CHAVES.modelo, v);
	}

	setTtsMudo(v: boolean) {
		this.ttsMudo = v;
		localStorage.setItem(CHAVES.ttsMudo, v ? '1' : '0');
	}

	setNome(v: string) {
		this.nome = v;
		localStorage.setItem(CHAVES.nome, v);
	}

	setTamanhoFonte(v: TamanhoFonte) {
		this.tamanhoFonte = v;
		localStorage.setItem(CHAVES.tamanhoFonte, v);
	}

	setReduzirMovimento(v: boolean) {
		this.reduzirMovimento = v;
		localStorage.setItem(CHAVES.reduzirMovimento, v ? '1' : '0');
	}
}

export const settings = new Settings();
