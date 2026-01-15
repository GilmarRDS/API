import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import random
import io
import xlsxwriter
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
# 2. BANCO DE DADOS
# ==========================================

conn = st.connection("gsheets", type=GSheetsConnection)

def definir_hora_atual():
    st.session_state['hora_exata_db'] = datetime.now().strftime("%d/%m/%Y às %H:%M:%S")

def carregar_dados():
    try:
        df_turmas = conn.read(worksheet="Turmas", ttl=0)
        df_curriculo = conn.read(worksheet="Curriculo", ttl=0)
        df_professores = conn.read(worksheet="Professores", ttl=0)
        df_dias = conn.read(worksheet="ConfigDias", ttl=0)
        
        # Estruturas
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
        st.error(f"Erro na conexão: {e}")
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
            
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")

# --- CRUD ---

def adicionar_turma(dado):
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

def adicionar_professor(dado):
    dt, dc, dp, dd = carregar_dados()
    dp = pd.concat([dp, pd.DataFrame([dado])], ignore_index=True)
    salvar_geral(dt, dc, dp, dd)

def limpar_tabela(aba):
    dt, dc, dp, dd = carregar_dados()
    if aba == 'Turmas': dt = dt.iloc[0:0]
    if aba == 'Professores': dp = dp.iloc[0:0]
    if aba == 'ConfigDias': dd = dd.iloc[0:0]
    salvar_geral(dt, dc, dp, dd)

# ==========================================
# 3. ALGORITMO DE ALOCAÇÃO
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
    # Reset
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
        
        if sucesso_tentativa:
            return grade_tentativa, None
        
        if tentativa == (MAX_TENTATIVAS - 1):
            return None, motivo_falha_atual

    return None, "Impossível matematicamente."

# --- FORMATAÇÃO VISUAL BONITA (POR ESCOLA) ---
def desenhar_tabela_escola(writer, nome_escola, dados_turnos):
    """
    Desenha uma aba inteira para a escola, empilhando os turnos/dias.
    dados_turnos = lista de tuplas (Titulo_Bloco, DataFrame)
    """
    # Cria a aba com nome limpo (max 31 chars)
    sheet_name = nome_escola[:30].replace("/","-")
    workbook = writer.book
    worksheet = workbook.add_worksheet(sheet_name)
    writer.sheets[sheet_name] = worksheet
    
    # --- ESTILOS PROFISSIONAIS ---
    # Azul Escuro para Título da Escola
    fmt_titulo_escola = workbook.add_format({
        'bold': True, 'align': 'center', 'valign': 'vcenter',
        'font_size': 18, 'bg_color': '#4472C4', 'font_color': 'white', 'border': 1
    })
    
    # Azul Claro para Subtítulos (Turno/Dia)
    fmt_subtitulo = workbook.add_format({
        'bold': True, 'align': 'center', 'valign': 'vcenter',
        'font_size': 12, 'bg_color': '#D9E1F2', 'border': 1
    })
    
    # Cabeçalho das Turmas (Verde suave)
    fmt_header_turma = workbook.add_format({
        'bold': True, 'align': 'center', 'valign': 'vcenter',
        'text_wrap': True, 'bg_color': '#E2EFDA', 'border': 1
    })
    
    # Célula Normal (Centralizada com quebra)
    fmt_celula = workbook.add_format({
        'align': 'center', 'valign': 'vcenter',
        'text_wrap': True, 'border': 1, 'font_size': 10
    })
    
    # Recreio (Cinza)
    fmt_recreio = workbook.add_format({
        'bold': True, 'align': 'center', 'valign': 'vcenter',
        'bg_color': '#F2F2F2', 'font_color': '#595959', 'border': 1
    })

    # --- DESENHO ---
    current_row = 0
    
    # 1. Título da Escola no Topo
    worksheet.merge_range(current_row, 0, current_row, 5, nome_escola, fmt_titulo_escola)
    current_row += 2 # Pula linha
    
    for titulo_bloco, df_grade in dados_turnos:
        if df_grade.empty: continue
        
        # Converte dicionário para DF se necessário
        if isinstance(df_grade, dict):
            df = pd.DataFrame(df_grade)
        else:
            df = df_grade
            
        num_cols = len(df.columns)
        
        # Título do Bloco (Ex: "MATUTINO - SEGUNDA-FEIRA")
        worksheet.merge_range(current_row, 0, current_row, num_cols, titulo_bloco, fmt_subtitulo)
        current_row += 1
        
        # Cabeçalhos das Turmas
        worksheet.write(current_row, 0, "Horário", fmt_header_turma)
        for col_idx, col_name in enumerate(df.columns):
            worksheet.write(current_row, col_idx + 1, col_name, fmt_header_turma)
            worksheet.set_column(col_idx + 1, col_idx + 1, 22) # Largura
        current_row += 1
        
        # Aulas 1 a 3
        for i in range(3):
            worksheet.write(current_row, 0, f"{i+1}ª Aula", fmt_celula)
            for col_idx, col_name in enumerate(df.columns):
                val = df.iloc[i][col_name]
                if val is None: val = ""
                worksheet.write(current_row, col_idx + 1, val, fmt_celula)
            current_row += 1
            
        # RECREIO
        worksheet.merge_range(current_row, 0, current_row, num_cols, "RECREIO", fmt_recreio)
        current_row += 1
        
        # Aulas 4 e 5
        for i in range(3, 5):
            worksheet.write(current_row, 0, f"{i+1}ª Aula", fmt_celula)
            for col_idx, col_name in enumerate(df.columns):
                val = df.iloc[i][col_name]
                if val is None: val = ""
                worksheet.write(current_row, col_idx + 1, val, fmt_celula)
            current_row += 1
            
        # Espaço entre blocos
        current_row += 2
        
    # Ajuste final da coluna A
    worksheet.set_column(0, 0, 12)

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

