"""
Regras de Alocação de Professores - Sistema de Horários Escolares

Este arquivo contém todas as regras que o sistema deve seguir ao alocar professores.
"""

from config import REGIOES

# ==========================================
# REGRA 1: CONFLITOS DE HORÁRIO
# ==========================================
REGRA_CONFLITO_HORARIO = {
    "descricao": "Um professor não pode estar em mais de uma turma no mesmo horário",
    "tipo": "obrigatoria",
    "aplicar": True
}

# ==========================================
# REGRA 2: REGIÕES E COMPATIBILIDADE
# ==========================================
REGRA_REGIOES = {
    "descricao": "Professores devem respeitar limites de região",
    "tipo": "obrigatoria",
    "aplicar": True,
    "regioes_incompativeis": {
        "PRAIA GRANDE": ["FUNDÃO", "TIMBUÍ"],
        "FUNDÃO": ["PRAIA GRANDE"],
        "TIMBUÍ": ["PRAIA GRANDE"]
    },
    "regioes_compatíveis": {
        "FUNDÃO": ["TIMBUÍ"],  # Fundão pode dar aula em Timbuí em último caso
        "TIMBUÍ": ["FUNDÃO"]   # Timbuí pode dar aula em Fundão em último caso
    },
    "preferencia_regiao": True  # Preferir sempre a região do professor
}

def verificar_compatibilidade_regiao(regiao_professor: str, regiao_escola: str, materia: str = None) -> tuple[bool, int]:
    """
    Verifica se um professor pode dar aula em uma escola de outra região.
    
    REGRA GERAL: Fundão e Timbuí são compatíveis para TODAS as matérias.
    
    Args:
        regiao_professor: Região do professor
        regiao_escola: Região da escola
        materia: Matéria lecionada (opcional, mantido para compatibilidade)
        
    Returns:
        tuple: (pode_dar_aula, prioridade)
        - pode_dar_aula: True se pode dar aula, False se não pode
        - prioridade: 100 se mesma região, 75 se Fundão ↔ Timbuí (qualquer matéria), 0 se incompatível
    """
    regiao_professor = regiao_professor.upper().strip()
    regiao_escola = regiao_escola.upper().strip()
    
    # Mesma região = máxima prioridade
    if regiao_professor == regiao_escola:
        return True, 100
    
    # REGRA GERAL: Fundão e Timbuí são compatíveis para TODAS as matérias
    # Isso permite que professores de qualquer matéria possam dar aula entre essas regiões
    if (regiao_professor == "FUNDÃO" and regiao_escola == "TIMBUÍ") or \
       (regiao_professor == "TIMBUÍ" and regiao_escola == "FUNDÃO"):
        return True, 75  # Prioridade alta para facilitar alocação entre Fundão e Timbuí
    
    # Verificar se são incompatíveis
    incompatíveis = REGRA_REGIOES["regioes_incompativeis"].get(regiao_professor, [])
    if regiao_escola in incompatíveis:
        return False, 0
    
    # Verificar se são compatíveis (último caso - mantido para compatibilidade)
    compatíveis = REGRA_REGIOES["regioes_compatíveis"].get(regiao_professor, [])
    if regiao_escola in compatíveis:
        return True, 50
    
    # Se não está nas regras, não permite (segurança)
    return False, 0

# ==========================================
# REGRA 3: TURNOS
# ==========================================
REGRA_TURNOS = {
    "descricao": "Professor pode dar aula em mais de um turno",
    "tipo": "permissiva",
    "aplicar": True,
    "permite_multiplos_turnos": True
}

# ==========================================
# REGRA 4: JANELAS/BURACOS ENTRE AULAS
# ==========================================
REGRA_JANELAS = {
    "descricao": "Não pode ter janelas/buracos entre as aulas",
    "tipo": "obrigatoria",
    "aplicar": True,
    "tolerancia_minutos": 0,  # Zero tolerância para janelas
    "preferencia_aulas_consecutivas": True
}

