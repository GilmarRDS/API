"""
Configurações e constantes do sistema de gestão escolar.
"""

# Regiões disponíveis
REGIOES = ["FUNDÃO", "PRAIA GRANDE", "TIMBUÍ"]

# Matérias de especialistas
MATERIAS_ESPECIALISTAS = [
    "ARTE",
    "EDUCAÇÃO FÍSICA",
    "ENSINO RELIGIOSO",
    "LÍNGUA INGLESA",
    "CONTAÇÃO DE HISTÓRIA"
]

# Ordem das séries/anos
ORDEM_SERIES = [
    "BERÇÁRIO", "CRECHE I", "CRECHE II", "CRECHE III",
    "PRÉ I", "PRÉ II",
    "1º ANO", "2º ANO", "3º ANO", "4º ANO", "5º ANO"
]

# Dias da semana
DIAS_SEMANA = [
    "SEGUNDA-FEIRA",
    "TERÇA-FEIRA",
    "QUARTA-FEIRA",
    "QUINTA-FEIRA",
    "SEXTA-FEIRA"
]

# Turnos disponíveis
TURNOS = ["MATUTINO", "VESPERTINO", "AMBOS"]

# Vínculos de professores
VINCULOS = ["DT", "EFETIVO"]

# Colunas padrão esperadas em cada aba
COLS_PADRAO = {
    "Turmas": ["ESCOLA", "NÍVEL", "TURMA", "TURNO", "SÉRIE/ANO", "REGIÃO"],
    "Curriculo": ["SÉRIE/ANO", "COMPONENTE", "QTD_AULAS"],
    "Professores": [
        "CÓDIGO", "NOME", "COMPONENTES", "CARGA_HORÁRIA",
        "REGIÃO", "VÍNCULO", "TURNO_FIXO", "ESCOLAS_ALOCADAS", "QTD_PL"
    ],
    "ConfigDias": ["SÉRIE/ANO", "DIA_PLANEJAMENTO"],
    "Agrupamentos": ["NOME_ROTA", "LISTA_ESCOLAS"],
    "Horario": ["ESCOLA", "TURMA", "TURNO", "DIA", "1ª", "2ª", "3ª", "4ª", "5ª"]
}

# Configurações de carga horária padrão
CARGA_MINIMA_PADRAO = 14
CARGA_MAXIMA_PADRAO = 30
MEDIA_ALVO_PADRAO = 20

# Limites do algoritmo de geração
MAX_TENTATIVAS_ALOCACAO = 50
LIMITE_NOVOS_PROFESSORES = 50

# Configurações de cache
CACHE_TTL_SEGUNDOS = 300  # Aumentado para 5 minutos para reduzir requisições

# Slots de aula por dia
SLOTS_AULA = 5
