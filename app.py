import streamlit as st
import pandas as pd
import os
import random
import io
import xlsxwriter

# ==========================================
# 1. CONFIGURAÇÕES E CONSTANTES
# ==========================================
DB_FILE = 'banco_de_dados.xlsx'

# --- LISTAS PARA ORGANIZAÇÃO ---

# 1. Matérias Exclusivas do Infantil (Campos de Experiência)
MATERIAS_INFANTIL_EXCLUSIVAS = [
    "EO - Eu, o Outro e o Nós",
    "CG - Corpo, Gestos e Movimentos",
    "TS - Traços, Sons, Cores e Formas",
    "EF - Escuta, Fala, Pensamento e Imaginação",
    "ET - Espaços, Tempos, Quantidades, Relações"
]

# 2. Matérias Exclusivas do Fundamental (Regentes)
MATERIAS_FUNDAMENTAL_EXCLUSIVAS = [
    "Língua Portuguesa",
    "Matemática",
    "Ciências",
    "História",
    "Geografia"
]

# 3. Especialistas (Comuns aos dois ou específicos de área)
MATERIAS_ESPECIALISTAS = [
    "Arte",
    "Educação Física",
    "Ensino Religioso",
    "Língua Inglesa"
]

# Listas completas para uso nos dropdowns de Currículo
COMPS_INFANTIL = MATERIAS_INFANTIL_EXCLUSIVAS + ["Arte", "Educação Física"]
COMPS_FUNDAMENTAL = MATERIAS_FUNDAMENTAL_EXCLUSIVAS + MATERIAS_ESPECIALISTAS

# Lista unificada para cadastro de professores
TODAS_MATERIAS = list(set(COMPS_INFANTIL + COMPS_FUNDAMENTAL))
TODAS_MATERIAS.sort()

# ==========================================
# 2. GESTÃO DO BANCO DE DADOS
# ==========================================
def inicializar_db():
    if not os.path.exists(DB_FILE):
        df_turmas = pd.DataFrame(columns=["Escola", "Nivel", "NomeTurma", "Turno", "AnoBase", "DiaPlanejamento"])
        df_curriculo = pd.DataFrame(columns=["AnoBase", "Materia"])
        df_professores = pd.DataFrame(columns=["Codigo", "Nome", "Componentes", "CH_Aulas", "Qtd_PL"]) 
        
        with pd.ExcelWriter(DB_FILE, engine='xlsxwriter') as writer:
            df_turmas.to_excel(writer, sheet_name='Turmas', index=False)
            df_curriculo.to_excel(writer, sheet_name='Curriculo', index=False)
            df_professores.to_excel(writer, sheet_name='Professores', index=False)