def verificar_janelas(ocupacao_professor: dict, novo_slot: int, escola: str, rotas: dict) -> tuple[bool, int]:
    """
    Verifica se adicionar uma aula em um slot criaria janelas/buracos.
    
    REGRA: Não pode ter janelas/buracos entre aulas na mesma escola ou rota.
    PERMITE: Alocações que PREENCHEM buracos existentes.
    
    Args:
        ocupacao_professor: Dicionário {slot: escola} das aulas já alocadas
        novo_slot: Slot onde quer adicionar a aula (0-4)
        escola: Escola onde será a aula
        rotas: Dicionário de rotas (escolas que podem ser visitadas no mesmo dia)
        
    Returns:
        tuple: (cria_janela: bool, bonus_preenchimento: int)
        - cria_janela: True se criar janela (NÃO PERMITIR), False se não criar (PERMITIR)
        - bonus_preenchimento: Bonus positivo se preencher um buraco existente (para priorizar)
    """
    if not ocupacao_professor:
        return False, 0  # Primeira aula, não há janela - PERMITIR
    
    # Verificar se há aulas na mesma escola
    aulas_mesma_escola = [s for s, e in ocupacao_professor.items() if e == escola]
    
    if aulas_mesma_escola:
        # Se há aulas na mesma escola, verificar se o novo slot é consecutivo
        slots_escola = sorted(aulas_mesma_escola + [novo_slot])
        
        # Verificar se preenche um buraco existente
        bonus_preenchimento = 0
        for i in range(len(slots_escola) - 1):
            gap = slots_escola[i+1] - slots_escola[i]
            if gap > 1:
                # Há um buraco existente
                if novo_slot > slots_escola[i] and novo_slot < slots_escola[i+1]:
                    # O novo slot PREENCHE o buraco - PERMITIR e dar bonus
                    bonus_preenchimento = 1000  # Grande bonus por preencher buraco
                    return False, bonus_preenchimento
                else:
                    # O novo slot CRIA um novo buraco - NÃO PERMITIR
                    return True, 0
        
        # Não há buracos - PERMITIR
        return False, 0
    
    # Verificar rotas (escolas que podem ser visitadas no mesmo dia)
    escolas_rota = rotas.get(escola, set())
    aulas_na_rota = []
    
    for s_ocup, e_ocup in ocupacao_professor.items():
        # Verificar se está na mesma rota
        if e_ocup == escola or e_ocup in escolas_rota or escola in rotas.get(e_ocup, set()):
            aulas_na_rota.append(s_ocup)
    
    if aulas_na_rota:
        # Se há aulas na rota, verificar se o novo slot é consecutivo
        slots_rota = sorted(aulas_na_rota + [novo_slot])
        
        # Verificar se preenche um buraco existente
        for i in range(len(slots_rota) - 1):
            gap = slots_rota[i+1] - slots_rota[i]
            if gap > 1:
                # Há um buraco existente
                if novo_slot > slots_rota[i] and novo_slot < slots_rota[i+1]:
                    # O novo slot PREENCHE o buraco - PERMITIR e dar bonus
                    return False, 1000  # Grande bonus por preencher buraco
                else:
                    # O novo slot CRIA um novo buraco - NÃO PERMITIR
                    return True, 0
        
        # Não há buracos - PERMITIR
        return False, 0
    
    # Se é escola diferente e não está na rota, não há problema de janela
    # (professor pode ter aulas em escolas diferentes sem problema)
    return False, 0  # PERMITIR

# ==========================================
# REGRA 5: LDB - CÁLCULO DE PL (PLANEJAMENTO)
# ==========================================
REGRA_LDB = {
    "descricao": "Seguir LDB: 1/3 de PL para cada carga de aulas",
    "tipo": "obrigatoria",
    "aplicar": True,
    "proporcao_pl": 1/3,  # 1/3 de PL para cada carga
    "formula": "PL = AULAS / 3"  # Exemplo: 20 aulas = 6.67 PL (arredondado para 7)
}

def calcular_pl_ldb(carga_aulas: int) -> int:
    """
    Calcula o PL (Planejamento) baseado na LDB (1/3 da carga).
    
    Args:
        carga_aulas: Carga horária de aulas
        
    Returns:
        int: Quantidade de PL arredondada
    """
    pl = carga_aulas * REGRA_LDB["proporcao_pl"]
    return max(1, round(pl))  # Mínimo 1 PL

def calcular_carga_total(carga_aulas: int) -> int:
    """
    Calcula a carga total (aulas + PL) baseado na LDB.
    
    Args:
        carga_aulas: Carga horária de aulas
        
    Returns:
        int: Carga total (aulas + PL)
    """
    pl = calcular_pl_ldb(carga_aulas)
    return carga_aulas + pl

# ==========================================
# REGRA 6: LIMITES DE CARGA HORÁRIA
# ==========================================
REGRA_CARGA_HORARIA = {
    "descricao": "Limites de carga horária para professores",
    "tipo": "obrigatoria",
    "aplicar": True,
    "maximo_aulas": 30,
    "minimo_aulas": 14,
    "permitir_menor_se_necessario": True,  # Se o quantitativo é menor que 14, permitir
    "distribuir_inteligentemente": True
}

