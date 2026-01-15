import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import random
import io
import xlsxwriter
import time
from datetime import datetime

# ==========================================
# 1. CONFIGURAÇÕES
# ==========================================

MATERIAS_ESPECIALISTAS = [
    "Arte (Infantil)",
    "Arte (Fund.)",
    "Ed. Física (Infantil)",
    "Ed. Física (Fund.)",
    "Ensino Religioso",
    "Língua Inglesa",
    "Contação de História" 
]

REGIOES_DISPONIVEIS = ["Fundão", "Praia Grande"]

# ==========================================
# 2. BANCO DE DADOS (BLINDADO)
# ==========================================

conn = st.connection("gsheets", type=GSheetsConnection)

def definir_hora_atual():
    st.session_state['hora_exata_db'] = datetime.now().strftime("%d/%m/%Y às %H:%M:%S")

def ler_planilha_segura(aba):
    tentativas = 0
    max_tentativas = 5
    while tentativas < max_tentativas:
        try:
            return conn.read(worksheet=aba, ttl=5) 
        except Exception as e:
            erro = str(e)
            if "429" in erro or "Quota exceeded" in erro:
                tentativas += 1
                tempo_espera = 2 * tentativas
                st.toast(f"⏳ Google ocupado. Aguardando {tempo_espera}s...", icon="⚠️")
                time.sleep(tempo_espera)
            else:
                raise e 
    return pd.DataFrame() 

