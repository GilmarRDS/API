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
    "Arte",
    "Educação Física",
    "Ensino Religioso",
    "Língua Inglesa",
    "Contação de História" 
]

# ==========================================
# 2. BANCO DE DADOS (GOOGLE SHEETS)
# ==========================================

conn = st.connection("gsheets", type=GSheetsConnection)

def carregar_dados():
    try:
        # Lê as 4 abas agora
        df_turmas = conn.read(worksheet="Turmas", ttl=0)
        df_curriculo = conn.read(worksheet="Curriculo", ttl=0)
        df_professores = conn.read(worksheet="Professores", ttl=0)
        df_dias = conn.read(worksheet="ConfigDias", ttl=0) # <--- NOVA TABELA
        
        # Criação de estrutura caso vazio
        if df_turmas.empty: df_turmas = pd.DataFrame(columns=["Escola", "Nivel", "NomeTurma", "Turno", "AnoBase"]) # Sem dia aqui
        if df_curriculo.empty: df_curriculo = pd.DataFrame(columns=["AnoBase", "Materia", "Quantidade"])
        if df_professores.empty: df_professores = pd.DataFrame(columns=["Codigo", "Nome", "Componentes", "CH_Aulas", "Qtd_PL"])
        if df_dias.empty: df_dias = pd.DataFrame(columns=["AnoBase", "DiaSemana"]) # <--- NOVA ESTRUTURA
        
        # Limpeza e Tratamento
        df_turmas = df_turmas.fillna("")
        df_curriculo = df_curriculo.fillna(0)
        df_professores = df_professores.fillna("")
        df_dias = df_dias.fillna("")
        
        if 'Nivel' not in df_turmas.columns and not df_turmas.empty:
             df_turmas['Nivel'] = "Ensino Fundamental"

        return df_turmas, df_curriculo, df_professores, df_dias

    except Exception as e:
        st.error(f"Erro na conexão com Google Sheets: {e}")
        st.warning("Verifique se você criou a aba nova 'ConfigDias' na planilha!")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def salvar_geral(df_t, df_c, df_p, df_d):
    """Salva todas as tabelas"""
    try:
        with st.spinner('Salvando no Banco de Dados...'):
            conn.update(worksheet="Turmas", data=df_t)
            conn.update(worksheet="Curriculo", data=df_c)
            conn.update(worksheet="Professores", data=df_p)
            conn.update(worksheet="ConfigDias", data=df_d)
            st.cache_data.clear()
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")

# --- Funções CRUD ---

def adicionar_turma(dado):
    dt, dc, dp, dd = carregar_dados()
    # Verifica se já existe turma igual para evitar duplicata visual
    dt = pd.concat([dt, pd.DataFrame([dado])], ignore_index=True)
    salvar_geral(dt, dc, dp, dd)

def salvar_curriculo_completo(ano, dia_semana, dict_quantidades):
    dt, dc, dp, dd = carregar_dados()
    
    # 1. Salva o DIA da semana para esse Ano (Planejamento em Rede)
    dd = dd[dd['AnoBase'] != ano] # Remove config anterior
    novo_dia = pd.DataFrame([{"AnoBase": ano, "DiaSemana": dia_semana}])
    dd = pd.concat([dd, novo_dia], ignore_index=True)

    # 2. Salva as QUANTIDADES de aulas
    dc = dc[dc['AnoBase'] != ano] # Remove currículo anterior
    novas_linhas = []
    for materia, qtd in dict_quantidades.items():
        if qtd > 0:
            novas_linhas.append({"AnoBase": ano, "Materia": materia, "Quantidade": qtd})
            
    if novas_linhas:
        dc = pd.concat([dc, pd.DataFrame(novas_linhas)], ignore_index=True)
    
    salvar_geral(dt, dc, dp, dd)

def adicionar_professor(dado):
    dt, dc, dp, dd = carregar_dados()
    dp = pd.concat([dp, pd.DataFrame([dado])], ignore_index=True)
    salvar_geral(dt, dc, dp, dd)

def limpar_tabela(aba):
    dt, dc, dp, dd = carregar_dados()
    if aba == 'Turmas': dt = dt.iloc[0:0]
    if aba == 'Curriculo': dc = dc.iloc[0:0] # Limpa as duas coisas ligadas a curriculo
    if aba == 'Professores': dp = dp.iloc[0:0]
    if aba == 'ConfigDias': dd = dd.iloc[0:0]
    salvar_geral(dt, dc, dp, dd)

# ==========================================
# 3. ALGORITMO
# ==========================================

