"""
Sistema de Gestão Escolar - Gerador de Horários
Aplicação Streamlit para gestão de turmas, professores e geração automática de horários.
"""
import hashlib
import colorsys
import streamlit as st
import pandas as pd
import time
from datetime import datetime
from typing import Tuple, List, Dict, Optional
import re
import random
import io
import xlsxwriter
import math
import copy
import gspread
from google.oauth2 import service_account
from inteligencia import analisar_demanda_inteligente
from inteligencia import gerar_novos_professores_inteligentes

from ch import gerar_dataframe_ch

# Importar configurações e utilitários
from config import (
    REGIOES, MATERIAS_ESPECIALISTAS, ORDEM_SERIES, DIAS_SEMANA, VINCULOS,
    COLS_PADRAO, CARGA_MINIMA_PADRAO, CARGA_MAXIMA_PADRAO, MEDIA_ALVO_PADRAO,
    MAX_TENTATIVAS_ALOCACAO, LIMITE_NOVOS_PROFESSORES, CACHE_TTL_SEGUNDOS, SLOTS_AULA
)
from utils import (
    remover_acentos, padronizar, limpar_materia, padronizar_materia_interna,
    gerar_sigla_regiao, gerar_sigla_materia, gerar_codigo_padrao,
    extrair_id_do_link, validar_dataframe
)
from regras_alocacao import (
    verificar_compatibilidade_regiao, verificar_janelas,
    calcular_pl_ldb, calcular_carga_total,
    verificar_limites_carga, distribuir_carga_inteligente,
    REGRA_CARGA_HORARIA, REGRA_DISTRIBUICAO
)

# ==========================================
# 1. FUNÇÕES UTILITÁRIAS 
# ==========================================

def extrair_id_real(codigo_sujo):
    """
    Remove o prefixo 'PL-' e espaços extras.
    Ex: 'PL-P1DTARTE ' -> 'P1DTARTE'
    """
    if not codigo_sujo or codigo_sujo == "---": 
        return "---"
    s = str(codigo_sujo).upper().strip()
    s = s.replace("PL-", "")
    return s
# ==========================================
# 2. CONFIGURAÇÕES & ESTILO
# ==========================================
st.set_page_config(page_title="Gerador Escolar Pro", page_icon="🎓", layout="wide")

if 'hora_db' not in st.session_state:
    st.session_state['hora_db'] = datetime.now().strftime("%H:%M")

