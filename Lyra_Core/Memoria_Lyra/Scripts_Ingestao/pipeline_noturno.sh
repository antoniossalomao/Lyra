#!/bin/bash
# pipeline_noturno.sh — roda toda a recuperação/expansão da memória da Lyra em sequência.
# Pensado para deixar rodando durante a madrugada sem supervisão.
set -e
cd "$(dirname "$0")"

echo "===== [1/5] Vetorizando Wikipedia PT-BR (GPU) ====="
python final.py

echo "===== [2/5] Vetorizando bases existentes: codigo, instrucoes, raciocinio, conversas (GPU) ====="
python vetorizar_todos.py --apenas=base_codigo,base_instrucoes_ptbr,base_raciocinio,base_conversas

echo "===== [3/5] Baixando e inserindo novos datasets no SurrealDB: Aya, br-quad, FaQuAD, MedPT ====="
python ingestao.py --apenas=aya_ptbr,br_quad,faquad,medpt

echo "===== [4/5] Limpando checkpoint de base_instrucoes_ptbr (Aya adicionou linhas novas) ====="
rm -f checkpoint_base_instrucoes_ptbr.json

echo "===== [5/5] Vetorizando dados novos: instrucoes+Aya, QA, medicina (GPU) ====="
python vetorizar_todos.py --apenas=base_instrucoes_ptbr,base_conhecimento_qa,base_medicina_ptbr

echo "===== PIPELINE NOTURNO COMPLETO ====="
