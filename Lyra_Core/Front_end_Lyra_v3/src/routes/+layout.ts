// SPA puro (sem SSR) — o app roda embutido no cerebro_maestro (:8000/ui) e,
// futuramente, dentro do Theia/Tauri. Nunca há um servidor Node renderizando
// isso; adapter-static + ssr=false é o par certo pro modo `fallback`.
export const ssr = false;