# Botão de emergência para limpar cache (sempre visível)
col_emergencia1, col_emergencia2 = st.columns([1, 5])
with col_emergencia1:
    if st.button("🚨 Reset Sistema", help="Limpa todo cache e recarrega dados do zero", type="primary"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.success("✅ Sistema resetado! Recarregue a página.")
        st.rerun()

st.markdown("""
<style>
    /* Estilo para o Card da Turma */
    .turma-card-moldura {
        background-color: #ffffff;
        border-radius: 8px;
        border-left: 5px solid #3498db;
        padding: 12px;
        margin-bottom: 15px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    
    .turma-titulo {
        font-weight: bold;
        color: #2c3e50;
        margin-bottom: 10px;
        border-bottom: 1px solid #eee;
    }

    /* Estilo para a linha da aula com cor dinâmica via inline style */
    .slot-aula-container {
        display: flex;
        align-items: center;
        margin-bottom: 4px;
        padding: 4px;
        border-radius: 4px;
    }

    .slot-label {
        font-weight: bold;
        color: #7f8c8d;
        width: 35px;
        font-size: 0.8em;
    }
</style>
""", unsafe_allow_html=True)


# ==========================================
# 3 FUNÇÕES DE GERAÇÃO DE CORES DINÂMICAS
# ==========================================

def get_contrast_text_color(hex_bg_color):
    """Garante leitura perfeita: fundo escuro = letra branca / fundo claro = letra preta."""
    hex_bg_color = hex_bg_color.lstrip('#')
    r, g, b = tuple(int(hex_bg_color[i:i+2], 16) for i in (0, 2, 4))
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#000000" if luminance > 0.5 else "#FFFFFF"

def gerar_estilo_professor_dinamico(id_professor):
    """Gera cores vibrantes baseadas no modelo das imagens do usuário."""
    if not id_professor or id_professor == "---":
        return {"bg": "#f8f9fa", "text": "#abb6c2", "border": "#e9ecef"}
    
    id_upper = str(id_professor).upper()
    
    # 1. CORES PRIORITÁRIAS (Baseadas fielmente nos seus prints)
    if "COHI" in id_upper: 
        bg = "#CCFF66" # Verde Lima
        txt = "#2E7D32"
    elif "EDFI" in id_upper: 
        bg = "#A000A0" # Magenta
        txt = "#FFFFFF"
    elif "ARTE" in id_upper: 
        # Alterna entre Marrom e Ciano para ARTE conforme o número no ID
        if any(c in id_upper for c in ["P1", "P3", "P5"]):
            bg = "#804000"; txt = "#FFFFFF" # Marrom
        else:
            bg = "#00FFFF"; txt = "#006064" # Ciano
    elif "ENRE" in id_upper: 
        bg = "#E3F2FD"; txt = "#0D47A1" # Azul Claro
    elif "LIIN" in id_upper: 
        bg = "#FFF9C4"; txt = "#F57F17" # Amarelo/Dourado
    
    # 2. SE NÃO FOR UMA MATÉRIA CONHECIDA, GERA COR ÚNICA SALTITANTE
    else:
        # Usamos um salt (sal) diferente para espalhar bem as cores
        hash_int = int(hashlib.sha256(id_upper.encode()).hexdigest(), 16)
        
        # O segredo é o multiplicador de Hue (matiz). 
        # Valores como 137.5 graus (razão áurea) espalham melhor
        hue = (hash_int % 360) / 360.0
        
        # Saturação alta para cores vivas como as suas
        saturation = 0.8 
        # Luminosidade balanceada
        lightness = 0.5 
        
        r, g, b = colorsys.hls_to_rgb(hue, lightness, saturation)
        bg = '#%02x%02x%02x' % (int(r*255), int(g*255), int(b*255))
        txt = get_contrast_text_color(bg)

    return {
        "bg": bg, 
        "text": txt, 
        "border": "rgba(0,0,0,0.2)"
    }
# ==========================================
# 4. CONEXÃO COM GOOGLE SHEETS
# ==========================================
@st.cache_resource
def init_gsheets_connection():
    """
    Inicializa a conexão com Google Sheets.
    
    Suporta múltiplas estruturas de configuração:
    - [connections.gsheets] (recomendado)
    - [gcp_service_account]
    - Estrutura direta no secrets
    
    Returns:
        tuple: (client, planilha_id) ou (None, None) em caso de erro
    """
    try:
        # VERIFICAR ESTRUTURA [connections.gsheets]
        if "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
            conn_secrets = st.secrets["connections"]["gsheets"]
            
            # Verificar se temos todas as credenciais necessárias
            creds_necessarias = ["type", "project_id", "private_key_id", "private_key", 
                               "client_email", "client_id", "spreadsheet"]
            
            for cred in creds_necessarias:
                if cred not in conn_secrets:
                    st.error(f"❌ '{cred}' não encontrado em [connections.gsheets]")
                    return None, None
            
            # Extrair o ID da planilha
            spreadsheet_url = conn_secrets.get("spreadsheet", "")
            PLANILHA_ID = extrair_id_do_link(spreadsheet_url)
            
            if not PLANILHA_ID:
                st.error("❌ Não foi possível extrair o ID da planilha")
                st.info(f"URL fornecida: {spreadsheet_url}")
                st.info("💡 Dica: Certifique-se de que o link está completo e no formato correto")
                return None, None
            
            # Debug: mostrar ID extraído (apenas no desenvolvimento)
            if st.secrets.get("DEBUG", False):
                st.sidebar.info(f"🔍 ID extraído: {PLANILHA_ID}")
            
            # Criar dicionário de credenciais
            credentials_dict = {
                "type": conn_secrets["type"],
                "project_id": conn_secrets["project_id"],
                "private_key_id": conn_secrets["private_key_id"],
                "private_key": conn_secrets["private_key"].replace('\\n', '\n'),
                "client_email": conn_secrets["client_email"],
                "client_id": conn_secrets["client_id"],
                "auth_uri": conn_secrets.get("auth_uri", "https://accounts.google.com/o/oauth2/auth"),
                "token_uri": conn_secrets.get("token_uri", "https://oauth2.googleapis.com/token"),
                "auth_provider_x509_cert_url": conn_secrets.get("auth_provider_x509_cert_url", "https://www.googleapis.com/oauth2/v1/certs"),
                "client_x509_cert_url": conn_secrets.get("client_x509_cert_url", f"https://www.googleapis.com/robot/v1/metadata/x509/{conn_secrets['client_email'].replace('@', '%40')}")
            }
        
        # TENTATIVA 2: Verificar se temos gcp_service_account
        elif "gcp_service_account" in st.secrets:
            credentials_dict = dict(st.secrets["gcp_service_account"])
            
            # Verificar se temos o ID da planilha
            if "PLANILHA_ID" in st.secrets:
                PLANILHA_ID = st.secrets["PLANILHA_ID"]
            elif "spreadsheet" in credentials_dict:
                PLANILHA_ID = extrair_id_do_link(credentials_dict["spreadsheet"])
            else:
                st.error("❌ Não encontrado: PLANILHA_ID ou spreadsheet")
                return None, None
        
        # TENTATIVA 3: Verificar se temos credenciais diretas
        elif all(key in st.secrets for key in ["type", "project_id", "private_key_id", "private_key", "client_email", "client_id"]):
            credentials_dict = {
                "type": st.secrets["type"],
                "project_id": st.secrets["project_id"],
                "private_key_id": st.secrets["private_key_id"],
                "private_key": st.secrets["private_key"].replace('\\n', '\n'),
                "client_email": st.secrets["client_email"],
                "client_id": st.secrets["client_id"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{st.secrets['client_email'].replace('@', '%40')}"
            }
            
            # Obter ID da planilha
            if "PLANILHA_ID" in st.secrets:
                PLANILHA_ID = st.secrets["PLANILHA_ID"]
            elif "spreadsheet" in st.secrets:
                PLANILHA_ID = extrair_id_do_link(st.secrets["spreadsheet"])
            else:
                st.error("❌ Não encontrado: PLANILHA_ID ou spreadsheet")
                return None, None
        
        # NENHUMA ESTRUTURA ENCONTRADA
        else:
            st.error("❌ Nenhuma estrutura de credenciais encontrada")
            st.write("**Estruturas verificadas:**")
            if "connections" in st.secrets:
                st.write("- [connections] encontrado")
                if "gsheets" in st.secrets["connections"]:
                    st.write("  - [gsheets] encontrado dentro de connections")
            if "gcp_service_account" in st.secrets:
                st.write("- [gcp_service_account] encontrado")
            
            # Mostrar todas as chaves disponíveis
            st.write("**Todas as chaves no secrets.toml:**")
            for key in st.secrets:
                st.write(f"- {key}")
            
            return None, None
        
        # CRIAR CREDENCIAIS
        credentials = service_account.Credentials.from_service_account_info(
            credentials_dict,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
        )
        
        # CONECTAR AO GOOGLE SHEETS
        client = gspread.authorize(credentials)
        
        # TESTAR A CONEXÃO (com retry)
        max_retries = 3
        for tentativa in range(max_retries):
            try:
                spreadsheet = client.open_by_key(PLANILHA_ID)
                st.sidebar.success(f"✅ Conectado!")
                st.sidebar.caption(f"📋 {spreadsheet.title}")
                return client, PLANILHA_ID
            except Exception as e:
                error_msg = str(e)
                
                # Se não for o último retry, tenta novamente
                if tentativa < max_retries - 1:
                    time.sleep(1)  # Aguarda 1 segundo antes de tentar novamente
                    continue
                
                # Última tentativa falhou, mostra erro detalhado
                st.error(f"❌ Erro ao acessar planilha (tentativa {tentativa + 1}/{max_retries}): {error_msg}")
                
                # Detectar tipo de erro específico
                if any(keyword in error_msg for keyword in ["Failed to resolve", "getaddrinfo failed", "NameResolutionError"]):
                    st.error("""
                    ## 🌐 Problema de DNS/Conectividade Detectado
                    
                    O Python não conseguiu resolver o DNS, mas o ping funciona.
                    Isso pode indicar:
                    - Problema com configuração de DNS do Python
                    - Firewall bloqueando conexões HTTPS do Python especificamente
                    - Problema temporário de DNS
                    
                    **💡 Soluções:**
                    1. Reinicie o Streamlit completamente
                    2. Verifique se há proxy configurado no sistema
                    3. Tente novamente em alguns minutos
                    4. Verifique se o Windows Firewall está bloqueando Python
                    """)
                elif "ConnectionPool" in error_msg or "Max retries exceeded" in error_msg:
                    st.warning("""
                    ## ⚠️ Problema de Conexão HTTPS Detectado
                    
                    ✅ **O ping funciona** (conectividade OK)  
                    ❌ **Mas HTTPS falha** (problema específico)
                    
                    **🔍 Diagnóstico:**
                    - DNS está funcionando ✅
                    - Conectividade básica OK ✅  
                    - HTTPS bloqueado ou com problema ❌
                    
                    **💡 Soluções (tente nesta ordem):**
                    
                    1. **Reinicie o Streamlit completamente**
                       - Feche todas as janelas do Streamlit
                       - Abra novamente: `streamlit run app.py`
                       
                    2. **Verifique Windows Firewall:**
                       - Abra "Firewall do Windows Defender com Segurança Avançada"
                       - Procure por regras bloqueando Python.exe
                       - Tente permitir temporariamente para testar
                       
                    3. **Teste HTTPS no PowerShell:**
                       ```powershell
                       Invoke-WebRequest -Uri https://sheets.googleapis.com
                       ```
                       - Se funcionar: problema específico do Python/gspread
                       - Se não funcionar: problema de rede/firewall
                       
                    4. **Configure proxy (se em rede corporativa):**
                       - Verifique se precisa de proxy
                       - Configure variáveis de ambiente se necessário
                       
                    5. **Atualize bibliotecas:**
                       ```bash
                       pip install --upgrade gspread google-auth requests urllib3
                       ```
                    """)
                elif "Permission denied" in error_msg or "403" in error_msg or "insufficient permissions" in error_msg.lower():
                    st.warning("""
                    **🔐 Problema de Permissão Detectado**
                    
                    A Service Account não tem permissão para acessar a planilha.
                    """)
                    if "client_email" in credentials_dict:
                        st.info(f"**📧 Compartilhe sua planilha com:** `{credentials_dict['client_email']}`")
                        st.info("**Permissão necessária:** Editor")
                elif "404" in error_msg or "not found" in error_msg.lower():
                    st.warning("""
                    **📋 Planilha Não Encontrada**
                    
                    O ID da planilha pode estar incorreto ou a planilha foi deletada.
                    """)
                else:
                    # Erro genérico
                    if "client_email" in credentials_dict:
                        st.info(f"**📧 Compartilhe sua planilha com:** `{credentials_dict['client_email']}`")
                        st.info("**Permissão necessária:** Editor")
                
                return None, None
            
    except Exception as e:
        st.error(f"❌ Erro na conexão: {str(e)}")
        return None, None

# Inicializar conexão
gs_client, PLANILHA_ID = init_gsheets_connection()

# ==========================================
# 5. VERIFICAR E AJUSTAR SECRETS.TOML
# ==========================================
if gs_client is None or not PLANILHA_ID:
    st.error("""
    ## ⚠️ Conexão não estabelecida
    
    **Seu `secrets.toml` parece estar assim:**
    ```toml
    [connections.gsheets]
    spreadsheet = "COLE_AQUI_O_LINK_DA_SUA_PLANILHA"
    type = "service_account"
    project_id = "seu-project-id"
    private_key_id = "sua-chave-id"
    private_key = "-----BEGIN PRIVATE KEY-----\\nsua-chave-privada-aqui\\n-----END PRIVATE KEY-----\\n"
    client_email = "seu-email@projeto.iam.gserviceaccount.com"
    client_id = "seu-client-id"
    auth_uri = "https://accounts.google.com/o/oauth2/auth"
    token_uri = "https://oauth2.googleapis.com/token"
    auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
    client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/seu-email%40projeto.iam.gserviceaccount.com"
    ```
    
    **Para corrigir:**
    
    1. **Cole o link da sua planilha** no campo `spreadsheet = `
    2. **Preencha todas as credenciais** da sua Service Account
    3. **Compartilhe a planilha** com o email do `client_email`
    4. **Dê permissão de Editor**
    5. **Recarregue a página**
    
    **Exemplo de link correto:**
    ```
    spreadsheet = "https://docs.google.com/spreadsheets/d/1A2B3C4D5E6F/edit"
    ```
    
    **Status atual do seu secrets.toml:**
    """)
    
    # Mostrar estrutura atual e diagnóstico detalhado
    if "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
        conn = st.secrets["connections"]["gsheets"]
        st.write("**Estrutura [connections.gsheets] encontrada:**")
        
        # Verificar cada campo
        campos_ok = True
        for key in ["type", "project_id", "private_key_id", "private_key", "client_email", "client_id", "spreadsheet"]:
            value = str(conn.get(key, ""))
            if "key" in key.lower() or "private" in key.lower():
                if value and len(value) > 10:
                    st.write(f"- `{key}`: ✅ Configurado (valor mascarado)")
                else:
                    st.write(f"- `{key}`: ❌ Vazio ou inválido")
                    campos_ok = False
            elif key == "spreadsheet":
                if value and "http" in value:
                    # Tentar extrair ID para validar
                    test_id = extrair_id_do_link(value)
                    if test_id:
                        st.write(f"- `{key}`: ✅ {value[:50]}... (ID: {test_id[:20]}...)")
                    else:
                        st.write(f"- `{key}`: ⚠️ Link encontrado mas ID não pôde ser extraído")
                        st.write(f"  Link completo: `{value}`")
                        campos_ok = False
                else:
                    st.write(f"- `{key}`: ❌ Vazio ou inválido")
                    campos_ok = False
            else:
                if value:
                    st.write(f"- `{key}`: ✅ Configurado")
                else:
                    st.write(f"- `{key}`: ❌ Vazio")
                    campos_ok = False
        
        # Verificar se a planilha foi compartilhada
        if campos_ok and "client_email" in conn:
            st.info(f"""
            **📧 Verifique se a planilha foi compartilhada:**
            
            Email da Service Account: `{conn['client_email']}`
            
            **Passos:**
            1. Abra sua planilha no Google Sheets
            2. Clique em "Compartilhar" (botão no canto superior direito)
            3. Cole o email acima
            4. Dê permissão de **Editor**
            5. Clique em "Concluído"
            6. Recarregue esta página
            """)
    
    # Formulário para testar manualmente
    with st.expander("🔧 Testar conexão manualmente", expanded=True):
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**🌐 Teste de Conectividade**")
            st.caption("Teste se consegue acessar os servidores do Google")
            
            if st.button("🔍 Testar Conectividade com Google"):
                import socket
                import urllib.request
                
                test_results = []
                
                # Teste 1: Resolução DNS
                try:
                    socket.gethostbyname("sheets.googleapis.com")
                    test_results.append(("✅ DNS", "Conseguiu resolver sheets.googleapis.com"))
                except socket.gaierror:
                    test_results.append(("❌ DNS", "NÃO conseguiu resolver sheets.googleapis.com"))
                
                # Teste 2: Conexão HTTP
                try:
                    response = urllib.request.urlopen("https://sheets.googleapis.com", timeout=5)
                    test_results.append(("✅ HTTP", f"Conseguiu conectar (Status: {response.getcode()})"))
                except Exception as e:
                    test_results.append(("❌ HTTP", f"NÃO conseguiu conectar: {str(e)[:100]}"))
                
                # Teste 3: Google.com geral
                try:
                    socket.gethostbyname("google.com")
                    test_results.append(("✅ Internet", "Tem conexão com a internet"))
                except socket.gaierror:
                    test_results.append(("❌ Internet", "NÃO tem conexão com a internet"))
                
                # Mostrar resultados
                for status, msg in test_results:
                    st.write(f"{status} {msg}")
                
                if all("✅" in r[0] for r in test_results):
                    st.success("🎉 Todos os testes passaram! A conexão deve funcionar.")
                else:
                    st.error("⚠️ Alguns testes falharam. Verifique sua conexão de rede.")
            
            st.markdown("---")
            st.write("**🔍 Testar extração de ID**")
            manual_url = st.text_input("Cole o link completo da sua planilha:", key="manual_url")
            
            if st.button("🔍 Testar extração de ID"):
                if manual_url:
                    test_id = extrair_id_do_link(manual_url)
                    if test_id:
                        st.success(f"✅ ID extraído: `{test_id}`")
                    else:
                        st.error("❌ Não consegui extrair o ID. Verifique o formato do link.")
                        st.code(manual_url)
                else:
                    st.warning("⚠️ Cole um link primeiro")
        
        with col2:
            st.write("**🔄 Limpar Cache**")
            st.caption("Se você alterou o secrets.toml, limpe o cache:")
            if st.button("🗑️ Limpar Cache e Recarregar"):
                st.cache_resource.clear()
                st.cache_data.clear()
                st.rerun()
            
            st.markdown("---")
            st.write("**💡 Soluções Rápidas**")
            st.caption("Tente estas soluções na ordem:")
            
            solucoes = [
                "1. Verifique se está conectado à internet",
                "2. Tente usar outra rede (hotspot do celular)",
                "3. Desative temporariamente o firewall do Windows",
                "4. Verifique se há proxy configurado",
                "5. Reinicie o roteador/modem",
                "6. Tente novamente em alguns minutos"
            ]
            
            for sol in solucoes:
                st.write(f"• {sol}")
    
    # Instruções finais
    st.markdown("---")
    st.info("""
    **📋 Checklist de Troubleshooting:**
    
    1. ✅ Verifique se todas as credenciais estão preenchidas no `secrets.toml`
    2. ✅ Confirme que o link da planilha está correto e completo
    3. ✅ **IMPORTANTE:** Compartilhe a planilha com o email da Service Account
    4. ✅ Dê permissão de **Editor** (não apenas Visualizador)
    5. ✅ Limpe o cache usando o botão acima
    6. ✅ Recarregue a página completamente (Ctrl+F5)
    
    **Se ainda não funcionar**, verifique os logs de erro acima para mais detalhes.
    """)
    
    st.stop()

# ==========================================
# 6. UTILITÁRIOS
# ==========================================
# Funções utilitárias foram movidas para utils.py
# Importadas no início do arquivo

# ==========================================
# 7. FUNÇÕES DE LEITURA/ESCRITA
# ==========================================

def ler_aba_gsheets(aba_nome: str, colunas_esperadas: List[str]) -> Tuple[pd.DataFrame, bool]:
    """
    Lê uma aba do Google Sheets e retorna um DataFrame padronizado.
    Versão BLINDADA: Usa get_all_values para evitar erro 'list index out of range' em abas vazias.
    """
    max_retries = 5
    base_delay = 2
    
    for tentativa in range(max_retries):
        try:
            if gs_client is None or not PLANILHA_ID:
                return pd.DataFrame(columns=colunas_esperadas), False

            # Rate limiting
            if tentativa > 0:
                time.sleep(base_delay * (2 ** tentativa))

            spreadsheet = gs_client.open_by_key(PLANILHA_ID)
            worksheet = spreadsheet.worksheet(aba_nome)

            # --- MUDANÇA PRINCIPAL AQUI ---
            # get_all_values() retorna uma lista de listas (crua), o que não dá erro se estiver vazia
            dados_brutos = worksheet.get_all_values()
            
            # Se a lista estiver vazia ou tiver apenas cabeçalho
            if not dados_brutos:
                return pd.DataFrame(columns=colunas_esperadas), True
            
            # A primeira linha é o cabeçalho
            headers = dados_brutos.pop(0)
            
            # Cria o DataFrame
            df = pd.DataFrame(dados_brutos, columns=headers)
            # ------------------------------
            
            # Padronizar nomes das colunas para maiúsculas/sem acento
            df.columns = [padronizar(c) for c in df.columns]
            
            # Garantir que temos todas as colunas esperadas
            for col in colunas_esperadas:
                col_norm = padronizar(col)
                if col_norm not in df.columns:
                    df[col_norm] = ""
            
            # Renomear para os nomes bonitos (originais)
            rename_dict = {}
            for col in colunas_esperadas:
                col_norm = padronizar(col)
                if col_norm in df.columns:
                    rename_dict[col_norm] = col
            
            if rename_dict:
                df = df.rename(columns=rename_dict)
            
            # Manter apenas as colunas esperadas na ordem certa
            df = df[colunas_esperadas].copy()
            
            # Limpeza final
            df = df.fillna("")
            for c in df.columns:
                if c in ["QTD_AULAS", "CARGA_HORÁRIA", "QTD_PL", "HORA_ALUNO", "HORA_PL", "TOTAL_HORAS", "MINUTOS_TOTAL"]:
                    # Converte para número, força 0 se der erro
                    df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0).astype(int)
                else:
                    df[c] = df[c].astype(str).apply(padronizar)
                    
            return df, True
            
        except gspread.exceptions.WorksheetNotFound:
            # Se a aba não existe, retornamos DataFrame vazio mas com status True (para o sistema criar depois)
            return pd.DataFrame(columns=colunas_esperadas), False
            
        except gspread.exceptions.APIError as e:
            error_str = str(e).lower()
            if '429' in error_str or 'quota exceeded' in error_str:
                if tentativa < max_retries - 1:
                    continue
            st.error(f"❌ Erro API ao ler '{aba_nome}': {e}")
            return pd.DataFrame(columns=colunas_esperadas), False
            
        except Exception as e:
            # Se for erro de índice (aba vazia), retornamos vazio sem alarde
            if "list index out of range" in str(e):
                return pd.DataFrame(columns=colunas_esperadas), True
                
            if tentativa < max_retries - 1:
                continue
            st.error(f"❌ Erro ao ler aba '{aba_nome}': {e}")
            return pd.DataFrame(columns=colunas_esperadas), False
    
    return pd.DataFrame(columns=colunas_esperadas), False


def escrever_aba_gsheets(aba_nome: str, df: pd.DataFrame) -> bool:
    """
    Escreve dados em uma aba do Google Sheets.
    Versão corrigida: Permite salvar DataFrames vazios (apenas cabeçalho) sem erro.
    """
    max_retries = 5
    base_delay = 2
    
    for tentativa in range(max_retries):
        try:
            if gs_client is None or not PLANILHA_ID:
                st.error(f"❌ Conexão não disponível para escrever na aba '{aba_nome}'")
                return False
            
            # Rate limiting
            if tentativa > 0:
                delay = base_delay * (2 ** tentativa)
                time.sleep(delay)
            
            spreadsheet = gs_client.open_by_key(PLANILHA_ID)
            
            # Verificar/Criar aba
            try:
                worksheet = spreadsheet.worksheet(aba_nome)
            except gspread.exceptions.WorksheetNotFound:
                cols = len(df.columns) if not df.empty else 1
                worksheet = spreadsheet.add_worksheet(title=aba_nome, rows=1000, cols=cols)
            
            # Limpar
            worksheet.clear()
            
            # Preparar dados (cabeçalho + valores)
            # SE ESTIVER VAZIO, SALVA APENAS O CABEÇALHO (Isso corrige o erro)
            if df.empty:
                values = [df.columns.tolist()]
            else:
                values = [df.columns.tolist()] + df.fillna("").values.tolist()
            
            # Atualizar
            worksheet.update(values, 'A1')
            
            return True
            
        except gspread.exceptions.APIError as e:
            error_str = str(e).lower()
            if '429' in error_str or 'quota exceeded' in error_str:
                if tentativa < max_retries - 1:
                    delay = base_delay * (2 ** tentativa)
                    time.sleep(delay)
                    continue
            return False
                
        except Exception as e:
            if tentativa < max_retries - 1:
                time.sleep(base_delay * (2 ** tentativa))
                continue
            st.error(f"❌ Erro ao salvar aba '{aba_nome}': {e}")
            return False
    
    return False

# ==========================================
# 8. LEITURA DE DADOS (CACHE)
# ==========================================
@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False, max_entries=1)
def carregar_banco():
    """
    Carrega todos os dados do Google Sheets, incluindo a nova tabela de Carga Horária (CH).
    """
    with st.spinner("🔄 Carregando sistema..."):
        # Se não houver conexão, retorna 7 dataframes vazios
        if gs_client is None or not PLANILHA_ID:
            empty_dfs = [pd.DataFrame() for _ in range(7)]
            return (*empty_dfs, False)
            
        try:
            # 1. Ler Turmas
            t, ok_t = ler_aba_gsheets("Turmas", COLS_PADRAO["Turmas"])
            
            # 2. Ler Curriculo
            c, ok_c = ler_aba_gsheets("Curriculo", COLS_PADRAO["Curriculo"])
            
            # 3. Ler Professores (combinando abas)
            p_ef, ok_ef = ler_aba_gsheets("ProfessoresEF", COLS_PADRAO["Professores"])
            p_dt, ok_dt = ler_aba_gsheets("ProfessoresDT", COLS_PADRAO["Professores"])
            
            if ok_ef and ok_dt:
                p = pd.concat([p_ef, p_dt], ignore_index=True)
                ok_p = True
            elif ok_ef:
                p = p_ef
                ok_p = True
            elif ok_dt:
                p = p_dt
                ok_p = True
            else:
                p, ok_p = ler_aba_gsheets("Professores", COLS_PADRAO["Professores"])
            
            # 4. Ler ConfigDias e Agrupamentos
            d, ok_d = ler_aba_gsheets("ConfigDias", COLS_PADRAO["ConfigDias"])
            r, ok_r = ler_aba_gsheets("Agrupamentos", COLS_PADRAO["Agrupamentos"])
            
            # 5. Ler Horario (opcional)
            h, ok_h = ler_aba_gsheets("Horario", COLS_PADRAO["Horario"])
            if not ok_h:
                h = pd.DataFrame()

            # 6. Ler Tabela CH (NOVA PARTE CORRIGIDA)
            ch_df, ok_ch = ler_aba_gsheets("CH", COLS_PADRAO["CH"])
            
            # Se a aba não existir ou estiver vazia, gera o padrão do código
            if not ok_ch or ch_df.empty:
                from ch import gerar_dataframe_ch
                ch_df = gerar_dataframe_ch()
            
            # Verificar se tudo essencial carregou
            sucesso = ok_t and ok_c and ok_p and ok_d and ok_r
            
            # Retorna os 7 DataFrames + Status
            return t, c, p, d, r, h, ch_df, sucesso
            
        except Exception as e:
            st.cache_data.clear()
            error_msg = str(e)
            st.error(f"❌ Erro ao carregar dados: {error_msg}")
            
            # Retorna vazios em caso de erro
            empty_dfs = [pd.DataFrame() for _ in range(7)]
            return (*empty_dfs, False)