def carregar_dados():
    try:
        df_turmas = ler_planilha_segura("Turmas")
        df_curriculo = ler_planilha_segura("Curriculo")
        df_professores = ler_planilha_segura("Professores")
        df_dias = ler_planilha_segura("ConfigDias")
        
        if df_turmas.empty: df_turmas = pd.DataFrame(columns=["Escola", "Nivel", "NomeTurma", "Turno", "AnoBase", "Regiao"])
        if df_curriculo.empty: df_curriculo = pd.DataFrame(columns=["AnoBase", "Materia", "Quantidade"])
        if df_professores.empty: df_professores = pd.DataFrame(columns=["Codigo", "Nome", "Componentes", "CH_Aulas", "Qtd_PL", "Escolas", "Regiao"])
        if df_dias.empty: df_dias = pd.DataFrame(columns=["AnoBase", "DiaSemana"])
        
        df_turmas = df_turmas.fillna("")
        df_curriculo = df_curriculo.fillna(0)
        df_professores = df_professores.fillna("")
        df_dias = df_dias.fillna("")
        
        return df_turmas, df_curriculo, df_professores, df_dias

    except Exception as e:
        st.error(f"Erro ao carregar dados: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def salvar_geral(df_t, df_c, df_p, df_d):
    try:
        with st.spinner('Salvando no Banco de Dados...'):
            conn.update(worksheet="Turmas", data=df_t)
            conn.update(worksheet="Curriculo", data=df_c)
            conn.update(worksheet="Professores", data=df_p)
            conn.update(worksheet="ConfigDias", data=df_d)
            st.cache_data.clear()
            definir_hora_atual() 
            st.success("✅ Salvo com sucesso!")
            time.sleep(1)
            st.rerun()
    except Exception as e:
        if "429" in str(e):
            st.error("O Google bloqueou temporariamente. Espere 1 minuto.")
        else:
            st.error(f"Erro ao salvar: {e}")

# --- CRUD RAPIDO ---

def adicionar_turma_rapido(dado):
    dt, dc, dp, dd = carregar_dados()
    dt = pd.concat([dt, pd.DataFrame([dado])], ignore_index=True)
    salvar_geral(dt, dc, dp, dd)

def salvar_curriculo_completo(ano, dia_semana, dict_quantidades):
    dt, dc, dp, dd = carregar_dados()
    dd = dd[dd['AnoBase'] != ano]
    dd = pd.concat([dd, pd.DataFrame([{"AnoBase": ano, "DiaSemana": dia_semana}])], ignore_index=True)
    dc = dc[dc['AnoBase'] != ano]
    novas = [{"AnoBase": ano, "Materia": m, "Quantidade": q} for m, q in dict_quantidades.items() if q > 0]
    if novas: dc = pd.concat([dc, pd.DataFrame(novas)], ignore_index=True)
    salvar_geral(dt, dc, dp, dd)

def adicionar_professor_rapido(dado):
    dt, dc, dp, dd = carregar_dados()
    dp = pd.concat([dp, pd.DataFrame([dado])], ignore_index=True)
    salvar_geral(dt, dc, dp, dd)

# ==========================================
# 3. ALGORITMO
# ==========================================

def normalizar_texto(texto):
    return str(texto).strip().lower()

def carregar_objetos_professores(df_prof):
    lista_profs = []
    for _, row in df_prof.iterrows():
        materias = [m.strip() for m in str(row['Componentes']).split(',')]
        escolas_norm = [normalizar_texto(e) for e in str(row['Escolas']).split(',')]
        regiao_prof = str(row['Regiao']).strip() 
        try: ch_limite = int(row['CH_Aulas'])
        except: ch_limite = 999 

        for mat in materias:
            if mat in MATERIAS_ESPECIALISTAS:
                lista_profs.append({
                    'id': f"{row['Codigo']} - {row['Nome']}", 
                    'codigo': row['Codigo'],
                    'nome': row['Nome'],
                    'materia': mat,
                    'escolas_norm': escolas_norm,
                    'regiao': regiao_prof,
                    'max_aulas': ch_limite, 
                    'aulas_atribuidas': 0,
                    'horarios_ocupados': []
                })
    return lista_profs

def resolver_horario_grade(turmas_do_dia, curriculo_df, lista_professores):
    for p in lista_professores:
        p['horarios_ocupados'] = []

    aulas_pendentes = []
    for turma in turmas_do_dia:
        curr_turma = curriculo_df[curriculo_df['AnoBase'] == turma['ano']]
        aulas_turma = []
        for _, row in curr_turma.iterrows():
            aulas_turma.extend([row['Materia']] * int(row['Quantidade']))
        
        while len(aulas_turma) < 5: aulas_turma.append("---")
        aulas_turma = aulas_turma[:5]
        
        for mat in aulas_turma:
            aulas_pendentes.append({
                'turma': turma,
                'materia': mat,
                'prioridade': 0 if mat == "---" else 1 
            })

    aulas_pendentes.sort(key=lambda x: x['prioridade'], reverse=True)
    MAX_TENTATIVAS = 5000 
    
    for tentativa in range(MAX_TENTATIVAS): 
        grade_tentativa = {t['nome_turma']: [None]*5 for t in turmas_do_dia}
        professores_temp = []
        for p in lista_professores:
            prof = p.copy()
            prof['horarios_ocupados'] = list(p['horarios_ocupados']) 
            prof['escolas_norm'] = list(p['escolas_norm'])
            professores_temp.append(prof)
        
        sucesso_tentativa = True
        motivo_falha_atual = ""
        
        random.shuffle(aulas_pendentes)
        aulas_pendentes.sort(key=lambda x: x['prioridade'], reverse=True) 

        for aula_info in aulas_pendentes:
            turma_obj = aula_info['turma']
            materia = aula_info['materia']
            nome_turma = turma_obj['nome_turma']
            escola_norm = normalizar_texto(turma_obj['escola_real'])
            regiao_turma = turma_obj['regiao_real']
            alocado = False
            
            slots_livres_turma = [i for i, val in enumerate(grade_tentativa[nome_turma]) if val is None]
            random.shuffle(slots_livres_turma) 
            
            analise_professores = [] 

            if materia == "---":
                if slots_livres_turma:
                    grade_tentativa[nome_turma][slots_livres_turma[0]] = "---"
                    alocado = True
            else:
                for slot in slots_livres_turma:
                    candidatos = []
                    for p in professores_temp:
                        if p['materia'] == materia:
                            motivo = []
                            ok = True
                            if slot in p['horarios_ocupados']: ok = False; motivo.append("Ocupado")
                            if p['aulas_atribuidas'] >= p['max_aulas']: ok = False; motivo.append("CH Max")
                            if p['regiao'] and p['regiao'] != regiao_turma: ok = False; motivo.append(f"Região")
                            if ok and escola_norm not in p['escolas_norm']: ok = False; motivo.append("Escola")
                            if ok: candidatos.append(p)
                            if tentativa == (MAX_TENTATIVAS - 1):
                                analise_professores.append(f"{p['nome']}: {','.join(motivo)}")
                    
                    if candidatos:
                        escolhido = random.choice(candidatos)
                        grade_tentativa[nome_turma][slot] = f"{materia}\n{escolhido['nome']}"
                        escolhido['horarios_ocupados'].append(slot)
                        escolhido['aulas_atribuidas'] += 1
                        alocado = True
                        break 
            
            if not alocado:
                sucesso_tentativa = False
                if tentativa == (MAX_TENTATIVAS - 1):
                    motivo_falha_atual = f"Falha '{materia}' em '{nome_turma}'.\n{ '; '.join(analise_professores[:3]) }"
                break 
        
        if sucesso_tentativa: return grade_tentativa, None
        if tentativa == (MAX_TENTATIVAS - 1): return None, motivo_falha_atual

    return None, "Impossível matematicamente."

# --- VISUAL PREVIEW ---
def criar_preview_com_recreio(df_dados):
    df = df_dados.copy()
    top = df.iloc[:3]
    bottom = df.iloc[3:]
    recreio = pd.DataFrame([["RECREIO"] * len(df.columns)], columns=df.columns)
    df_final = pd.concat([top, recreio, bottom]).reset_index(drop=True)
    df_final.index = ["1ª Aula", "2ª Aula", "3ª Aula", "RECREIO", "4ª Aula", "5ª Aula"]
    return df_final

# --- VISUAL EXCEL ---
def desenhar_tabela_escola(writer, nome_escola, dados_turnos):
    sheet_name = nome_escola[:30].replace("/","-")
    workbook = writer.book
    worksheet = workbook.add_worksheet(sheet_name)
    writer.sheets[sheet_name] = worksheet
    
    fmt_titulo_escola = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'font_size': 18, 'bg_color': '#4472C4', 'font_color': 'white', 'border': 1})
    fmt_subtitulo = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'font_size': 12, 'bg_color': '#D9E1F2', 'border': 1})
    fmt_header_turma = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'text_wrap': True, 'bg_color': '#E2EFDA', 'border': 1})
    fmt_celula = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'text_wrap': True, 'border': 1, 'font_size': 10})
    fmt_recreio = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'bg_color': '#F2F2F2', 'font_color': '#595959', 'border': 1})

    current_row = 0
    worksheet.merge_range(current_row, 0, current_row, 5, nome_escola, fmt_titulo_escola)
    current_row += 2 
    
    for titulo_bloco, df_grade in dados_turnos:
        if df_grade.empty: continue
        if isinstance(df_grade, dict): df = pd.DataFrame(df_grade)
        else: df = df_grade
            
        num_cols = len(df.columns)
        worksheet.merge_range(current_row, 0, current_row, num_cols, titulo_bloco, fmt_subtitulo)
        current_row += 1
        
        worksheet.write(current_row, 0, "Horário", fmt_header_turma)
        for col_idx, col_name in enumerate(df.columns):
            worksheet.write(current_row, col_idx + 1, col_name, fmt_header_turma)
            worksheet.set_column(col_idx + 1, col_idx + 1, 22) 
        current_row += 1
        
        for i in range(3):
            worksheet.write(current_row, 0, f"{i+1}ª Aula", fmt_celula)
            for col_idx, col_name in enumerate(df.columns):
                val = df.iloc[i][col_name]
                if val is None: val = ""
                worksheet.write(current_row, col_idx + 1, val, fmt_celula)
            current_row += 1
            
        worksheet.merge_range(current_row, 0, current_row, num_cols, "RECREIO", fmt_recreio)
        current_row += 1
        
        for i in range(3, 5):
            worksheet.write(current_row, 0, f"{i+1}ª Aula", fmt_celula)
            for col_idx, col_name in enumerate(df.columns):
                val = df.iloc[i][col_name]
                if val is None: val = ""
                worksheet.write(current_row, col_idx + 1, val, fmt_celula)
            current_row += 1
            
        current_row += 2
    worksheet.set_column(0, 0, 12)

