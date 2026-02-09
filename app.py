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

# --- IMPORTS PARA PDF ---
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
# AQUI ESTAVA FALTANDO O PageBreak
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether, PageBreak, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.lib.units import mm
import io


# ==========================================
# 1 FUNÇÃO GERADORA DE PDF 
# ==========================================
def gerar_pdf_escola(df_horario, nome_escola, dia_filtro="Todos", config_visual=None):
    """
    Gera PDF respeitando o modo de visualização (Nome, Matéria, etc).
    config_visual: dict com keys {'modo': str, 'map_nome': dict, 'map_comp': dict}
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), 
                            rightMargin=10*mm, leftMargin=10*mm, 
                            topMargin=10*mm, bottomMargin=10*mm)
    
    elements = []
    styles = getSampleStyleSheet()
    
    # Estilos
    estilo_titulo = ParagraphStyle('Titulo', parent=styles['Heading1'], alignment=1, fontSize=16, spaceAfter=10)
    estilo_card_titulo = ParagraphStyle('CardTitle', parent=styles['Normal'], fontSize=10, fontName='Helvetica-Bold', textColor=colors.black)
    estilo_aula = ParagraphStyle('Aula', parent=styles['Normal'], fontSize=8, alignment=1, textColor=colors.black, fontName='Helvetica-Bold', leading=9) # Leading ajustado para quebras de linha
    estilo_recreio = ParagraphStyle('Recreio', parent=styles['Normal'], fontSize=6, alignment=1, textColor=colors.gray)

    # --- HELPER DE FORMATAÇÃO (REPLICA A LÓGICA DA UI) ---
    def formatar_para_pdf(codigo):
        if not config_visual: return codigo
        if not codigo or codigo == "---": return "-"
        
        modo = config_visual.get('modo', 'Apenas Código')
        map_nome = config_visual.get('map_nome', {})
        map_comp = config_visual.get('map_comp', {})
        
        nome = map_nome.get(codigo, codigo)
        # Tenta pegar primeiro nome e último para economizar espaço
        if len(nome.split()) > 1:
            nome_curto = nome.split()[0] + " " + nome.split()[-1]
        else:
            nome_curto = nome
            
        mat = map_comp.get(codigo, "?")
        
        # Lógica de Exibição (Igual ao formatar_celula da Aba 8)
        if modo == "Apenas Código": return codigo
        if modo == "Nome do Professor": return nome_curto
        if modo == "Matéria/Componente": return mat
        if modo == "Nome + Matéria": return f"{nome_curto}<br/>({mat})" # <br/> quebra linha no PDF
        if modo == "Código + Nome": return f"{codigo}<br/>{nome_curto}"
        if modo == "Código + Componente": return f"{codigo}<br/>{mat}"
        return codigo

    # Cabeçalho
    titulo_texto = f"Horário Escolar - {nome_escola}"
    if dia_filtro not in ["Todos", "Todos os Dias"]:
        titulo_texto += f" ({dia_filtro})"

    # Adicionar imagem do brasão
    try:
        img_path = "img/EMAIL BRASÃO FUNDÃO_QUADRADA.png"
        img = Image(img_path, width=50*mm, height=50*mm)
        img.hAlign = 'CENTER'
        elements.append(img)
        elements.append(Spacer(1, 5*mm))
    except:
        # Se não conseguir carregar a imagem, continua sem ela
        pass

    elements.append(Paragraph(titulo_texto, estilo_titulo))
    elements.append(Spacer(1, 5*mm))

    if df_horario.empty:
        elements.append(Paragraph("Sem dados para gerar.", styles['Normal']))
        doc.build(elements)
        buffer.seek(0)
        return buffer

    # Lista de dias
    if dia_filtro in ["Todos", "Todos os Dias"]:
        dias_para_imprimir = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira"]
    else:
        dias_para_imprimir = [dia_filtro]

    dias_impressos = 0

    for dia_nome in dias_para_imprimir:
        df_dia = df_horario[df_horario['DIA'].apply(padronizar) == padronizar(dia_nome)]
        
        if df_dia.empty: continue 
        dias_impressos += 1

        elements.append(Paragraph(f"📅 {dia_nome}", styles['Heading2']))
        elements.append(Spacer(1, 2*mm))

        turnos = sorted(df_dia['TURNO'].unique())
        
        for turno in turnos:
            elements.append(Paragraph(f"☀️ Turno: {turno}", styles['Heading3']))
            elements.append(Spacer(1, 2*mm))

            df_turno = df_dia[df_dia['TURNO'] == turno]
            turmas_lista = sorted(df_turno['TURMA'].unique())

            # GRID DE CARTÕES
            row_cards = []
            
            for turma in turmas_lista:
                row_dados = df_turno[df_turno['TURMA'] == turma].iloc[0]
                
                card_data = []
                card_styles = []
                
                # Header Turma
                card_data.append([Paragraph(f"👥 {turma}", estilo_card_titulo), ""]) 
                card_styles.append(('SPAN', (0,0), (1,0)))
                card_styles.append(('BACKGROUND', (0,0), (1,0), colors.whitesmoke))
                card_styles.append(('BOTTOMPADDING', (0,0), (1,0), 6))
                
                # Aulas
                for i, slot in enumerate(["1ª", "2ª", "3ª", "4ª", "5ª"]):
                    prof_cod = row_dados.get(slot, "---")
                    
                    # COR DE FUNDO
                    estilo_app = gerar_estilo_professor_dinamico(prof_cod)
                    try:
                        bg_color = HexColor(estilo_app['bg'])
                        txt_color = HexColor(estilo_app['text'])
                    except:
                        bg_color = colors.white
                        txt_color = colors.black

                    # TEXTO FORMATADO (AQUI ESTÁ A MÁGICA QUE SEGUE O FILTRO)
                    texto_formatado = formatar_para_pdf(prof_cod)
                    
                    # Estilo da Célula
                    estilo_celula = ParagraphStyle(f'Cell{turma}{slot}', parent=estilo_aula, textColor=txt_color)
                    
                    row_idx = len(card_data)
                    card_data.append([slot, Paragraph(texto_formatado, estilo_celula)])
                    
                    card_styles.append(('BACKGROUND', (0, row_idx), (1, row_idx), bg_color))
                    card_styles.append(('ALIGN', (0, row_idx), (0, row_idx), 'CENTER'))
                    card_styles.append(('VALIGN', (0, row_idx), (1, row_idx), 'MIDDLE'))
                    card_styles.append(('GRID', (0, row_idx), (1, row_idx), 0.5, colors.white))

                    if slot == "3ª":
                        row_idx = len(card_data)
                        card_data.append(["", Paragraph("— RECREIO —", estilo_recreio)])
                        card_styles.append(('SPAN', (0, row_idx), (1, row_idx)))
                        card_styles.append(('TOPPADDING', (0, row_idx), (1, row_idx), 1))
                        card_styles.append(('BOTTOMPADDING', (0, row_idx), (1, row_idx), 1))

                t_card = Table(card_data, colWidths=[10*mm, 75*mm])
                t_card.setStyle(TableStyle(card_styles + [
                    ('BOX', (0,0), (-1,-1), 1, colors.lightgrey),
                    ('ROUNDEDCORNERS', [5, 5, 5, 5])
                ]))
                row_cards.append(t_card)

            # Organizar em Grid de 3
            grid_data = [row_cards[i:i + 3] for i in range(0, len(row_cards), 3)]
            if grid_data:
                while len(grid_data[-1]) < 3: grid_data[-1].append(Spacer(1, 1))

            t_grid = Table(grid_data, colWidths=[90*mm, 90*mm, 90*mm])
            t_grid.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('LEFTPADDING', (0,0), (-1,-1), 2),
                ('RIGHTPADDING', (0,0), (-1,-1), 2),
                ('BOTTOMPADDING', (0,0), (-1,-1), 10),
            ]))
            
            elements.append(t_grid)
            elements.append(Spacer(1, 5*mm))
            
        elements.append(PageBreak())

    if dias_impressos == 0:
        elements.append(Paragraph("Nenhuma aula encontrada.", styles['Normal']))

    doc.build(elements)
    buffer.seek(0)
    return buffer

# ==========================================
# 2.1 PDF POR PROFESSOR (HORÁRIO + PL)
# ==========================================
def gerar_pdf_prof_pl(ocupacao_por_dia, map_nome, map_comp, modo_vis, nome_escola, descricao_turno):
    """
    Gera um PDF em que cada professor aparece como linha
    (colunas: 1ª a 5ª aula), para cada dia.
    ocupacao_por_dia: {dia_label: {cod_prof: {slot: texto}}}
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )

    styles = getSampleStyleSheet()
    elements = []

    if descricao_turno:
        titulo = f"Horário + PL por Professor - {nome_escola} ({descricao_turno})"
    else:
        titulo = f"Horário + PL por Professor - {nome_escola}"

    # Adicionar imagem do brasão
    try:
        img_path = "img/EMAIL BRASÃO FUNDÃO_QUADRADA.png"
        img = Image(img_path, width=50*mm, height=50*mm)
        img.hAlign = 'CENTER'
        elements.append(img)
        elements.append(Spacer(1, 5*mm))
    except:
        # Se não conseguir carregar a imagem, continua sem ela
        pass

    elements.append(Paragraph(titulo, styles["Heading1"]))
    elements.append(Spacer(1, 5 * mm))

    def formatar_prof_exibicao(codigo):
        if not codigo or codigo == "---":
            return "---"
        nome = map_nome.get(codigo, codigo)
        mat = map_comp.get(codigo, "?")
        partes = str(nome).split()
        if len(partes) > 1:
            nome_curto = partes[0] + " " + partes[-1]
        else:
            nome_curto = nome

        if modo_vis == "Apenas Código":
            return codigo
        if modo_vis == "Nome do Professor":
            return nome_curto
        if modo_vis == "Matéria/Componente":
            return mat
        if modo_vis == "Nome + Matéria":
            return f"{nome} ({mat})"
        if modo_vis == "Código + Nome":
            return f"{codigo} - {nome}"
        if modo_vis == "Código + Componente":
            return f"{codigo} ({mat})"
        return codigo

    dias_ordenados = list(ocupacao_por_dia.keys())
    if not dias_ordenados:
        elements.append(Paragraph("Nenhuma informação de horário/PL encontrada.", styles["Normal"]))
        doc.build(elements)
        buffer.seek(0)
        return buffer

    # Ordena dias na sequência padrão dos DIAS_SEMANA, quando possível
    ordem_dias = {padronizar(d): i for i, d in enumerate(DIAS_SEMANA)}
    dias_ordenados.sort(key=lambda d: ordem_dias.get(padronizar(d), 99))

    # Estilos para quebra de linha nas células
    estilo_cell = ParagraphStyle(
        "CellSmall",
        parent=styles["Normal"],
        fontSize=7,
        leading=8,
        alignment=1,  # centralizado
        spaceAfter=0,
        spaceBefore=0,
    )
    estilo_prof = ParagraphStyle(
        "ProfSmall",
        parent=styles["Normal"],
        fontSize=7,
        leading=8,
        alignment=0,  # esquerda
        spaceAfter=0,
        spaceBefore=0,
    )

    def txt_para_paragraph(txt: str, estilo: ParagraphStyle) -> Paragraph:
        s = str(txt or "---")
        # quebra em múltiplas linhas dentro da célula
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        s = s.replace(" / ", "<br/>")
        return Paragraph(s, estilo)

    for dia_label in dias_ordenados:
        titulo_dia = f"📅 {dia_label}"
        if descricao_turno:
            titulo_dia += f" - Turno: {descricao_turno}"
        elements.append(Paragraph(titulo_dia, styles["Heading2"]))
        elements.append(Spacer(1, 2 * mm))

        dados_prof = ocupacao_por_dia[dia_label]
        if not dados_prof:
            elements.append(Paragraph("Sem dados para este dia.", styles["Normal"]))
            elements.append(Spacer(1, 4 * mm))
            continue

        # Cabeçalho da tabela
        header = ["Professor", "1ª", "2ª", "3ª", "4ª", "5ª"]
        data = [header]

        # Ordenar professores por nome exibido
        def nome_sort(cod):
            return formatar_prof_exibicao(cod)

        cods_ordenados = sorted(dados_prof.keys(), key=lambda c: nome_sort(c).lower())

        for cod in cods_ordenados:
            linha_slots = dados_prof[cod]
            row = [txt_para_paragraph(formatar_prof_exibicao(cod), estilo_prof)]
            for slot in ["1ª", "2ª", "3ª", "4ª", "5ª"]:
                row.append(txt_para_paragraph(linha_slots.get(slot, "---"), estilo_cell))
            data.append(row)

        # Mais largura para evitar sobreposição (A4 paisagem ~277mm úteis com margens)
        t = Table(data, colWidths=[75 * mm, 40 * mm, 40 * mm, 40 * mm, 40 * mm, 40 * mm], repeatRows=1)

        # Estilos base + cores por professor (igual ideia dos cards)
        estilos_tbl = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("LEADING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
        ]

        # Cores por professor, célula a célula, imitando os cards da tela
        for row_idx, cod in enumerate(cods_ordenados, start=1):
            est = gerar_estilo_professor_dinamico(cod)
            try:
                prof_bg = HexColor(est["bg"])
                prof_txt = HexColor(est["text"])
                neutro_bg = HexColor("#f8f9fa")
                neutro_txt = HexColor("#abb6c2")
            except Exception:
                prof_bg = colors.lightgrey
                prof_txt = colors.black
                neutro_bg = colors.whitesmoke
                neutro_txt = colors.grey

            # Coluna do nome do professor: fundo branco, borda esquerda colorida
            estilos_tbl.append(("BACKGROUND", (0, row_idx), (0, row_idx), colors.white))
            estilos_tbl.append(("LINEBEFORE", (0, row_idx), (0, row_idx), 2, prof_bg))
            estilos_tbl.append(("TEXTCOLOR", (0, row_idx), (0, row_idx), colors.black))

            # Slots 1ª a 5ª: mesma lógica dos cards (vazio = cinza, ocupado = cor do prof)
            linha_slots = dados_prof[cod]
            slots = ["1ª", "2ª", "3ª", "4ª", "5ª"]
            for col_offset, slot in enumerate(slots, start=1):
                val = str(linha_slots.get(slot, "---") or "").strip()
                if not val or val == "---":
                    bg = neutro_bg
                    txt = neutro_txt
                else:
                    bg = prof_bg
                    txt = prof_txt
                estilos_tbl.append(
                    ("BACKGROUND", (col_offset, row_idx), (col_offset, row_idx), bg)
                )
                estilos_tbl.append(
                    ("TEXTCOLOR", (col_offset, row_idx), (col_offset, row_idx), txt)
                )

        t.setStyle(TableStyle(estilos_tbl))

        elements.append(t)
        elements.append(Spacer(1, 8 * mm))

    doc.build(elements)
    buffer.seek(0)
    return buffer