# Carregar dados com tratamento de erro robusto
try:
    # Note a variável 'dch' adicionada aqui ⬇️
    dt, dc, dp, dd, da, dh, dch, sistema_seguro = carregar_banco()
except Exception as e:
    st.error(f"❌ Erro crítico ao inicializar sistema: {str(e)}")
    st.info("💡 **Tente:**\n"
            "1. Clique no botão '🚨 Reset Sistema' acima\n"
            "2. Recarregue a página completamente (Ctrl+F5)\n"
            "3. Verifique sua conexão com a internet\n"
            "4. Confirme se as credenciais estão corretas no secrets.toml")
    # Forçar parada se houver erro crítico
    st.stop()

# ==========================================
# 9. FUNÇÕES DE SALVAR
# ==========================================
def salvar_seguro(dt, dc, dp, dd, da, dh=None):
    """Salva todos os dados no Google Sheets com rate limiting"""
    try:
        with st.status("💾 Salvando...", expanded=True) as status:
            # Escrever cada aba com delay entre requisições para evitar quota exceeded
            status.write("📝 Salvando Turmas...")
            if not escrever_aba_gsheets("Turmas", dt.fillna("")):
                return
            time.sleep(0.5)  # Delay entre requisições
            
            status.write("📝 Salvando Currículo...")
            if not escrever_aba_gsheets("Curriculo", dc.fillna("")):
                return
            time.sleep(0.5)
            
            # Separar professores por vínculo e salvar nas abas corretas
            if not dp.empty:
                # Garantir que a coluna VÍNCULO existe e está padronizada
                if 'VÍNCULO' in dp.columns:
                    dp['VÍNCULO'] = dp['VÍNCULO'].astype(str).apply(padronizar)
                    # Separar por vínculo
                    dp_ef = dp[dp['VÍNCULO'].str.contains('EFETIVO', case=False, na=False)].copy()
                    dp_dt = dp[~dp['VÍNCULO'].str.contains('EFETIVO', case=False, na=False)].copy()
                    
                    # Salvar nas abas separadas
                    status.write("📝 Salvando ProfessoresEF...")
                    if not escrever_aba_gsheets("ProfessoresEF", dp_ef.fillna("")):
                        return
                    time.sleep(0.5)
                    
                    status.write("📝 Salvando ProfessoresDT...")
                    if not escrever_aba_gsheets("ProfessoresDT", dp_dt.fillna("")):
                        return
                    time.sleep(0.5)
                else:
                    # Se não tiver coluna VÍNCULO, salvar tudo em ProfessoresDT (compatibilidade)
                    status.write("📝 Salvando ProfessoresDT...")
                    if not escrever_aba_gsheets("ProfessoresDT", dp.fillna("")):
                        return
                    time.sleep(0.5)
            else:
                # Se estiver vazio, criar abas vazias
                status.write("📝 Criando abas vazias de professores...")
                escrever_aba_gsheets("ProfessoresEF", pd.DataFrame(columns=COLS_PADRAO["Professores"]).fillna(""))
                time.sleep(0.5)
                escrever_aba_gsheets("ProfessoresDT", pd.DataFrame(columns=COLS_PADRAO["Professores"]).fillna(""))
                time.sleep(0.5)
            
            status.write("📝 Salvando ConfigDias...")
            if not escrever_aba_gsheets("ConfigDias", dd.fillna("")):
                return
            time.sleep(0.5)
            
            status.write("📝 Salvando Agrupamentos...")
            if not escrever_aba_gsheets("Agrupamentos", da.fillna("")):
                return
            time.sleep(0.5)
            
            if dh is not None:
                status.write("📝 Salvando Horário...")
                if not escrever_aba_gsheets("Horario", dh.fillna("")):
                    return
                time.sleep(0.5)
            
            # Limpar cache
            st.cache_data.clear()
            status.update(label="✅ Salvo!", state="complete", expanded=False)
            
        time.sleep(1)
        st.rerun()
    except Exception as e: 
        st.error(f"Erro ao salvar: {e}")
        if '429' in str(e) or 'Quota exceeded' in str(e):
            st.info("💡 **Quota da API excedida.** Aguarde alguns minutos antes de tentar salvar novamente.")
        
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")

def botao_salvar(label, key):
    """Botão de salvar com verificação"""
    if sistema_seguro and PLANILHA_ID:
        if st.button(label, key=key, type="primary", use_container_width=True):
            salvar_seguro(dt, dc, dp, dd, da)
    else:
        st.button(f"🔒 {label}", key=key, disabled=True, use_container_width=True)

# ==========================================
# 10. CÉREBRO: RH ROBIN HOOD CORRIGIDO
# ==========================================
def gerar_professores_v52(
    dt: pd.DataFrame,
    dc: pd.DataFrame,
    dp_existente: pd.DataFrame,
    carga_minima: int = CARGA_MINIMA_PADRAO,
    carga_maxima: int = CARGA_MAXIMA_PADRAO,
    media_alvo: int = MEDIA_ALVO_PADRAO
) -> Tuple[pd.DataFrame, List]:
    """Versão corrigida: calcula demanda corretamente"""
    
    # 1. Calcular demanda TOTAL por região e matéria
    demanda_total = {}
    for _, turma in dt.iterrows():
        reg = padronizar(turma['REGIÃO'])
        serie = turma['SÉRIE/ANO']
        curr = dc[dc['SÉRIE/ANO'] == serie]
        for _, item in curr.iterrows():
            mat = padronizar_materia_interna(item['COMPONENTE'])
            qtd = int(item['QTD_AULAS'])
            chave = (reg, mat)
            demanda_total[chave] = demanda_total.get(chave, 0) + qtd
    
    # 2. Contar professores existentes
    contadores = {}
    professores_por_regiao_materia = {}
    
    for _, p in dp_existente.iterrows():
        reg = padronizar(p['REGIÃO'])
        mats = [padronizar_materia_interna(m) for m in str(p['COMPONENTES']).split(',') if m]
        num = 0
        match = re.search(r'P(\d+)', str(p['CÓDIGO']))
        if match: 
            num = int(match.group(1))
        
        for m in mats:
            chave = (reg, m)
            if num > contadores.get(chave, 0):
                contadores[chave] = num
            
            # Armazena professor por região/matéria
            if chave not in professores_por_regiao_materia:
                professores_por_regiao_materia[chave] = []
            professores_por_regiao_materia[chave].append({
                'carga': int(p['CARGA_HORÁRIA']),
                'vinculo': p['VÍNCULO'],
                'escolas': [padronizar(x) for x in str(p['ESCOLAS_ALOCADAS']).split(',') if padronizar(x)]
            })
    
    # 3. Reduzir demanda com professores existentes (considerando compatibilidade Fundão/Timbuí)
    demanda_restante = {}
    
    for (reg, mat), total in demanda_total.items():
        demanda_restante[(reg, mat)] = total
        
        # Verificar professores da mesma região/matéria
        if (reg, mat) in professores_por_regiao_materia:
            for prof in professores_por_regiao_materia[(reg, mat)]:
                carga_disponivel = min(prof['carga'], carga_maxima)
                if carga_disponivel > 0:
                    if demanda_restante[(reg, mat)] > 0:
                        usado = min(demanda_restante[(reg, mat)], carga_disponivel)
                        demanda_restante[(reg, mat)] -= usado
        
        # REGRA ESPECIAL: Professores de Fundão podem cobrir demanda de Timbuí e vice-versa
        if reg == "FUNDÃO":
            reg_compativel = "TIMBUÍ"
            if (reg_compativel, mat) in professores_por_regiao_materia:
                for prof in professores_por_regiao_materia[(reg_compativel, mat)]:
                    carga_disponivel = min(prof['carga'], carga_maxima)
                    if carga_disponivel > 0:
                        if demanda_restante[(reg, mat)] > 0:
                            usado = min(demanda_restante[(reg, mat)], carga_disponivel)
                            demanda_restante[(reg, mat)] -= usado
        elif reg == "TIMBUÍ":
            reg_compativel = "FUNDÃO"
            if (reg_compativel, mat) in professores_por_regiao_materia:
                for prof in professores_por_regiao_materia[(reg_compativel, mat)]:
                    carga_disponivel = min(prof['carga'], carga_maxima)
                    if carga_disponivel > 0:
                        if demanda_restante[(reg, mat)] > 0:
                            usado = min(demanda_restante[(reg, mat)], carga_disponivel)
                            demanda_restante[(reg, mat)] -= usado
    
    # 4. Agrupar necessidade de Fundão e Timbuí para criar vagas compartilhadas
    necessidade = {}
    necessidade_fundao_timbui = {}  # Agrupar por matéria
    
    for chave, restante in demanda_restante.items():
        reg, mat = chave
        if restante > 0:
            if reg in ["FUNDÃO", "TIMBUÍ"]:
                if mat not in necessidade_fundao_timbui:
                    necessidade_fundao_timbui[mat] = {"FUNDÃO": 0, "TIMBUÍ": 0}
                necessidade_fundao_timbui[mat][reg] = restante
            else:
                necessidade[chave] = restante
    
    # Criar vagas compartilhadas para Fundão/Timbuí quando há demanda em ambas ou quando faz sentido
    for mat, deficits in necessidade_fundao_timbui.items():
        demanda_fundao = deficits["FUNDÃO"]
        demanda_timbui = deficits["TIMBUÍ"]
        
        # Se há demanda em ambas ou demanda significativa em uma, criar vaga compartilhada
        if demanda_fundao > 0 or demanda_timbui > 0:
            demanda_total_compartilhada = demanda_fundao + demanda_timbui
            # Criar vaga compartilhada se a demanda total justificar
            if demanda_total_compartilhada >= carga_minima:
                necessidade[("FUNDÃO", mat)] = demanda_total_compartilhada  # Usar Fundão como região principal
            else:
                # Se demanda pequena, criar vagas separadas
                if demanda_fundao > 0:
                    necessidade[("FUNDÃO", mat)] = demanda_fundao
                if demanda_timbui > 0:
                    necessidade[("TIMBUÍ", mat)] = demanda_timbui
    
    # 5. Criar novos professores apenas para necessidade real
    novos_profs = []
    
    for (reg, mat), deficit in necessidade.items():
        if deficit <= 0:
            continue
        
        # REGRA 7: Distribuir carga de forma inteligente
        cargas = distribuir_carga_inteligente(deficit)
        
        # Validar cargas
        cargas_validas = []
        for carga in cargas:
            valido, msg = verificar_limites_carga(carga, deficit)
            if valido:
                cargas_validas.append(carga)
        
        if not cargas_validas:
            cargas_validas = [min(deficit, REGRA_CARGA_HORARIA["maximo_aulas"])]
        
        cargas = cargas_validas
        
        # Cria os professores
        for i, carga in enumerate(cargas):
            if carga > 0:
                # Atualiza contador
                chave_cont = (reg, mat)
                contadores[chave_cont] = contadores.get(chave_cont, 0) + 1
                
                # Gera código
                cod = gerar_codigo_padrao(contadores[chave_cont], "DT", reg, mat)
                
                # REGRA ESPECIAL: Se for Fundão e há demanda de Timbuí também, criar vaga compartilhada
                escolas_regiao = []
                nome_vaga = f"VAGA {mat} {reg}"
                
                if reg == "FUNDÃO" and mat in necessidade_fundao_timbui:
                    # Verificar se há demanda de Timbuí também
                    demanda_timbui = necessidade_fundao_timbui[mat].get("TIMBUÍ", 0)
                    if demanda_timbui > 0:
                        # Criar vaga compartilhada
                        escolas_fundao = list(set(dt[dt['REGIÃO'] == "FUNDÃO"]['ESCOLA'].unique())) if not dt.empty else []
                        escolas_timbui = list(set(dt[dt['REGIÃO'] == "TIMBUÍ"]['ESCOLA'].unique())) if not dt.empty else []
                        escolas_regiao = escolas_fundao[:2] + escolas_timbui[:2]
                        nome_vaga = f"VAGA {mat} FUNDÃO/TIMBUÍ"
                    else:
                        escolas_regiao = list(set(dt[dt['REGIÃO'] == reg]['ESCOLA'].unique())) if not dt.empty else []
                else:
                    escolas_regiao = list(set(dt[dt['REGIÃO'] == reg]['ESCOLA'].unique())) if not dt.empty else []
                
                # REGRA 5: Calcular PL baseado na LDB (1/3)
                pl_ldb = calcular_pl_ldb(round(carga))
                
                novos_profs.append({
                    "CÓDIGO": cod,
                    "NOME": nome_vaga,
                    "COMPONENTES": mat,
                    "CARGA_HORÁRIA": round(carga),
                    "REGIÃO": reg,
                    "VÍNCULO": "DT",
                    "TURNO_FIXO": "",
                    "ESCOLAS_ALOCADAS": ",".join(escolas_regiao[:4]) if escolas_regiao else "",  # Até 4 escolas se compartilhada
                    "QTD_PL": pl_ldb  # PL calculado pela LDB
                })
    
    return pd.DataFrame(novos_profs), []

