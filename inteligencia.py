import pandas as pd
import math
from config import MATERIAS_ESPECIALISTAS, DIAS_SEMANA, SLOTS_AULA, CARGA_MAXIMA_PADRAO
from utils import padronizar, padronizar_materia_interna
from regras_alocacao import distribuir_carga_inteligente

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
            
            # B. Contabilizar Simultaneidade (O Pulo do Gato 🐱)
            # Se a turma tem aula na "SEGUNDA-FEIRA", incrementamos o contador daquele dia
            for dia in dias_aula:
                # Se o dia na config for específico para uma matéria (ex: Ed Física só terça), 
                # a lógica seria mais complexa. Aqui assumimos que o dia de planejamento 
                # é onde ocorrem as aulas de especialistas.
                
                chave_sim = (dia, turno_turma, regiao, mat)
                # Cada aula conta como 1 slot ocupado naquele dia/turno
                # Se a turma tem 2 aulas, ela ocupa o professor por 2 slots
                mapa_simultaneidade[chave_sim] = mapa_simultaneidade.get(chave_sim, 0) + 1

    # 2. Calcular o PICO de demanda para cada Região/Matéria
    pico_demanda = {} # { (Região, Matéria): Max_Profs_Simultaneos }
    
    for (dia, turno, reg, mat), qtd_turmas in mapa_simultaneidade.items():
        chave = (reg, mat)
        # O pico é determinado por quantas turmas têm aula ao mesmo tempo
        # Se temos 5 slots por dia, e 10 turmas precisam de aula naquele dia,
        # O mínimo de professores é: teto(Turmas / Slots)
        # Ex: 10 turmas em 1 manhã (5 slots) = Mínimo 2 professores rodando.
        # Ex: 10 turmas todas no 1º horário (Config rígida) = 10 professores.
        
        # Assumindo distribuição ótima DENTRO do turno (professores rodando):
        minimo_necessario_no_turno = math.ceil(qtd_turmas / SLOTS_AULA)
        
        atual = pico_demanda.get(chave, 0)
        pico_demanda[chave] = max(atual, minimo_necessario_no_turno)

    # 3. Gerar Sugestões Finais
    sugestoes = []
    
    for (reg, mat), total_aulas in volume_total.items():
        # Mínimo técnico (Simultaneidade)
        min_profs_simultaneos = pico_demanda.get((reg, mat), 1)
        
        # Mínimo por volume (Carga Horária)
        # Ex: 100 aulas / 30 (max) = 3.33 -> 4 professores
        min_profs_volume = math.ceil(total_aulas / CARGA_MAXIMA_PADRAO)
        
        # O número real de vagas é o MAIOR entre os dois critérios
        # Se tenho pouco volume, mas tudo na segunda-feira, vence a simultaneidade.
        qtd_vagas_necessarias = max(min_profs_simultaneos, min_profs_volume)
        
        # Calcular a carga ideal para essa quantidade de vagas
        carga_media = math.ceil(total_aulas / qtd_vagas_necessarias)
        
        # Ajustar distribuição (tentar manter números redondos)
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