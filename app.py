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
# 2. BANCO DE DADOS
# ==========================================

conn = st.connection("gsheets", type=GSheetsConnection)

def carregar_dados():
    try:
        df_turmas = conn.read(worksheet="Turmas", ttl=0)
        df_curriculo = conn.read(worksheet="Curriculo", ttl=0)
        df_professores = conn.read(worksheet="Professores", ttl=0)
        df_dias = conn.read(worksheet="ConfigDias", ttl=0)
        
        if df_turmas.empty: df_turmas = pd.DataFrame(columns=["Escola", "Nivel", "NomeTurma", "Turno", "AnoBase"])
        if df_curriculo.empty: df_curriculo = pd.DataFrame(columns=["AnoBase", "Materia", "Quantidade"])
        # VOLTEI COM CH_AULAS E QTD_PL AQUI
        if df_professores.empty: df_professores = pd.DataFrame(columns=["Codigo", "Nome", "Componentes", "CH_Aulas", "Qtd_PL"])
        if df_dias.empty: df_dias = pd.DataFrame(columns=["AnoBase", "DiaSemana"])
        
        # Tratamento
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
        with st.spinner('Salvando...'):
            conn.update(worksheet="Turmas", data=df_t)
            conn.update(worksheet="Curriculo", data=df_c)
            conn.update(worksheet="Professores", data=df_p)
            conn.update(worksheet="ConfigDias", data=df_d)
            st.cache_data.clear()
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
# 3. ALGORITMO (AGORA RESPEITA CH)
# ==========================================

def carregar_objetos_professores(df_prof):
    lista_profs = []
    for _, row in df_prof.iterrows():
        materias = [m.strip() for m in str(row['Componentes']).split(',')]
        
        # Garante que CH seja número (se estiver vazio, assume infinito/sem limite)
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
                    'max_aulas': ch_limite, # LIMITE DE AULAS
                    'aulas_atribuidas': 0,  # CONTADOR
                    'horarios_ocupados': []
                })
    return lista_profs

def resolver_horario_grade(turmas_do_dia, curriculo_df, lista_professores):
    # Reseta estado DIÁRIO (ocupação de horário), mas NÃO o contador total de aulas se fossemos fazer semanal.
    # Como o sistema gera por "turno/dia", vamos considerar que o limite CH é global.
    # OBS: Para ser perfeito, o contador 'aulas_atribuidas' deveria persistir entre os dias.
    # Aqui, para simplificar, ele reinicia por rodada, mas já serve para bloquear conflito no mesmo dia.
    
    for p in lista_professores:
        p['horarios_ocupados'] = []
        # p['aulas_atribuidas'] = 0 # Se quiser reiniciar a contagem a cada dia gerado, descomente.

    grade_final = {t['nome_turma']: ["---"]*5 for t in turmas_do_dia}
    
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

    for _ in range(100): 
        grade_tentativa = {k: v[:] for k, v in grade_final.items()}
        
        # Copia lista de professores para simular essa tentativa
        # Importante: Precisamos copiar o dicionário profundamente para não alterar o original se falhar
        professores_temp = []
        for p in lista_professores:
            professores_temp.append(p.copy())
            professores_temp[-1]['horarios_ocupados'] = list(p['horarios_ocupados']) # Copia a lista também
        
        sucesso = True
        
        for slot in range(5):
            turmas_embaralhadas = list(demandas.keys())
            random.shuffle(turmas_embaralhadas)
            
            for nome_turma in turmas_embaralhadas:
                materia_desejada = demandas[nome_turma][slot]
                
                if materia_desejada == "---":
                    grade_tentativa[nome_turma][slot] = "---"
                    continue
                
                # Filtra Candidatos Válidos:
                # 1. Dá a matéria certa
                # 2. Livre neste horário
                # 3. Não estourou a Carga Horária (CH)
                candidatos = []
                for p in professores_temp:
                    if (p['materia'] == materia_desejada and 
                        slot not in p['horarios_ocupados'] and 
                        p['aulas_atribuidas'] < p['max_aulas']):
                        candidatos.append(p)
                
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
st.set_page_config(page_title="Gerador Grade Excel", layout="wide")
st.title("🎓 Gerador de Horários (Rede)")

dt, dc, dp, dd = carregar_dados()