# ==========================================
# 2. FUNÇÕES UTILITÁRIAS (COLE AQUI)
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
# 3. CONFIGURAÇÕES & ESTILO
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
# 4 FUNÇÕES DE ESTILO E CORES (V3 - ÚNICAS E VIBRANTES + SUPORTE PL)
# ==========================================

# --- HELPER PARA LIMPAR O CÓDIGO (IGNORAR O "PL-") ---
def extrair_id_real(codigo_sujo):
    """Transforma 'PL-P1DTARTE' em 'P1DTARTE' para checar conflitos e cores."""
    if not codigo_sujo or codigo_sujo == "---": return "---"
    return str(codigo_sujo).replace("PL-", "").strip()

def get_contrast_text_color(hex_bg_color):
    """Define se a letra é preta ou branca baseada na luminosidade do fundo."""
    if not hex_bg_color: return "#000000"
    hex_bg_color = hex_bg_color.lstrip('#')
    try:
        r, g, b = tuple(int(hex_bg_color[i:i+2], 16) for i in (0, 2, 4))
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return "#000000" if luminance > 0.55 else "#FFFFFF"
    except:
        return "#000000"

def gerar_estilo_professor_dinamico(id_professor):
    """
    Gera uma cor ÚNICA para cada código.
    Mesmo professores da mesma matéria terão tons diferentes.
    """
    if not id_professor or id_professor == "---":
        return {"bg": "#f8f9fa", "text": "#abb6c2", "border": "#e9ecef"}
    
    # --- MUDANÇA IMPORTANTE PARA O PL ---
    # Usamos o ID "limpo" para gerar a cor. 
    # Assim, 'P1DTARTE' e 'PL-P1DTARTE' terão exatamente a mesma cor!
    id_limpo = extrair_id_real(id_professor)
    id_upper = str(id_limpo).upper()
    
    # Gera um hash inteiro único baseado em TODOS os caracteres do código
    hash_val = int(hashlib.md5(id_upper.encode()).hexdigest(), 16)
    
    # Define a Matiz (Hue) baseada na matéria, mas com variação forte pelo hash
    if "COHI" in id_upper: 
        hue_base = 0.25 # Verde
        hue = hue_base + ((hash_val % 20) / 100.0 - 0.1) # Varia +/- 10%
    elif "EDFI" in id_upper: 
        hue_base = 0.90 # Magenta
        hue = hue_base + ((hash_val % 20) / 100.0 - 0.1)
    elif "ARTE" in id_upper: 
        # Arte varia drasticamente entre Laranja, Marrom e Ciano dependendo do código
        opcoes_arte = [0.08, 0.5, 0.05, 0.55] 
        hue = opcoes_arte[hash_val % 4]
    elif "ENRE" in id_upper: 
        hue_base = 0.6 # Azul
        hue = hue_base + ((hash_val % 15) / 100.0 - 0.07)
    elif "LIIN" in id_upper: 
        hue_base = 0.14 # Amarelo
        hue = hue_base + ((hash_val % 10) / 100.0 - 0.05)
    else:
        # Se não reconhecer, espalha totalmente
        hue = (hash_val % 360) / 360.0

    # A MÁGICA DA DIFERENÇA: Saturação e Luminosidade baseadas no hash
    saturation = 0.6 + ((hash_val % 40) / 100.0) # 0.6 a 1.0
    lightness = 0.35 + ((hash_val % 50) / 100.0) # 0.35 a 0.85

    r, g, b = colorsys.hls_to_rgb(hue % 1.0, lightness, saturation)
    bg_hex = '#%02x%02x%02x' % (int(r*255), int(g*255), int(b*255))
    txt_hex = get_contrast_text_color(bg_hex)
    
    # Borda um pouco mais escura que o fundo para definição
    return {"bg": bg_hex, "text": txt_hex, "border": "rgba(0,0,0,0.2)"}
# ==========================================
# 5 CONEXÃO COM GOOGLE SHEETS
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
# Definimos sistema_seguro imediatamente para que o resto do código o reconheça
sistema_seguro = (gs_client is not None and PLANILHA_ID is not None)

# ==========================================
# 6 VERIFICAR E AJUSTAR SECRETS.TOML
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
# 7 UTILITÁRIOS
# ==========================================
# Funções utilitárias foram movidas para utils.py
# Importadas no início do arquivo

# ==========================================
# 8 FUNÇÕES DE LEITURA/ESCRITA
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


# 2. SEGUNDO: Defina a função carregar_banco
@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def carregar_banco():
    # Verifica se o sistema está seguro
    if not sistema_seguro: 
        return (pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), 
                pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), False)
    
    # Carrega todas as abas
    t, _ = ler_aba_gsheets("Turmas", COLS_PADRAO["Turmas"])
    c, _ = ler_aba_gsheets("Curriculo", COLS_PADRAO["Curriculo"])
    pe, _ = ler_aba_gsheets("ProfessoresEF", COLS_PADRAO["Professores"])
    pd_dt, _ = ler_aba_gsheets("ProfessoresDT", COLS_PADRAO["Professores"])
    p = pd.concat([pe, pd_dt], ignore_index=True)
    d, _ = ler_aba_gsheets("ConfigDias", COLS_PADRAO["ConfigDias"])
    r, _ = ler_aba_gsheets("Agrupamentos", COLS_PADRAO["Agrupamentos"])
    h, _ = ler_aba_gsheets("Horario", COLS_PADRAO["Horario"])
    ch, _ = ler_aba_gsheets("CH", COLS_PADRAO["CH"])
    
    # Se CH estiver vazio, gera padrão
    if ch.empty: ch = gerar_dataframe_ch()
    
    # Carrega PL
    pl, _ = ler_aba_gsheets("HorarioPL", COLS_PADRAO["Horario"])

    # === CALCULAR CARGA HORÁRIA E PL DOS PROFESSORES BASEADO NO HORÁRIO ATUAL ===
    if not p.empty and (not h.empty or not pl.empty):
        carga_dict = {}
        pl_dict = {}
        escolas_dict = {}

        # Processar Horário (aulas)
        if not h.empty:
            for _, row in h.iterrows():
                for slot in ["1ª", "2ª", "3ª", "4ª", "5ª"]:
                    prof = row[slot]
                    if prof and prof != "---" and not str(prof).startswith("PL-"):
                        carga_dict[prof] = carga_dict.get(prof, 0) + 1
                        if prof not in escolas_dict:
                            escolas_dict[prof] = set()
                        escolas_dict[prof].add(row['ESCOLA'])

        # Processar PL
        if not pl.empty:
            for _, row in pl.iterrows():
                for slot in ["1ª", "2ª", "3ª", "4ª", "5ª"]:
                    val = row[slot]
                    if val and str(val).startswith("PL-"):
                        prof = extrair_id_real(val)
                        pl_dict[prof] = pl_dict.get(prof, 0) + 1
                        if prof not in escolas_dict:
                            escolas_dict[prof] = set()
                        escolas_dict[prof].add(row['ESCOLA'])

        # Atualizar DataFrame de Professores
        for idx, row in p.iterrows():
            cod = row['CÓDIGO']
            carga = carga_dict.get(cod, 0)
            qtd_pl = pl_dict.get(cod, 0)
            p.at[idx, 'CARGA_HORÁRIA'] = carga
            p.at[idx, 'QTD_PL'] = qtd_pl
            escs = escolas_dict.get(cod, set())
            if escs:
                p.at[idx, 'ESCOLAS_ALOCADAS'] = ",".join(sorted(escs))

    return t, c, p, d, r, h, ch, pl, True

# 3. TERCEIRO: Agora sim, chame a função (bloco try...except)
# --- CARREGAMENTO INICIAL ---
try:
    dt, dc, dp, dd, da, dh, dch, dpl, dados_ok = carregar_banco()