# --- ABAS ---
t1, t2, t3, t4 = st.tabs(["1. Configuração", "2. Turmas", "3. Professores", "4. Gerar Grade"])

with t1:
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
            st.success(f"Salvo!")
            st.rerun()

with t2:
    st.markdown("### Cadastro de Turmas")
    with st.form("nova_turma"):
        c1, c2 = st.columns(2)
        esc = c1.text_input("Escola")
        tnm = c2.text_input("Turma (Ex: A)")
        c3, c4, c5 = st.columns(3)
        trn = c3.selectbox("Turno", ["Matutino", "Vespertino"])
        regiao = c4.selectbox("Região", REGIOES_DISPONIVEIS)
        ano = c5.selectbox("Ano Base", ["Berçário", "Creche I", "Creche II", "Creche III", "Pré I", "Pré II", "1º Ano", "2º Ano", "3º Ano", "4º Ano", "5º Ano"])
        if st.form_submit_button("➕ Adicionar Turma"):
            if not esc or not tnm: st.error("Preencha Escola e Turma!")
            else:
                if any(x in ano for x in ["Creche", "Pré", "Berçário"]): nivel_auto = "Infantil"
                else: nivel_auto = "Fundamental"
                adicionar_turma({"Escola": esc, "NomeTurma": tnm, "Turno": trn, "AnoBase": ano, "Nivel": nivel_auto, "Regiao": regiao})
                st.success(f"Turma salva!")
                st.rerun()
    if not dt.empty:
        st.dataframe(dt, use_container_width=True)
        if st.button("🗑️ Apagar Turmas"):
            limpar_tabela('Turmas')
            st.rerun()