def resolver_horario(turmas_do_dia, curriculo_df, recursos_max):
    for _ in range(5000):
        grade = {t['id']: [None]*5 for t in turmas_do_dia}
        uso_recursos = {p: {} for p in range(5)}
        
        turmas_random = turmas_do_dia.copy()
        random.shuffle(turmas_random)
        
        sucesso_global = True
        
        for turma in turmas_random:
            # Pega as aulas baseadas no Ano da turma
            curr_turma = curriculo_df[curriculo_df['AnoBase'] == turma['ano']]
            
            aulas_para_agendar = []
            for _, row in curr_turma.iterrows():
                qtd = int(row['Quantidade'])
                mat = row['Materia']
                aulas_para_agendar.extend([mat] * qtd)
            
            while len(aulas_para_agendar) < 5:
                aulas_para_agendar.append("---")
            
            aulas_para_agendar = aulas_para_agendar[:5]
            random.shuffle(aulas_para_agendar)
            
            slots_livres = [0, 1, 2, 3, 4]
            
            for materia in aulas_para_agendar:
                alocado = False
                random.shuffle(slots_livres)
                
                for slot in slots_livres:
                    if grade[turma['id']][slot] is not None: continue
                    
                    if materia == "---":
                        grade[turma['id']][slot] = "---"
                        alocado = True
                        slots_livres.remove(slot)
                        break
                    else:
                        qtd_usada = uso_recursos[slot].get(materia, 0)
                        capacidade = recursos_max.get(materia, 0)
                        if capacidade == 0: capacidade = 1
                        
                        if qtd_usada < capacidade:
                            grade[turma['id']][slot] = materia
                            uso_recursos[slot][materia] = qtd_usada + 1
                            alocado = True
                            slots_livres.remove(slot)
                            break
                
                if not alocado:
                    sucesso_global = False
                    break
            
            if not sucesso_global: break
            
        if sucesso_global: return grade
    return None

def formatar_visual(grade):
    if not grade: return pd.DataFrame()
    df = pd.DataFrame(grade)
    recreio = pd.DataFrame({col: ["RECREIO"] for col in df.columns}, index=[2.5])
    df = pd.concat([df.iloc[:3], recreio, df.iloc[3:]]).reset_index(drop=True)
    df.index = ["1ª Aula", "2ª Aula", "3ª Aula", "Recreio", "4ª Aula", "5ª Aula"]
    return df

# ==========================================
# 4. INTERFACE GRÁFICA
# ==========================================
st.set_page_config(page_title="Gerador Automático (Rede)", layout="wide")
st.title("🧩 Sistema de Planejamento em Rede")

# Carrega todas as 4 tabelas
dt, dc, dp, dd = carregar_dados()