# ==========================================
# 11. CÉREBRO: GERAÇÃO E ALOCAÇÃO INTELIGENTE
# ==========================================
def carregar_objs(df):
    professores = {}
    for _, r in df.iterrows():
        cod = str(r['CÓDIGO'])
        mats = [padronizar_materia_interna(m) for m in str(r['COMPONENTES']).split(',') if m]
        vinc = str(r['VÍNCULO']).strip().upper()
        professores[cod] = {
            'id': cod, 'nome': r['NOME'], 'mats': set(mats), 'reg': padronizar(r['REGIÃO']),
            'vin': vinc, 'tf': padronizar(r['TURNO_FIXO']),
            'escolas_base': set([padronizar(x) for x in str(r['ESCOLAS_ALOCADAS']).split(',') if padronizar(x)]),
            'max': int(r['CARGA_HORÁRIA']), 'atrib': 0, 'ocup': {}, 'escolas_reais': set(), 'regs_alocadas_historico': set()
        }
    return list(professores.values())

def carregar_rotas(df):
    m = {}
    for _, row in df.iterrows():
        escs = [padronizar(x) for x in str(row['LISTA_ESCOLAS']).split(',') if padronizar(x)]
        for e in escs: m[e] = set(escs)
    return m

def resolver_grade_inteligente(
    turmas: List,
    curriculo: pd.DataFrame,
    profs: List,
    rotas: Dict,
    turno_atual: str,
    mapa_escola_regiao: Dict,
    max_tentativas: int = MAX_TENTATIVAS_ALOCACAO
) -> Tuple[bool, Dict, str, List]:
    """Versão corrigida: não cria professores em excesso"""
    turno_atual = padronizar(turno_atual)
    
    # Preparar demandas REAIS
    demandas = []
    for turma in turmas:
        curr = curriculo[curriculo['SÉRIE/ANO'] == turma['ano']]
        aulas = []
        for _, r in curr.iterrows():
            mat = padronizar_materia_interna(r['COMPONENTE'])
            if mat in [padronizar_materia_interna(m) for m in MATERIAS_ESPECIALISTAS]:
                aulas.extend([mat] * int(r['QTD_AULAS']))
        
        while len(aulas) < SLOTS_AULA:
            aulas.append("---")
        
        for slot, mat in enumerate(aulas[:SLOTS_AULA]):
            if mat != "---":
                demandas.append({
                    'turma': turma,
                    'mat': mat,
                    'slot': slot,
                    'prioridade': 1
                })
    
    # Se não há demandas, retornar grade vazia
    if not demandas:
        grade_vazia = {t['nome_turma']: ["---"] * SLOTS_AULA for t in turmas}
        return True, grade_vazia, "Nenhuma demanda de especialistas", profs
    
    # NÃO criar professores durante alocação - será consolidado depois
    for tentativa in range(max_tentativas):
        grade = {t['nome_turma']: [None] * SLOTS_AULA for t in turmas}
        profs_temp = copy.deepcopy(profs)
        random.shuffle(demandas)
        
        sucesso = True
        
        for item in demandas:
            turma, mat, slot = item['turma'], item['mat'], item['slot']
            esc, reg = padronizar(turma['escola_real']), padronizar(turma['regiao_real'])
            
            # Encontrar candidatos
            candidatos = []
            
            for p in profs_temp:
                # REGRA: Verificar se o professor leciona a matéria
                if mat not in p['mats']:
                    continue
                
                # REGRA: Verificar turno fixo (se aplicável)
                if p['tf'] and p['tf'] not in ["AMBOS", "", turno_atual]:
                    continue
                
                # REGRA: Verificar compatibilidade de região (com matéria para regras especiais)
                pode_dar_aula, prioridade_regiao = verificar_compatibilidade_regiao(p['reg'], reg, mat)
                if not pode_dar_aula:
                    continue  # Região incompatível
                
                # REGRA: Verificar limite de carga horária
                if p['atrib'] >= min(p['max'], REGRA_CARGA_HORARIA["maximo_aulas"]):
                    continue
                
                # REGRA 1: Verificar conflito de horário (mesmo slot = impossível)
                if slot in p['ocup']:
                    continue  # Professor já está ocupado neste horário
                
                # REGRA 4: Verificar janelas/buracos entre aulas (apenas na mesma escola)
                # Janelas são permitidas entre escolas diferentes (professor pode se deslocar)
                tem_janela = False
                if p['ocup']:  # Só verifica se já tem aulas alocadas
                    # Verificar se há aulas na mesma escola
                    tem_aula_mesma_escola = any(e_occ == esc for e_occ in p['ocup'].values())
                    
                    if tem_aula_mesma_escola:
                        # Só verifica janela se há aulas na mesma escola
                        tem_janela = verificar_janelas(p['ocup'], slot, esc, rotas)
                        if tem_janela:
                            continue  # Criaria janela/buraco na mesma escola
                
                # Verificar conflitos de deslocamento (escolas diferentes, sem rota)
                # Tornar mais flexível: permitir deslocamento se houver tempo suficiente
                conflito_deslocamento = False
                for s_occ, e_occ in p['ocup'].items():
                    if e_occ != esc:
                        # Verificar se estão na mesma rota
                        mesma_rota = esc in rotas.get(e_occ, set()) or e_occ in rotas.get(esc, set())
                        if not mesma_rota:
                            # Escolas diferentes sem rota: verificar se slots são muito próximos
                            dist = abs(s_occ - slot)
                            # Permitir deslocamento se houver pelo menos 1 slot de diferença (dist >= 1)
                            # Isso permite: 1ª aula escola A, 3ª aula escola B (tempo para deslocar)
                            if dist < 1:  # Apenas bloquear se for exatamente o mesmo slot
                                conflito_deslocamento = True
                                break
                
                if conflito_deslocamento:
                    continue
                
                # Score de prioridade (quanto maior, melhor)
                score = 0
                
                # Máxima prioridade: Professor efetivo na escola base
                if p['vin'] == "EFETIVO" and esc in p['escolas_base']:
                    score += 100000
                
                # Alta prioridade: Mesma região ou compatibilidade Fundão ↔ Timbuí
                # REGRA GERAL: Fundão e Timbuí são compatíveis para TODAS as matérias
                if ((p['reg'] == "FUNDÃO" and reg == "TIMBUÍ") or \
                    (p['reg'] == "TIMBUÍ" and reg == "FUNDÃO")):
                    score += prioridade_regiao * 1500  # Bonus para facilitar alocação entre Fundão e Timbuí
                else:
                    score += prioridade_regiao * 1000
                
                # Prioridade: Escola base do professor
                if esc in p['escolas_base']:
                    score += 2000
                
                # Prioridade: Escola já visitada pelo professor
                if esc in p['escolas_reais']:
                    score += 1000
                
                # Prioridade: Carga disponível (preferir professores com mais espaço)
                score += (REGRA_CARGA_HORARIA["maximo_aulas"] - p['atrib']) * 10
                
                # Prioridade: Aulas consecutivas na mesma escola
                if esc in [e for s, e in p['ocup'].items()]:
                    score += 500
                
                candidatos.append((score, p))
            
            if candidatos:
                # Escolhe o melhor
                candidatos.sort(key=lambda x: -x[0])
                escolhido = candidatos[0][1]
                grade[turma['nome_turma']][slot] = escolhido['id']
                escolhido['ocup'][slot] = esc
                escolhido['atrib'] += 1
                escolhido['escolas_reais'].add(esc)
            else:
                # NÃO criar professores durante alocação - será consolidado depois
                # Marcar como não alocado para consolidação posterior
                sucesso = False
                grade[turma['nome_turma']][slot] = "---"
                
                # Debug: verificar por que não encontrou candidatos
                if tentativa == 0:  # Só na primeira tentativa para não poluir logs
                    profs_disponiveis = [p for p in profs_temp if mat in p['mats']]
                    if profs_disponiveis:
                        # Há professores da matéria, mas foram bloqueados pelas regras
                        pass  # Será tratado na consolidação
        
        # Verifica se todas as aulas foram alocadas
        todas_alocadas = all(all(v is not None for v in linha) for linha in grade.values())
        
        if todas_alocadas and sucesso:
            # Preenche qualquer slot None com "---"
            for t_nome, aulas in grade.items():
                for i in range(SLOTS_AULA):
                    if aulas[i] is None:
                        grade[t_nome][i] = "---"
            
            # Atualiza a lista original de professores
            for p_novo in profs_temp:
                if p_novo['id'] not in [p['id'] for p in profs]:
                    profs.append(p_novo)
            
            return True, grade, f"Sucesso na tentativa {tentativa+1}", profs
    
    # Se não conseguiu, retorna o que tem
    for t_nome, aulas in grade.items():
        for i in range(SLOTS_AULA):
            if aulas[i] is None:
                grade[t_nome][i] = "---"
    
    return False, grade, "Não foi possível alocar todas as aulas", profs

def desenhar_xls(writer, escola, dados):
    wb = writer.book
    ws = wb.add_worksheet(escola[:30].replace("/","-"))
    fmt = wb.add_format({'border':1, 'align':'center', 'text_wrap':True, 'valign': 'vcenter'})
    r=0
    ws.write(r,0,escola, wb.add_format({'bold': True, 'size': 14})); r+=2
    for tit, df in dados:
        ws.write(r,0,tit, wb.add_format({'bold': True, 'bg_color': '#D3D3D3'})); r+=1
        for i, col in enumerate(df.columns): ws.write(r, i+1, col, wb.add_format({'bold': True, 'border': 1, 'align': 'center', 'bg_color': '#F0F0F0'}))
        r+=1
        for idx, row in df.iterrows():
            try:
                label_idx = f"{int(idx)+1}ª"
            except:
                label_idx = str(idx)
            ws.write(r, 0, label_idx, fmt)
            for i, val in enumerate(row): ws.write(r, i+1, val if val else "", fmt)
            r+=1
        r+=1