except Exception as e:
    # Se der erro, cria tabelas vazias
    dt = pd.DataFrame(columns=COLS_PADRAO["Turmas"])
    dc = pd.DataFrame(columns=COLS_PADRAO["Curriculo"])
    dp = pd.DataFrame(columns=COLS_PADRAO["Professores"])
    dd = pd.DataFrame(columns=COLS_PADRAO["ConfigDias"])
    da = pd.DataFrame(columns=COLS_PADRAO["Agrupamentos"])
    dh = pd.DataFrame(columns=COLS_PADRAO["Horario"])
    dch = pd.DataFrame(columns=COLS_PADRAO["CH"])
    dpl = pd.DataFrame(columns=COLS_PADRAO["Horario"]) # dpl definido aqui!

# ==========================================
# 9 LEITURA DE DADOS (CACHE)
# ==========================================
@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False, max_entries=1)
def carregar_banco():
    """
    Carrega todos os dados do Google Sheets com pausas estratégicas para evitar erro 429 (Quota Exceeded).
    """
    with st.spinner("🔄 Carregando sistema (com pausas de segurança)..."):
        # Se não houver conexão, retorna 7 dataframes vazios
        if gs_client is None or not PLANILHA_ID:
            empty_dfs = [pd.DataFrame() for _ in range(7)]
            return (*empty_dfs, False)
            
        try:
            # 1. Ler Turmas
            t, ok_t = ler_aba_gsheets("Turmas", COLS_PADRAO["Turmas"])
            time.sleep(1.5) # <--- PAUSA DE SEGURANÇA
            
            # 2. Ler Curriculo
            c, ok_c = ler_aba_gsheets("Curriculo", COLS_PADRAO["Curriculo"])
            time.sleep(1.5) # <--- PAUSA DE SEGURANÇA
            
            # 3. Ler Professores (combinando abas)
            p_ef, ok_ef = ler_aba_gsheets("ProfessoresEF", COLS_PADRAO["Professores"])
            time.sleep(1.0) 
            p_dt, ok_dt = ler_aba_gsheets("ProfessoresDT", COLS_PADRAO["Professores"])
            time.sleep(1.5) # <--- PAUSA DE SEGURANÇA
            
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
            time.sleep(1.0)
            r, ok_r = ler_aba_gsheets("Agrupamentos", COLS_PADRAO["Agrupamentos"])
            time.sleep(1.0)
            
            # 5. Ler Horario (opcional)
            h, ok_h = ler_aba_gsheets("Horario", COLS_PADRAO["Horario"])
            if not ok_h: h = pd.DataFrame()
            time.sleep(1.0)

            # 6. Ler Tabela CH
            ch_df, ok_ch = ler_aba_gsheets("CH", COLS_PADRAO["CH"])
            time.sleep(1.0)
            if not ok_ch or ch_df.empty:
                from ch import gerar_dataframe_ch
                ch_df = gerar_dataframe_ch()
            
            # 7. Ler HorarioPL (NOVA)
            pl, ok_pl = ler_aba_gsheets("HorarioPL", COLS_PADRAO["Horario"])
            if not ok_pl: pl = pd.DataFrame()

            # Verificar se tudo essencial carregou
            sucesso = ok_t and ok_c and ok_p and ok_d and ok_r
            
            # Retorna os 8 DataFrames + Status (Note que adicionei 'pl' no final)
            return t, c, p, d, r, h, ch_df, pl, sucesso
            
        except Exception as e:
            st.cache_data.clear()
            error_msg = str(e)
            if '429' in error_msg:
                st.warning("⚠️ O sistema está lendo muito rápido. Aguarde 1 minuto e recarregue a página.")
            else:
                st.error(f"❌ Erro ao carregar dados: {error_msg}")
            
            # Retorna vazios em caso de erro (8 dataframes agora)
            empty_dfs = [pd.DataFrame() for _ in range(8)]
            return (*empty_dfs, False)

# ==========================================
# 10 FUNÇÕES DE SALVAR
# ==========================================
def salvar_seguro(dt, dc, dp, dd, da, dh=None, dpl=None):
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

            # NOVO BLOCO PARA O PL
            if dpl is not None:
                status.write("📝 Salvando Horário PL...")
                # Garante que dpl não é None antes de salvar
                if not escrever_aba_gsheets("HorarioPL", dpl.fillna("")):
                    st.error("Erro ao escrever na aba HorarioPL")
                    return
                time.sleep(0.5)
            
            # CRUCIAL: Limpar o cache para o sistema baixar os dados novos na próxima vez
            st.cache_data.clear()
            status.update(label="✅ Salvo com Sucesso!", state="complete", expanded=False)
            
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
# 11 CÉREBRO: RH ROBIN HOOD CORRIGIDO
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
# 12 CÉREBRO: GERAÇÃO E ALOCAÇÃO INTELIGENTE
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
# 13 INTERFACE PRINCIPAL
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
t1, t2, t3, t4, t5, t6, t7, t8, t9, t10, t11 = st.tabs([
    "📊 Dashboard", 
    "⚙️ Config", 
    "📍 Rotas", 
    "🏫 Turmas", 
    "👨‍🏫 Professores", 
    "💼 Vagas", 
    "🚀 Gerador", 
    "📅 Ver Horário", 
    "✏️ Editor Manual",
    "📘 Gestão de PL",
    "🧮 Horário/PL por Prof./Componente"
])


# ABA 1: DASHBOARD GERENCIAL (COMPLETO)

