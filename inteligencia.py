import pandas as pd
import math
import re

# 1. Importar Configurações
from config import MATERIAS_ESPECIALISTAS, DIAS_SEMANA, SLOTS_AULA, CARGA_MAXIMA_PADRAO, MEDIA_ALVO_PADRAO

# 2. Importar Utilitários
# (Aqui só trazemos o que realmente existe em utils.py)
from utils import padronizar, padronizar_materia_interna, gerar_codigo_padrao

# 3. Importar Regras
# (A função calcular_pl_ldb mora AQUI, em regras_alocacao.py)
from regras_alocacao import distribuir_carga_inteligente, calcular_pl_ldb

# ==============================================================================
# FUNÇÃO 1: ANÁLISE DE DEMANDA (CÉREBRO)
# ==============================================================================
def analisar_demanda_inteligente(dt, dc, dd, da):
    """
    Analisa a demanda considerando:
    1. Volume total de aulas
    2. Simultaneidade (aulas acontecendo ao mesmo tempo)
    3. Agrupamento por Região
    """
    # Dicionário para mapear ocupação: { (Dia, Turno, Região, Matéria): Qtd_Turmas_Simultaneas }
    mapa_simultaneidade = {}
    
    # Dicionário para volume total: { (Região, Matéria): Total_Aulas }
    volume_total = {}

    # 1. Expandir a demanda no tempo (Cruzando Turmas + ConfigDias + Currículo)
    for _, turma in dt.iterrows():
        serie = turma['SÉRIE/ANO']
        regiao = padronizar(turma['REGIÃO'])
        turno_turma = turma['TURNO']
        
        # Buscar dias configurados para essa série
        dias_config = dd[dd['SÉRIE/ANO'] == serie]
        
        # Se não tiver dia configurado, assumimos distribuição uniforme (fallback)
        dias_aula = dias_config['DIA_PLANEJAMENTO'].unique() if not dias_config.empty else DIAS_SEMANA
        
        # Buscar currículo (quais matérias essa turma tem)
        curr = dc[dc['SÉRIE/ANO'] == serie]
        
        for _, item in curr.iterrows():
            mat = padronizar_materia_interna(item['COMPONENTE'])
            
            # Só nos interessa especialistas
            if mat not in [padronizar_materia_interna(m) for m in MATERIAS_ESPECIALISTAS]:
                continue
                
            qtd_aulas = int(item['QTD_AULAS'])
            
            # A. Contabilizar Volume Total
            chave_vol = (regiao, mat)
            volume_total[chave_vol] = volume_total.get(chave_vol, 0) + qtd_aulas
            
            # B. Contabilizar Simultaneidade
            for dia in dias_aula:
                chave_sim = (dia, turno_turma, regiao, mat)
                mapa_simultaneidade[chave_sim] = mapa_simultaneidade.get(chave_sim, 0) + 1

    # 2. Calcular o PICO de demanda para cada Região/Matéria
    pico_demanda = {} 
    
    for (dia, turno, reg, mat), qtd_turmas in mapa_simultaneidade.items():
        chave = (reg, mat)
        # O mínimo de professores é: teto(Turmas / Slots)
        minimo_necessario_no_turno = math.ceil(qtd_turmas / SLOTS_AULA)
        
        atual = pico_demanda.get(chave, 0)
        pico_demanda[chave] = max(atual, minimo_necessario_no_turno)

    # 3. Gerar Sugestões Finais
    sugestoes = []
    
    for (reg, mat), total_aulas in volume_total.items():
        # Mínimo técnico (Simultaneidade)
        min_profs_simultaneos = pico_demanda.get((reg, mat), 1)
        
        # Mínimo por volume (Carga Horária)
        min_profs_volume = math.ceil(total_aulas / CARGA_MAXIMA_PADRAO)
        
        # O número real de vagas é o MAIOR entre os dois critérios
        qtd_vagas_necessarias = max(min_profs_simultaneos, min_profs_volume)
        
        # Calcular distribuição
        cargas_finais = distribuir_carga_inteligente(total_aulas, qtd_vagas_necessarias)
        
        sugestoes.append({
            "Região": reg,
            "Matéria": mat,
            "Volume Total": total_aulas,
            "Pico Simultâneo": min_profs_simultaneos,
            "Vagas Sugeridas": qtd_vagas_necessarias,
            "Distribuição": cargas_finais
        })
        
    return pd.DataFrame(sugestoes)