# --- FUNÇÃO DE NORMALIZAÇÃO PARA O PAINEL DE VAGAS ---
def normalizar_nome_materia(nome):
    """Converte 'Arte (Infantil)' em 'Arte', etc."""
    nome_lower = nome.lower()
    if "arte" in nome_lower: return "Arte"
    if "física" in nome_lower or "fisica" in nome_lower: return "Educação Física"
    return nome # Retorna o nome original se não for desses dois

# ==========================================
# 4. INTERFACE GRÁFICA
# ==========================================
st.set_page_config(page_title="Gerador Escolar", layout="wide")
st.title("🎓 Gerador de Horários (Rede)")

if 'hora_exata_db' not in st.session_state:
    st.session_state['hora_exata_db'] = "Ainda não houve gravação."

dt, dc, dp, dd = carregar_dados()

# --- SIDEBAR ---
st.sidebar.markdown("### ☁️ Status")
hora_tela = st.session_state['hora_exata_db']
if "Ainda não" in hora_tela:
    st.sidebar.info(f"ℹ️ {hora_tela}")
else:
    st.sidebar.success(f"✅ Salvo em:\n**{hora_tela}**")

if st.sidebar.button("🔄 Forçar Atualização"):
    st.cache_data.clear()
    definir_hora_atual() 
    st.rerun()

