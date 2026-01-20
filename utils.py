"""
Funções utilitárias para processamento de texto e dados.
"""

import re
import unicodedata
from typing import Optional, List
import pandas as pd
from config import MATERIAS_ESPECIALISTAS


def remover_acentos(texto: str) -> str:
    """
    Remove acentos de uma string.
    
    Args:
        texto: String a ser processada
        
    Returns:
        String sem acentos
    """
    if not isinstance(texto, str):
        return str(texto)
    nfkd = unicodedata.normalize('NFKD', texto)
    return "".join([c for c in nfkd if not unicodedata.combining(c)])


def padronizar(texto) -> str:
    """
    Padroniza um texto: remove acentos, converte para maiúsculas e remove espaços extras.
    
    Args:
        texto: Texto a ser padronizado
        
    Returns:
        Texto padronizado
    """
    if pd.isna(texto):
        return ""
    txt = remover_acentos(str(texto).upper().strip())
    if txt == "NAN":
        return ""
    return " ".join(txt.split())


def limpar_materia(nome: str) -> str:
    """
    Limpa e padroniza o nome de uma matéria.
    
    Args:
        nome: Nome da matéria
        
    Returns:
        Nome padronizado da matéria
    """
    nome_padrao = padronizar(nome)
    if "ART" in nome_padrao:
        return "ARTE"
    if "FISICA" in nome_padrao:
        return "EDUCAÇÃO FÍSICA"
    if "INGLE" in nome_padrao:
        return "LÍNGUA INGLESA"
    if "RELIGIO" in nome_padrao:
        return "ENSINO RELIGIOSO"
    if "HIST" in nome_padrao and "CONTA" in nome_padrao:
        return "CONTAÇÃO DE HISTÓRIA"
    return nome


def padronizar_materia_interna(nome: str) -> str:
    """
    Padroniza o nome de uma matéria para uso interno (sem acentos, maiúsculas).
    
    Args:
        nome: Nome da matéria
        
    Returns:
        Nome padronizado para uso interno
    """
    return remover_acentos(limpar_materia(nome)).upper()


def gerar_sigla_regiao(regiao: str) -> str:
    """
    Gera sigla de uma região.
    
    Args:
        regiao: Nome da região
        
    Returns:
        Sigla da região (P, F, T ou X)
    """
    reg = padronizar(regiao)
    if "PRAIA" in reg:
        return "P"
    if "FUND" in reg:
        return "F"
    if "TIMB" in reg:
        return "T"
    return "X"


def gerar_sigla_materia(nome: str) -> str:
    """
    Gera sigla de uma matéria.
    
    Args:
        nome: Nome da matéria
        
    Returns:
        Sigla da matéria
    """
    nome = padronizar(nome)
    if "ART" in nome:
        return "ARTE"
    if "FISICA" in nome:
        return "EDFI"
    if "INGLE" in nome:
        return "LIIN"
    if "RELIGIO" in nome:
        return "ENRE"
    if "HIST" in nome and "CONTA" in nome:
        return "COHI"
    
    palavras = nome.split()
    if len(palavras) > 1:
        return (palavras[0][:2] + palavras[1][:2]).upper()
    return nome[:4].upper()


def gerar_codigo_padrao(numero: int, tipo: str, regiao: str, materia: str) -> str:
    """
    Gera código padrão de professor.
    
    Args:
        numero: Número sequencial do professor
        tipo: Tipo de vínculo (DT ou EFETIVO)
        regiao: Região do professor
        materia: Matéria lecionada
        
    Returns:
        Código no formato P{numero}{tipo}{regiao}{materia}
    """
    t = "D" if tipo == "DT" else "E"
    r = gerar_sigla_regiao(regiao)
    m = gerar_sigla_materia(materia)
    return f"P{numero}{t}{r}{m}"


def extrair_id_do_link(url: str) -> Optional[str]:
    """
    Extrai o ID da planilha a partir de uma URL do Google Sheets.
    
    Args:
        url: URL completa ou ID da planilha
        
    Returns:
        ID da planilha ou None se não encontrar
    """
    if not url:
        return None
    
    # Remove parâmetros de consulta
    url = url.split('?')[0]
    
    # Procura pelo padrão /d/ID/
    padrao = r'/spreadsheets/d/([a-zA-Z0-9-_]+)'
    match = re.search(padrao, url)
    
    if match:
        return match.group(1)
    
    # Se não encontrar, tenta outros padrões
    padroes = [
        r'd/([a-zA-Z0-9-_]{44})',  # ID de 44 caracteres
        r'key=([a-zA-Z0-9-_]+)',   # key=ID
        r'id=([a-zA-Z0-9-_]+)'     # id=ID
    ]
    
    for padrao in padroes:
        match = re.search(padrao, url)
        if match:
            return match.group(1)
    
    # Se for apenas o ID (não uma URL)
    if re.match(r'^[a-zA-Z0-9-_]{44}$', url):
        return url
    
    return None


def validar_dataframe(df: pd.DataFrame, colunas_esperadas: List[str]) -> bool:
    """
    Valida se um DataFrame tem as colunas esperadas.
    
    Args:
        df: DataFrame a ser validado
        colunas_esperadas: Lista de colunas esperadas
        
    Returns:
        True se todas as colunas estão presentes, False caso contrário
    """
    if df.empty:
        return False
    
    colunas_presentes = set(df.columns)
    colunas_esperadas_set = set(colunas_esperadas)
    
    return colunas_esperadas_set.issubset(colunas_presentes)