# ==========================================
# 12. INTERFACE PRINCIPAL
# ==========================================
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2997/2997322.png", width=60)
    st.title("Gestor Escolar")
    
    # Status da conexão
    if gs_client is None:
        st.error("⚠️ Erro na conexão com Google Sheets")
    elif not PLANILHA_ID:
        st.error("⚠️ ID da planilha não encontrado")
    elif sistema_seguro:
        st.success("✅ Sistema Carregado")
        try:
            spreadsheet = gs_client.open_by_key(PLANILHA_ID)
            st.caption(f"📋 {spreadsheet.title}")
        except:
            pass
    else:
        st.warning("⚠️ Dados incompletos")
    
    if st.button("🔄 Atualizar Dados", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    
    st.markdown("---")
    st.caption(f"Última atualização: {st.session_state['hora_db']}")

# Verificar conexão antes de mostrar abas
if gs_client is None or not PLANILHA_ID:
    st.stop()

# Criar abas
t1, t2, t3, t4, t5, t6, t7, t8, t9 = st.tabs([
    "📊 Dashboard", 
    "⚙️ Config", 
    "📍 Rotas", 
    "🏫 Turmas", 
    "👨‍🏫 Professores", 
    "💼 Vagas", 
    "🚀 Gerador", 
    "📅 Ver Horário", 
    "✏️ Editor Manual"  
])

# ==========================================
# 13 ABAS DA APLICAÇÃO
# ==========================================
# ABA 1: DASHBOARD
with t1:
    if dt.empty: 
        st.info("📝 Cadastre turmas na aba '🏫 Turmas'.")
    else:
        # Cálculo REAL da demanda
        total_aulas_especialistas = 0
        for _, turma in dt.iterrows():
            curr = dc[dc['SÉRIE/ANO'] == turma['SÉRIE/ANO']]
            for _, item in curr.iterrows():
                if padronizar_materia_interna(item['COMPONENTE']) in [padronizar_materia_interna(m) for m in MATERIAS_ESPECIALISTAS]:
                    total_aulas_especialistas += int(item['QTD_AULAS'])
        
        st.info(f"📊 **Demanda Real:** {total_aulas_especialistas} aulas semanais de especialistas")
        
        c1,c2,c3,c4,c5 = st.columns(5)
        with c1: sel_regiao = st.multiselect("🌍 Região", sorted(dt['REGIÃO'].unique()))
        with c2: 
            esc_opts = dt[dt['REGIÃO'].isin(sel_regiao)]['ESCOLA'].unique() if sel_regiao else dt['ESCOLA'].unique()
            sel_escola = st.selectbox("🏢 Escola", ["Rede Completa"] + sorted(list(esc_opts)))
        with c3: sel_nivel = st.selectbox("👶/👦 Nível", ["Todos"] + sorted(dt['NÍVEL'].unique().tolist()))
        with c4: sel_serie = st.selectbox("📚 Série", ["Todas"] + ORDEM_SERIES)
        with c5: sel_turma = st.selectbox("🔠 Turma", ["Todas"] + sorted(dt['TURMA'].unique().tolist()))
        st.markdown("---")
        alvo = dt.copy()
        if sel_regiao: alvo = alvo[alvo['REGIÃO'].isin(sel_regiao)]
        if sel_escola != "Rede Completa": alvo = alvo[alvo['ESCOLA'] == sel_escola]
        if sel_nivel != "Todos": alvo = alvo[alvo['NÍVEL'] == sel_nivel]
        if sel_serie != "Todas": alvo = alvo[alvo['SÉRIE/ANO'] == sel_serie]
        if sel_turma != "Todas": alvo = alvo[alvo['TURMA'] == sel_turma]
        dem, oferta = {}, {}
        tot_dem, tot_of = 0, 0
        for _, r in alvo.iterrows():
            curr = dc[dc['SÉRIE/ANO'] == r['SÉRIE/ANO']]
            for _, i in curr.iterrows():
                m = limpar_materia(i['COMPONENTE'])
                qtd = int(i['QTD_AULAS'])
                dem[m] = dem.get(m, 0) + qtd
                tot_dem += qtd
        for _, p in dp.iterrows():
            if sel_regiao and p['REGIÃO'] not in sel_regiao: continue
            if p['VÍNCULO'] == 'EFETIVO' and sel_escola != "Rede Completa" and sel_escola not in str(p['ESCOLAS_ALOCADAS']): continue
            ms = [limpar_materia(x) for x in str(p['COMPONENTES']).split(',')]
            ch = int(p['CARGA_HORÁRIA'])
            if ms:
                rat = ch / len(ms)
                for m in ms: oferta[m] = oferta.get(m, 0) + rat
                tot_of += ch
        c_m, c_r = st.columns([3,1])
        with c_m:
            m1,m2,m3,m4 = st.columns(4)
            m1.metric("Turmas", len(alvo))
            m2.metric("Demanda", tot_dem)
            m3.metric("Oferta", int(tot_of))
            m4.metric("Déficit", max(0, tot_dem - tot_of))
        with c_r: ch_padrao = st.slider("Média Aulas/Prof", 10, 40, 20)
        res = []
        for m, q in dem.items():
            o = oferta.get(m, 0)
            s = q-o
            res.append({"Matéria": m, "Falta": int(s), "Novos": round(s/ch_padrao, 1) if s>0 else 0, "Status": "🔴" if s>0 else "🟢"})
        st.dataframe(pd.DataFrame(res), use_container_width=True)

# ABA 2: CONFIG (MANTENHA O MESMO CÓDIGO)
with t2:
    c1, c2 = st.columns(2)
    with c1:
        st.write("📅 Dias"); dd = st.data_editor(dd, num_rows="dynamic", key="edd")
        with st.form("fd"):
            a = st.selectbox("Série", ORDEM_SERIES)
            d = st.selectbox("Dia", DIAS_SEMANA)
            if st.form_submit_button("Add"): 
                dd = pd.concat([dd, pd.DataFrame([{"SÉRIE/ANO": a, "DIA_PLANEJAMENTO": d}])], ignore_index=True); salvar_seguro(dt, dc, dp, dd, da)
    with c2:
        st.write("📚 Currículo"); dc = st.data_editor(dc, num_rows="dynamic", key="edc")
        with st.form("fc"):
            a = st.selectbox("Série", ORDEM_SERIES, key="aca")
            m = st.selectbox("Matéria", MATERIAS_ESPECIALISTAS)
            q = st.number_input("Qtd", 1, 10, 2)
            if st.form_submit_button("Add"):
                dc = pd.concat([dc, pd.DataFrame([{"SÉRIE/ANO": a, "COMPONENTE": m, "QTD_AULAS": q}])], ignore_index=True); salvar_seguro(dt, dc, dp, dd, da)
    botao_salvar("Salvar Config", "bcfg")
    
    st.markdown("---")
    st.subheader("📜 Tabela de PL (Lei 1.071/2017)")

    # Mostra a tabela atual do código
    df_pl_padrao = gerar_dataframe_ch()
    st.dataframe(df_pl_padrao, use_container_width=True, hide_index=True)

    if st.button("💾 Gravar Tabela PL na Planilha Google"):
        if sistema_seguro:
            escrever_aba_gsheets("CH", df_pl_padrao)
            st.success("✅ Tabela de Carga Horária salva na aba 'CH'!")
        else:
            st.error("Sem conexão com a planilha.")
            
# ABA 3: ROTAS (MANTENHA O MESMO CÓDIGO)
with t3:
    da = st.data_editor(da, num_rows="dynamic", key="edr")
    with st.expander("Nova Rota"):
        with st.form("fr"):
            n = st.text_input("Nome")
            l = st.multiselect("Escolas", sorted(dt['ESCOLA'].unique()) if not dt.empty else [])
            if st.form_submit_button("Criar"):
                da = pd.concat([da, pd.DataFrame([{"NOME_ROTA": n, "LISTA_ESCOLAS": ",".join(l)}])], ignore_index=True); salvar_seguro(dt, dc, dp, dd, da)
    botao_salvar("Salvar Rotas", "brot")

# ABA 4: TURMAS (MANTENHA O MESMO CÓDIGO)
with t4:
    with st.expander("➕ Nova Turma", expanded=False):
        with st.form("ft"):
            c1,c2,c3 = st.columns(3)
            e = c1.selectbox("Escola", sorted(dt['ESCOLA'].unique()) + ["NOVA..."] if not dt.empty else ["NOVA..."])
            if e=="NOVA...": e = c1.text_input("Nome Escola")
            t = c2.text_input("Turma")
            tn = c3.selectbox("Turno", ["MATUTINO", "VESPERTINO"])
            c4,c5 = st.columns(2)
            an = c4.selectbox("Ano", ORDEM_SERIES)
            rg = c5.selectbox("Região", REGIOES)
            if st.form_submit_button("Salvar"):
                nv = "INFANTIL" if "ANO" not in an else "FUNDAMENTAL"
                dt = pd.concat([dt, pd.DataFrame([{"ESCOLA": padronizar(e), "TURMA": padronizar(t), "TURNO": tn, "SÉRIE/ANO": an, "REGIÃO": rg, "NÍVEL": nv}])], ignore_index=True); salvar_seguro(dt, dc, dp, dd, da)
    dt = st.data_editor(dt, num_rows="dynamic", key="edt")
    botao_salvar("Salvar Turmas", "btur")

# ABA 5: PROFESSORES
with t5:
    # --- 1. ESTATÍSTICAS REAIS ---
    if not dt.empty and not dc.empty:
        st.info("📊 **Estatísticas Reais da Rede:**")
        col1, col2, col3 = st.columns(3)
        
        # Calcular demanda real
        demanda_real = 0
        for _, turma in dt.iterrows():
            curr = dc[dc['SÉRIE/ANO'] == turma['SÉRIE/ANO']]
            for _, item in curr.iterrows():
                if padronizar_materia_interna(item['COMPONENTE']) in [padronizar_materia_interna(m) for m in MATERIAS_ESPECIALISTAS]:
                    demanda_real += int(item['QTD_AULAS'])
        
        # Calcular oferta real
        oferta_real = 0
        for _, prof in dp.iterrows():
            oferta_real += int(prof['CARGA_HORÁRIA'])
        
        with col1:
            st.metric("Aulas Demanda", demanda_real)
        with col2:
            st.metric("Aulas Oferta", oferta_real)
        with col3:
            saldo = demanda_real - oferta_real
            st.metric("Saldo", saldo, delta_color="inverse")
        
        if saldo > 0:
            st.warning(f"⚠️ Déficit de {saldo} aulas! Use a ferramenta abaixo para corrigir.")

    # --- 2. FERRAMENTA INTELIGENTE (CORRIGIDA) ---
    st.markdown("---")
    
    # Preparar estado para não sumir o resultado
    if 'resultado_vagas_smart' not in st.session_state:
        st.session_state['resultado_vagas_smart'] = None

    with st.expander("🤖 Ferramenta: Gerar Vagas Automáticas (INTELIGENTE)", expanded=False):
        st.info("🚀 Esta ferramenta agora considera **Dias de Aula**, **Simultaneidade** e **Rotas**, além do volume total.")
        
        # Layout das colunas APENAS para o texto e o botão
        c_rh1, c_btn = st.columns([3,1])
        
        with c_rh1: 
            st.write("**Como funciona:**")
            st.caption("1. Analisa o 'ConfigDias' para ver quantas turmas têm aula ao mesmo tempo.")
            st.caption("2. Define o mínimo de professores para cobrir esse pico.")
            st.caption("3. Cria vagas compartilhadas entre Fundão e Timbuí automaticamente.")
            
        with c_btn:
            st.write(""); st.write("")
            # Capturamos o clique aqui
            processar = st.button("🚀 Calcular e Criar Vagas", use_container_width=True)

        # --- LÓGICA DE PROCESSAMENTO (Fora das colunas para largura total) ---
        if processar:
            if dt.empty or dc.empty or dd.empty:
                st.error("❌ Faltam dados (Turmas, Currículo ou ConfigDias).")
            else:
                with st.spinner("Processando demanda inteligente..."):
                    from inteligencia import gerar_novos_professores_inteligentes
                    novos, analise = gerar_novos_professores_inteligentes(dt, dc, dd, da, dp)
                    
                    if not novos.empty:
                        # 1. Salvar no banco
                        dp = pd.concat([dp, novos], ignore_index=True)
                        salvar_seguro(dt, dc, dp, dd, da)
                        
                        # 2. Salvar no Estado para mostrar após o refresh
                        st.session_state['resultado_vagas_smart'] = novos
                        
                        # 3. Recarregar
                        st.rerun()
                    else:
                        st.session_state['resultado_vagas_smart'] = pd.DataFrame() # Vazio para indicar sucesso sem vagas
                        st.success("✅ O quadro atual já atende toda a demanda!")

        # --- EXIBIÇÃO DO RESULTADO (Persistente) ---
        if st.session_state['resultado_vagas_smart'] is not None:
            res = st.session_state['resultado_vagas_smart']
            if not res.empty:
                st.divider()
                st.success(f"✅ {len(res)} novos contratos foram criados e salvos!")
                
                st.markdown("### 📋 Detalhes dos Novos Contratos:")
                st.dataframe(
                    res[['CÓDIGO', 'NOME', 'CARGA_HORÁRIA', 'REGIÃO', 'QTD_PL']], 
                    use_container_width=True
                )
            
            # Botão para limpar a visualização
            if st.button("🧹 Limpar Resultado da Tela"):
                st.session_state['resultado_vagas_smart'] = None
                st.rerun()

    # --- 3. ADICIONAR PROFESSOR MANUAL ---
    with st.expander("➕ Novo Professor Manual", expanded=False):
        tp = st.radio("Vínculo", ["DT", "EFETIVO"], horizontal=True)
        with st.form("fp"):
            c1,c2 = st.columns([1,3])
            cd = c1.text_input("Cod")
            nm = c2.text_input("Nome")
            c3,c4,c5 = st.columns(3)
            ch = c3.number_input("Aulas", 1, 60, 20)
            pl = c4.number_input("PL", 0, 10, 0)
            rg = c5.selectbox("Região", REGIOES)
            cm = st.multiselect("Matérias", MATERIAS_ESPECIALISTAS)
            if tp == "EFETIVO":
                ef_esc = st.multiselect("Escolas", sorted(dt['ESCOLA'].unique()) if not dt.empty else [])
                ef_trn = st.selectbox("Turno", ["", "MATUTINO", "VESPERTINO", "AMBOS"])
            else: ef_esc, ef_trn = [], ""
            
            if st.form_submit_button("Salvar"):
                str_esc = ",".join(ef_esc) if ef_esc else ""
                dp = pd.concat([dp, pd.DataFrame([{
                    "CÓDIGO": cd, "NOME": padronizar(nm), "CARGA_HORÁRIA": ch, 
                    "QTD_PL": pl, "REGIÃO": rg, "COMPONENTES": ",".join(cm), 
                    "VÍNCULO": tp, "ESCOLAS_ALOCADAS": str_esc, "TURNO_FIXO": ef_trn
                }])], ignore_index=True)
                salvar_seguro(dt, dc, dp, dd, da)

    # --- 4. TABELA GERAL EDITÁVEL ---
    st.markdown("---")
    st.markdown("### 👨‍🏫 Quadro Geral de Professores")
    dp = st.data_editor(dp, num_rows="dynamic", key="edp", use_container_width=True)
    botao_salvar("Salvar Alterações na Tabela", "bprof")

# ABA 6: VAGAS - Gerador de Possibilidades
with t6:
    st.markdown("### 💼 Gerador de Vagas - Planejamento de Equipe")
    st.info("💡 Use esta aba para criar vagas (contratos) antes de gerar o horário. A análise abaixo ajuda a definir quantos professores são necessários.")

    # Aviso sobre quota da API
    if not sistema_seguro:
        st.warning("⚠️ **Atenção:** Sistema rodando sem conexão segura ou com limitações de API.")

    # Botão para limpar cache manual
    col_cache1, col_cache2 = st.columns([1, 4])
    with col_cache1:
        if st.button("🔄 Limpar Cache", help="Recarrega dados do Google Sheets", key="btn_limpar_cache_vagas"):
            st.cache_data.clear()
            st.success("✅ Cache limpo! Recarregando...")
            st.rerun()
    with col_cache2:
        st.caption("💡 O cache é atualizado automaticamente a cada 5 minutos.")

    # Inicializar lista de vagas na sessão
    if 'vagas_criadas' not in st.session_state:
        st.session_state['vagas_criadas'] = []

    # --- FERRAMENTA 1: GERADOR RÁPIDO (Por Volume) ---
    st.markdown("---")
    with st.expander("⚡ Gerador Rápido (Baseado em Volume Total)", expanded=False):
        st.info("🚀 Cria vagas baseando-se apenas no total de aulas, sem considerar dias específicos.")
        col_gen1, col_gen2, col_gen3, col_gen4 = st.columns([1, 1, 1, 1])
        with col_gen1:
            carga_min_auto = st.number_input("Carga Mínima", 5, 20, CARGA_MINIMA_PADRAO, key="gen_min")
        with col_gen2:
            carga_max_auto = st.number_input("Carga Máxima", 20, 50, CARGA_MAXIMA_PADRAO, key="gen_max")
        with col_gen3:
            media_alvo_auto = st.number_input("Média Alvo", 10, 40, MEDIA_ALVO_PADRAO, key="gen_media")
        with col_gen4:
            st.write(""); st.write("")
            if st.button("🚀 Gerar Vagas (Simples)", type="primary", use_container_width=True):
                # ... (Lógica antiga mantida para quem quer geração rápida por volume) ...
                # Se quiser, podemos remover isso depois, mas é útil ter um fallback.
                pass 
                st.warning("Para geração inteligente baseada em horários, use a análise no final da página!")

    # --- FERRAMENTA 2: FORMULÁRIO MANUAL ---
    with st.expander("➕ Criar Nova Vaga Manualmente", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            materia_vaga = st.selectbox("📚 Matéria", MATERIAS_ESPECIALISTAS, key="vag_mat")
            regioes_vaga = st.multiselect(
                "📍 Região(ões) - (Fundão + Timbuí são compatíveis)",
                REGIOES, default=[], key="vag_reg"
            )
            vinculo_vaga = st.radio("🔗 Vínculo", VINCULOS, horizontal=True, key="vag_vin")

        with col2:
            carga_vaga = st.number_input("⏰ Carga Horária (Aulas)", 1, 50, 20, key="vag_carga")
            quantidade_vagas = st.number_input("🔢 Quantidade de Vagas", 1, 50, 1, key="vag_qtd")

        # Lógica de validação e criação manual
        if st.button("➕ Adicionar à Lista", type="primary", use_container_width=True):
            if not regioes_vaga:
                st.error("❌ Selecione pelo menos uma região!")
            else:
                if "PRAIA GRANDE" in regioes_vaga and ("FUNDÃO" in regioes_vaga or "TIMBUÍ" in regioes_vaga):
                    st.error("❌ Praia Grande não combina com Fundão/Timbuí.")
                else:
                    # Cálculo de PL e criação
                    pl_calculado = calcular_pl_ldb(carga_vaga)
                    
                    # Gerar IDs
                    numeros = [int(re.search(r'P(\d+)', str(r['CÓDIGO'])).group(1)) 
                              for _, r in dp.iterrows() if re.search(r'P(\d+)', str(r['CÓDIGO']))]
                    prox_num = max(numeros) + 1 if numeros else 1

                    # Criar vaga compartilhada ou separada
                    if len(regioes_vaga) > 1 and "FUNDÃO" in regioes_vaga and "TIMBUÍ" in regioes_vaga:
                        # Vaga Compartilhada
                        esc_f = list(set(dt[dt['REGIÃO'] == "FUNDÃO"]['ESCOLA'].unique()))
                        esc_t = list(set(dt[dt['REGIÃO'] == "TIMBUÍ"]['ESCOLA'].unique()))
                        escolas_mix = (esc_f[:2] if esc_f else []) + (esc_t[:2] if esc_t else [])
                        
                        for i in range(quantidade_vagas):
                            vaga = {
                                "CÓDIGO": gerar_codigo_padrao(prox_num+i, vinculo_vaga, "FUNDAO", materia_vaga),
                                "NOME": f"VAGA {materia_vaga} FUNDÃO/TIMBUÍ",
                                "COMPONENTES": materia_vaga,
                                "CARGA_HORÁRIA": carga_vaga,
                                "REGIÃO": "FUNDÃO",
                                "VÍNCULO": vinculo_vaga,
                                "TURNO_FIXO": "",
                                "ESCOLAS_ALOCADAS": ",".join(escolas_mix),
                                "QTD_PL": pl_calculado
                            }
                            st.session_state['vagas_criadas'].append(vaga)
                        st.success(f"✅ {quantidade_vagas} vaga(s) compartilhada(s) adicionada(s)!")
                    else:
                        # Vagas Individuais
                        count = 0
                        for reg in regioes_vaga:
                            esc_r = list(set(dt[dt['REGIÃO'] == reg]['ESCOLA'].unique()))
                            for i in range(quantidade_vagas):
                                vaga = {
                                    "CÓDIGO": gerar_codigo_padrao(prox_num+count, vinculo_vaga, reg, materia_vaga),
                                    "NOME": f"VAGA {materia_vaga} {reg}",
                                    "COMPONENTES": materia_vaga,
                                    "CARGA_HORÁRIA": carga_vaga,
                                    "REGIÃO": reg,
                                    "VÍNCULO": vinculo_vaga,
                                    "TURNO_FIXO": "",
                                    "ESCOLAS_ALOCADAS": ",".join(esc_r[:2]),
                                    "QTD_PL": pl_calculado
                                }
                                st.session_state['vagas_criadas'].append(vaga)
                                count += 1
                        st.success(f"✅ {count} vaga(s) adicionada(s)!")
                    st.rerun()

    # --- LISTA E SALVAMENTO ---
    st.markdown("---")
    st.markdown("### 📋 Vagas Preparadas")

    if st.session_state['vagas_criadas']:
        df_vagas = pd.DataFrame(st.session_state['vagas_criadas'])
        
        # Métricas
        m1, m2, m3 = st.columns(3)
        m1.metric("Novas Vagas", len(df_vagas))
        m2.metric("Total Aulas", df_vagas['CARGA_HORÁRIA'].sum())
        m3.metric("Custo (Aulas+PL)", df_vagas['CARGA_HORÁRIA'].sum() + df_vagas['QTD_PL'].sum())

        # Edição
        df_editado = st.data_editor(df_vagas, num_rows="dynamic", use_container_width=True, key="ed_vagas_main")
        st.session_state['vagas_criadas'] = df_editado.to_dict('records')

        # Botões
        b1, b2 = st.columns([1, 4])
        if b1.button("🗑️ Limpar"):
            st.session_state['vagas_criadas'] = []
            st.rerun()
        
        if b2.button("💾 GRAVAR NO BANCO DE DADOS", type="primary", use_container_width=True):
            if sistema_seguro:
                # Validação de duplicação
                cods_exist = set(dp['CÓDIGO'].astype(str))
                cods_new = set(df_editado['CÓDIGO'].astype(str))
                if cods_exist.intersection(cods_new):
                    st.error(f"❌ Códigos duplicados: {cods_exist.intersection(cods_new)}")
                else:
                    dp_new = pd.concat([dp, df_editado], ignore_index=True)
                    salvar_seguro(dt, dc, dp_new, dd, da)
                    st.session_state['vagas_criadas'] = []
                    st.success("✅ Vagas gravadas com sucesso!")
                    time.sleep(1)
                    st.rerun()
            else:
                st.error("Erro de conexão.")

        # Preview agrupado
        st.caption("Resumo por Região:")
        st.dataframe(df_editado.groupby(['REGIÃO', 'COMPONENTES'])['CARGA_HORÁRIA'].sum().reset_index())

    else:
        # --- AQUI ENTRA A NOVA INTELIGÊNCIA ---
        st.info("📝 A lista está vazia. Use a análise abaixo para saber o que criar.")

        st.markdown("---")
        st.markdown("### 🧠 Sugestão Inteligente (Considera Dias e Turnos)")
        st.caption("Analisa o 'ConfigDias' para detectar se todas as aulas caem no mesmo dia (pico de simultaneidade).")

        # Botão para chamar a inteligência
        if st.button("🔎 Analisar Demanda com Inteligência", type="primary"):
            if dt.empty or dc.empty:
                st.error("⚠️ Necessário carregar Turmas e Currículo!")
            else:
                with st.spinner("Cruzando horários, rotas e regiões..."):
                    # IMPORTANTE: Chama a função do seu arquivo inteligencia.py
                    from inteligencia import analisar_demanda_inteligente
                    df_sugestao = analisar_demanda_inteligente(dt, dc, dd, da)
                    
                if not df_sugestao.empty:
                    st.success("✅ Análise concluída! Veja abaixo as sugestões baseadas na logística real.")
                    st.markdown("""
                    > **O que é o Pico Simultâneo?** > Se você tem 10 turmas com aula na *Segunda-Feira de manhã*, você precisa de **10 professores** naquele momento, mesmo que eles não tenham mais aulas na semana. O sistema detectou esses gargalos.
                    """)
                    
                    # Separar Fundão/Timbuí para análise especial
                    df_ft = df_sugestao[df_sugestao['Região'].isin(['FUNDÃO', 'TIMBUÍ'])].copy()
                    df_outros = df_sugestao[~df_sugestao['Região'].isin(['FUNDÃO', 'TIMBUÍ'])].copy()
                    
                    # Exibir Fundão e Timbuí
                    if not df_ft.empty:
                        st.subheader("📍 Análise Integrada: Fundão & Timbuí")
                        for mat in df_ft['Matéria'].unique():
                            dados = df_ft[df_ft['Matéria'] == mat]
                            total_vol = dados['Volume Total'].sum()
                            # Somamos os picos pois podem cair no mesmo dia
                            max_simul = dados['Pico Simultâneo'].sum() 
                            
                            with st.container():
                                st.markdown(f"**📚 {mat}**")
                                c1, c2, c3 = st.columns(3)
                                c1.metric("Volume Total", f"{total_vol} aulas")
                                c2.metric("Pico Simultâneo", f"{max_simul} profs", help="Mínimo de professores rodando ao mesmo tempo no pior horário.")
                                
                                # Recalcula sugestão unificada
                                num_vagas = max(max_simul, math.ceil(total_vol / MEDIA_ALVO_PADRAO))
                                cargas = distribuir_carga_inteligente(total_vol, num_vagas)
                                
                                c3.info(f"Sugestão: **{num_vagas} vaga(s)**")
                                st.write(f"Distribuição recomendada: `{cargas}`")
                                st.divider()

                    # Exibir Outras Regiões
                    if not df_outros.empty:
                        st.subheader("📍 Outras Regiões")
                        st.dataframe(
                            df_outros[['Região', 'Matéria', 'Volume Total', 'Pico Simultâneo', 'Vagas Sugeridas', 'Distribuição']], 
                            use_container_width=True,
                            hide_index=True
                        )
                else:
                    st.warning("Nenhuma demanda de especialistas encontrada para analisar.")

# ABA 7: GERADOR 
with t7:
    if sistema_seguro:
        st.subheader("🔍 Depuração da Demanda")
        
        total_aulas_especialistas = 0
        detalhes_demanda = []
        
        for _, turma in dt.iterrows():
            curr = dc[dc['SÉRIE/ANO'] == turma['SÉRIE/ANO']]
            for _, item in curr.iterrows():
                mat = padronizar_materia_interna(item['COMPONENTE'])
                if mat in [padronizar_materia_interna(m) for m in MATERIAS_ESPECIALISTAS]:
                    qtd = int(item['QTD_AULAS'])
                    total_aulas_especialistas += qtd
                    detalhes_demanda.append({
                        'Escola': turma['ESCOLA'],
                        'Turma': turma['TURMA'],
                        'Matéria': mat,
                        'Aulas': qtd,
                        'Série': turma['SÉRIE/ANO']
                    })
        
        st.write(f"**Total de aulas de especialistas (semanal):** {total_aulas_especialistas}")
        st.write(f"**Total de professores existentes:** {len(dp)}")
        
        if st.checkbox("Mostrar detalhes da demanda"):
            st.dataframe(pd.DataFrame(detalhes_demanda))
        
        st.markdown("---")
        
        if st.button("🚀 Gerar e Salvar Grade (COM CONTROLE)"):
            with st.status("Processando Rede...", expanded=True) as status:
                # Verificar se há dados suficientes
                if dt.empty:
                    st.error("❌ Não há turmas cadastradas!")
                    st.stop()
                if dc.empty:
                    st.error("❌ Não há currículo configurado!")
                    st.stop()
                if dp.empty:
                    st.warning("⚠️ Não há professores cadastrados! O sistema criará professores automaticamente.")
                
                profs_obj = carregar_objs(dp)
                rotas_obj = carregar_rotas(da)
                map_esc_reg = dict(zip(dt['ESCOLA'], dt['REGIÃO']))
                
                status.write(f"📊 Dados carregados:")
                status.write(f"  • {len(dt)} turmas")
                status.write(f"  • {len(profs_obj)} professores")
                status.write(f"  • {len(rotas_obj)} rotas configuradas")
                
                merged = pd.merge(dt, dd, on="SÉRIE/ANO", how="left").fillna({'DIA_PLANEJAMENTO': 'NÃO CONFIGURADO'})
                escolas = merged['ESCOLA'].unique()
                
                # Resetar estado INICIAL dos professores
                for p in profs_obj:
                    p['ocup'] = {}
                    p['atrib'] = 0
                    p['escolas_reais'] = set()
                    p['regs_alocadas_historico'] = set()
                
                status.write(f"🏫 Processando {len(escolas)} escolas...")
                novos_horarios = []
                escolas_processadas = 0
                
                for esc in escolas:
                    status.write(f"  • Processando escola: {esc}")
                    df_e = merged[merged['ESCOLA'] == esc]
                    
                    # Processar TODAS as combinações de dia/turno, mesmo sem DIA_PLANEJAMENTO configurado
                    combinacoes = df_e[['DIA_PLANEJAMENTO', 'TURNO']].drop_duplicates()
                    
                    # Se não houver DIA_PLANEJAMENTO configurado, processar por turno apenas
                    if combinacoes.empty or combinacoes['DIA_PLANEJAMENTO'].isna().all():
                        turnos = df_e['TURNO'].unique()
                        for turno in turnos:
                            turmas_f = df_e[df_e['TURNO'] == turno]
                            dia = 'NÃO CONFIGURADO'
                            
                            lt = [{
                                'nome_turma': r['TURMA'], 
                                'ano': r['SÉRIE/ANO'], 
                                'escola_real': esc, 
                                'regiao_real': r['REGIÃO']
                            } for _, r in turmas_f.iterrows()]
                            
                            if not lt:  # Pular se não houver turmas
                                continue
                            
                            # Resetar ocup antes de cada dia/turno (cada dia/turno é independente)
                            for p in profs_obj:
                                p['ocup'] = {}
                            
                            # Resolve a grade (NÃO cria professores - apenas marca "---" se não encontrar)
                            sucesso, res, mensagem, profs_obj = resolver_grade_inteligente(
                                lt, dc, profs_obj, rotas_obj, turno, map_esc_reg
                            )
                            
                            # Contar quantas aulas foram alocadas corretamente
                            total_alocadas = sum(sum(1 for a in aulas if a and a != "---" and a is not None) for aulas in res.values()) if res else 0
                            
                            # Contar aulas esperadas baseado no currículo
                            total_esperadas = 0
                            for turma in lt:
                                curr_turma = dc[dc['SÉRIE/ANO'] == turma['ano']]
                                for _, item_curr in curr_turma.iterrows():
                                    mat_curr = padronizar_materia_interna(item_curr['COMPONENTE'])
                                    if mat_curr in [padronizar_materia_interna(m) for m in MATERIAS_ESPECIALISTAS]:
                                        total_esperadas += int(item_curr['QTD_AULAS'])
                            
                            status.write(f"    • {dia} - {turno}: {mensagem} ({len(lt)} turmas, {total_alocadas}/{total_esperadas} aulas alocadas)")
                            
                            # Diagnóstico detalhado se não alocou nada
                            if total_alocadas == 0 and total_esperadas > 0:
                                status.write(f"      ⚠️ NENHUMA aula alocada! Verificando professores disponíveis...")
                                materias_necessarias = set()
                                for turma in lt:
                                    curr_turma = dc[dc['SÉRIE/ANO'] == turma['ano']]
                                    for _, item_curr in curr_turma.iterrows():
                                        mat_curr = padronizar_materia_interna(item_curr['COMPONENTE'])
                                        if mat_curr in [padronizar_materia_interna(m) for m in MATERIAS_ESPECIALISTAS]:
                                            materias_necessarias.add(mat_curr)
                                
                                for mat_nec in materias_necessarias:
                                    reg_nec = padronizar(lt[0]['regiao_real']) if lt else ""
                                    profs_disponiveis = sum(1 for p in profs_obj if mat_nec in p['mats'] and 
                                                           p['atrib'] < min(p['max'], REGRA_CARGA_HORARIA["maximo_aulas"]))
                                    pode_regiao = sum(1 for p in profs_obj if mat_nec in p['mats'] and 
                                                     verificar_compatibilidade_regiao(p['reg'], reg_nec, mat_nec)[0])
                                    status.write(f"        • {mat_nec}: {profs_disponiveis} profs disponíveis, {pode_regiao} compatíveis com região {reg_nec}")
                            
                            for t_nome, aulas in res.items():
                                novos_horarios.append([esc, t_nome, turno, dia] + aulas)
                    else:
                        # Processar normalmente com DIA_PLANEJAMENTO configurado
                        for _, b in combinacoes.iterrows():
                            dia, turno = b['DIA_PLANEJAMENTO'], b['TURNO']
                            turmas_f = df_e[(df_e['DIA_PLANEJAMENTO']==dia) & (df_e['TURNO']==turno)]
                            
                            lt = [{
                                'nome_turma': r['TURMA'], 
                                'ano': r['SÉRIE/ANO'], 
                                'escola_real': esc, 
                                'regiao_real': r['REGIÃO']
                            } for _, r in turmas_f.iterrows()]
                            
                            if not lt:  # Pular se não houver turmas
                                continue
                            
                            # Resetar ocup antes de cada dia/turno (cada dia/turno é independente)
                            for p in profs_obj:
                                p['ocup'] = {}
                            
                            # Resolve a grade (NÃO cria professores - apenas marca "---" se não encontrar)
                            sucesso, res, mensagem, profs_obj = resolver_grade_inteligente(
                                lt, dc, profs_obj, rotas_obj, turno, map_esc_reg
                            )
                            
                            # Contar quantas aulas foram alocadas corretamente
                            total_alocadas = sum(sum(1 for a in aulas if a and a != "---" and a is not None) for aulas in res.values()) if res else 0
                            
                            # Contar aulas esperadas baseado no currículo
                            total_esperadas = 0
                            for turma in lt:
                                curr_turma = dc[dc['SÉRIE/ANO'] == turma['ano']]
                                for _, item_curr in curr_turma.iterrows():
                                    mat_curr = padronizar_materia_interna(item_curr['COMPONENTE'])
                                    if mat_curr in [padronizar_materia_interna(m) for m in MATERIAS_ESPECIALISTAS]:
                                        total_esperadas += int(item_curr['QTD_AULAS'])
                            
                            status.write(f"    • {dia} - {turno}: {mensagem} ({len(lt)} turmas, {total_alocadas}/{total_esperadas} aulas alocadas)")
                            
                            # Diagnóstico detalhado se não alocou nada
                            if total_alocadas == 0 and total_esperadas > 0:
                                status.write(f"      ⚠️ NENHUMA aula alocada! Verificando professores disponíveis...")
                                materias_necessarias = set()
                                for turma in lt:
                                    curr_turma = dc[dc['SÉRIE/ANO'] == turma['ano']]
                                    for _, item_curr in curr_turma.iterrows():
                                        mat_curr = padronizar_materia_interna(item_curr['COMPONENTE'])
                                        if mat_curr in [padronizar_materia_interna(m) for m in MATERIAS_ESPECIALISTAS]:
                                            materias_necessarias.add(mat_curr)
                                
                                for mat_nec in materias_necessarias:
                                    reg_nec = padronizar(lt[0]['regiao_real']) if lt else ""
                                    profs_disponiveis = sum(1 for p in profs_obj if mat_nec in p['mats'] and 
                                                           p['atrib'] < min(p['max'], REGRA_CARGA_HORARIA["maximo_aulas"]))
                                    pode_regiao = sum(1 for p in profs_obj if mat_nec in p['mats'] and 
                                                     verificar_compatibilidade_regiao(p['reg'], reg_nec, mat_nec)[0])
                                    status.write(f"        • {mat_nec}: {profs_disponiveis} profs disponíveis, {pode_regiao} compatíveis com região {reg_nec}")
                            
                            for t_nome, aulas in res.items():
                                novos_horarios.append([esc, t_nome, turno, dia] + aulas)
                    
                    escolas_processadas += 1
                
                # NÃO converter professores criados durante alocação
                # Tudo será consolidado na FASE 2 abaixo
                
                # Atualizar cargas horárias dos professores existentes baseado nas alocações
                status.write("📊 Atualizando cargas horárias e PL dos professores...")
                for p_obj in profs_obj:
                    # Encontrar professor no DataFrame
                    idx = dp[dp['CÓDIGO'] == p_obj['id']].index
                    if len(idx) > 0:
                        # Atualizar carga horária com base nas atribuições reais
                        carga_atual = p_obj['atrib']
                        if carga_atual > 0:
                            dp.loc[idx[0], 'CARGA_HORÁRIA'] = max(carga_atual, dp.loc[idx[0], 'CARGA_HORÁRIA'])
                            
                            # REGRA 5: Atualizar PL baseado na LDB
                            pl_ldb = calcular_pl_ldb(dp.loc[idx[0], 'CARGA_HORÁRIA'])
                            dp.loc[idx[0], 'QTD_PL'] = pl_ldb
                            
                            # Atualizar escolas alocadas
                            escolas_reais = ','.join(p_obj['escolas_reais']) if p_obj['escolas_reais'] else dp.loc[idx[0], 'ESCOLAS_ALOCADAS']
                            if escolas_reais:
                                dp.loc[idx[0], 'ESCOLAS_ALOCADAS'] = escolas_reais
                
                # ===== FASE 2: CONSOLIDAR VAGAS NÃO PREENCHIDAS =====
                status.write("📊 Analisando demanda não atendida e consolidando...")
                
                # Contar demanda não preenchida por região/matéria
                # Método melhorado: contar slots "---" e identificar matéria pela posição no currículo
                demanda_nao_preenchida = {}
                
                # Criar DataFrame de horários para análise
                df_horarios_temp = pd.DataFrame(novos_horarios, columns=COLS_PADRAO["Horario"])
                
                # Agrupar por escola/turma para processar uma vez cada
                turmas_processadas = set()
                
                for _, row in df_horarios_temp.iterrows():
                    esc = row['ESCOLA']
                    turma_nome = row['TURMA']
                    chave_turma = (esc, turma_nome)
                    
                    if chave_turma in turmas_processadas:
                        continue
                    turmas_processadas.add(chave_turma)
                    
                    # Encontrar informações da turma
                    df_turma = dt[(dt['ESCOLA'] == esc) & (dt['TURMA'] == turma_nome)]
                    if df_turma.empty:
                        continue
                    
                    serie = df_turma.iloc[0]['SÉRIE/ANO']
                    regiao = padronizar(df_turma.iloc[0]['REGIÃO'])
                    
                    # Buscar currículo da série e criar lista de aulas esperadas
                    curr = dc[dc['SÉRIE/ANO'] == serie]
                    aulas_esperadas = []
                    for _, item in curr.iterrows():
                        mat = padronizar_materia_interna(item['COMPONENTE'])
                        if mat in [padronizar_materia_interna(m) for m in MATERIAS_ESPECIALISTAS]:
                            qtd = int(item['QTD_AULAS'])
                            aulas_esperadas.extend([mat] * qtd)
                    
                    # Buscar todas as linhas dessa turma no horário
                    linhas_turma = df_horarios_temp[(df_horarios_temp['ESCOLA'] == esc) & 
                                                    (df_horarios_temp['TURMA'] == turma_nome)]
                    
                    # Contar quantas aulas de cada matéria foram alocadas
                    materias_alocadas = {}
                    for _, linha in linhas_turma.iterrows():
                        for col in ['1ª', '2ª', '3ª', '4ª', '5ª']:
                            prof_id = linha[col]
                            if prof_id != '---' and prof_id:
                                # Encontrar matéria do professor
                                prof_df = dp[dp['CÓDIGO'] == prof_id]
                                if not prof_df.empty:
                                    comps = str(prof_df.iloc[0]['COMPONENTES'])
                                    mats_prof = [padronizar_materia_interna(m.strip()) for m in comps.split(',') if m.strip()]
                                    for mat_prof in mats_prof:
                                        if mat_prof in [padronizar_materia_interna(m) for m in MATERIAS_ESPECIALISTAS]:
                                            materias_alocadas[mat_prof] = materias_alocadas.get(mat_prof, 0) + 1
                    
                    # Contar quantas aulas de cada matéria faltam
                    materias_esperadas_dict = {}
                    for mat in aulas_esperadas:
                        materias_esperadas_dict[mat] = materias_esperadas_dict.get(mat, 0) + 1
                    
                    # Calcular déficit
                    for mat, qtd_esperada in materias_esperadas_dict.items():
                        qtd_alocada = materias_alocadas.get(mat, 0)
                        deficit = qtd_esperada - qtd_alocada
                        if deficit > 0:
                            chave = (regiao, mat)
                            demanda_nao_preenchida[chave] = demanda_nao_preenchida.get(chave, 0) + deficit
                
                total_aulas_faltando = sum(demanda_nao_preenchida.values())
                status.write(f"📊 Total de aulas não preenchidas: {total_aulas_faltando} em {len(demanda_nao_preenchida)} combinações região/matéria")
                
                # Mostrar detalhes
                if demanda_nao_preenchida:
                    status.write("📋 Detalhes por região/matéria:")
                    for (reg, mat), qtd in sorted(demanda_nao_preenchida.items()):
                        status.write(f"  • {mat} - {reg}: {qtd} aulas faltando")
                
                # ===== CRIAR NOVOS PROFESSORES CONSOLIDADOS =====
                if demanda_nao_preenchida:
                    status.write("🔄 Criando novos professores consolidados para vagas não preenchidas...")
                    
                    novos_profs = []
                    numeros_existentes = []
                    
                    # Coletar números existentes de todos os professores (incluindo os criados durante alocação)
                    for _, p_row in dp.iterrows():
                        match = re.search(r'P(\d+)', str(p_row['CÓDIGO']))
                        if match:
                            numeros_existentes.append(int(match.group(1)))
                    
                    proximo_numero = max(numeros_existentes) + 1 if numeros_existentes else 1
                    
                    for (reg, mat), qtd_aulas in sorted(demanda_nao_preenchida.items()):
                        if qtd_aulas <= 0:
                            continue
                        
                        # REGRA 7: Distribuir carga de forma inteligente
                        cargas = distribuir_carga_inteligente(qtd_aulas)
                        
                        # Validar cada carga
                        cargas_validas = []
                        for carga in cargas:
                            valido, msg = verificar_limites_carga(carga, qtd_aulas)
                            if valido:
                                cargas_validas.append(carga)
                            else:
                                # Ajustar para o mínimo se necessário
                                if REGRA_CARGA_HORARIA["permitir_menor_se_necessario"]:
                                    carga_ajustada = max(1, min(carga, qtd_aulas))
                                    cargas_validas.append(carga_ajustada)
                        
                        # Se não gerou cargas válidas, usar distribuição simples respeitando limites
                        if not cargas_validas:
                            carga_max = REGRA_CARGA_HORARIA["maximo_aulas"]
                            carga_min = REGRA_CARGA_HORARIA["minimo_aulas"]
                            if qtd_aulas <= carga_max:
                                cargas_validas = [qtd_aulas]
                            else:
                                # Dividir respeitando limites
                                num_profs = math.ceil(qtd_aulas / carga_max)
                                carga_por_prof = qtd_aulas / num_profs
                                cargas_validas = []
                                restante = qtd_aulas
                                for i in range(num_profs):
                                    if i == num_profs - 1:
                                        carga = restante
                                    else:
                                        carga = min(carga_max, max(carga_min, round(carga_por_prof)))
                                        restante -= carga
                                    cargas_validas.append(max(1, carga))
                        
                        cargas = cargas_validas
                        
                        # Criar os professores
                        escolas_regiao = list(set(dt[dt['REGIÃO'] == reg]['ESCOLA'].unique()))
                        
                        for i, carga in enumerate(cargas):
                            if carga > 0:
                                cod = gerar_codigo_padrao(proximo_numero, "DT", reg, mat)
                                proximo_numero += 1
                                
                                # REGRA 5: Calcular PL baseado na LDB (1/3)
                                pl_ldb = calcular_pl_ldb(carga)
                                
                                novos_profs.append({
                                    "CÓDIGO": cod,
                                    "NOME": f"VAGA {mat} {reg}",
                                    "COMPONENTES": mat,
                                    "CARGA_HORÁRIA": carga,
                                    "REGIÃO": reg,
                                    "VÍNCULO": "DT",
                                    "TURNO_FIXO": "",
                                    "ESCOLAS_ALOCADAS": ",".join(escolas_regiao[:2]),
                                    "QTD_PL": pl_ldb  # PL calculado pela LDB
                                })
                                
                                status.write(f"  ✅ {cod}: {carga}h ({mat} - {reg})")
                    
                    # Adicionar novos professores ao dataframe
                    if novos_profs:
                        dp_com_novos = pd.concat([dp, pd.DataFrame(novos_profs)], ignore_index=True)
                        status.write(f"✅ {len(novos_profs)} novos professores consolidados criados")
                    else:
                        dp_com_novos = dp
                else:
                    dp_com_novos = dp
                    status.write("✅ Todas as vagas foram preenchidas!")
                
                df_horario = pd.DataFrame(novos_horarios, columns=COLS_PADRAO["Horario"])
                
                status.write("💾 Salvando no banco de dados...")
                salvar_seguro(dt, dc, dp_com_novos, dd, da, df_horario)
                
                status.update(label="✅ Grade Gerada com Sucesso!", state="complete", expanded=False)
                st.success(f"Processamento concluído! {escolas_processadas} escolas processadas.")
    else:
        st.warning("⚠️ Configure a conexão com Google Sheets primeiro.")

# ==========================================
# ABA 8: VER HORÁRIO (COMPLETO: CARDS + FILTRO DIA + NOVAS OPÇÕES)
# ==========================================
with t8:
    if dh.empty: 
        st.info("✨ Nenhum horário gerado ainda. Vá na aba '🚀 Gerador' para criar a primeira grade da rede.")
    else:
        st.markdown("### 📅 Visualização da Grade")
        
        # --- 1. CONFIGURAÇÃO DE VISUALIZAÇÃO ---
        with st.container():
            map_nome = dict(zip(dp['CÓDIGO'], dp['NOME']))
            map_comp = dict(zip(dp['CÓDIGO'], dp['COMPONENTES']))
            
            opcoes_vis = [
                "Apenas Código", "Nome do Professor", "Matéria/Componente", 
                "Nome + Matéria", "Código + Nome", "Código + Componente"
            ]
            modo_vis = st.radio("Exibir:", opcoes_vis, horizontal=True)
            
            def formatar_celula(codigo):
                if not codigo or codigo == "---": return "---"
                nome = map_nome.get(codigo, codigo)
                mat = map_comp.get(codigo, "?")
                if modo_vis == "Apenas Código": return codigo
                if modo_vis == "Nome do Professor": return nome.split()[0] + " " + nome.split()[-1] if len(nome.split()) > 1 else nome
                if modo_vis == "Matéria/Componente": return mat
                if modo_vis == "Nome + Matéria": return f"{nome} ({mat})"
                if modo_vis == "Código + Nome": return f"{codigo} - {nome}"
                if modo_vis == "Código + Componente": return f"{codigo} ({mat})"
                return codigo

        st.divider()

        # --- 2. FILTROS ---
        c1, c2 = st.columns(2)
        with c1:
            esc_sel = st.selectbox("🏢 Escola", sorted(dh['ESCOLA'].unique()), key="view_esc_card")
        with c2:
            dia_sel = st.selectbox("📆 Dia", ["Todos os Dias"] + sorted(dh['DIA'].unique().tolist()), key="view_dia_card")

        # --- 3. EXIBIÇÃO EM CARTÕES ---
        df_view = dh[dh['ESCOLA'] == esc_sel].copy()
        if dia_sel != "Todos os Dias": df_view = df_view[df_view['DIA'] == dia_sel]

        if df_view.empty:
            st.warning("Nenhum horário encontrado.")
        else:
            dias_para_mostrar = [dia_sel] if dia_sel != "Todos os Dias" else DIAS_SEMANA
            
            for dia in dias_para_mostrar:
                df_dia = df_view[df_view['DIA'] == dia]
                if df_dia.empty: continue
                
                # FILTRO DE NORMALIZAÇÃO (Corrige Terça-Feira)
                dia_norm = padronizar(dia)
                turmas_no_dia = df_dia['TURMA'].unique()
                turmas_validas_dia = []
                
                for t in turmas_no_dia:
                    dados_t = dt[dt['TURMA'] == t]
                    if not dados_t.empty:
                        serie = dados_t.iloc[0]['SÉRIE/ANO']
                        config = dd[dd['SÉRIE/ANO'] == serie]
                        if not config.empty:
                            if dia_norm in [padronizar(d) for d in config['DIA_PLANEJAMENTO'].unique()]:
                                turmas_validas_dia.append(t)
                        else:
                            turmas_validas_dia.append(t)
                    else:
                        turmas_validas_dia.append(t)
                
                if not turmas_validas_dia: continue
                
                st.markdown(f"#### 📅 {dia}")
                for turno in sorted(df_dia['TURNO'].unique()):
                    df_turno = df_dia[df_dia['TURNO'] == turno]
                    turmas_finais = [t for t in sorted(df_turno['TURMA'].unique()) if t in turmas_validas_dia]
                    if not turmas_finais: continue

                    st.caption(f"☀️ {turno}")
                    cols = st.columns(3)
                    
                    for i, turma in enumerate(turmas_finais):
                        linha_turma = df_turno[df_turno['TURMA'] == turma].iloc[0]
                        with cols[i % 3]:
                            html_card = f'<div class="turma-card-moldura"><div class="turma-titulo">👥 {linha_turma["TURMA"]}</div>'
                            for slot in ["1ª", "2ª", "3ª", "4ª", "5ª"]:
                                prof_id = linha_turma.get(slot, "---")
                                estilo = gerar_estilo_professor_dinamico(prof_id)
                                html_card += f'''
                                <div class="slot-aula-container" style="background-color: {estilo['bg']}; color: {estilo['text']}; border: 1px solid {estilo['border']};">
                                    <div class="slot-label" style="color: {estilo['text']}; opacity: 0.7;">{slot}</div>
                                    <div style="flex-grow: 1; text-align: center; font-weight: 800; font-size: 0.9em;">{formatar_celula(prof_id)}</div>
                                </div>'''
                                if slot == "3ª":
                                    html_card += '<div style="text-align:center; font-size:9px; font-weight:bold; color:#999; margin:2px 0;">— RECREIO —</div>'
                            html_card += "</div>"
                            st.markdown(html_card, unsafe_allow_html=True)
            st.divider()
             
# ==========================================
# ABA 9: EDITOR MANUAL
# ==========================================
with t9:
    st.markdown("### ✏️ Montagem Manual (Visual)")
    if dt.empty:
        st.warning("⚠️ Cadastre turmas primeiro.")
    else:
        c1, c2, c3 = st.columns(3)
        with c1: esc_man = st.selectbox("🏢 Escola", sorted(dt['ESCOLA'].unique()), key="m_esc")
        with c2: dia_man = st.selectbox("📅 Dia", DIAS_SEMANA, key="m_dia")
        with c3:
            turnos_disp = dt[dt['ESCOLA'] == esc_man]['TURNO'].unique()
            turno_man = st.selectbox("☀️ Turno", sorted(turnos_disp), key="m_trn") if len(turnos_disp) > 0 else None

        if turno_man:
            dia_norm_man = padronizar(dia_man)
            # Filtro robusto de turmas por dia/config
            turmas_alvo = []
            df_base_t = dt[(dt['ESCOLA'] == esc_man) & (dt['TURNO'] == turno_man)]
            for _, r_t in df_base_t.iterrows():
                config = dd[dd['SÉRIE/ANO'] == r_t['SÉRIE/ANO']]
                if not config.empty:
                    if dia_norm_man in [padronizar(d) for d in config['DIA_PLANEJAMENTO'].unique()]:
                        turmas_alvo.append(r_t['TURMA'])
                else: turmas_alvo.append(r_t['TURMA'])
            
            turmas_alvo = sorted(list(set(turmas_alvo)))

            if not turmas_alvo:
                st.info(f"🚫 Nenhuma turma para {dia_man}.")
            else:
                horario_atual = {}
                if not dh.empty:
                    mask = (dh['ESCOLA'] == esc_man) & (dh['DIA'].apply(padronizar) == dia_norm_man) & (dh['TURNO'] == turno_man)
                    for _, row in dh[mask].iterrows():
                        horario_atual[row['TURMA']] = {s: row[s] for s in ["1ª", "2ª", "3ª", "4ª", "5ª"]}

                lista_profs = ["---"] + sorted(dp['CÓDIGO'].unique().tolist())
                escolhas_t9 = {}
                grid = st.columns(3)
                
                for idx, turma in enumerate(turmas_alvo):
                    with grid[idx % 3]:
                        st.markdown(f'<div class="turma-card-moldura" style="background:#f9f9f9;"><div class="turma-titulo">👥 {turma}</div>', unsafe_allow_html=True)
                        for slot in ["1ª", "2ª", "3ª", "4ª", "5ª"]:
                            val_ini = horario_atual.get(turma, {}).get(slot, "---")
                            if val_ini not in lista_profs: val_ini = "---"
                            
                            res_prof = st.selectbox(f"{slot} ({turma})", lista_profs, 
                                                   index=lista_profs.index(val_ini),
                                                   key=f"ed_{turma}_{slot}", label_visibility="collapsed")
                            
                            # Indicador visual de cor no editor
                            est = gerar_estilo_professor_dinamico(res_prof)
                            if res_prof != "---":
                                st.markdown(f'<div style="background:{est["bg"]}; color:{est["text"]}; border-radius:4px; font-size:10px; font-weight:800; text-align:center; margin-top:-10px; margin-bottom:5px; border:1px solid rgba(0,0,0,0.1);">{res_prof}</div>', unsafe_allow_html=True)
                            
                            escolhas_t9[(turma, slot)] = res_prof
                        st.markdown('</div>', unsafe_allow_html=True)

                st.divider()
                if st.button("💾 Salvar Alterações Manuais", type="primary", use_container_width=True):
                    # RECONSTRUÇÃO DA LÓGICA DE SALVAMENTO
                    novas_linhas = []
                    for t in turmas_alvo:
                        linha = {"ESCOLA": esc_man, "TURMA": t, "TURNO": turno_man, "DIA": dia_man}
                        for s in ["1ª", "2ª", "3ª", "4ª", "5ª"]:
                            linha[s] = escolhas_t9[(t, s)]
                        novas_linhas.append(linha)
                    
                    if not dh.empty:
                        # Remove apenas as turmas/dia/escola que foram editadas
                        mask_rem = (dh['ESCOLA'] == esc_man) & (dh['DIA'].apply(padronizar) == dia_norm_man) & (dh['TURNO'] == turno_man)
                        dh = dh[~mask_rem]
                    
                    dh = pd.concat([dh, pd.DataFrame(novas_linhas)], ignore_index=True)
                    salvar_seguro(dt, dc, dp, dd, da, dh)
                    st.success("✅ Grade salva com sucesso!")
                    time.sleep(1)
                    st.rerun()