# --- SIDEBAR ---
st.sidebar.header("🔄 Controle")
if st.sidebar.button("Atualizar Dados"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()
st.sidebar.header("🔢 Professores (Disponibilidade)")
recursos = {}
capacidade_calc = {m: 0 for m in MATERIAS_ESPECIALISTAS}

if not dp.empty and 'Componentes' in dp.columns:
    for _, row in dp.iterrows():
        lista = [x.strip() for x in str(row['Componentes']).split(',')]
        for item in lista:
            if item in MATERIAS_ESPECIALISTAS:
                capacidade_calc[item] += 1

for mat in MATERIAS_ESPECIALISTAS:
    val_inicial = capacidade_calc.get(mat, 0)
    if val_inicial == 0: val_inicial = 1
    recursos[mat] = st.number_input(f"{mat}", min_value=0, value=val_inicial, key=f"rec_{mat}")

# --- ABAS ---
t1, t2, t3, t4 = st.tabs(["1. Configuração de Rede (Dia/Aulas)", "2. Turmas", "3. Professores", "4. Gerar"])

# ABA 1: CONFIGURAÇÃO DE REDE
with t1:
    st.markdown("### Configuração por Ano/Série")
    st.info("Aqui você define o dia do planejamento e quantas aulas de cada especialista o ano tem.")
    
    ano_sel = st.selectbox("Selecione o Ano/Etapa:", [
        "Berçário", "Creche I", "Creche II", "Creche III", "Pré I", "Pré II",
        "1º Ano", "2º Ano", "3º Ano", "4º Ano", "5º Ano"
    ])
    
    # Recupera o dia atual salvo no banco, se houver
    dia_atual_bd = "Segunda-feira" # Padrão
    if not dd.empty:
        filtro_dia = dd[dd['AnoBase'] == ano_sel]
        if not filtro_dia.empty:
            dia_atual_bd = filtro_dia.iloc[0]['DiaSemana']

    st.markdown(f"#### 📅 1. Qual dia da semana é o planejamento do {ano_sel}?")
    dia_sel = st.selectbox("Dia da Semana:", 
                           ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira"],
                           index=["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira"].index(dia_atual_bd))
    
    st.markdown(f"#### 📚 2. Quais aulas o {ano_sel} tem nesse dia?")
    with st.form("form_rede"):
        col_inputs = st.columns(3)
        quantidades_input = {}
        idx = 0
        for mat in MATERIAS_ESPECIALISTAS:
            with col_inputs[idx % 3]:
                val_atual = 0
                if not dc.empty:
                    filtro = dc[(dc['AnoBase'] == ano_sel) & (dc['Materia'] == mat)]
                    if not filtro.empty:
                        val_atual = int(filtro.iloc[0]['Quantidade'])
                quantidades_input[mat] = st.number_input(f"{mat}", min_value=0, max_value=5, value=val_atual)
            idx += 1
            
        total_aulas = sum(quantidades_input.values())
        st.caption(f"Total: {total_aulas}/5 aulas.")
        
        if st.form_submit_button("💾 Salvar Configuração do Ano"):
            if total_aulas > 5:
                st.error("Máximo de 5 aulas!")
            else:
                salvar_curriculo_completo(ano_sel, dia_sel, quantidades_input)
                st.success(f"Configuração salva! Agora todas as turmas de {ano_sel} serão na {dia_sel}.")
                st.rerun()

    # Tabela Resumo
    if not dd.empty:
        st.write("---")
        st.write("**Planejamento Definido:**")
        st.dataframe(dd, use_container_width=True)

# ABA 2: TURMAS (SIMPLIFICADA)
with t2:
    st.markdown("### Cadastro de Turmas")
    st.caption("Note que não pedimos mais o dia da semana. O sistema pega isso automaticamente da Aba 1.")
    
    with st.form("nova_turma"):
        c1, c2 = st.columns(2)
        esc = c1.text_input("Escola")
        tnome = c2.text_input("Nome da Turma (Ex: A)")
        
        c3, c4 = st.columns(2)
        turno = c3.selectbox("Turno", ["Matutino", "Vespertino"])
        ano_base = c4.selectbox("Ano Base", [
            "Berçário", "Creche I", "Creche II", "Creche III", "Pré I", "Pré II",
            "1º Ano", "2º Ano", "3º Ano", "4º Ano", "5º Ano"
        ])
        
        if st.form_submit_button("➕ Adicionar Turma"):
            adicionar_turma({
                "Escola": esc, "NomeTurma": tnome, "Turno": turno, 
                "AnoBase": ano_base, 
                "Nivel": "Infantil" if "Creche" in ano_base or "Pré" in ano_base else "Fundamental"
            })
            st.success("Turma salva!")
            st.rerun()
            
    if not dt.empty:
        # Mostra o dia da semana junto na tabela (Cruzamento de dados)
        if not dd.empty:
            df_view = pd.merge(dt, dd, on="AnoBase", how="left")
            df_view = df_view.rename(columns={"DiaSemana": "Dia Planejamento (Automático)"})
        else:
            df_view = dt
        st.dataframe(df_view, use_container_width=True)
        
        if st.button("🗑️ Apagar Turmas"):
            limpar_tabela('Turmas')
            st.rerun()

# ABA 3: PROFESSORES
with t3:
    st.markdown("### Professores Especialistas")
    with st.form("novo_prof"):
        c1, c2 = st.columns([1,3])
        cod = c1.text_input("Código")
        nome = c2.text_input("Nome")
        comps = st.multiselect("Matérias:", MATERIAS_ESPECIALISTAS)
        if st.form_submit_button("💾 Salvar Professor"):
            if comps:
                adicionar_professor({"Codigo": cod, "Nome": nome, "Componentes": ", ".join(comps), "CH_Aulas": 0, "Qtd_PL": 0})
                st.success("Salvo!")
                st.rerun()
            else: st.error("Selecione matéria.")
    if not dp.empty:
        st.dataframe(dp, use_container_width=True)
        if st.button("🗑️ Apagar Profs"):
            limpar_tabela('Professores')
            st.rerun()

# ABA 4: GERAR
with t4:
    st.header("🚀 Gerar Horários")
    
    if st.button("PROCESSAR AGENDAMENTO", type="primary"):
        if dt.empty or dd.empty or dc.empty:
            st.error("Faltam dados! Verifique se configurou os Dias (Aba 1) e criou Turmas (Aba 2).")
        else:
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
                
                # Cruzar Turmas com a Configuração de Dias
                # Isso adiciona a coluna 'DiaSemana' em cada turma automaticamente
                df_completo = pd.merge(dt, dd, on="AnoBase", how="inner")
                
                turnos = df_completo['Turno'].unique()
                dias_possiveis = df_completo['DiaSemana'].unique()
                
                log_erros = []
                
                for turno in turnos:
                    for dia in dias_possiveis:
                        # Pega turmas que são desse turno E que o AnoBase delas cai nesse dia
                        filtro = df_completo[(df_completo['Turno'] == turno) & (df_completo['DiaSemana'] == dia)]
                        
                        if filtro.empty: continue
                        
                        lista_turmas = []
                        for _, row in filtro.iterrows():
                            lista_turmas.append({
                                'id': f"{row['Escola']} - {row['NomeTurma']} ({row['AnoBase']})",
                                'ano': row['AnoBase']
                            })
                        
                        resultado = resolver_horario(lista_turmas, dc, recursos)
                        
                        if resultado:
                            st.subheader(f"📅 {dia} - {turno}")
                            df_visual = formatar_visual(resultado)
                            st.dataframe(df_visual, use_container_width=True)
                            
                            sheet_name = f"{dia[:3]}_{turno[:3]}".replace("-", "")
                            df_visual.to_excel(writer, sheet_name=sheet_name)
                        else:
                            msg = f"❌ Falha em {dia} ({turno}): Sem professor suficiente."
                            st.error(msg)
                            log_erros.append(msg)
                
                if not log_erros:
                    st.success("Sucesso Total!")
            
            excel_buffer.seek(0)
            st.download_button("📥 Baixar Excel", excel_buffer, "Horario_Rede.xlsx")