# --- SIDEBAR ---
if st.sidebar.button("🔄 Atualizar"):
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
    st.info("Defina o dia que o **REGENTE** planeja (sai de sala) e quais especialistas entram.")
    
    ano_sel = st.selectbox("Ano:", ["Berçário", "Creche I", "Creche II", "Creche III", "Pré I", "Pré II", "1º Ano", "2º Ano", "3º Ano", "4º Ano", "5º Ano"])
    
    dia_atual = "Segunda-feira"
    if not dd.empty:
        f = dd[dd['AnoBase'] == ano_sel]
        if not f.empty: dia_atual = f.iloc[0]['DiaSemana']

    dia_sel = st.selectbox("Dia Planejamento (Regente):", ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira"], index=["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira"].index(dia_atual))
    
    st.divider()
    st.write(f"**Quantidades de Aulas para {ano_sel}:**")
    
    with st.form("conf"):
        col_inp = st.columns(3)
        qts = {}
        i=0
        for mat in MATERIAS_ESPECIALISTAS:
            with col_inp[i%3]:
                v=0
                if not dc.empty:
                    f = dc[(dc['AnoBase']==ano_sel) & (dc['Materia']==mat)]
                    if not f.empty: v = int(f.iloc[0]['Quantidade'])
                qts[mat] = st.number_input(f"{mat}", 0, 5, v)
            i+=1
        
        st.caption("Dica: Se for Creche, preencha apenas as matérias (Infantil).")
        
        if st.form_submit_button("Salvar Configuração"):
            salvar_curriculo_completo(ano_sel, dia_sel, qts)
            st.success("Salvo!")
            st.rerun()

with t2:
    st.markdown("### Turmas")
    with st.form("nt"):
        c1,c2 = st.columns(2)
        esc = c1.text_input("Escola")
        tnm = c2.text_input("Turma (Ex: A)")
        c3,c4 = st.columns(2)
        trn = c3.selectbox("Turno", ["Matutino", "Vespertino"])
        ano = c4.selectbox("Ano", ["Berçário", "Creche I", "Creche II", "Creche III", "Pré I", "Pré II", "1º Ano", "2º Ano", "3º Ano", "4º Ano", "5º Ano"])
        if st.form_submit_button("Adicionar"):
            adicionar_turma({"Escola": esc, "NomeTurma": tnm, "Turno": trn, "AnoBase": ano})
            st.success("Salvo!")
            st.rerun()
    if not dt.empty:
        st.dataframe(dt, use_container_width=True)
        if st.button("Limpar Turmas"):
            limpar_tabela('Turmas')
            st.rerun()

with t3:
    st.markdown("### Professores (Especialistas)")
    with st.form("np"):
        c_cod, c_nom = st.columns([1, 3])
        cod = c_cod.text_input("Cód. Professor") 
        nm = c_nom.text_input("Nome do Professor")
        
        c_ch, c_pl = st.columns(2)
        # NOVOS CAMPOS AQUI
        ch = c_ch.number_input("CH Aulas (Máximo de aulas em sala)", min_value=1, value=13)
        pl = c_pl.number_input("Qtd. PLs", min_value=0, value=7)

        st.write("Selecione as matérias que ele pode dar:")
        cps = st.multiselect("Matérias:", MATERIAS_ESPECIALISTAS)
        
        if st.form_submit_button("Salvar Professor"):
            if cps and nm:
                adicionar_professor({
                    "Codigo": cod, 
                    "Nome": nm, 
                    "Componentes": ",".join(cps),
                    "CH_Aulas": ch,   # Salvando
                    "Qtd_PL": pl      # Salvando
                })
                st.success("Salvo!")
                st.rerun()
            else:
                st.error("Preencha Nome e Matérias.")
                
    if not dp.empty:
        st.dataframe(dp, use_container_width=True)
        if st.button("Limpar Professores"):
            limpar_tabela('Professores')
            st.rerun()

with t4:
    st.header("🚀 Gerar Grade")
    
    if st.button("GERAR TABELA", type="primary"):
        if dt.empty or dp.empty:
            st.error("Cadastre turmas e professores primeiro.")
        else:
            objs_profs = carregar_objetos_professores(dp)
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                
                df_full = pd.merge(dt, dd, on="AnoBase", how="inner")
                turnos = df_full['Turno'].unique()
                dias = df_full['DiaSemana'].unique()
                erros = []
                
                for turno in turnos:
                    for dia in dias:
                        filtro = df_full[(df_full['Turno'] == turno) & (df_full['DiaSemana'] == dia)]
                        if filtro.empty: continue
                        
                        lista_turmas = []
                        for _, row in filtro.iterrows():
                            nome_coluna = f"{row['AnoBase']} {row['NomeTurma']} ({row['Escola'][:5]})"
                            lista_turmas.append({'nome_turma': nome_coluna, 'ano': row['AnoBase']})
                        
                        resultado = resolver_horario_grade(lista_turmas, dc, objs_profs)
                        
                        if resultado:
                            st.subheader(f"📅 {dia} - {turno}")
                            df_excel = formatar_para_excel_grade(resultado)
                            st.dataframe(df_excel, use_container_width=True)
                            sheet_nm = f"{dia[:3]}_{turno[:3]}".replace("-","")
                            df_excel.to_excel(writer, sheet_name=sheet_nm)
                        else:
                            msg = f"❌ {dia}/{turno}: Falta professor (ou CH estourada) para a demanda."
                            st.error(msg)
                            erros.append(msg)
                
                if not erros:
                    st.success("Tabelas geradas!")
                    
            buffer.seek(0)
            st.download_button("📥 Baixar Planilha Pronta", buffer, "Horario_Grade_Final.xlsx")