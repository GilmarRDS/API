"""
ch.py
Tabela de Carga Horária e PL (Planejamento) conforme Lei Municipal 1.071/2017 - Fundão/ES.
"""

import pandas as pd

# Mapeamento exato: {Hora_Aluno: Hora_PL}
TABELA_PL_FUNDAO = {
    1: 0,
    2: 1,
    3: 1,
    4: 2,
    5: 2,
    6: 3,
    7: 3,
    8: 4,
    9: 4,
    10: 5,
    11: 5,
    12: 6,
    13: 6,
    14: 7,
    15: 7,
    16: 8,
    17: 8,
    18: 9,
    19: 9,
    20: 10,
    21: 10,
    22: 11,
    23: 11,
    24: 12,
    25: 12,
    26: 13,
    27: 13,
    28: 14,
    29: 14,
    30: 15,
    31: 15,
    32: 16,
    33: 16,
    34: 17,
    35: 17
}

def obter_pl_exato(hora_aluno: int) -> int:
    """
    Retorna o PL exato conforme a tabela municipal.
    Para valores acima de 35, segue a lógica de divisão inteira por 2 (padrão da tabela).
    """
    if hora_aluno in TABELA_PL_FUNDAO:
        return TABELA_PL_FUNDAO[hora_aluno]
    else:
        # Pela lógica da tabela, o PL é aproximadamente a metade arredondada para baixo
        return int(hora_aluno // 2)

def gerar_dataframe_ch():
    """
    Gera um DataFrame com a tabela completa para salvar no Google Sheets.
    """
    dados = []
    for ha, pl in TABELA_PL_FUNDAO.items():
        total = ha + pl
        minutos = total * 50
        dados.append({
            "HORA_ALUNO": ha,
            "HORA_PL": pl,
            "TOTAL_HORAS": total,
            "MINUTOS_TOTAL": minutos
        })
    return pd.DataFrame(dados)