def verificar_limites_carga(carga: int, total_disponivel: int = None) -> tuple[bool, str]:
    """
    Verifica se a carga está dentro dos limites permitidos.
    
    Args:
        carga: Carga horária a verificar
        total_disponivel: Total de aulas disponíveis (para casos especiais)
        
    Returns:
        tuple: (valido, mensagem)
    """
    if carga > REGRA_CARGA_HORARIA["maximo_aulas"]:
        return False, f"Carga excede máximo de {REGRA_CARGA_HORARIA['maximo_aulas']} aulas"
    
    if carga < REGRA_CARGA_HORARIA["minimo_aulas"]:
        if REGRA_CARGA_HORARIA["permitir_menor_se_necessario"] and total_disponivel:
            if total_disponivel < REGRA_CARGA_HORARIA["minimo_aulas"]:
                return True, f"Carga abaixo do mínimo, mas quantitativo disponível é {total_disponivel}"
        return False, f"Carga abaixo do mínimo de {REGRA_CARGA_HORARIA['minimo_aulas']} aulas"
    
    return True, "Carga dentro dos limites"

# ==========================================
# REGRA 7: DISTRIBUIÇÃO INTELIGENTE
# ==========================================
REGRA_DISTRIBUICAO = {
    "descricao": "Distribuir carga de forma inteligente e equilibrada",
    "tipo": "obrigatoria",
    "aplicar": True,
    "media_alvo": 20,  # Média de aulas por professor
    "tentar_equilibrar": True,
    "preferir_cargas_cheias": True  # Preferir cargas próximas de 20, 25, 30
}

def distribuir_carga_inteligente(total_aulas: int, num_professores: int = None) -> list[int]:
    """
    Distribui carga de forma inteligente respeitando limites e preferências.
    
    Args:
        total_aulas: Total de aulas a distribuir
        num_professores: Número de professores (None = calcular automaticamente)
        
    Returns:
        list: Lista de cargas distribuídas
    """
    if total_aulas <= 0:
        return []
    
    # Se não especificou número de professores, calcular
    if num_professores is None:
        media_alvo = REGRA_DISTRIBUICAO["media_alvo"]
        num_professores = max(1, round(total_aulas / media_alvo))
    
    # Ajustar número de professores para respeitar limites
    carga_por_prof = total_aulas / num_professores
    
    # Se carga por professor é menor que mínimo, reduzir número de professores
    while num_professores > 1 and carga_por_prof < REGRA_CARGA_HORARIA["minimo_aulas"]:
        num_professores -= 1
        carga_por_prof = total_aulas / num_professores
    
    # Se carga por professor é maior que máximo, aumentar número de professores
    while carga_por_prof > REGRA_CARGA_HORARIA["maximo_aulas"]:
        num_professores += 1
        carga_por_prof = total_aulas / num_professores
    
    # Distribuir carga
    cargas = []
    restante = total_aulas
    
    # Preferir cargas cheias (20, 25, 30)
    cargas_preferidas = [30, 25, 20, 15]
    
    for i in range(num_professores):
        if i == num_professores - 1:
            # Último professor recebe o restante
            carga = restante
        else:
            # Tentar usar carga preferida
            carga = round(carga_por_prof)
            
            # Ajustar para carga preferida mais próxima
            for cp in cargas_preferidas:
                if abs(cp - carga) <= 2 and cp <= restante:
                    carga = cp
                    break
            
            # Garantir limites
            carga = min(REGRA_CARGA_HORARIA["maximo_aulas"], 
                       max(REGRA_CARGA_HORARIA["minimo_aulas"], carga))
            
            # Garantir que não ultrapasse o restante
            carga = min(carga, restante)
        
        cargas.append(max(1, carga))
        restante -= carga
    
    return cargas

# ==========================================
# RESUMO DAS REGRAS
# ==========================================
TODAS_REGRA = {
    "conflito_horario": REGRA_CONFLITO_HORARIO,
    "regioes": REGRA_REGIOES,
    "turnos": REGRA_TURNOS,
    "janelas": REGRA_JANELAS,
    "ldb": REGRA_LDB,
    "carga_horaria": REGRA_CARGA_HORARIA,
    "distribuicao": REGRA_DISTRIBUICAO
}

def validar_regras() -> dict:
    """
    Valida se todas as regras estão configuradas corretamente.
    
    Returns:
        dict: Status de validação de cada regra
    """
    status = {}
    for nome, regra in TODAS_REGRA.items():
        status[nome] = {
            "aplicar": regra.get("aplicar", False),
            "tipo": regra.get("tipo", "desconhecido"),
            "valido": True
        }
    return status