with t1:
    if dt.empty or dc.empty:
        st.info("📝 O Dashboard ficará ativo assim que você cadastrar Turmas e Currículo.")
    else:
        st.markdown("### 📊 Visão Geral da Rede")

        # --- 1. FILTROS GLOBAIS ---
        c_f1, c_f2, c_f3 = st.columns(3)
        with c_f1: 
            regioes_disp = sorted(dt['REGIÃO'].unique())
            filtro_regiao = st.multiselect("🌍 Região", regioes_disp, default=regioes_disp)
        with c_f2:
            if filtro_regiao:
                opcoes_escolas = dt[dt['REGIÃO'].isin(filtro_regiao)]['ESCOLA'].unique()
            else:
                opcoes_escolas = dt['ESCOLA'].unique()
            filtro_escola = st.selectbox("🏢 Escola", ["Todas"] + sorted(list(opcoes_escolas)))
        with c_f3:
            filtro_materia = st.selectbox("📚 Matéria", ["Todas"] + MATERIAS_ESPECIALISTAS)

        
        # 2. CÁLCULO DE DEMANDA (NECESSIDADE)
        
        df_turmas_filt = dt.copy()
        if filtro_regiao: 
            df_turmas_filt = df_turmas_filt[df_turmas_filt['REGIÃO'].isin(filtro_regiao)]
        if filtro_escola != "Todas": 
            df_turmas_filt = df_turmas_filt[df_turmas_filt['ESCOLA'] == filtro_escola]

        demanda_por_materia = {}
        total_aulas_demanda = 0
        auditoria_demanda = []

        for _, row in df_turmas_filt.iterrows():
            serie = row['SÉRIE/ANO']
            turma_nome = row['TURMA']
            escola_nome = row['ESCOLA']
            
            curr = dc[dc['SÉRIE/ANO'] == serie]
            
            for _, item in curr.iterrows():
                mat_nome = padronizar_materia_interna(item['COMPONENTE'])
                if mat_nome in [padronizar_materia_interna(m) for m in MATERIAS_ESPECIALISTAS]:
                    if filtro_materia == "Todas" or padronizar_materia_interna(filtro_materia) == mat_nome:
                        qtd = int(item['QTD_AULAS'])
                        demanda_por_materia[mat_nome] = demanda_por_materia.get(mat_nome, 0) + qtd
                        total_aulas_demanda += qtd
                        auditoria_demanda.append(f"📌 {escola_nome} - {turma_nome}: +{qtd} {mat_nome}")

       
        # 3. CÁLCULO DE OFERTA (PROFESSORES)
        
        df_profs_filt = dp.copy()
        
        # Filtro de Região
        if filtro_regiao: 
            df_profs_filt = df_profs_filt[df_profs_filt['REGIÃO'].isin(filtro_regiao)]
            
        # Filtro de Escola (Lógica: Professor está alocado nesta escola?)
        if filtro_escola != "Todas":
            esc_alvo_norm = padronizar(filtro_escola)
            def checar_escola(escolas_str):
                if pd.isna(escolas_str) or escolas_str == "": return False 
                # Separa a lista de escolas do professor e verifica
                escolas_prof = [padronizar(e.strip()) for e in str(escolas_str).split(',')]
                return esc_alvo_norm in escolas_prof

            df_profs_filt = df_profs_filt[df_profs_filt['ESCOLAS_ALOCADAS'].apply(checar_escola)]

        oferta_por_materia = {}
        total_aulas_oferta = 0
        auditoria_oferta = []

        for _, row in df_profs_filt.iterrows():
            nome_prof = row['NOME']
            cod_prof = row['CÓDIGO']
            # Pega as matérias que esse professor dá
            comps = [padronizar_materia_interna(c.strip()) for c in str(row['COMPONENTES']).split(',')]
            
            # --- CÁLCULO DE AULAS ---
            # Lê diretamente a coluna CARGA_HORÁRIA como sendo a quantidade de aulas
            carga_aulas = int(row['CARGA_HORÁRIA'])
            
            # Filtra apenas especialistas
            mats_validas = [c for c in comps if c in [padronizar_materia_interna(m) for m in MATERIAS_ESPECIALISTAS]]
            
            if mats_validas:
                # Se der mais de uma matéria, divide. Se der só uma, pega tudo.
                carga_por_mat = carga_aulas / len(mats_validas)
                
                for c in mats_validas:
                    if filtro_materia == "Todas" or padronizar_materia_interna(filtro_materia) == c:
                        oferta_por_materia[c] = oferta_por_materia.get(c, 0) + carga_por_mat
                        total_aulas_oferta += carga_por_mat
                        
                        auditoria_oferta.append(f"👨‍🏫 {cod_prof} ({nome_prof}): Dispõe de {carga_por_mat:.1f} aulas de {c}")

        # --- 4. EXIBIÇÃO DOS INDICADORES ---
        st.divider()
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Turmas Analisadas", len(df_turmas_filt))
        k2.metric("Demanda (Necessidade)", total_aulas_demanda)
        k3.metric("Oferta (Professores)", int(total_aulas_oferta))
        
        saldo = int(total_aulas_oferta - total_aulas_demanda)
        k4.metric("Saldo", saldo, delta_color="normal" if saldo >= 0 else "inverse")

        # --- 5. DETETIVE DE CÁLCULOS (ABRA AQUI PARA CONFERIR) ---
        with st.expander("🕵️‍♀️ Detetive de Cálculos (Clique para ver de onde vêm os números)🕵️‍♀️"):
            d1, d2 = st.columns(2)
            with d1:
                st.markdown("**🔍 Detalhe da Demanda (Turmas)**")
                if auditoria_demanda:
                    st.text("\n".join(auditoria_demanda[:50])) # Mostra os primeiros 50
                    if len(auditoria_demanda) > 50: st.caption("... e mais turmas.")
                else:
                    st.write("Nenhuma demanda encontrada.")
            
            with d2:
                st.markdown("**🔍 Detalhe da Oferta (Professores)**")
                if auditoria_oferta:
                    # AQUI VOCÊ VAI VER O VALOR QUE O SISTEMA ESTÁ LENDO
                    st.text("\n".join(auditoria_oferta))
                else:
                    st.write("Nenhum professor encontrado para esta escola.")

        # --- 6. TABELA DE BALANÇO ---
        st.subheader("📉 Balanço por Matéria")
        dados_tabela = []
        todas_mats = set(list(demanda_por_materia.keys()) + list(oferta_por_materia.keys()))
        
        for m in sorted(list(todas_mats)):
            dem = demanda_por_materia.get(m, 0)
            ofe = int(oferta_por_materia.get(m, 0))
            dif = ofe - dem
            status = "✅ OK" if dif == 0 else (f"🔵 Sobra {dif}" if dif > 0 else f"🔴 Falta {abs(dif)}")
            
            dados_tabela.append({
                "Matéria": m,
                "Necessidade": dem,
                "Disponível": ofe,
                "Saldo": dif,
                "Status": status
            })
        
        if dados_tabela:
            st.dataframe(pd.DataFrame(dados_tabela), use_container_width=True, hide_index=True)

        # --- 7. GALERIA VISUAL (RESTAURADA) ---
        st.divider()
        st.subheader(f"🎨 Professores Alocados: {filtro_escola}")
        st.caption("Cores de identificação geradas pelo sistema:")

        # --- MAPEAMENTO: AULAS -> HORAS RELOGIO (ABA CH) ---
        def _parse_num(valor):
            if valor is None or pd.isna(valor):
                return None
            if isinstance(valor, (int, float)):
                return float(valor)
            s = str(valor).strip().lower()
            if not s:
                return None
            # Formatos tipo "23:30"
            if ":" in s:
                partes = s.split(":")
                if len(partes) == 2 and partes[0].isdigit() and partes[1].isdigit():
                    return int(partes[0]) + (int(partes[1]) / 60)
            # Formatos tipo "23h", "23 h", "23h30"
            m = re.match(r"^\s*(\d+)\s*h(?:\s*(\d+))?\s*$", s)
            if m:
                horas = int(m.group(1))
                mins = int(m.group(2) or 0)
                return horas + (mins / 60)
            # Número simples com ponto ou vírgula
            s = s.replace(",", ".")
            m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
            if m:
                try:
                    return float(m.group(0))
                except Exception:
                    return None
            return None

        def _montar_mapa_aulas_ch(df, aulas_col):
            mapa = {}
            for _, row in df.iterrows():
                aulas_val = _parse_num(row.get(aulas_col))
                ch_val = _parse_num(row.get("CH"))
                if aulas_val is None or ch_val is None:
                    continue
                if aulas_val <= 0 or ch_val <= 0:
                    continue
                mapa[int(aulas_val)] = ch_val
            return mapa

        def _montar_mapa_hora(df, cols_ch):
            mapa = {}
            for _, row in df.iterrows():
                aulas_val = _parse_num(row.get("HORA_ALUNO"))
                if aulas_val is None or aulas_val <= 0:
                    continue
                if "MINUTOS_TOTAL" in cols_ch:
                    minutos_val = _parse_num(row.get("MINUTOS_TOTAL"))
                    if minutos_val is None or minutos_val <= 0:
                        continue
                    ch_val = minutos_val / 60
                elif "TOTAL_HORAS" in cols_ch:
                    total_aulas = _parse_num(row.get("TOTAL_HORAS"))
                    if total_aulas is None or total_aulas <= 0:
                        continue
                    ch_val = (total_aulas * 50) / 60
                else:
                    continue
                mapa[int(aulas_val)] = ch_val
            return mapa

        mapa_ch = {}
        if isinstance(dch, pd.DataFrame) and not dch.empty:
            cols_ch = set(dch.columns)
            mapa_aulas = {}
            mapa_hora = {}
            if "CH" in cols_ch:
                if "AULAS" in cols_ch:
                    mapa_aulas = _montar_mapa_aulas_ch(dch, "AULAS")
                if not mapa_aulas and "AULA" in cols_ch:
                    mapa_aulas = _montar_mapa_aulas_ch(dch, "AULA")
            if "HORA_ALUNO" in cols_ch:
                mapa_hora = _montar_mapa_hora(dch, cols_ch)

            if mapa_aulas:
                mapa_ch = mapa_aulas
            elif mapa_hora:
                mapa_ch = mapa_hora

        def _formatar_horas(valor):
            if valor is None:
                return "-"
            if abs(valor - int(valor)) < 1e-9:
                return f"{int(valor)}h"
            return f"{valor:.2f}h".replace(".", ",")

        if not df_profs_filt.empty:
            # Ordena para ficar bonito
            df_profs_filt['MAT_PRINCIPAL'] = df_profs_filt['COMPONENTES'].apply(lambda x: str(x).split(',')[0])
            df_vis = df_profs_filt.sort_values(by=['MAT_PRINCIPAL', 'NOME'])
            
            cols_vis = st.columns(6)
            for idx, (_, p) in enumerate(df_vis.iterrows()):
                cod = p['CÓDIGO']
                # Pega primeiro e último nome
                nomes = p['NOME'].split()
                nome_curto = f"{nomes[0]} {nomes[-1]}" if len(nomes) > 1 else nomes[0]
                
                # Gera a cor
                estilo = gerar_estilo_professor_dinamico(cod)
                carga_aulas = p.get('CARGA_HORÁRIA', 0)
                try:
                    carga_aulas = int(carga_aulas)
                except Exception:
                    carga_aulas = 0
                horas_relogio = mapa_ch.get(carga_aulas)
                if horas_relogio is None and carga_aulas:
                    horas_relogio = (carga_aulas * 50) / 60
                ch_txt = _formatar_horas(horas_relogio)
                
                with cols_vis[idx % 6]:
                    st.markdown(f"""
                    <div style="
                        background-color: {estilo['bg']}; 
                        color: {estilo['text']}; 
                        border: 1px solid {estilo['border']};
                        border-radius: 6px; 
                        padding: 8px; 
                        margin-bottom: 10px;
                        text-align: center;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    ">
                        <div style="font-weight: 800; font-size: 13px;">{cod}</div>
                        <div style="font-size: 11px; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{nome_curto}</div>
                        <div style="font-size: 9px; opacity: 0.9; margin-top: 2px;">{p['COMPONENTES'][:15]}</div>
                        <div style="font-size: 9px; opacity: 0.9; margin-top: 2px;">CH: {ch_txt}</div>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.info("Nenhum professor alocado nesta escola para exibir na galeria.")

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

# ==========================================
# ABA 5: GESTÃO DE PROFESSORES (EDIÇÃO COMPLETA)
# ==========================================
with t5:
    st.markdown("### 👨‍🏫 Gestão do Corpo Docente")
    
    # --- 1. PREPARAÇÃO DE DADOS ---
    if dt.empty:
        st.warning("⚠️ Cadastre turmas primeiro para carregar a lista de escolas.")
        lista_escolas = []
    else:
        lista_escolas = sorted(dt['ESCOLA'].unique())
    
    # --- 2. FILTROS ---
    with st.container():
        c1, c2, c3 = st.columns([2, 2, 1])
        esc_sel = c1.selectbox("Filtrar por Escola", ["Todas as Escolas"] + lista_escolas)
        busca = c2.text_input("Buscar por Nome ou Código")
        c3.metric("Total de Professores", len(dp))

    # --- 3. TABELA DE SELEÇÃO ---
    df_show = dp.copy()
    
    # Aplica filtros
    if esc_sel != "Todas as Escolas":
        alvo = padronizar(esc_sel)
        df_show = df_show[df_show['ESCOLAS_ALOCADAS'].apply(lambda x: alvo in [padronizar(e.strip()) for e in str(x).split(',')])]
    
    if busca:
        t = padronizar(busca)
        df_show = df_show[df_show['NOME'].apply(padronizar).str.contains(t) | df_show['CÓDIGO'].str.contains(t.upper())]

    st.info("👇 Marque a caixa **'Editar'** para abrir a ficha completa do professor.")
    
    # Coluna de seleção manual (compatível com todas as versões)
    df_show.insert(0, "Editar", False)
    
    # Exibe tabela resumida (apenas para encontrar o professor)
    df_tabela = st.data_editor(
        df_show,
        column_config={
            "Editar": st.column_config.CheckboxColumn("Selecionar", width="small"),
            "CÓDIGO": st.column_config.TextColumn("Código", disabled=True),
            "NOME": st.column_config.TextColumn("Nome", disabled=True),
            "ESCOLAS_ALOCADAS": st.column_config.TextColumn("Escolas", disabled=True),
            "COMPONENTES": st.column_config.TextColumn("Matérias", disabled=True),
        },
        use_container_width=True,
        hide_index=True,
        key="tabela_professores_completa"
    )

    # --- 4. FICHA COMPLETA DE EDIÇÃO ---
    selecionados = df_tabela[df_tabela["Editar"] == True]

    if not selecionados.empty:
        # Pega o primeiro selecionado
        idx_real = selecionados.index[0]
        prof = dp.loc[idx_real]
        
        st.divider()
        st.markdown(f"### ✏️ Editando: **{prof['NOME']}** ({prof['CÓDIGO']})")
        
        with st.form("form_edicao_completa"):
            # Linha 1: Dados Básicos
            c_a, c_b, c_c = st.columns([1, 2, 1])
            nome_ed = c_b.text_input("Nome Completo", value=prof['NOME'])
            cod_ed = c_a.text_input("Código (ID)", value=prof['CÓDIGO'], disabled=True, help="O código não pode ser alterado.")
            
            # Linha 2: Contrato e Localização
            c_d, c_e, c_f = st.columns(3)
            
            # Região
            reg_atual = prof['REGIÃO'] if prof['REGIÃO'] in REGIOES else REGIOES[0]
            reg_ed = c_d.selectbox("Região", REGIOES, index=REGIOES.index(reg_atual))
            
            # Vínculo
            vinc_ops = ["DT", "EFETIVO"]
            vinc_atual = prof['VÍNCULO'] if prof['VÍNCULO'] in vinc_ops else "DT"
            vinc_ed = c_e.selectbox("Vínculo", vinc_ops, index=vinc_ops.index(vinc_atual))
            
            # Turno Fixo
            turnos_ops = ["", "MATUTINO", "VESPERTINO", "AMBOS"]
            turno_atual = prof['TURNO_FIXO'] if prof['TURNO_FIXO'] in turnos_ops else ""
            turno_ed = c_f.selectbox("Turno Fixo (Disponibilidade)", turnos_ops, index=turnos_ops.index(turno_atual))

            # Linha 3: Carga Horária
            c_g, c_h = st.columns(2)
            ch_ed = c_g.number_input("Carga Horária (Aulas)", value=int(prof['CARGA_HORÁRIA']), step=1)
            pl_ed = c_h.number_input("Carga de PL", value=int(prof['QTD_PL']), step=1)

            # Linha 4: Listas (Escolas e Matérias)
            st.markdown("---")
            c_i, c_j = st.columns(2)
            
            # Escolas (Multiselect)
            escolas_atuais = [e.strip() for e in str(prof['ESCOLAS_ALOCADAS']).split(',') if e.strip()]
            lista_escolas_total = sorted(list(set(lista_escolas + escolas_atuais))) # Garante que as atuais apareçam
            escolas_ed = c_i.multiselect("🏫 Escolas de Atuação", lista_escolas_total, default=escolas_atuais)
            
            # Matérias (Multiselect)
            mats_atuais = [m.strip() for m in str(prof['COMPONENTES']).split(',') if m.strip()]
            lista_mats_total = sorted(list(set(MATERIAS_ESPECIALISTAS + mats_atuais)))
            mats_ed = c_j.multiselect("📚 Matérias / Componentes", lista_mats_total, default=mats_atuais)

            # Botão Salvar
            st.markdown("<br>", unsafe_allow_html=True)
            if st.form_submit_button("💾 Salvar Todas as Alterações", type="primary"):
                # Atualiza o DataFrame Principal
                dp.at[idx_real, 'NOME'] = padronizar(nome_ed)
                dp.at[idx_real, 'REGIÃO'] = reg_ed
                dp.at[idx_real, 'VÍNCULO'] = vinc_ed
                dp.at[idx_real, 'TURNO_FIXO'] = turno_ed
                dp.at[idx_real, 'CARGA_HORÁRIA'] = ch_ed
                dp.at[idx_real, 'QTD_PL'] = pl_ed
                dp.at[idx_real, 'ESCOLAS_ALOCADAS'] = ",".join(escolas_ed)
                dp.at[idx_real, 'COMPONENTES'] = ",".join(mats_ed)
                
                salvar_seguro(dt, dc, dp, dd, da)
                st.success(f"✅ Dados de **{nome_ed}** atualizados com sucesso!")
                time.sleep(1)
                st.rerun()

    # --- 5. CADASTRO DE NOVO PROFESSOR ---
    st.markdown("---")
    with st.expander("➕ Cadastrar Novo Professor", expanded=False):
        with st.form("form_novo_prof_v3"):
            st.write("Preencha todos os dados para o novo cadastro:")
            
            nc1, nc2 = st.columns([1, 3])
            n_cod = nc1.text_input("Código (Ex: P100DTARTE)")
            n_nom = nc2.text_input("Nome Completo")
            
            nc3, nc4, nc5, nc6 = st.columns(4)
            n_reg = nc3.selectbox("Região", REGIOES)
            n_vin = nc4.selectbox("Vínculo", ["DT", "EFETIVO"])
            n_trn = nc5.selectbox("Turno Fixo", ["", "MATUTINO", "VESPERTINO", "AMBOS"])
            n_ch = nc6.number_input("Carga (Aulas)", 1, 60, 25)
            
            nc7, nc8 = st.columns(2)
            n_esc = nc7.multiselect("Escolas", lista_escolas)
            n_mat = nc8.multiselect("Matérias", MATERIAS_ESPECIALISTAS)
            
            n_pl = st.number_input("PL", 0, 20, 0)
            
            if st.form_submit_button("Cadastrar Professor"):
                if not n_cod:
                    st.error("Código é obrigatório.")
                elif n_cod.strip().upper() in dp['CÓDIGO'].values:
                    st.error("Este código já existe no sistema.")
                else:
                    novo = {
                        "CÓDIGO": n_cod.strip().upper(),
                        "NOME": padronizar(n_nom),
                        "REGIÃO": n_reg,
                        "VÍNCULO": n_vin,
                        "TURNO_FIXO": n_trn,
                        "CARGA_HORÁRIA": n_ch,
                        "QTD_PL": n_pl,
                        "ESCOLAS_ALOCADAS": ",".join(n_esc),
                        "COMPONENTES": ",".join(n_mat)
                    }
                    dp = pd.concat([dp, pd.DataFrame([novo])], ignore_index=True)
                    salvar_seguro(dt, dc, dp, dd, da)
                    st.success("Professor cadastrado!")
                    time.sleep(1)
                    st.rerun()

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

# ABA 7: GERADOR (MANTENHA O MESMO CÓDIGO)
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
# ABA 8: VER HORÁRIO (VISUAL COMPLETO + PDF)
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

        ## --- 2. FILTROS E BOTÃO DE PDF ---
        c1, c2, c3 = st.columns([2, 2, 1.5])
        with c1:
            esc_sel = st.selectbox("🏢 Escolha a Escola", sorted(dh['ESCOLA'].unique()), key="sel_esc_t8")
        with c2:
            dia_sel = st.selectbox("📆 Filtrar por Dia", ["Todos os Dias"] + DIAS_SEMANA, key="sel_dia_t8")
        with c3:
            # BOTÃO DE PDF
            st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True) 
            if st.button("📄 Baixar PDF desta Escola", type="primary", use_container_width=True):
                with st.spinner("Gerando documento visual..."):
                    
                    # 1. PREPARA CONFIGURAÇÃO VISUAL (Captura o que você vê na tela)
                    config_visual = {
                        'modo': modo_vis,  # <--- O filtro que você selecionou no Radio Button
                        'map_nome': map_nome, # Os nomes dos professores
                        'map_comp': map_comp  # As matérias
                    }
                    
                    # 2. FILTRA DADOS
                    df_pdf = dh[dh['ESCOLA'] == esc_sel]
                    
                    # 3. GERA PDF COM CONFIGURAÇÃO
                    pdf_bytes = gerar_pdf_escola(
                        df_pdf, 
                        esc_sel, 
                        dia_filtro=dia_sel,
                        config_visual=config_visual  # <--- Passamos a configuração aqui
                    )
                    
                    nome_arquivo = f"Horario_{esc_sel.replace(' ', '_')}_{dia_sel}.pdf"
                    st.download_button(
                        label="📥 Clique para Salvar PDF",
                        data=pdf_bytes,
                        file_name=nome_arquivo,
                        mime='application/pdf'
                    )
        # --- 3. VISUALIZAÇÃO NA TELA (SEU CÓDIGO ORIGINAL MANTIDO) ---
        df_view = dh[dh['ESCOLA'] == esc_sel].copy()
        dias_para_mostrar = [dia_sel] if dia_sel != "Todos os Dias" else DIAS_SEMANA
        
        for dia in dias_para_mostrar:
            dia_norm = padronizar(dia)
            df_dia = df_view[df_view['DIA'].apply(padronizar) == dia_norm]
            
            if df_dia.empty: continue
            
            # Validação de quais turmas exibir (ConfigDias)
            turmas_dia = df_dia['TURMA'].unique()
            turmas_v = []
            for t in turmas_dia:
                d_t = dt[dt['TURMA'] == t]
                if not d_t.empty:
                    serie = d_t.iloc[0]['SÉRIE/ANO']
                    cfg = dd[dd['SÉRIE/ANO'] == serie]
                    if not cfg.empty:
                        if dia_norm in [padronizar(d) for d in cfg['DIA_PLANEJAMENTO'].unique()]:
                            turmas_v.append(t)
                    else: turmas_v.append(t)
                else: turmas_v.append(t)
            
            if not turmas_v: continue
            
            st.markdown(f"#### 📅 {dia}")
            for turno in sorted(df_dia['TURNO'].unique()):
                df_turno = df_dia[df_dia['TURNO'] == turno]
                turmas_f = [t for t in sorted(df_turno['TURMA'].unique()) if t in turmas_v]
                
                if not turmas_f: continue
                st.caption(f"☀️ Turno: {turno}")
                
                cols = st.columns(3)
                for i, t_nome in enumerate(turmas_f):
                    linha = df_turno[df_turno['TURMA'] == t_nome].iloc[0]
                    with cols[i % 3]:
                        # Início do Card
                        html = f'<div class="turma-card-moldura"><div class="turma-titulo">👥 {t_nome}</div>'
                        
                        for slot in ["1ª", "2ª", "3ª", "4ª", "5ª"]:
                            cod = linha.get(slot, "---")
                            est = gerar_estilo_professor_dinamico(cod)
                            txt_exib = formatar_celula(cod)
                            
                            html += f'''
                            <div class="slot-aula-container" style="background-color: {est['bg']}; color: {est['text']}; border: 1px solid {est['border']};">
                                <div class="slot-label" style="color: {est['text']}; opacity: 0.6;">{slot}</div>
                                <div style="flex-grow: 1; text-align: center; font-weight: 800; font-size: 0.95em; letter-spacing: 0.5px;">
                                    {txt_exib}
                                </div>
                            </div>'''
                            
                            if slot == "3ª":
                                html += f'<div style="text-align:center; padding: 2px 0; border-top: 1px dashed #ccc; border-bottom: 1px dashed #ccc; margin: 2px 0;"><span style="font-size: 9px; font-weight: bold; color: #999; letter-spacing: 2px;">RECREIO</span></div>'
                        
                        html += "</div>"
                        st.markdown(html, unsafe_allow_html=True)
            st.divider()
             
# ==========================================
# ABA 9: EDITOR MANUAL (COM FILTRO DE MATÉRIA)
# ==========================================
with t9:
    st.markdown("### ✏️ Editor Manual de Horário")
    
    if dt.empty or dc.empty:
        st.warning("⚠️ É necessário carregar Turmas e Currículo para editar.")
    else:
        # --- 1. FILTROS (4 COLUNAS: ESCOLA, DIA, TURNO, MATÉRIA) ---
        c1, c2, c3, c4 = st.columns(4)
        
        with c1: esc_man = st.selectbox("🏢 Escola", sorted(dt['ESCOLA'].unique()), key="m_esc_t9_filter")
        with c2: dia_man = st.selectbox("📅 Dia", DIAS_SEMANA, key="m_dia_t9_filter")
        with c3:
            turnos_disp = dt[dt['ESCOLA'] == esc_man]['TURNO'].unique()
            turno_man = st.selectbox("☀️ Turno", sorted(turnos_disp), key="m_trn_t9_filter") if len(turnos_disp) > 0 else None
        
        # NOVO FILTRO DE COMPONENTE PARA O EDITOR
        with c4:
            filtro_comp_editor = st.selectbox("📚 Filtrar Profs por", ["Todos"] + MATERIAS_ESPECIALISTAS, key="m_comp_t9_filter")

        if turno_man:
            st.divider()
            dia_norm_man = padronizar(dia_man)
            
            # --- 2. PREPARAR LISTA DE PROFESSORES (COM FILTRO) ---
            if filtro_comp_editor != "Todos":
                # Função para verificar se o professor dá a matéria selecionada
                comp_alvo_ed = padronizar_materia_interna(filtro_comp_editor)
                def tem_materia_ed(comps_str):
                    lista = [padronizar_materia_interna(c.strip()) for c in str(comps_str).split(',')]
                    return comp_alvo_ed in lista

                df_profs_ed = dp[dp['COMPONENTES'].apply(tem_materia_ed)]
                # Lista filtrada + "---"
                lista_profs = ["---"] + sorted(df_profs_ed["C\u00D3DIGO"].unique().tolist())
                st.caption(f"Exibindo apenas professores de: **{filtro_comp_editor}**")
            else:
                # Lista completa
                lista_profs = ["---"] + sorted(dp["C\u00D3DIGO"].unique().tolist())

            # --- 3. IDENTIFICAR TURMAS ---
            df_base_t = dt[(dt['ESCOLA'] == esc_man) & (dt['TURNO'] == turno_man)]
            turmas_alvo_info = []
            
            for _, r_t in df_base_t.iterrows():
                serie_t = r_t['SÉRIE/ANO']
                config = dd[dd['SÉRIE/ANO'] == serie_t]
                if not config.empty:
                    dias_ok = [padronizar(d) for d in config['DIA_PLANEJAMENTO'].unique()]
                    if dia_norm_man in dias_ok: 
                        turmas_alvo_info.append({'nome': r_t['TURMA'], 'serie': serie_t})
                else: 
                    turmas_alvo_info.append({'nome': r_t['TURMA'], 'serie': serie_t})
            
            turmas_alvo_info = sorted(turmas_alvo_info, key=lambda x: x['nome'])

            if not turmas_alvo_info:
                st.info(f"🚫 Nenhuma turma configurada para {dia_man} neste turno.")
            else:
                # --- 4. PREPARAÇÃO DE DADOS (HORÁRIOS) ---
                horario_atual = {}
                if not dh.empty:
                    mask_tela = (dh['ESCOLA'] == esc_man) & \
                                (dh['DIA'].apply(padronizar) == dia_norm_man) & \
                                (dh['TURNO'] == turno_man)
                    for _, row in dh[mask_tela].iterrows():
                        horario_atual[row['TURMA']] = {s: row[s] for s in ["1ª", "2ª", "3ª", "4ª", "5ª"]}

                # Histórico (para validação)
                aulas_semanais_db = {}
                if not dh.empty:
                    mask_hist = (dh['ESCOLA'] == esc_man) & \
                                (dh['TURNO'] == turno_man) & \
                                (dh['DIA'].apply(padronizar) != dia_norm_man) 
                    df_hist = dh[mask_hist]
                    for _, row in df_hist.iterrows():
                        t_nome = row['TURMA']
                        if t_nome not in aulas_semanais_db: aulas_semanais_db[t_nome] = []
                        for s in ["1ª", "2ª", "3ª", "4ª", "5ª"]:
                            if row[s] and row[s] != "---":
                                aulas_semanais_db[t_nome].append(row[s])

                # Conflitos (AGORA PEGA PL E AULA DE OUTROS LUGARES)
                dh_conflito = pd.DataFrame()
                if not dh.empty:
                    mask_editando_agora = (dh['ESCOLA'] == esc_man) & \
                                          (dh['DIA'].apply(padronizar) == dia_norm_man) & \
                                          (dh['TURNO'] == turno_man)
                    df_resto = dh[~mask_editando_agora]
                    if not df_resto.empty:
                        dh_conflito = df_resto[
                            (df_resto['DIA'].apply(padronizar) == dia_norm_man) & 
                            (df_resto['TURNO'] == turno_man)
                        ]
                
                # ADICIONA TABELA DE PL (dpl) AOS CONFLITOS TAMBÉM
                # Se um professor estiver fazendo PL em outro lugar, ele não pode dar aula aqui
                if not dpl.empty:
                    dpl_conflito = dpl[
                        (dpl['DIA'].apply(padronizar) == dia_norm_man) & 
                        (dpl['TURNO'] == turno_man)
                    ]
                    # Junta os dois DataFrames de conflito
                    if not dpl_conflito.empty:
                        dh_conflito = pd.concat([dh_conflito, dpl_conflito])

                escolhas_t9 = {}
                
                # --- 5. RENDERIZAR GRID ---
                grid = st.columns(3)
                
                for idx, t_info in enumerate(turmas_alvo_info):
                    turma = t_info['nome']
                    serie = t_info['serie']
                    
                    with grid[idx % 3]:
                        st.markdown(f'<div class="turma-card-moldura" style="background:#fcfcfc; padding:10px;"><div class="turma-titulo">{turma} <small>({serie})</small></div>', unsafe_allow_html=True)
                        
                        for slot in ["1ª", "2ª", "3ª", "4ª", "5ª"]:
                            val_ini = horario_atual.get(turma, {}).get(slot, "---")
                            
                            # Lógica Inteligente para o Dropdown:
                            # Se o valor que já está salvo (val_ini) NÃO estiver na lista filtrada (lista_profs),
                            # nós adicionamos ele temporariamente para não "sumir" com o professor da tela.
                            opcoes_locais = lista_profs.copy()
                            if val_ini != "---" and val_ini not in opcoes_locais:
                                opcoes_locais.append(val_ini)
                                # Ordena novamente para ficar bonito, mantendo "---" no início
                                opcoes_locais = ["---"] + sorted([x for x in opcoes_locais if x != "---"])
                            
                            c_lbl, c_sel = st.columns([1, 4])
                            with c_lbl: 
                                st.markdown(f"<div style='padding-top:10px; font-weight:bold; font-size:11px;'>{slot}</div>", unsafe_allow_html=True)
                            with c_sel:
                                try:
                                    idx_sel = opcoes_locais.index(val_ini)
                                except:
                                    idx_sel = 0

                                res_prof = st.selectbox("", opcoes_locais, 
                                                      index=idx_sel, 
                                                      key=f"ed_main_{turma}_{slot}_{dia_man}", 
                                                      label_visibility="collapsed")
                                
                                # Corzinha
                                if res_prof != "---":
                                    # Se for PL, mostra diferente, mas com a mesma cor base
                                    cod_real = extrair_id_real(res_prof)
                                    est = gerar_estilo_professor_dinamico(cod_real)
                                    
                                    if str(res_prof).startswith("PL-"):
                                        st.markdown(f'<div style="background:{est["bg"]}; color:{est["text"]}; font-size:10px; text-align:center; border-radius:3px; margin-top:-10px; margin-bottom:5px; opacity: 0.7; border: 1px dashed {est["border"]};">{res_prof}</div>', unsafe_allow_html=True)
                                    else:
                                        st.markdown(f'<div style="background:{est["bg"]}; color:{est["text"]}; font-size:10px; text-align:center; border-radius:3px; margin-top:-10px; margin-bottom:5px;">{res_prof}</div>', unsafe_allow_html=True)
                                
                                escolhas_t9[(turma, slot)] = res_prof
                            
                            if slot == "3ª": 
                                st.markdown("<div style='text-align:center; font-size:9px; color:#ccc; margin:2px 0;'>— RECREIO —</div>", unsafe_allow_html=True)
                        
                        st.markdown('</div>', unsafe_allow_html=True)

                # --- 6. VALIDAÇÃO E SALVAMENTO ---
                st.divider()
                if st.button("💾 Validar e Salvar Horário", type="primary", use_container_width=True):
                    erros = []
                    
                    try: regiao_escola = padronizar(dt[dt['ESCOLA'] == esc_man].iloc[0]['REGIÃO'])
                    except: regiao_escola = ""

                    # Validação 1: Matriz
                    for t_info in turmas_alvo_info:
                        tn, ts = t_info['nome'], t_info['serie']
                        curr = dc[dc['SÉRIE/ANO'] == ts]
                        p_edit = [escolhas_t9[(tn, s)] for s in ["1ª", "2ª", "3ª", "4ª", "5ª"] if escolhas_t9[(tn, s)] != "---"]
                        tot = aulas_semanais_db.get(tn, []) + p_edit
                        
                        cnt = {}
                        for p in tot:
                            # Ignora se for PL na contagem de matriz
                            if str(p).startswith("PL-"): continue
                            
                            d = dp[dp['CÓDIGO'] == p]
                            if not d.empty:
                                cs = [padronizar_materia_interna(x.strip()) for x in str(d.iloc[0]['COMPONENTES']).split(',')]
                                for c in cs:
                                    if c in [padronizar_materia_interna(m) for m in MATERIAS_ESPECIALISTAS]: cnt[c] = cnt.get(c, 0) + 1
                        
                        for _, i in curr.iterrows():
                            m = padronizar_materia_interna(i['COMPONENTE'])
                            mt = int(i['QTD_AULAS'])
                            if m in [padronizar_materia_interna(x) for x in MATERIAS_ESPECIALISTAS]:
                                if cnt.get(m, 0) > mt:
                                    erros.append(f"⛔ **Excesso ({tn}):** {m} ({cnt.get(m,0)}/{mt})")

                    # Validação 2: Conflitos
                    for slot_v in ["1ª", "2ª", "3ª", "4ª", "5ª"]:
                        # Local
                        ps = [escolhas_t9[(t['nome'], slot_v)] for t in turmas_alvo_info if escolhas_t9[(t['nome'], slot_v)] != "---"]
                        # Remove PLs da validação de duplicidade LOCAL (pois PL é tratado na aba 10, aqui focamos em aula)
                        # Mas se o professor estiver dando 2 AULAS ao mesmo tempo, é erro.
                        ps_aula = [p for p in ps if not str(p).startswith("PL-")]
                        
                        dups = set([x for x in ps_aula if ps_aula.count(x) > 1])
                        for d in dups: erros.append(f"❌ **Duplicidade Local:** {d} em duas turmas na {slot_v} aula.")
                        
                        # Externo (Rede) - Checa tanto AULA quanto PL em outras escolas
                        for t_info in turmas_alvo_info:
                            p_chk = escolhas_t9[(t_info['nome'], slot_v)]
                            if p_chk == "---" or str(p_chk).startswith("PL-"): continue
                            
                            prof_id_chk = extrair_id_real(p_chk)
                            
                            # Valida Região
                            dp_chk = dp[dp['CÓDIGO'] == prof_id_chk]
                            if not dp_chk.empty:
                                r_chk = padronizar(dp_chk.iloc[0]['REGIÃO'])
                                pode, _ = verificar_compatibilidade_regiao(r_chk, regiao_escola)
                                if not pode: erros.append(f"🌍 **Região:** {p_chk} ({r_chk}) inválido aqui.")
                            
                            if not dh_conflito.empty:
                                # Verifica conflitos considerando ID real (para pegar conflito com PL também)
                                conf = dh_conflito[dh_conflito[slot_v].apply(extrair_id_real) == prof_id_chk]
                                for _, r_c in conf.iterrows():
                                    tipo = "PL" if str(r_c[slot_v]).startswith("PL-") else "Aula"
                                    erros.append(f"⛔ **Rede:** {p_chk} já tem {tipo} na {r_c['ESCOLA']} ({slot_v} aula).")

                    if erros:
                        st.error("### 🛑 SALVAMENTO BLOQUEADO")
                        for e in sorted(list(set(erros))): st.write(e)
                        st.stop()
                    else:
                        with st.spinner("Salvando..."):
                            novas = []
                            for t in turmas_alvo_info:
                                ln = {"ESCOLA": esc_man, "TURMA": t['nome'], "TURNO": turno_man, "DIA": dia_man}
                                for s in ["1ª", "2ª", "3ª", "4ª", "5ª"]: ln[s] = escolhas_t9[(t['nome'], s)]
                                novas.append(ln)
                            
                            # Remove dados antigos (apenas do banco de aulas - dh)
                            if not dh.empty:
                                mask_rm = (dh['ESCOLA'] == esc_man) & \
                                          (dh['DIA'].apply(padronizar) == dia_norm_man) & \
                                          (dh['TURNO'] == turno_man)
                                dh = dh[~mask_rm]
                            
                            dh = pd.concat([dh, pd.DataFrame(novas)], ignore_index=True)
                            
                            # Salva passando dpl para não perder os PLs
                            salvar_seguro(dt, dc, dp, dd, da, dh, dpl)
                            st.success("✅ Horário salvo com sucesso!")
                            time.sleep(1)
                            st.rerun()
# ==========================================
# ABA 10: GESTÃO DE PL (FINAL - CORREÇÃO DE SINTAXE)
# ==========================================
with t10:
    st.markdown("### 📘 Gestão de PL (Planejamento por Área)")
    
    if dt.empty or dp.empty: 
        st.warning("⚠️ Carregue Turmas e Professores primeiro.")
    else:
        # --- 1. FILTROS ---
        c1, c2, c3, c4 = st.columns(4)
        with c1: e_pl = st.selectbox("Escola", sorted(dt['ESCOLA'].unique()), key="pl_e_v15")
        with c2: d_pl = st.selectbox("Dia", DIAS_SEMANA, key="pl_d_v15")
        with c3: 
            trns = dt[dt['ESCOLA'] == e_pl]['TURNO'].unique()
            t_pl = st.selectbox("Turno", sorted(trns), key="pl_t_v15") if len(trns) > 0 else None
        with c4: f_pl = st.selectbox("Componente", MATERIAS_ESPECIALISTAS, key="pl_f_v15")

        if t_pl and f_pl:
            st.divider()
            dn = padronizar(d_pl)
            comp_alvo = padronizar_materia_interna(f_pl)

            # --- 2. FILTRAR PROFESSORES ---
            def valida_prof(row):
                escolas = [padronizar(e.strip()) for e in str(row['ESCOLAS_ALOCADAS']).split(',')]
                mats = [padronizar_materia_interna(m.strip()) for m in str(row['COMPONENTES']).split(',')]
                return (padronizar(e_pl) in escolas) and (comp_alvo in mats)

            df_profs_area = dp[dp.apply(valida_prof, axis=1)]
            
            if df_profs_area.empty:
                st.info(f"🚫 Nenhum professor de {f_pl} alocado nesta escola.")
            else:
                profs_lista = df_profs_area.to_dict('records')
                st.success(f"👥 Editando PL de **{len(profs_lista)}** professores.")

                # --- 3. MAPEAMENTO DE AULAS ---
                ocupacao_aula = {}
                if not dh.empty:
                    msk = (dh['TURNO'] == t_pl) & (dh['DIA'].apply(padronizar) == dn)
                    for _, row in dh[msk].iterrows():
                        esc_aula = row['ESCOLA']
                        nm_turma = row['TURMA']
                        aviso = nm_turma if esc_aula == e_pl else f"{nm_turma} ({esc_aula})"
                        
                        for s in ["1ª", "2ª", "3ª", "4ª", "5ª"]:
                            if row[s] and row[s] != "---" and not str(row[s]).startswith("PL-"):
                                cid = extrair_id_real(row[s])
                                if cid not in ocupacao_aula: ocupacao_aula[cid] = {}
                                ocupacao_aula[cid][s] = aviso

                # --- 4. CARREGAMENTO POR CÉLULA ---
                mapa_pl_por_id = {} 
                if not dpl.empty:
                    msk_pl = (dpl['ESCOLA'] == e_pl) & (dpl['TURNO'] == t_pl) & (dpl['DIA'].apply(padronizar) == dn)
                    df_pl_filt = dpl[msk_pl]
                    
                    for _, r in df_pl_filt.iterrows():
                        for s in ["1ª", "2ª", "3ª", "4ª", "5ª"]:
                            valor_celula = str(r[s]).strip()
                            if valor_celula.startswith("PL-"):
                                id_extraido = extrair_id_real(valor_celula) 
                                if id_extraido not in mapa_pl_por_id:
                                    mapa_pl_por_id[id_extraido] = {}
                                mapa_pl_por_id[id_extraido][s] = valor_celula

                # --- 5. RENDERIZAR GRID ---
                cols_head = st.columns([2, 1, 1, 1, 1, 1])
                cols_head[0].markdown("**Professor**")
                
                # --- CORREÇÃO AQUI ---
                for i, s in enumerate(["1ª", "2ª", "3ª", "4ª", "5ª"]): 
                    cols_head[i+1].markdown(f"**{s}**")
                # ---------------------
                
                st.divider()

                chaves_widgets = {} 

                for p in profs_lista:
                    cod_orig = p['CÓDIGO']
                    cod_limpo = extrair_id_real(cod_orig)
                    nome_simples = str(p['NOME']).strip()
                    
                    est = gerar_estilo_professor_dinamico(cod_orig)
                    
                    cols = st.columns([2, 1, 1, 1, 1, 1])
                    cols[0].markdown(f"<div style='border-left:5px solid {est['bg']}; padding-left:5px;'><b>{nome_simples}</b><br><small>{cod_orig}</small></div>", unsafe_allow_html=True)
                    
                    # --- CORREÇÃO AQUI TAMBÉM (LOOP DE COLUNAS) ---
                    for i, slot in enumerate(["1ª", "2ª", "3ª", "4ª", "5ª"]):
                    # ----------------------------------------------
                        with cols[i+1]:
                            # 1. AULA
                            info_aula = ocupacao_aula.get(cod_limpo, {}).get(slot)
                            if info_aula:
                                st.markdown(f"<div style='background:#eee; padding:5px; text-align:center; font-size:0.7em; color:#555;'>AULA<br><b>{info_aula}</b></div>", unsafe_allow_html=True)
                            else:
                                # 2. PL CHECKBOX (Usa ID para buscar estado)
                                val_banco = mapa_pl_por_id.get(cod_limpo, {}).get(slot, "")
                                ja_tem_pl = str(val_banco).startswith("PL-")
                                
                                k_chk = f"chk_pl_v15_{cod_limpo}_{slot}_{dn}_{t_pl}"
                                chaves_widgets[(cod_orig, slot)] = k_chk 
                                
                                checked = st.checkbox("PL", value=ja_tem_pl, key=k_chk, label_visibility="collapsed")
                                
                                if checked:
                                    st.markdown(f"<div style='text-align:center; margin-top:-18px;'><span style='background:{est['bg']}; color:{est['text']}; padding:2px 5px; border-radius:4px; font-size:0.8em;'>PL</span></div>", unsafe_allow_html=True)
                                else:
                                    st.markdown("<div style='text-align:center; margin-top:-18px; color:#ddd;'>-</div>", unsafe_allow_html=True)
                    st.markdown("---")

                # --- 6. SALVAMENTO (COM NOME + CÓDIGO) ---
                if st.button("💾 GRAVAR ALTERAÇÕES", type="primary", use_container_width=True):
                    with st.status("Processando...", expanded=True) as status:
                        
                        lista_novos = []
                        professores_na_tela_ids = set() 
                        contagem_pl = 0

                        for p in profs_lista:
                            cod_orig = p['CÓDIGO']
                            cod_limpo = extrair_id_real(cod_orig)
                            nome_prof = str(p['NOME']).strip()
                            
                            # ID ÚNICO PARA O BANCO
                            nome_unico_banco = f"{nome_prof} ({cod_orig})"
                            
                            professores_na_tela_ids.add(nome_unico_banco)
                            
                            row = {
                                "ESCOLA": e_pl,
                                "COMPONENTE": f_pl,
                                "PROFESSOR": nome_unico_banco, 
                                "TURMA": "PL",
                                "TURNO": t_pl,
                                "DIA": d_pl
                            }
                            
                            for s in ["1ª", "2ª", "3ª", "4ª", "5ª"]:
                                if ocupacao_aula.get(cod_limpo, {}).get(s):
                                    row[s] = "---"
                                else:
                                    k_chk = chaves_widgets.get((cod_orig, s))
                                    if k_chk and st.session_state.get(k_chk, False):
                                        row[s] = f"PL-{cod_orig}"
                                        contagem_pl += 1
                                    else:
                                        row[s] = "---"
                            
                            lista_novos.append(row)
                        
                        df_novos = pd.DataFrame(lista_novos)
                        
                        status.write(f"📊 Detectados {contagem_pl} marcações de PL.")

                        if not dpl.empty:
                            status.write("🧹 Atualizando registros...")
                            
                            if 'PROFESSOR' in dpl.columns:
                                # REMOÇÃO SEGURA (SEM PARÊNTESES ANINHADOS COMPLEXOS)
                                m_esc = dpl['ESCOLA'] == e_pl
                                m_trn = dpl['TURNO'] == t_pl
                                m_dia = dpl['DIA'].apply(padronizar) == dn
                                m_prf = dpl['PROFESSOR'].isin(professores_na_tela_ids)
                                
                                condicao_remover = m_esc & m_trn & m_dia & m_prf
                                dpl = dpl[~condicao_remover]
                            else:
                                # Fallback
                                m_esc = dpl['ESCOLA'] == e_pl
                                m_trn = dpl['TURNO'] == t_pl
                                m_dia = dpl['DIA'].apply(padronizar) == dn
                                m_tur = dpl['TURMA'] == 'PL'
                                
                                condicao_remover = m_esc & m_trn & m_dia & m_tur
                                dpl = dpl[~condicao_remover]

                        if not df_novos.empty:
                            dpl = pd.concat([dpl, df_novos], ignore_index=True)
                        
                        status.write("☁️ Enviando para Google Sheets...")
                        salvar_seguro(dt, dc, dp, dd, da, dh, dpl)
                        
                        status.update(label=f"✅ Salvo! {contagem_pl} PLs registrados.", state="complete", expanded=False)
                        time.sleep(1)
                        st.rerun()

# ==========================================
# ABA 11: VISÃO POR COMPONENTE/PROFESSOR
# ==========================================
with t11:
    st.markdown("### 🧮 Horário e PL por Componente/Professor")
    
    if dt.empty or dp.empty:
        st.warning("⚠️ Carregue Turmas e Professores primeiro.")
    elif dh.empty and dpl.empty:
        st.info("✨ Ainda não há horários ou PLs registrados.")
    else:
        # --- 1. FILTROS BÁSICOS ---
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            escolas_disp = sorted(dt['ESCOLA'].unique())
            default_esc = escolas_disp[0:1] if escolas_disp else []
            escolas_res = st.multiselect(
                "🏢 Escolas",
                escolas_disp,
                default=default_esc,
                key="res_escs_t11"
            )
            st.caption(
                "Dica: selecione **duas ou mais escolas** quando o mesmo componente "
                "estiver dividido entre unidades diferentes. Os cards mostrarão a turma "
                "junto com o nome da escola para facilitar a leitura."
            )
        with c2:
            dia_res = st.selectbox("📆 Dia", ["Todos"] + DIAS_SEMANA, key="res_dia_t11")
        with c3:
            if escolas_res:
                turnos_disp = dt[dt['ESCOLA'].isin(escolas_res)]['TURNO'].unique()
                turno_res = st.selectbox(
                    "☀️ Turno",
                    ["Todos"] + sorted(turnos_disp),
                    key="res_trn_t11"
                ) if len(turnos_disp) > 0 else "Todos"
            else:
                turno_res = "Todos"
        with c4:
            comp_res = st.selectbox(
                "📚 Componente",
                ["Todos"] + MATERIAS_ESPECIALISTAS,
                key="res_comp_t11"
            )

        # --- MODO DE EXIBIÇÃO (CÓDIGO / NOME / ETC) ---
        opcoes_vis = [
            "Apenas Código", "Nome do Professor", "Matéria/Componente",
            "Nome + Matéria", "Código + Nome", "Código + Componente"
        ]
        modo_vis = st.radio(
            "Exibir professor como:",
            opcoes_vis,
            horizontal=True,
            key="modo_vis_t11"
        )

        # Mapas auxiliares
        map_nome = dict(zip(dp['CÓDIGO'], dp['NOME']))
        map_comp = dict(zip(dp['CÓDIGO'], dp['COMPONENTES']))

        def componentes_prof(cod):
            """Retorna lista de componentes normalizados de um professor."""
            comps_raw = str(map_comp.get(cod, "")).split(',')
            return [padronizar_materia_interna(c.strip()) for c in comps_raw if c.strip()]

        def formatar_prof_exibicao(codigo):
            if not codigo or codigo == "---":
                return "---"
            nome = map_nome.get(codigo, codigo)
            mat = map_comp.get(codigo, "?")
            partes = nome.split()
            if len(partes) > 1:
                nome_curto = partes[0] + " " + partes[-1]
            else:
                nome_curto = nome

            if modo_vis == "Apenas Código":
                return codigo
            if modo_vis == "Nome do Professor":
                return nome_curto
            if modo_vis == "Matéria/Componente":
                return mat
            if modo_vis == "Nome + Matéria":
                return f"{nome} ({mat})"
            if modo_vis == "Código + Nome":
                return f"{codigo} - {nome}"
            if modo_vis == "Código + Componente":
                return f"{codigo} ({mat})"
            return codigo

        comp_alvo_norm = padronizar_materia_interna(comp_res) if comp_res != "Todos" else None

        def prof_passa_filtro_comp(cod_real):
            if not comp_alvo_norm:
                return True
            return comp_alvo_norm in (componentes_prof(cod_real) or [])

        if not escolas_res:
            st.info("Nenhuma escola selecionada. Escolha ao menos uma no filtro de escolas para visualizar os cards de horário/PL.")

        # --- BOTÃO DE PDF (VISÃO POR PROFESSOR, IGUAL A ESTE PAINEL) ---
        if escolas_res and (not dh.empty or not dpl.empty):
            dia_filtro_pdf = "Todos" if dia_res == "Todos" else dia_res
            with st.container():
                c_pdf1, c_pdf2 = st.columns([3, 1.5])
                with c_pdf2:
                    st.markdown("<div style='height: 4px'></div>", unsafe_allow_html=True)
                    if st.button("📄 Baixar PDF (Visão por Professor)", type="primary", use_container_width=True, key="btn_pdf_t11"):
                        with st.spinner("Gerando documento visual (professores)..."):
                            # Monta ocupação por dia/professor/slot, igual aos cards
                            ocupacao_por_dia = {}

                            # Dataframes base para o conjunto de escolas selecionadas
                            df_h_pdf = dh[dh['ESCOLA'].isin(escolas_res)].copy() if not dh.empty else None
                            df_pl_pdf = dpl[dpl['ESCOLA'].isin(escolas_res)].copy() if not dpl.empty else None

                            dias_pdf = [dia_filtro_pdf] if dia_filtro_pdf != "Todos" else DIAS_SEMANA

                            comp_alvo_norm_pdf = padronizar_materia_interna(comp_res) if comp_res != "Todos" else None

                            def prof_passa_filtro_comp_pdf(cod_real):
                                if not comp_alvo_norm_pdf:
                                    return True
                                return comp_alvo_norm_pdf in (componentes_prof(cod_real) or [])

                            for dia_lbl in dias_pdf:
                                dn_pdf = padronizar(dia_lbl)
                                ocupacao = {}

                                def garantir_prof_pdf(cod):
                                    if cod not in ocupacao:
                                        ocupacao[cod] = {s: {"aulas": set(), "pl": False} for s in ["1ª", "2ª", "3ª", "4ª", "5ª"]}

                                # Aulas
                                if df_h_pdf is not None:
                                    dfh = df_h_pdf[df_h_pdf['DIA'].apply(padronizar) == dn_pdf]
                                    if turno_res != "Todos":
                                        dfh = dfh[dfh['TURNO'] == turno_res]

                                    for _, row in dfh.iterrows():
                                        turma = str(row.get("TURMA", "")).strip()
                                        esc_aula = str(row.get("ESCOLA", "")).strip()
                                        for slot in ["1ª", "2ª", "3ª", "4ª", "5ª"]:
                                            val = row.get(slot)
                                            if not val or val == "---":
                                                continue
                                            texto = str(val).strip()
                                            cod_real = extrair_id_real(texto)
                                            if cod_real == "---":
                                                continue
                                            if not prof_passa_filtro_comp_pdf(cod_real):
                                                continue

                                            garantir_prof_pdf(cod_real)
                                            if texto.startswith("PL-"):
                                                ocupacao[cod_real][slot]["pl"] = True
                                            else:
                                                if turma:
                                                    if len(escolas_res) > 1 and esc_aula:
                                                        label_turma = f"{turma} ({esc_aula})"
                                                    else:
                                                        label_turma = turma
                                                    ocupacao[cod_real][slot]["aulas"].add(label_turma)

                                # PLs puros
                                if df_pl_pdf is not None:
                                    dfp = df_pl_pdf[df_pl_pdf['DIA'].apply(padronizar) == dn_pdf]
                                    if turno_res != "Todos":
                                        dfp = dfp[dfp['TURNO'] == turno_res]

                                    for _, row in dfp.iterrows():
                                        for slot in ["1ª", "2ª", "3ª", "4ª", "5ª"]:
                                            texto = str(row.get(slot) or "").strip()
                                            if not texto.startswith("PL-"):
                                                continue
                                            cod_real = extrair_id_real(texto)
                                            if cod_real == "---":
                                                continue
                                            if not prof_passa_filtro_comp_pdf(cod_real):
                                                continue
                                            garantir_prof_pdf(cod_real)
                                            ocupacao[cod_real][slot]["pl"] = True

                                if not ocupacao:
                                    continue

                                # Converte para texto final por slot
                                ocup_texto = {}
                                for cod, slots_info in ocupacao.items():
                                    ocup_texto[cod] = {}
                                    for slot in ["1ª", "2ª", "3ª", "4ª", "5ª"]:
                                        aulas = sorted(list(slots_info[slot]["aulas"]))
                                        tem_pl = slots_info[slot]["pl"]
                                        if aulas:
                                            texto_slot = " / ".join(aulas)
                                        elif tem_pl:
                                            texto_slot = "PL"
                                        else:
                                            texto_slot = "---"
                                        ocup_texto[cod][slot] = texto_slot

                                if ocup_texto:
                                    ocupacao_por_dia[dia_lbl] = ocup_texto

                            nome_pdf = " / ".join(escolas_res) if len(escolas_res) > 1 else escolas_res[0]
                            desc_turno = None
                            if turno_res != "Todos":
                                desc_turno = str(turno_res)

                            pdf_bytes = gerar_pdf_prof_pl(
                                ocupacao_por_dia,
                                map_nome,
                                map_comp,
                                modo_vis,
                                nome_pdf,
                                desc_turno,
                            )
                            nome_esc_arquivo = "MULTI_ESCOLAS" if len(escolas_res) > 1 else escolas_res[0].replace(" ", "_")
                            nome_arquivo = f"Horario_PL_Prof_{nome_esc_arquivo}_{dia_filtro_pdf}.pdf"
                            st.download_button(
                                label="📥 Clique para Salvar PDF (Professores)",
                                data=pdf_bytes,
                                file_name=nome_arquivo,
                                mime="application/pdf",
                                key="dl_pdf_t11",
                            )

        # Dataframes base por conjunto de escolas (para visão por professor)
        df_h_base = dh[dh['ESCOLA'].isin(escolas_res)].copy() if not dh.empty else None
        df_pl_base = dpl[dpl['ESCOLA'].isin(escolas_res)].copy() if not dpl.empty else None

        dias_para_mostrar = [dia_res] if dia_res != "Todos" else DIAS_SEMANA

        houve_dados = False

        for dia_label in dias_para_mostrar:
            dn = padronizar(dia_label)

            # --- 2. MONTAR OCUPAÇÃO POR PROFESSOR (CARDS) PARA O DIA ---
            ocupacao = {}

            def garantir_prof(cod):
                if cod not in ocupacao:
                    ocupacao[cod] = {s: {"aulas": set(), "pl": False} for s in ["1ª", "2ª", "3ª", "4ª", "5ª"]}

            # AULAS (dh)
            if df_h_base is not None:
                df_h = df_h_base[df_h_base['DIA'].apply(padronizar) == dn]
                if turno_res != "Todos":
                    df_h = df_h[df_h['TURNO'] == turno_res]

                for _, row in df_h.iterrows():
                    turma = str(row.get("TURMA", "")).strip()
                    esc_aula = str(row.get("ESCOLA", "")).strip()
                    for slot in ["1ª", "2ª", "3ª", "4ª", "5ª"]:
                        val = row.get(slot)
                        if not val or val == "---":
                            continue
                        texto = str(val).strip()
                        cod_real = extrair_id_real(texto)
                        if cod_real == "---":
                            continue
                        if not prof_passa_filtro_comp(cod_real):
                            continue

                        garantir_prof(cod_real)
                        if texto.startswith("PL-"):
                            ocupacao[cod_real][slot]["pl"] = True
                        else:
                            if turma:
                                # Se houver mais de uma escola selecionada, exibe também o nome da escola
                                if len(escolas_res) > 1 and esc_aula:
                                    label_turma = f"{turma} ({esc_aula})"
                                else:
                                    label_turma = turma
                                ocupacao[cod_real][slot]["aulas"].add(label_turma)

            # PLs (dpl)
            if df_pl_base is not None:
                df_pl = df_pl_base[df_pl_base['DIA'].apply(padronizar) == dn]
                if turno_res != "Todos":
                    df_pl = df_pl[df_pl['TURNO'] == turno_res]

                for _, row in df_pl.iterrows():
                    for slot in ["1ª", "2ª", "3ª", "4ª", "5ª"]:
                        texto = str(row.get(slot) or "").strip()
                        if not texto.startswith("PL-"):
                            continue
                        cod_real = extrair_id_real(texto)
                        if cod_real == "---":
                            continue
                        if not prof_passa_filtro_comp(cod_real):
                            continue
                        garantir_prof(cod_real)
                        ocupacao[cod_real][slot]["pl"] = True

            # --- 3. RENDER POR DIA (CARDS) ---
            if not ocupacao:
                continue

            houve_dados = True
            if turno_res != "Todos":
                st.markdown(f"#### 📅 {dia_label} - Turno: {turno_res}")
            else:
                st.markdown(f"#### 📅 {dia_label} - Todos os turnos")

            # Ordena por nome e depois por código
            def nome_sort(cod):
                return str(map_nome.get(cod, cod))

            profs_ordenados = sorted(ocupacao.keys(), key=lambda c: (nome_sort(c).lower(), c))

            cols = st.columns(3)
            for i, cod in enumerate(profs_ordenados):
                titulo_prof = formatar_prof_exibicao(cod)
                comps = str(map_comp.get(cod, "")).strip()
                est = gerar_estilo_professor_dinamico(cod)

                with cols[i % 3]:
                    html = f'<div class="turma-card-moldura"><div class="turma-titulo">👨‍🏫 {titulo_prof}<br/><small>{comps}</small></div>'

                    for slot in ["1ª", "2ª", "3ª", "4ª", "5ª"]:
                        aulas = sorted(list(ocupacao[cod][slot]["aulas"]))
                        tem_pl = ocupacao[cod][slot]["pl"]

                        if aulas:
                            texto_slot = " / ".join(aulas)
                        elif tem_pl:
                            texto_slot = "PL"
                        else:
                            texto_slot = "---"

                        # Cor: usa a cor do professor quando ocupado; neutro quando vazio
                        if texto_slot == "---":
                            bg = "#f8f9fa"
                            tx = "#abb6c2"
                            br = "#e9ecef"
                        else:
                            bg = est["bg"]
                            tx = est["text"]
                            br = est["border"]

                        html += f'''
                        <div class="slot-aula-container" style="background-color: {bg}; color: {tx}; border: 1px solid {br};">
                            <div class="slot-label" style="color: {tx}; opacity: 0.6;">{slot}</div>
                            <div style="flex-grow: 1; text-align: center; font-weight: 800; font-size: 0.95em; letter-spacing: 0.5px;">
                                {texto_slot}
                            </div>
                        </div>'''

                        if slot == "3ª":
                            html += '<div style="text-align:center; padding: 2px 0; border-top: 1px dashed #ccc; border-bottom: 1px dashed #ccc; margin: 2px 0;"><span style="font-size: 9px; font-weight: bold; color:#999; letter-spacing: 2px;">RECREIO</span></div>'

                    html += "</div>"
                    st.markdown(html, unsafe_allow_html=True)

            st.divider()

        if not houve_dados:
            st.info("Nenhum horário ou PL encontrado para os filtros selecionados.")