# ==============================================================================
# FUNÇÃO 2: GERAÇÃO DE OBJETOS (CRIAÇÃO)
# ==============================================================================
def gerar_novos_professores_inteligentes(dt, dc, dd, da, dp_existente):
    """
    1. Executa a análise inteligente (simultaneidade + volume).
    2. Converte as sugestões em objetos de professor prontos para o DataFrame.
    """
    # 1. Obter a análise baseada em dados
    df_analise = analisar_demanda_inteligente(dt, dc, dd, da)
    
    if df_analise.empty:
        return pd.DataFrame(), pd.DataFrame() # Sem sugestões (retorna vazio compatível)

    novos_professores = []
    
    # 2. Descobrir o último número de ID
    numeros_existentes = []
    for _, p_row in dp_existente.iterrows():
        match = re.search(r'P(\d+)', str(p_row['CÓDIGO']))
        if match:
            numeros_existentes.append(int(match.group(1)))
    
    proximo_numero = max(numeros_existentes) + 1 if numeros_existentes else 1

    # 3. Separar demandas
    demanda_fundao = df_analise[df_analise['Região'] == 'FUNDÃO'].set_index('Matéria')
    demanda_timbui = df_analise[df_analise['Região'] == 'TIMBUÍ'].set_index('Matéria')
    demanda_outras = df_analise[~df_analise['Região'].isin(['FUNDÃO', 'TIMBUÍ'])]

    # --- LÓGICA A: VAGAS COMPARTILHADAS (FUNDÃO + TIMBUÍ) ---
    todas_materias_ft = set(demanda_fundao.index).union(set(demanda_timbui.index))
    
    for mat in todas_materias_ft:
        # Obter dados de cada região
        dados_f = demanda_fundao.loc[mat] if mat in demanda_fundao.index else None
        dados_t = demanda_timbui.loc[mat] if mat in demanda_timbui.index else None
        
        # Calcular totais combinados
        vol_f = dados_f['Volume Total'] if dados_f is not None else 0
        vol_t = dados_t['Volume Total'] if dados_t is not None else 0
        total_vol = vol_f + vol_t
        
        pico_f = dados_f['Pico Simultâneo'] if dados_f is not None else 0
        pico_t = dados_t['Pico Simultâneo'] if dados_t is not None else 0
        total_pico = pico_f + pico_t 
        
        # Calcular vagas necessárias (Pico vs Volume)
        qtd_vagas = max(total_pico, math.ceil(total_vol / CARGA_MAXIMA_PADRAO))
        
        if qtd_vagas > 0:
            cargas = distribuir_carga_inteligente(total_vol, qtd_vagas)
            
            # Buscar escolas
            esc_f = list(set(dt[dt['REGIÃO'] == "FUNDÃO"]['ESCOLA'].unique()))
            esc_t = list(set(dt[dt['REGIÃO'] == "TIMBUÍ"]['ESCOLA'].unique()))
            escolas_mix = (esc_f[:2] if esc_f else []) + (esc_t[:2] if esc_t else [])
            
            for carga in cargas:
                codigo = gerar_codigo_padrao(proximo_numero, "DT", "FUNDAO", mat)
                novos_professores.append({
                    "CÓDIGO": codigo,
                    "NOME": f"VAGA {mat} FUNDÃO/TIMBUÍ (INTELIGENTE)",
                    "COMPONENTES": mat,
                    "CARGA_HORÁRIA": carga,
                    "QTD_PL": calcular_pl_ldb(carga),
                    "REGIÃO": "FUNDÃO",
                    "VÍNCULO": "DT",
                    "TURNO_FIXO": "",
                    "ESCOLAS_ALOCADAS": ",".join(escolas_mix)
                })
                proximo_numero += 1

    # --- LÓGICA B: OUTRAS REGIÕES ---
    for _, row in demanda_outras.iterrows():
        reg = row['Região']
        mat = row['Matéria']
        cargas = row['Distribuição']
        
        escolas_reg = list(set(dt[dt['REGIÃO'] == reg]['ESCOLA'].unique()))
        
        for carga in cargas:
            codigo = gerar_codigo_padrao(proximo_numero, "DT", reg, mat)
            novos_professores.append({
                "CÓDIGO": codigo,
                "NOME": f"VAGA {mat} {reg} (INTELIGENTE)",
                "COMPONENTES": mat,
                "CARGA_HORÁRIA": carga,
                "QTD_PL": calcular_pl_ldb(carga),
                "REGIÃO": reg,
                "VÍNCULO": "DT",
                "TURNO_FIXO": "",
                "ESCOLAS_ALOCADAS": ",".join(escolas_reg[:3])
            })
            proximo_numero += 1
            
    return pd.DataFrame(novos_professores), df_analise