def carregar_dados():
    inicializar_db()
    try:
        xls = pd.ExcelFile(DB_FILE)
        df_turmas = pd.read_excel(xls, 'Turmas')
        df_curriculo = pd.read_excel(xls, 'Curriculo')
        
        if 'Nivel' not in df_turmas.columns:
            df_turmas['Nivel'] = "Ensino Fundamental"
            
        if 'Professores' in xls.sheet_names:
            df_professores = pd.read_excel(xls, 'Professores')
            cols_profs = ["Codigo", "Nome", "Componentes", "CH_Aulas", "Qtd_PL"]
            for col in cols_profs:
                if col not in df_professores.columns:
                    df_professores[col] = ""
        else:
            df_professores = pd.DataFrame(columns=["Codigo", "Nome", "Componentes", "CH_Aulas", "Qtd_PL"])
            
        return df_turmas, df_curriculo, df_professores
    except Exception as e:
        st.error(f"Erro ao ler banco de dados: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def salvar_geral(df_t, df_c, df_p):
    with pd.ExcelWriter(DB_FILE, engine='xlsxwriter') as writer:
        df_t.to_excel(writer, sheet_name='Turmas', index=False)
        df_c.to_excel(writer, sheet_name='Curriculo', index=False)
        df_p.to_excel(writer, sheet_name='Professores', index=False)

def adicionar_turma(nova_turma):
    df_t, df_c, df_p = carregar_dados()
    df_t = pd.concat([df_t, pd.DataFrame([nova_turma])], ignore_index=True)
    salvar_geral(df_t, df_c, df_p)

def adicionar_curriculo(ano, materias):
    df_t, df_c, df_p = carregar_dados()
    df_c = df_c[df_c['AnoBase'] != ano]
    novas = [{"AnoBase": ano, "Materia": m} for m in materias]
    df_c = pd.concat([df_c, pd.DataFrame(novas)], ignore_index=True)
    salvar_geral(df_t, df_c, df_p)

def adicionar_professor_completo(codigo, nome, componentes_lista, ch, pls):
    df_t, df_c, df_p = carregar_dados()
    comps_str = ", ".join(componentes_lista)
    novo_prof = {"Codigo": codigo, "Nome": nome, "Componentes": comps_str, "CH_Aulas": ch, "Qtd_PL": pls}
    df_p = pd.concat([df_p, pd.DataFrame([novo_prof])], ignore_index=True)
    salvar_geral(df_t, df_c, df_p)

def limpar_banco(tipo):
    df_t, df_c, df_p = carregar_dados()
    if tipo == 'Turmas':
        df_t = pd.DataFrame(columns=["Escola", "Nivel", "NomeTurma", "Turno", "AnoBase", "DiaPlanejamento"])
    elif tipo == 'Curriculo':
        df_c = pd.DataFrame(columns=["AnoBase", "Materia"])
    elif tipo == 'Professores':
        df_p = pd.DataFrame(columns=["Codigo", "Nome", "Componentes", "CH_Aulas", "Qtd_PL"])
    salvar_geral(df_t, df_c, df_p)

# ==========================================
# 3. ALGORITMO (BACKEND)
# ==========================================
def resolver_horario(turmas_do_dia, curriculo_dict, recursos_max):
    for _ in range(2000): # Aumentei tentativas
        grade = {t['id']: [None]*5 for t in turmas_do_dia}
        uso_recursos = {p: {} for p in range(5)}
        
        turmas_random = turmas_do_dia.copy()
        random.shuffle(turmas_random)
        
        sucesso_total = True
        
        for turma in turmas_random:
            materias = curriculo_dict.get(turma['ano'], [])
            
            # Fallback inteligente dependendo do nível se não tiver currículo
            if not materias:
                if "Creche" in turma['ano'] or "Pré" in turma['ano']:
                     materias = ["EO - Eu, o Outro e o Nós", "Educação Física", "Arte", "CG - Corpo, Gestos e Movimentos", "TS - Traços, Sons, Cores e Formas"]
                else:
                     materias = ["Arte", "Educação Física", "Ensino Religioso", "Língua Inglesa", "Educação Física"]
            
            # Ajustar para 5 aulas
            if len(materias) < 5:
                materias = (materias * 5)[:5]
            else:
                materias = materias[:5]
                
            aulas_para_agendar = materias.copy()
            random.shuffle(aulas_para_agendar)
            
            for materia in aulas_para_agendar:
                alocado = False
                slots = list(range(5))
                random.shuffle(slots)
                
                for p in slots:
                    if grade[turma['id']][p] is not None: continue
                    
                    qtd_usada = uso_recursos[p].get(materia, 0)
                    limite = recursos_max.get(materia, 0)
                    if limite == 0: limite = 1 # Evita travar se não cadastrado
                    
                    if qtd_usada < limite:
                        grade[turma['id']][p] = materia
                        uso_recursos[p][materia] = qtd_usada + 1
                        alocado = True
                        break
                
                if not alocado:
                    sucesso_total = False
                    break
            if not sucesso_total: break
        
        if sucesso_total:
            return grade
    return None

def formatar_para_excel_visual(grade_dict):
    if not grade_dict: return pd.DataFrame()
    df = pd.DataFrame(grade_dict)
    parte1 = df.iloc[0:3]
    parte2 = df.iloc[3:5]
    recreio_row = pd.DataFrame({col: ["RECREIO"] for col in df.columns}, index=[3])
    df_final = pd.concat([parte1, recreio_row, parte2])
    df_final.index = ["1ª Aula", "2ª Aula", "3ª Aula", "Recreio", "4ª Aula", "5ª Aula"]
    return df_final

# ==========================================
# 4. INTERFACE GRÁFICA (FRONTEND)
# ==========================================
st.set_page_config(page_title="Gestor Escolar Completo", layout="wide")
st.title("🎓 Sistema de Horários Integrado")

df_t, df_c, df_p = carregar_dados()

# --- SIDEBAR (CAPACIDADE) ---
st.sidebar.header("📋 Capacidade Docente")
st.sidebar.caption("Defina quantos professores existem na rede.")

recursos_finais = {}
capacidade_real = {m: 0 for m in TODAS_MATERIAS}

# Calcular profs cadastrados
if not df_p.empty and 'Componentes' in df_p.columns:
    for _, row in df_p.iterrows():
        materias_prof = [m.strip() for m in str(row['Componentes']).split(',')]
        for m in materias_prof:
            for m_oficial in TODAS_MATERIAS:
                if m.lower() == m_oficial.lower() or m_oficial.startswith(m.split(' - ')[0]):
                    capacidade_real[m_oficial] += 1

# === CORREÇÃO DO ERRO DE CHAVE DUPLICADA AQUI ===
# Criamos grupos separados para evitar que "Arte" apareça duas vezes com a mesma chave

with st.sidebar.expander("Professores Especialistas (Comuns)", expanded=True):
    st.caption("Atendem Infantil e Fundamental")
    for mat in MATERIAS_ESPECIALISTAS:
        val = capacidade_real.get(mat, 0)
        # Se for especialista, garantimos pelo menos 1 se não houver cadastro, pra não dar erro
        if val == 0: val = 1 
        recursos_finais[mat] = st.number_input(f"{mat}", min_value=0, value=val, key=f"res_{mat}_especialista")

with st.sidebar.expander("Professores Regentes (Infantil)", expanded=False):
    for mat in MATERIAS_INFANTIL_EXCLUSIVAS:
        val = capacidade_real.get(mat, 0)
        recursos_finais[mat] = st.number_input(f"{mat[:15]}...", min_value=0, value=val, help=mat, key=f"res_{mat}_inf")

with st.sidebar.expander("Professores Regentes (Fundamental)", expanded=False):
    for mat in MATERIAS_FUNDAMENTAL_EXCLUSIVAS:
        val = capacidade_real.get(mat, 0)
        recursos_finais[mat] = st.number_input(f"{mat}", min_value=0, value=val, key=f"res_{mat}_fund")

# --- ABAS ---
tab1, tab2, tab3, tab4 = st.tabs(["📚 1. Currículo", "🏫 2. Turmas", "👨‍🏫 3. Professores", "🚀 4. Gerar"])

# ABA 1: CURRICULO
with tab1:
    st.markdown("### Definir Currículo do Dia de Planejamento")
    
    tipo_ensino = st.radio("Nível de Ensino:", ["Educação Infantil", "Ensino Fundamental"], horizontal=True)
    
    col1, col2 = st.columns([1, 2])
    
    if tipo_ensino == "Educação Infantil":
        anos_opcoes = ["Berçário", "Creche I", "Creche II", "Creche III", "Pré I", "Pré II"]
        materias_opcoes = COMPS_INFANTIL # Inclui Arte e Ed Fisica
    else:
        anos_opcoes = ["1º Ano", "2º Ano", "3º Ano", "4º Ano", "5º Ano"]
        materias_opcoes = COMPS_FUNDAMENTAL # Inclui Arte e Ed Fisica
        
    ano_sel = col1.selectbox("Ano/Etapa", anos_opcoes)
    mats_sel = col2.multiselect("Selecione 5 Tempos:", materias_opcoes)
    
    if st.button("💾 Salvar Currículo"):
        if len(mats_sel) > 0:
            adicionar_curriculo(ano_sel, mats_sel)
            st.success(f"Currículo de {ano_sel} salvo!")
            st.rerun()
        else:
            st.error("Selecione as matérias.")
            
    if not df_c.empty:
        st.divider()
        st.markdown("**Currículos Cadastrados:**")
        st.dataframe(df_c.groupby('AnoBase')['Materia'].apply(list).reset_index(), use_container_width=True)

# ABA 2: TURMAS
with tab2:
    st.markdown("### Cadastro de Turmas")
    with st.form("form_turma", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        escola = c1.text_input("Escola")
        nivel = c2.selectbox("Nível", ["Educação Infantil", "Ensino Fundamental"])
        turno = c3.selectbox("Turno", ["Matutino", "Vespertino"])
        
        c4, c5, c6 = st.columns(3)
        turma_nome = c4.text_input("Nome da Turma (ex: Creche II A)")
        
        if nivel == "Educação Infantil":
            ano_base = c5.selectbox("Etapa", ["Berçário", "Creche I", "Creche II", "Creche III", "Pré I", "Pré II"])
        else:
            ano_base = c5.selectbox("Ano", ["1º Ano", "2º Ano", "3º Ano", "4º Ano", "5º Ano"])
            
        dia = c6.selectbox("Dia Planejamento", ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira"])
        
        if st.form_submit_button("➕ Criar Turma"):
            if escola and turma_nome:
                adicionar_turma({
                    "Escola": escola, 
                    "Nivel": nivel,
                    "NomeTurma": turma_nome, 
                    "Turno": turno, 
                    "AnoBase": ano_base, 
                    "DiaPlanejamento": dia
                })
                st.success("Turma Criada!")
                st.rerun()
            else:
                st.warning("Preencha o nome da escola e turma.")

    if not df_t.empty:
        st.write("---")
        filtro_nivel = st.selectbox("Filtrar tabela por:", ["Todos", "Educação Infantil", "Ensino Fundamental"])
        df_show = df_t if filtro_nivel == "Todos" else df_t[df_t['Nivel'] == filtro_nivel]
        st.dataframe(df_show, use_container_width=True)
        
        if st.button("🗑️ Apagar Todas as Turmas"):
            limpar_banco("Turmas")
            st.rerun()

# ABA 3: PROFESSORES
with tab3:
    st.markdown("### Quadro de Professores")
    with st.form("form_prof"):
        c1, c2 = st.columns([1, 3])
        cod = c1.text_input("Código (ex: P1INF)")
        nome = c2.text_input("Nome Completo")
        
        # Dropdown com todas as matérias possíveis
        comps = st.multiselect("Componentes Curriculares", TODAS_MATERIAS)
        
        c3, c4 = st.columns(2)
        ch = c3.number_input("Carga Horária", value=20)
        pl = c4.number_input("Qtd PLs", value=5)
        
        if st.form_submit_button("Cadastrar Professor"):
            if cod and nome and comps:
                adicionar_professor_completo(cod, nome, comps, ch, pl)
                st.success("Professor Salvo!")
                st.rerun()
            else:
                st.error("Preencha Código, Nome e Componentes.")
                
    if not df_p.empty:
        st.dataframe(df_p, use_container_width=True)
        if st.button("🗑️ Limpar Professores"):
            limpar_banco("Professores")
            st.rerun()

# ABA 4: GERAR
with tab4:
    st.header("Gerar Horários")
    st.info("O sistema vai gerar abas separadas para Infantil e Fundamental.")
    
    if st.button("🚀 PROCESSAR TUDO", type="primary"):
        if df_t.empty:
            st.error("Sem dados de turmas.")
        else:
            curr_dict = df_c.groupby('AnoBase')['Materia'].apply(list).to_dict()
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                niveis = df_t['Nivel'].unique()
                
                conflitos_log = []
                
                for nivel in niveis:
                    st.subheader(f"🔷 {nivel}")
                    df_nivel = df_t[df_t['Nivel'] == nivel]
                    
                    turnos = df_nivel['Turno'].unique()
                    for turno in turnos:
                        df_turno = df_nivel[df_nivel['Turno'] == turno]
                        dias = df_turno['DiaPlanejamento'].unique()
                        
                        for dia in dias:
                            turmas_dia = df_turno[df_turno['DiaPlanejamento'] == dia]
                            
                            lista_algo = []
                            for _, row in turmas_dia.iterrows():
                                uid = f"{row['Escola']} {row['NomeTurma']}"
                                lista_algo.append({'id': uid, 'ano': row['AnoBase']})
                            
                            # Tentar resolver
                            res = resolver_horario(lista_algo, curr_dict, recursos_finais)
                            
                            if res:
                                df_vis = formatar_para_excel_visual(res)
                                st.write(f"**{turno} - {dia}**")
                                st.dataframe(df_vis, use_container_width=True)
                                
                                prefixo = "INF" if "Infantil" in nivel else "FUND"
                                sheet_name = f"{prefixo}_{turno[:3]}_{dia[:3]}"
                                df_vis.to_excel(writer, sheet_name=sheet_name)
                            else:
                                msg = f"FALHA: {nivel} - {dia} ({turno}). Falta professor!"
                                st.error(msg)
                                conflitos_log.append(msg)
            
                if not conflitos_log:
                    st.success("Todos os horários gerados com sucesso!")
                    
            output.seek(0)
            st.download_button("📥 Baixar Planilha Completa", output, "Horarios_Escolares.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")