with t3:
    st.markdown("### Professores Especialistas")
    lista_escolas_existentes = []
    if not dt.empty: lista_escolas_existentes = sorted(dt['Escola'].unique().tolist())
    with st.form("novo_prof"):
        c_cod, c_nom = st.columns([1, 3])
        cod = c_cod.text_input("Código")
        nm = c_nom.text_input("Nome")
        c_ch, c_pl, c_reg = st.columns(3)
        ch = c_ch.number_input("CH Aulas", 1, 30, 13)
        pl = c_pl.number_input("PLs", 0, 10, 7)
        reg_prof = c_reg.selectbox("Região de Atuação", REGIOES_DISPONIVEIS)
        st.markdown("---")
        if lista_escolas_existentes: escolas_sel = st.multiselect("Escolas Específicas:", lista_escolas_existentes)
        else: escolas_sel = []
        st.markdown("---")
        cps = st.multiselect("Matérias:", MATERIAS_ESPECIALISTAS)
        if st.form_submit_button("💾 Salvar Professor"):
            if cps and nm and escolas_sel:
                adicionar_professor({"Codigo": cod, "Nome": nm, "Componentes": ",".join(cps), "CH_Aulas": ch, "Qtd_PL": pl, "Escolas": ",".join(escolas_sel), "Regiao": reg_prof})
                st.success("Salvo!")
                st.rerun()
            else: st.error("Preencha campos.")
    if not dp.empty:
        st.dataframe(dp, use_container_width=True)
        if st.button("🗑️ Apagar Professores"):
            limpar_tabela('Professores')
            st.rerun()

with t4:
    st.header("🚀 Gerar Grade por Escola")
    if st.button("GERAR ARQUIVO DE ESCOLAS", type="primary"):
        if dt.empty or dp.empty: st.error("Cadastre dados primeiro.")
        else:
            objs_profs = carregar_objetos_professores(dp)
            buffer = io.BytesIO()
            
            # --- NOVA LÓGICA DE GERAÇÃO POR ESCOLA ---
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                
                df_full = pd.merge(dt, dd, on="AnoBase", how="inner")
                escolas_unicas = df_full['Escola'].unique()
                
                progresso = st.progress(0, text="Iniciando...")
                erros_gerais = []
                sucesso_algum = False
                
                for idx, escola in enumerate(escolas_unicas):
                    progresso.progress((idx+1)/len(escolas_unicas), text=f"Gerando para: {escola}...")
                    
                    dados_para_excel = [] # Vai guardar (Titulo, DF)
                    
                    # Filtra tudo dessa escola
                    df_escola = df_full[df_full['Escola'] == escola]
                    
                    # Identifica quais dias e turnos essa escola tem
                    dias_turnos = df_escola[['DiaSemana', 'Turno']].drop_duplicates()
                    
                    for _, row in dias_turnos.iterrows():
                        dia = row['DiaSemana']
                        turno = row['Turno']
                        
                        # Filtra as turmas específicas deste bloco
                        turmas_bloco = df_escola[(df_escola['DiaSemana'] == dia) & (df_escola['Turno'] == turno)]
                        
                        lista_turmas_algoritmo = []
                        for _, t_row in turmas_bloco.iterrows():
                            # Nome da turma simplificado para a coluna
                            lista_turmas_algoritmo.append({
                                'nome_turma': t_row['NomeTurma'], # Ex: "1º Ano A"
                                'ano': t_row['AnoBase'], 
                                'escola_real': escola, 
                                'regiao_real': t_row['Regiao']
                            })
                        
                        # Roda o algoritmo
                        resultado, motivo = resolver_horario_grade(lista_turmas_algoritmo, dc, objs_profs)
                        
                        if resultado:
                            titulo_bloco = f"{turno.upper()} - {dia.upper()}"
                            df_res = pd.DataFrame(resultado)
                            dados_para_excel.append((titulo_bloco, df_res))
                            sucesso_algum = True
                        else:
                            erros_gerais.append(f"{escola} ({dia}/{turno}): {motivo}")

                    # Se gerou algo para essa escola, desenha a aba
                    if dados_para_excel:
                        desenhar_tabela_escola(writer, escola, dados_para_excel)
                
                progresso.empty()
                
                if sucesso_algum:
                    st.success("✅ Planilha gerada com sucesso! Baixe abaixo.")
                    if erros_gerais:
                        with st.expander("⚠️ Ver avisos de turmas não geradas"):
                            for e in erros_gerais: st.write(e)
                else:
                    st.error("Não foi possível gerar nenhuma grade. Verifique os cadastros.")
                    if erros_gerais:
                        for e in erros_gerais: st.write(e)

            buffer.seek(0)
            st.download_button("📥 Baixar Planilha Bonita (.xlsx)", buffer, "Horarios_Por_Escola.xlsx")