st.sidebar.divider()
st.sidebar.caption("Infantil = Creche/Pré | Fund. = Fundamental")

# --- ABAS REORGANIZADAS (VAGAS É A PRIMEIRA) ---
t1, t2, t3, t4, t5 = st.tabs(["1. 📊 Quadro de Vagas", "2. Configuração", "3. Turmas", "4. Professores", "5. Gerar Grade"])

# --- ABA 1: QUADRO DE VAGAS UNIFICADO E FILTRADO ---
with t1:
    st.header("📊 Painel de Vagas e Alertas")
    
    if dt.empty or dc.empty:
        st.warning("Cadastre Turmas e Curículo primeiro.")
    else:
        # --- FILTROS NO TOPO ---
        c_filt1, c_filt2 = st.columns(2)
        
        # Filtro de Escola
        lista_escolas = sorted(dt['Escola'].unique().tolist())
        opcoes_filtro = ["Rede Completa"] + lista_escolas
        filtro_escola = c_filt1.selectbox("Filtrar por Escola:", opcoes_filtro)
        
        # Filtro de Matéria (Componente)
        # Cria lista de materias unificadas para o filtro
        materias_unificadas_filtro = sorted(list(set([normalizar_nome_materia(m) for m in MATERIAS_ESPECIALISTAS])))
        filtro_componente = c_filt2.multiselect("Filtrar por Componente:", materias_unificadas_filtro)

        # 1. CÁLCULO DA DEMANDA (UNIFICADA)
        demanda_total = {} 
        if filtro_escola == "Rede Completa": turmas_alvo = dt
        else: turmas_alvo = dt[dt['Escola'] == filtro_escola]

        for _, row_turma in turmas_alvo.iterrows():
            ano_turma = row_turma['AnoBase']
            curriculo_ano = dc[dc['AnoBase'] == ano_turma]
            for _, row_curr in curriculo_ano.iterrows():
                mat_orig = row_curr['Materia']
                qtd = int(row_curr['Quantidade'])
                
                # UNIFICAÇÃO AQUI
                mat_unificada = normalizar_nome_materia(mat_orig)
                
                if mat_unificada in demanda_total: demanda_total[mat_unificada] += qtd
                else: demanda_total[mat_unificada] = qtd
        
        # 2. CÁLCULO DA OFERTA (UNIFICADA)
        oferta_total = {}
        if not dp.empty:
            for _, row_prof in dp.iterrows():
                atende_escola = True
                if filtro_escola != "Rede Completa":
                    escolas_do_prof = str(row_prof['Escolas'])
                    if filtro_escola not in escolas_do_prof: atende_escola = False
                
                if atende_escola:
                    try: ch = int(row_prof['CH_Aulas'])
                    except: ch = 0
                    mats_prof = [m.strip() for m in str(row_prof['Componentes']).split(',')]
                    
                    # Evita somar a CH do mesmo professor duas vezes se ele dá "Arte Inf" e "Arte Fund"
                    materias_unificadas_professor = set()
                    for m in mats_prof:
                        if m in MATERIAS_ESPECIALISTAS:
                            materias_unificadas_professor.add(normalizar_nome_materia(m))
                    
                    for m_unif in materias_unificadas_professor:
                        if m_unif not in oferta_total: oferta_total[m_unif] = 0
                        oferta_total[m_unif] += ch

        # FILTRAGEM FINAL DOS DADOS PARA EXIBIÇÃO
        # Se usuário selecionou componentes, filtra aqui
        materias_para_exibir = materias_unificadas_filtro
        if filtro_componente:
            materias_para_exibir = filtro_componente

        # TOTAIS GERAIS (DA SELEÇÃO ATUAL)
        soma_nec = 0
        soma_oferta = 0
        for m in materias_para_exibir:
            soma_nec += demanda_total.get(m, 0)
            soma_oferta += oferta_total.get(m, 0)
        
        saldo_geral = soma_oferta - soma_nec

        # --- PAINEL DE MÉTRICAS ---
        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("Aulas Necessárias", soma_nec)
        col_m2.metric("Aulas Cadastradas", soma_oferta)
        col_m3.metric("Saldo de Aulas", saldo_geral, delta_color="normal")
        
        st.markdown("---")
        
        # --- ALERTA DETETIVE ---
        st.subheader("📍 Alertas de Escolas")
        alertas_encontrados = False
        escolas_para_checar = lista_escolas if filtro_escola == "Rede Completa" else [filtro_escola]
        
        for esc in escolas_para_checar:
            turmas_da_escola = dt[dt['Escola'] == esc]
            if turmas_da_escola.empty: continue
            
            necessidade_escola = set()
            for _, t in turmas_da_escola.iterrows():
                cur_t = dc[dc['AnoBase'] == t['AnoBase']]
                for _, c in cur_t.iterrows():
                    if int(c['Quantidade']) > 0: 
                        # Adiciona a necessidade UNIFICADA
                        necessidade_escola.add(normalizar_nome_materia(c['Materia']))
            
            professores_na_escola = dp[dp['Escolas'].str.contains(esc, na=False, regex=False)]
            
            for materia_nec_unif in necessidade_escola:
                # Se filtrou componente e este não está na lista, pula
                if filtro_componente and materia_nec_unif not in filtro_componente: continue

                tem_prof = False
                for _, p in professores_na_escola.iterrows():
                    # Verifica se o professor dá alguma matéria que normaliza para a necessidade
                    comps_prof = [m.strip() for m in str(p['Componentes']).split(',')]
                    for cp in comps_prof:
                        if normalizar_nome_materia(cp) == materia_nec_unif:
                            tem_prof = True
                            break
                    if tem_prof: break
                
                if not tem_prof:
                    alertas_encontrados = True
                    st.error(f"⚠️ **{esc}**: NENHUM professor de **{materia_nec_unif}** cadastrado!")

        if not alertas_encontrados: st.success("✅ Cobertura OK para os filtros selecionados.")
        st.markdown("---")

        col_calc, col_res = st.columns([1, 2])
        with col_calc:
            st.subheader("🧮 Calculadora")
            aulas_contrato = st.number_input("Média de aulas por contrato:", min_value=1, value=20) 

        with col_res:
            dados_tabela = []
            for mat in materias_para_exibir:
                qtd_aulas = demanda_total.get(mat, 0)
                # Mostra mesmo se for 0, se foi filtrado
                professores_necessarios = qtd_aulas / aulas_contrato
                ch_disponivel = oferta_total.get(mat, 0)
                saldo_aulas = ch_disponivel - qtd_aulas
                status = "✅ OK"
                if saldo_aulas < 0: status = f"❌ Faltam {abs(saldo_aulas)}"
                else: status = f"🔵 Sobram {saldo_aulas}"
                dados_tabela.append({"Matéria": mat, "Demanda": qtd_aulas, "Contratos Nec.": f"{professores_necessarios:.1f}", "CH Oferta": ch_disponivel, "Situação": status})
            
            if dados_tabela:
                df_vagas = pd.DataFrame(dados_tabela)
                st.dataframe(df_vagas, use_container_width=True)

