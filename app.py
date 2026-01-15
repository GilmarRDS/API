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

# ==========================================
# 2. BANCO DE DADOS (GOOGLE SHEETS)
# ==========================================

conn = st.connection("gsheets", type=GSheetsConnection)

def atualiza_relogio():
    st.session_state['ultima_atualizacao'] = datetime.now().strftime("%d/%m/%Y às %H:%M:%S")

def carregar_dados():
    try:
        df_turmas = conn.read(worksheet="Turmas", ttl=0)
        df_curriculo = conn.read(worksheet="Curriculo", ttl=0)
        df_professores = conn.read(worksheet="Professores", ttl=0)
        df_dias = conn.read(worksheet="ConfigDias", ttl=0)
        
        if df_turmas.empty: 
            df_turmas = pd.DataFrame(columns=["Escola", "Nivel", "NomeTurma", "Turno", "AnoBase"])
        
        if df_curriculo.empty: 
            df_curriculo = pd.DataFrame(columns=["AnoBase", "Materia", "Quantidade"])
        
        # ADICIONADO COLUNA 'Escolas'
        if df_professores.empty: 
            df_professores = pd.DataFrame(columns=["Codigo", "Nome", "Componentes", "CH_Aulas", "Qtd_PL", "Escolas"])
            
        if df_dias.empty: 
            df_dias = pd.DataFrame(columns=["AnoBase", "DiaSemana"])
        
        df_turmas = df_turmas.fillna("")
        df_curriculo = df_curriculo.fillna(0)
        df_professores = df_professores.fillna("")
        df_dias = df_dias.fillna("")
        
        atualiza_relogio()
        return df_turmas, df_curriculo, df_professores, df_dias

    except Exception as e:
        st.error(f"Erro na conexão com Google Sheets: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def salvar_geral(df_t, df_c, df_p, df_d):
    try:
        with st.spinner('Salvando na nuvem...'):
            conn.update(worksheet="Turmas", data=df_t)
            conn.update(worksheet="Curriculo", data=df_c)
            conn.update(worksheet="Professores", data=df_p)
            conn.update(worksheet="ConfigDias", data=df_d)
            st.cache_data.clear()
            atualiza_relogio()
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")

# --- FUNÇÕES CRUD ---

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
# 3. ALGORITMO INTELIGENTE
# ==========================================

def carregar_objetos_professores(df_prof):
    """Carrega professores e suas escolas"""
    lista_profs = []
    for _, row in df_prof.iterrows():
        materias = [m.strip() for m in str(row['Componentes']).split(',')]
        
        # Carrega lista de escolas desse professor
        escolas_prof = [e.strip() for e in str(row['Escolas']).split(',')]
        
        try:
            ch_limite = int(row['CH_Aulas'])
        except:
            ch_limite = 999 

        for mat in materias:
            if mat in MATERIAS_ESPECIALISTAS:
                lista_profs.append({
                    'id': f"{row['Codigo']} - {row['Nome']}", 
                    'codigo': row['Codigo'],
                    'nome': row['Nome'],
                    'materia': mat,
                    'escolas': escolas_prof, # NOVA PROPRIEDADE
                    'max_aulas': ch_limite, 
                    'aulas_atribuidas': 0,
                    'horarios_ocupados': []
                })
    return lista_profs

def resolver_horario_grade(turmas_do_dia, curriculo_df, lista_professores):
    # Reseta ocupação
    for p in lista_professores:
        p['horarios_ocupados'] = []

    grade_final = {t['nome_turma']: ["---"]*5 for t in turmas_do_dia}
    
    # 1. Demanda
    demandas = {}
    for turma in turmas_do_dia:
        curr_turma = curriculo_df[curriculo_df['AnoBase'] == turma['ano']]
        aulas = []
        for _, row in curr_turma.iterrows():
            aulas.extend([row['Materia']] * int(row['Quantidade']))
        
        while len(aulas) < 5: aulas.append("---")
        aulas = aulas[:5]
        random.shuffle(aulas)
        demandas[turma['nome_turma']] = aulas

    # 2. Distribuição
    for _ in range(100): 
        grade_tentativa = {k: v[:] for k, v in grade_final.items()}
        
        professores_temp = []
        for p in lista_professores:
            prof = p.copy()
            prof['horarios_ocupados'] = list(p['horarios_ocupados'])
            # Importante: Copiar a lista de escolas também para garantir integridade
            prof['escolas'] = list(p['escolas']) 
            professores_temp.append(prof)
        
        sucesso = True
        
        for slot in range(5):
            turmas_embaralhadas = list(demandas.keys())
            random.shuffle(turmas_embaralhadas)
            
            for nome_turma in turmas_embaralhadas:
                materia_desejada = demandas[nome_turma][slot]
                
                if materia_desejada == "---":
                    grade_tentativa[nome_turma][slot] = "---"
                    continue
                
                # Descobre qual é a escola desta turma (foi passada no objeto turma)
                escola_da_turma = turma['escola_real']
                
                # Busca candidato válido:
                # 1. Dá a matéria
                # 2. Livre neste horário
                # 3. Tem saldo de CH
                # 4. TRABALHA NESTA ESCOLA (NOVO)
                candidatos = [
                    p for p in professores_temp 
                    if p['materia'] == materia_desejada 
                    and slot not in p['horarios_ocupados']
                    and p['aulas_atribuidas'] < p['max_aulas']
                    and escola_da_turma in p['escolas'] # VERIFICAÇÃO DE ESCOLA
                ]
                
                if candidatos:
                    escolhido = random.choice(candidatos)
                    grade_tentativa[nome_turma][slot] = f"{materia_desejada}\n{escolhido['nome']} ({escolhido['codigo']})"
                    
                    escolhido['horarios_ocupados'].append(slot)
                    escolhido['aulas_atribuidas'] += 1
                else:
                    sucesso = False 
                    break
            if not sucesso: break
        
        if sucesso:
            return grade_tentativa

    return None 

def formatar_para_excel_grade(grade_dict):
    if not grade_dict: return pd.DataFrame()
    df = pd.DataFrame(grade_dict)
    recreio = pd.DataFrame({col: ["RECREIO"] for col in df.columns}, index=[2.5])
    df = pd.concat([df.iloc[:3], recreio, df.iloc[3:]]).reset_index(drop=True)
    df.index = ["1ª Aula", "2ª Aula", "3ª Aula", "Recreio", "4ª Aula", "5ª Aula"]
    return df

# ==========================================
# 4. INTERFACE GRÁFICA
# ==========================================
st.set_page_config(page_title="Gerador Escolar", layout="wide")
st.title("🎓 Gerador de Horários (Rede)")

if 'ultima_atualizacao' not in st.session_state:
    st.session_state['ultima_atualizacao'] = "Aguardando dados..."

dt, dc, dp, dd = carregar_dados()

# --- SIDEBAR ---
st.sidebar.markdown("### ☁️ Status")
hora_tela = st.session_state['ultima_atualizacao']
if "Aguardando" in hora_tela:
    st.sidebar.warning(f"🕒 {hora_tela}")
else:
    st.sidebar.success(f"✅ Atualizado em:\n**{hora_tela}**")

if st.sidebar.button("🔄 Forçar Atualização"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()
st.sidebar.markdown("**Legenda:**")
st.sidebar.caption("Infantil = Creche/Pré")
st.sidebar.caption("Fund. = Ensino Fundamental")

# --- ABAS ---
t1, t2, t3, t4 = st.tabs(["1. Configuração Rede", "2. Turmas", "3. Professores", "4. Gerar Grade"])

with t1:
    st.markdown("### Configuração por Ano/Série")
    st.info("Dia do Planejamento do Regente.")
    
    ano_sel = st.selectbox("Ano:", [
        "Berçário", "Creche I", "Creche II", "Creche III", "Pré I", "Pré II",
        "1º Ano", "2º Ano", "3º Ano", "4º Ano", "5º Ano"
    ])
    
    dia_atual = "Segunda-feira"
    if not dd.empty:
        f = dd[dd['AnoBase'] == ano_sel]
        if not f.empty: dia_atual = f.iloc[0]['DiaSemana']

    dia_sel = st.selectbox("Dia Planejamento:", 
                           ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira"], 
                           index=["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira"].index(dia_atual))
    
    st.divider()
    st.write(f"**Quantidades de Aulas ({ano_sel}):**")
    
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
        tnm = c2.text_input("Turma (Ex: A, B)")
        
        c3, c4 = st.columns(2)
        trn = c3.selectbox("Turno", ["Matutino", "Vespertino"])
        
        lista_anos = ["Berçário", "Creche I", "Creche II", "Creche III", "Pré I", "Pré II", "1º Ano", "2º Ano", "3º Ano", "4º Ano", "5º Ano"]
        ano = c4.selectbox("Ano Base", lista_anos)
        
        if st.form_submit_button("➕ Adicionar Turma"):
            if any(x in ano for x in ["Creche", "Pré", "Berçário"]):
                nivel_auto = "Infantil"
            else:
                nivel_auto = "Fundamental"
                
            adicionar_turma({
                "Escola": esc, 
                "NomeTurma": tnm, 
                "Turno": trn, 
                "AnoBase": ano,
                "Nivel": nivel_auto
            })
            st.success(f"Turma salva! Nível: {nivel_auto}")
            st.rerun()
            
    if not dt.empty:
        st.dataframe(dt, use_container_width=True)
        if st.button("🗑️ Apagar Todas as Turmas"):
            limpar_tabela('Turmas')
            st.rerun()

with t3:
    st.markdown("### Professores Especialistas")
    
    # Pega lista de escolas cadastradas nas turmas para facilitar
    lista_escolas_existentes = []
    if not dt.empty:
        lista_escolas_existentes = sorted(dt['Escola'].unique().tolist())

    with st.form("novo_prof"):
        c_cod, c_nom = st.columns([1, 3])
        cod = c_cod.text_input("Código (Ex: P1)")
        nm = c_nom.text_input("Nome Completo")
        
        c_ch, c_pl = st.columns(2)
        ch = c_ch.number_input("Carga Horária (Máx Aulas)", min_value=1, value=13)
        pl = c_pl.number_input("Qtd. PLs", min_value=0, value=7)
        
        st.markdown("---")
        # SELEÇÃO DAS ESCOLAS (MULTISELECT)
        if lista_escolas_existentes:
            escolas_sel = st.multiselect("Em quais escolas ele trabalha?", lista_escolas_existentes)
        else:
            st.warning("Cadastre turmas primeiro para aparecerem as escolas aqui.")
            escolas_sel = []

        st.markdown("---")
        cps = st.multiselect("Matérias que leciona:", MATERIAS_ESPECIALISTAS)
        
        if st.form_submit_button("💾 Salvar Professor"):
            if cps and nm and cod and escolas_sel:
                adicionar_professor({
                    "Codigo": cod, 
                    "Nome": nm, 
                    "Componentes": ",".join(cps),
                    "CH_Aulas": ch,
                    "Qtd_PL": pl,
                    "Escolas": ",".join(escolas_sel) # Salva separado por vírgula
                })
                st.success("Professor Salvo!")
                st.rerun()
            else:
                st.error("Preencha Código, Nome, Escolas e Matérias.")
                
    if not dp.empty:
        st.dataframe(dp, use_container_width=True)
        if st.button("🗑️ Apagar Todos os Professores"):
            limpar_tabela('Professores')
            st.rerun()

with t4:
    st.header("🚀 Gerar Grade")
    
    if st.button("GERAR TABELA AGORA", type="primary"):
        if dt.empty or dp.empty:
            st.error("Cadastre dados primeiro.")
        else:
            objs_profs = carregar_objetos_professores(dp)
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                
                df_full = pd.merge(dt, dd, on="AnoBase", how="inner")
                turnos = df_full['Turno'].unique()
                dias = df_full['DiaSemana'].unique()
                erros = []
                sucesso_geral = False
                
                for turno in turnos:
                    for dia in dias:
                        filtro = df_full[(df_full['Turno'] == turno) & (df_full['DiaSemana'] == dia)]
                        if filtro.empty: continue
                        
                        lista_turmas = []
                        for _, row in filtro.iterrows():
                            # Passa a escola REAL para o algoritmo filtrar
                            nome_coluna = f"{row['AnoBase']} {row['NomeTurma']} ({row['Escola'][:10]})"
                            lista_turmas.append({
                                'nome_turma': nome_coluna, 
                                'ano': row['AnoBase'],
                                'escola_real': row['Escola'] # <--- Importante para o filtro
                            })
                        
                        resultado = resolver_horario_grade(lista_turmas, dc, objs_profs)
                        
                        if resultado:
                            sucesso_geral = True
                            st.subheader(f"📅 {dia} - {turno}")
                            df_excel = formatar_para_excel_grade(resultado)
                            st.dataframe(df_excel, use_container_width=True)
                            sheet_nm = f"{dia[:3]}_{turno[:3]}".replace("-","")
                            df_excel.to_excel(writer, sheet_name=sheet_nm)
                        else:
                            msg = f"❌ Falha em {dia}/{turno}: Professor não atende a escola ou sem CH."
                            st.error(msg)
                            erros.append(msg)
                
                if sucesso_geral and not erros:
                    st.success("✅ Sucesso Total!")
                elif sucesso_geral and erros:
                    st.warning("⚠️ Parcialmente gerado.")
                    
            buffer.seek(0)
            st.download_button("📥 Baixar Excel", buffer, "Horario_Rede_Final.xlsx")