# --- ABA 2: CONFIGURAÇÃO ---
with t2:
    st.markdown("### Configuração por Ano/Série")
    ano_sel = st.selectbox("Ano:", ["Berçário", "Creche I", "Creche II", "Creche III", "Pré I", "Pré II", "1º Ano", "2º Ano", "3º Ano", "4º Ano", "5º Ano"])
    dia_atual = "Segunda-feira"
    if not dd.empty:
        f = dd[dd['AnoBase'] == ano_sel]
        if not f.empty: dia_atual = f.iloc[0]['DiaSemana']
    dia_sel = st.selectbox("Dia Planejamento:", ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira"], index=["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira"].index(dia_atual))
    st.divider()
    with st.form("conf_curriculo"):
        col_inp = st.columns(3)
        qts = {}
        i=0
        for mat in MATERIAS_ESPECIALISTAS:
            with col_inp[i%3]:
                v = 0
                if not dc.empty:
                    f = dc[(dc['AnoBase']==ano_sel) & (dc['Materia']==mat)]
                    if not f.empty: v = int(f.iloc[0]['Quantidade'])
                qts[mat] = st.number_input(f"{mat}", 0, 5, v)
            i+=1
        if st.form_submit_button("💾 Salvar Configuração"):
            salvar_curriculo_completo(ano_sel, dia_sel, qts)

# --- ABA 3: TURMAS ---
with t3:
    st.markdown("### Cadastro de Turmas")
    with st.expander("➕ Adicionar Nova Turma (Formulário)", expanded=False):
        with st.form("nova_turma"):
            c1, c2 = st.columns(2)
            esc = c1.text_input("Escola")
            tnm = c2.text_input("Turma (Ex: A)")
            c3, c4, c5 = st.columns(3)
            trn = c3.selectbox("Turno", ["Matutino", "Vespertino"])
            regiao = c4.selectbox("Região", REGIOES_DISPONIVEIS)
            ano = c5.selectbox("Ano Base", ["Berçário", "Creche I", "Creche II", "Creche III", "Pré I", "Pré II", "1º Ano", "2º Ano", "3º Ano", "4º Ano", "5º Ano"])
            if st.form_submit_button("➕ Adicionar"):
                if not esc or not tnm: st.error("Preencha Escola e Turma!")
                else:
                    if any(x in ano for x in ["Creche", "Pré", "Berçário"]): nivel_auto = "Infantil"
                    else: nivel_auto = "Fundamental"
                    adicionar_turma_rapido({"Escola": esc, "NomeTurma": tnm, "Turno": trn, "AnoBase": ano, "Nivel": nivel_auto, "Regiao": regiao})
    
    st.markdown("---")
    st.write("### 📝 Editar ou Excluir Turmas")
    if not dt.empty:
        turmas_editadas = st.data_editor(dt, num_rows="dynamic", key="editor_turmas", use_container_width=True)
        if st.button("💾 SALVAR ALTERAÇÕES EM TURMAS", type="primary"):
            salvar_geral(turmas_editadas, dc, dp, dd)

# --- ABA 4: PROFESSORES ---
with t4:
    st.markdown("### Professores Especialistas")
    with st.expander("➕ Adicionar Novo Professor (Formulário)", expanded=False):
        lista_escolas_existentes = []
        if not dt.empty: lista_escolas_existentes = sorted(dt['Escola'].unique().tolist())
        with st.form("novo_prof"):
            c_cod, c_nom = st.columns([1, 3])
            cod = c_cod.text_input("Código")
            nm = c_nom.text_input("Nome")
            c_ch, c_pl, c_reg = st.columns(3)
            ch = c_ch.number_input("CH Aulas (Em sala)", 1, 30, 13)
            pl = c_pl.number_input("PLs", 0, 10, 7)
            reg_prof = c_reg.selectbox("Região de Atuação", REGIOES_DISPONIVEIS)
            st.markdown("---")
            if lista_escolas_existentes: escolas_sel = st.multiselect("Escolas Específicas:", lista_escolas_existentes)
            else: escolas_sel = []
            st.markdown("---")
            cps = st.multiselect("Matérias:", MATERIAS_ESPECIALISTAS)
            if st.form_submit_button("💾 Salvar Professor"):
                if cps and nm and escolas_sel:
                    adicionar_professor_rapido({"Codigo": cod, "Nome": nm, "Componentes": ",".join(cps), "CH_Aulas": ch, "Qtd_PL": pl, "Escolas": ",".join(escolas_sel), "Regiao": reg_prof})
    
    st.markdown("---")
    st.write("### 📝 Editar ou Excluir Professores")
    if not dp.empty:
        professores_editados = st.data_editor(dp, num_rows="dynamic", key="editor_profs", use_container_width=True)
        if st.button("💾 SALVAR ALTERAÇÕES EM PROFESSORES", type="primary"):
            salvar_geral(dt, dc, professores_editados, dd)

# --- ABA 5: GERAR GRADE ---
with t5:
    st.header("🚀 Gerar Grade por Escola")
    st.info("O sistema mostrará prévias das tabelas abaixo enquanto gera o arquivo final.")
    
    if st.button("GERAR TABELAS", type="primary"):
        if dt.empty or dp.empty: st.error("Cadastre dados primeiro.")
        else:
            objs_profs = carregar_objetos_professores(dp)
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                df_full = pd.merge(dt, dd, on="AnoBase", how="inner")
                escolas_unicas = df_full['Escola'].unique()
                progresso = st.progress(0, text="Iniciando...")
                erros_gerais = []
                sucesso_algum = False
                
                st.markdown("---")
                st.subheader("👀 Visualização em Tempo Real")
                
                for idx, escola in enumerate(escolas_unicas):
                    progresso.progress((idx+1)/len(escolas_unicas), text=f"Gerando: {escola}...")
                    dados_para_excel = [] 
                    df_escola = df_full[df_full['Escola'] == escola]
                    dias_turnos = df_escola[['DiaSemana', 'Turno']].drop_duplicates()
                    
                    for _, row in dias_turnos.iterrows():
                        dia = row['DiaSemana']
                        turno = row['Turno']
                        turmas_bloco = df_escola[(df_escola['DiaSemana'] == dia) & (df_escola['Turno'] == turno)]
                        
                        lista_turmas_algoritmo = []
                        for _, t_row in turmas_bloco.iterrows():
                            lista_turmas_algoritmo.append({
                                'nome_turma': t_row['NomeTurma'],
                                'ano': t_row['AnoBase'], 
                                'escola_real': escola, 
                                'regiao_real': t_row['Regiao']
                            })
                        
                        resultado, motivo = resolver_horario_grade(lista_turmas_algoritmo, dc, objs_profs)
                        if resultado:
                            titulo_bloco = f"{turno.upper()} - {dia.upper()}"
                            df_res = pd.DataFrame(resultado)
                            dados_para_excel.append((titulo_bloco, df_res))
                            sucesso_algum = True
                        else:
                            erros_gerais.append(f"{escola} ({dia}/{turno}): {motivo}")

                    if dados_para_excel:
                        desenhar_tabela_escola(writer, escola, dados_para_excel)
                        with st.expander(f"🏫 **{escola}** (Clique para ver)", expanded=False):
                            for titulo, df_raw in dados_para_excel:
                                st.markdown(f"**{titulo}**")
                                df_visual = criar_preview_com_recreio(df_raw)
                                st.dataframe(df_visual, use_container_width=True)
                                st.divider()
                
                progresso.empty()
                if sucesso_algum:
                    st.success("✅ Processo concluído! Baixe o arquivo final abaixo.")
                    if erros_gerais:
                        with st.expander("⚠️ Ver avisos de erro"):
                            for e in erros_gerais: st.write(e)
                else: st.error("Falha geral.")

            buffer.seek(0)
            st.download_button("📥 Baixar Planilha Completa (.xlsx)", buffer, "Horarios_Por_Escola.xlsx")