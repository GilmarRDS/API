import streamlit as st
# Se der erro de importação: pip install streamlit-gsheets-connection
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import time
from datetime import datetime
import re
import random
import io
import xlsxwriter

# ==========================================
# 1. CONFIGURAÇÕES
# ==========================================
st.set_page_config(page_title="Gerador Escolar Pro", layout="wide")

MATERIAS_ESPECIALISTAS = [
    "ARTE", "EDUCAÇÃO FÍSICA", "ENSINO RELIGIOSO", 
    "LÍNGUA INGLESA", "CONTAÇÃO DE HISTÓRIA"
]

REGIOES = ["FUNDÃO", "PRAIA GRANDE", "TIMBUÍ"]

# NOMES PADRÃO (O sistema exige estes nomes exatos)
COLS_PADRAO = {
    "Turmas": ["ESCOLA", "NÍVEL", "TURMA", "TURNO", "SÉRIE/ANO", "REGIÃO"],
    "Curriculo": ["SÉRIE/ANO", "COMPONENTE", "QTD_AULAS"],
    "Professores": ["CÓDIGO", "NOME", "COMPONENTES", "CARGA_HORÁRIA", "REGIÃO", "VÍNCULO", "TURNO_FIXO", "ESCOLAS_ALOCADAS", "QTD_PL"],
    "ConfigDias": ["SÉRIE/ANO", "DIA_PLANEJAMENTO"],
    "Agrupamentos": ["NOME_ROTA", "LISTA_ESCOLAS"]
}

# ==========================================
# 2. CONEXÃO & UTILITÁRIOS
# ==========================================
conn = st.connection("gsheets", type=GSheetsConnection)

def definir_hora():
    st.session_state['hora_db'] = datetime.now().strftime("%H:%M:%S")

def padronizar(texto):
    if pd.isna(texto): return ""
    return str(texto).strip().upper()

def limpar_materia(nome):
    nome = padronizar(nome)
    nome = re.sub(r'\s*\(.*?\)', '', nome)
    if "ART" in nome: return "ARTE"
    if "FISICA" in nome or "FÍSICA" in nome: return "EDUCAÇÃO FÍSICA"
    if "INGLE" in nome: return "LÍNGUA INGLESA"
    if "RELIGIO" in nome: return "ENSINO RELIGIOSO"
    if "HIST" in nome and "CONT" in nome: return "CONTAÇÃO DE HISTÓRIA"
    return nome

# ==========================================
# 3. LEITURA COM DETETIVE DE ERROS
# ==========================================
def ler_aba_segura(aba, colunas_esperadas):
    try:
        # Lê a planilha bruta
        df = conn.read(worksheet=aba, ttl=0)
        
        if df.empty:
            # Se estiver vazia, cria a estrutura certa
            return pd.DataFrame(columns=colunas_esperadas), True
            
        # Padroniza os cabeçalhos que vieram do Excel (Maiúsculo e sem espaços nas pontas)
        df.columns = [str(c).strip().upper() for c in df.columns]
        
        # --- O DETETIVE ENTRA EM AÇÃO AQUI ---
        colunas_faltantes = []
        for col_esperada in colunas_esperadas:
            if col_esperada not in df.columns:
                colunas_faltantes.append(col_esperada)
        
        # Se faltar coluna, mostra o alerta detalhado
        if colunas_faltantes:
            st.error(f"🚨 **ERRO CRÍTICO NA ABA: '{aba}'**")
            st.markdown(f"❌ **O sistema precisa destas colunas e não encontrou:**")
            st.code(f"{', '.join(colunas_faltantes)}")
            
            st.markdown(f"👀 **O que tem lá no Excel agora:**")
            st.caption(f"{list(df.columns)}")
            
            st.warning("⚠️ **AÇÃO NECESSÁRIA:** Vá no Google Sheets e renomeie as colunas para ficar IGUAL ao texto vermelho acima.")
            st.divider()
            
            # Retorna Falso para bloquear o botão de salvar
            return pd.DataFrame(), False 
            
        # Se chegou aqui, está tudo certo. Filtra e limpa.
        df = df[colunas_esperadas]
        df = df.dropna(how='all')
        
        # Tipagem
        for c in df.columns:
            if c in ["QTD_AULAS", "CARGA_HORÁRIA", "QTD_PL"]:
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0).astype(int)
            else:
                df[c] = df[c].astype(str).apply(padronizar)
                
        return df, True # True = Pode salvar
        
    except Exception as e:
        st.error(f"Erro técnico ao ler {aba}: {e}")
        return pd.DataFrame(), False

@st.cache_data(ttl=60, show_spinner="Inspecionando Planilha...")
def carregar_banco():
    # Carrega cada aba e verifica se está saudável
    t, ok_t = ler_aba_segura("Turmas", COLS_PADRAO["Turmas"])
    c, ok_c = ler_aba_segura("Curriculo", COLS_PADRAO["Curriculo"])
    p, ok_p = ler_aba_segura("Professores", COLS_PADRAO["Professores"])
    d, ok_d = ler_aba_segura("ConfigDias", COLS_PADRAO["ConfigDias"])
    r, ok_r = ler_aba_segura("Agrupamentos", COLS_PADRAO["Agrupamentos"])
    
    # Só libera o sistema se TODAS as abas estiverem OK
    sistema_seguro = (ok_t and ok_c and ok_p and ok_d and ok_r)
    return t, c, p, d, r, sistema_seguro

def salvar_seguro(dt, dc, dp, dd, da):
    try:
        with st.spinner("Salvando..."):
            conn.update(worksheet="Turmas", data=dt)
            conn.update(worksheet="Curriculo", data=dc)
            conn.update(worksheet="Professores", data=dp)
            conn.update(worksheet="ConfigDias", data=dd)
            conn.update(worksheet="Agrupamentos", data=da)
            st.cache_data.clear()
            st.success("✅ Salvo com sucesso!")
            time.sleep(1)
            st.rerun()
    except Exception as e:
        if "429" in str(e): st.error("⚠️ Google ocupado. Espere 1 minuto.")
        else: st.error(f"Erro ao salvar: {e}")

def restaurar_cabecalhos_emergencia():
    """Botão de pânico que reescreve os cabeçalhos certos"""
    try:
        for aba, cols in COLS_PADRAO.items():
            try: df_raw = conn.read(worksheet=aba, ttl=0)
            except: df_raw = pd.DataFrame()
            
            # Se estiver vazio ou errado, recria
            if df_raw.empty:
                conn.update(worksheet=aba, data=pd.DataFrame(columns=cols))
            else:
                # Tenta aproveitar os dados se o numero de colunas bater
                if len(df_raw.columns) == len(cols):
                    df_raw.columns = cols
                    conn.update(worksheet=aba, data=df_raw)
                else:
                    # Se não bater, cria colunas novas
                    for c in cols: 
                        if c not in df_raw.columns: df_raw[c] = ""
                    conn.update(worksheet=aba, data=df_raw[cols])
        
        st.cache_data.clear()
        st.success("✅ Cabeçalhos corrigidos! O sistema deve funcionar agora.")
        time.sleep(2)
        st.rerun()
    except Exception as e:
        st.error(f"Erro ao restaurar: {e}")

# ==========================================
# 4. INTERFACE
# ==========================================
if 'hora_db' not in st.session_state: st.session_state['hora_db'] = datetime.now().strftime("%H:%M")

# Carrega Dados
dt, dc, dp, dd, da, sistema_seguro = carregar_banco()

st.sidebar.title("🛡️ Gestor Escolar")

if not sistema_seguro:
    st.error("🚫 O SISTEMA ESTÁ TRAVADO PARA SUA SEGURANÇA")
    st.info("Corrija os nomes das colunas no Google Sheets conforme os erros acima.")
    if st.button("🆘 Corrigir Cabeçalhos Automaticamente"):
        restaurar_cabecalhos_emergencia()
else:
    if st.sidebar.button("🔄 Atualizar"):
        st.cache_data.clear()
        st.rerun()

t1, t2, t3, t4, t5, t6 = st.tabs(["📊 Vagas", "⚙️ Config", "📍 Rotas", "🏫 Turmas", "👨‍🏫 Professores", "🚀 Gerar"])

def botao_salvar(label, key):
    if sistema_seguro:
        if st.button(label, key=key, type="primary"):
            salvar_seguro(dt, dc, dp, dd, da)
    else:
        st.button(f"🚫 {label} (Bloqueado)", key=key, disabled=True)

# 2. CONFIG
with t2:
    st.markdown("### ⚙️ Configuração")
    col_d, col_c = st.columns(2)
    with col_d:
        st.write("📅 **Dias**")
        if not dd.empty: dd = st.data_editor(dd, num_rows="dynamic", key="edd")
        with st.form("fd"):
            a = st.selectbox("Série", ["BERÇÁRIO", "CRECHE I", "CRECHE II", "CRECHE III", "PRÉ I", "PRÉ II", "1º ANO", "2º ANO", "3º ANO", "4º ANO", "5º ANO"])
            d = st.selectbox("Dia", ["SEGUNDA-FEIRA", "TERÇA-FEIRA", "QUARTA-FEIRA", "QUINTA-FEIRA", "SEXTA-FEIRA"])
            if st.form_submit_button("Add Dia"):
                if sistema_seguro:
                    dd = pd.concat([dd, pd.DataFrame([{"SÉRIE/ANO": a, "DIA_PLANEJAMENTO": d}])], ignore_index=True)
                    salvar_seguro(dt, dc, dp, dd, da)
    
    with col_c:
        st.write("📚 **Currículo**")
        if not dc.empty: dc = st.data_editor(dc, num_rows="dynamic", key="edc")
        with st.form("fc"):
            a = st.selectbox("Série", ["BERÇÁRIO", "CRECHE I", "CRECHE II", "CRECHE III", "PRÉ I", "PRÉ II", "1º ANO", "2º ANO", "3º ANO", "4º ANO", "5º ANO"], key="aca")
            m = st.selectbox("Matéria", MATERIAS_ESPECIALISTAS)
            q = st.number_input("Qtd", 1, 10, 2)
            if st.form_submit_button("Add Matéria"):
                if sistema_seguro:
                    dc = pd.concat([dc, pd.DataFrame([{"SÉRIE/ANO": a, "COMPONENTE": m, "QTD_AULAS": q}])], ignore_index=True)
                    salvar_seguro(dt, dc, dp, dd, da)
    
    botao_salvar("💾 Salvar Alterações Config", "btn_save_config")

# 3. ROTAS
with t3:
    if not da.empty: da = st.data_editor(da, num_rows="dynamic", key="edr")
    botao_salvar("💾 Salvar Rotas", "btn_save_rotas")
    
    with st.expander("Nova Rota"):
        with st.form("fr"):
            n = st.text_input("Nome Rota")
            l = st.multiselect("Escolas", sorted(dt['ESCOLA'].unique()) if not dt.empty else [])
            if st.form_submit_button("Criar"):
                if sistema_seguro:
                    da = pd.concat([da, pd.DataFrame([{"NOME_ROTA": n, "LISTA_ESCOLAS": ",".join(l)}])], ignore_index=True)
                    salvar_seguro(dt, dc, dp, dd, da)

# 4. TURMAS
with t4:
    st.markdown("### 🏫 Turmas")
    with st.expander("➕ Nova Turma", expanded=True):
        with st.form("ft"):
            c1,c2 = st.columns(2)
            e = c1.selectbox("Escola", sorted(dt['ESCOLA'].unique()) + ["NOVA..."] if not dt.empty else ["NOVA..."])
            if e=="NOVA...": e = c1.text_input("Nome Escola")
            t = c2.text_input("Turma (A, B...)")
            tn = st.selectbox("Turno", ["MATUTINO", "VESPERTINO"])
            an = st.selectbox("Ano", ["BERÇÁRIO", "CRECHE I", "CRECHE II", "CRECHE III", "PRÉ I", "PRÉ II", "1º ANO", "2º ANO", "3º ANO", "4º ANO", "5º ANO"])
            rg = st.selectbox("Região", REGIOES)
            if st.form_submit_button("Salvar"):
                if sistema_seguro:
                    nv = "INFANTIL" if "ANO" not in an else "FUNDAMENTAL"
                    dt = pd.concat([dt, pd.DataFrame([{"ESCOLA": padronizar(e), "TURMA": padronizar(t), "TURNO": tn, "SÉRIE/ANO": an, "REGIÃO": rg, "NÍVEL": nv}])], ignore_index=True)
                    salvar_seguro(dt, dc, dp, dd, da)
    
    if not dt.empty:
        dt = st.data_editor(dt, num_rows="dynamic", use_container_width=True, key="edt")
        botao_salvar("💾 Salvar Turmas", "btn_save_turmas")

# 5. PROFS
with t5:
    st.markdown("### 👨‍🏫 Professores")
    with st.expander("➕ Novo Professor", expanded=True):
        tp = st.radio("Vínculo", ["DT", "EFETIVO"], horizontal=True)
        with st.form("fp"):
            c1,c2 = st.columns([1,3])
            cd = c1.text_input("Cod")
            nm = c2.text_input("Nome")
            c3,c4 = st.columns(2)
            ch = st.number_input("CH", 1, 60, 25)
            pl = st.number_input("PL (Qtd)", 0, 10, 0)
            rg = st.selectbox("Região", REGIOES)
            cm = st.multiselect("Matérias", MATERIAS_ESPECIALISTAS)
            ef_esc = st.multiselect("Escola Fixa (Efetivo)", sorted(dt['ESCOLA'].unique()) if not dt.empty else [])
            ef_trn = st.selectbox("Turno Fixo", ["", "MATUTINO", "VESPERTINO", "AMBOS"])
            if st.form_submit_button("Salvar"):
                if sistema_seguro:
                    dp = pd.concat([dp, pd.DataFrame([{"CÓDIGO": cd, "NOME": padronizar(nm), "CARGA_HORÁRIA": ch, "QTD_PL": pl, "REGIÃO": rg, "COMPONENTES": ",".join(cm), "VÍNCULO": tp, "ESCOLAS_ALOCADAS": ",".join(ef_esc), "TURNO_FIXO": ef_trn}])], ignore_index=True)
                    salvar_seguro(dt, dc, dp, dd, da)
    
    if not dp.empty:
        dp = st.data_editor(dp, num_rows="dynamic", use_container_width=True, key="edp")
        botao_salvar("💾 Salvar Professores", "btn_save_profs")

# 1. VAGAS (Read Only)
with t1:
    st.header("📊 Quadro de Vagas")
    if dt.empty: st.warning("Sem dados.")
    else:
        sel = st.selectbox("Filtrar", ["Todas"] + sorted(dt['ESCOLA'].unique()))
        dem = {}
        alvo = dt if sel == "Todas" else dt[dt['ESCOLA']==sel]
        for _, r in alvo.iterrows():
            curr = dc[dc['SÉRIE/ANO'] == r['SÉRIE/ANO']]
            for _, i in curr.iterrows():
                m = limpar_materia(i['COMPONENTE'])
                dem[m] = dem.get(m, 0) + int(i['QTD_AULAS'])
        oferta = {}
        for _, p in dp.iterrows():
            if p['VÍNCULO'] == 'EFETIVO':
                if sel != "Todas" and sel not in str(p['ESCOLAS_ALOCADAS']): continue
                ms = [limpar_materia(x) for x in str(p['COMPONENTES']).split(',')]
                for m in ms: oferta[m] = oferta.get(m, 0) + int(p['CARGA_HORÁRIA'])
        res = []
        for m, q in dem.items():
            o = oferta.get(m, 0)
            res.append({"Matéria": m, "Demanda": q, "Efetivos": o, "Saldo DT": max(0, q-o)})
        st.dataframe(pd.DataFrame(res), use_container_width=True)

# 6. GERAR
def carregar_objetos_professores(df):
    lista = []
    for _, row in df.iterrows():
        mats = [limpar_materia(m) for m in str(row['COMPONENTES']).split(',')]
        for m in mats:
            if m in MATERIAS_ESPECIALISTAS:
                lista.append({
                    'id': str(row['CÓDIGO']), 'nome': row['NOME'], 'materia': m,
                    'regiao': row['REGIÃO'], 'vinculo': row.get('VÍNCULO','DT'),
                    'turno_fixo': row.get('TURNO_FIXO',''), 'escolas_fixas': str(row.get('ESCOLAS_ALOCADAS','')).split(','),
                    'max_aulas': int(row['CARGA_HORÁRIA']), 'aulas_atribuidas': 0, 'horarios_ocupados': [], 'escolas_atendidas_atual': set()
                })
    return lista

def carregar_mapa_rotas(df):
    m = {}
    for _, row in df.iterrows():
        escs = str(row['LISTA_ESCOLAS']).split(',')
        for e in escs: m[padronizar(e)] = [padronizar(x) for x in escs]
    return m

def resolver_grade(turmas, curriculo, profs, rotas, turno):
    turno = padronizar(turno)
    for p in profs: p['horarios_ocupados'] = []
    demandas = []
    for turma in turmas:
        curr = curriculo[curriculo['SÉRIE/ANO'] == turma['ano']]
        aulas = []
        for _, r in curr.iterrows():
            if r['QTD_AULAS'] > 0:
                aulas.extend([limpar_materia(r['COMPONENTE'])] * int(r['QTD_AULAS']))
        while len(aulas) < 5: aulas.append("---")
        for mat in aulas[:5]: demandas.append({'turma': turma, 'mat': mat, 'pri': 0 if mat=="---" else 1})
    demandas.sort(key=lambda x: x['pri'], reverse=True)
    
    for _ in range(500):
        grade = {t['nome_turma']: [None]*5 for t in turmas}
        profs_sim = [p.copy() for p in profs] 
        for p in profs_sim:
            p['horarios_ocupados'] = list(p['horarios_ocupados'])
            p['escolas_atendidas_atual'] = set(p['escolas_atendidas_atual'])
        random.shuffle(demandas)
        demandas.sort(key=lambda x: x['pri'], reverse=True)
        sucesso = True
        for item in demandas:
            turma, mat = item['turma'], item['mat']
            nm_t, esc, reg = turma['nome_turma'], turma['escola_real'], turma['regiao_real']
            slots = [i for i, v in enumerate(grade[nm_t]) if v is None]
            random.shuffle(slots)
            alocado = False
            if mat == "---":
                if slots: grade[nm_t][slots[0]] = "---"; alocado=True
            else:
                for slot in slots:
                    candidatos = []
                    for p in profs_sim:
                        if p['materia'] != mat: continue
                        score = 0
                        if p['vinculo'] == "EFETIVO":
                            if p['turno_fixo'] and p['turno_fixo'] not in ["AMBOS", ""] and p['turno_fixo'] != turno: continue
                            atende = False
                            for ef in p['escolas_fixas']:
                                if padronizar(ef) == padronizar(esc): atende=True
                            if atende: score += 2000
                            else: continue 
                        else:
                            if p['regiao'] != reg: continue
                            if slot in p['horarios_ocupados']: continue
                            if p['aulas_atribuidas'] >= p['max_aulas']: continue
                            if esc in p['escolas_atendidas_atual']: score += 100
                            elif any(x in p['escolas_atendidas_atual'] for x in rotas.get(esc,[])): score += 50
                            elif len(p['escolas_atendidas_atual']) == 0: score += 10
                        candidatos.append((score, p))
                    if candidatos:
                        candidatos.sort(key=lambda x: x[0], reverse=True)
                        best = candidatos[0][0]
                        escolhido = random.choice([c[1] for c in candidatos if c[0]==best])
                        lbl = escolhido['nome']
                        if escolhido['vinculo'] == "EFETIVO": lbl += " (Ef)"
                        grade[nm_t][slot] = f"{mat}\n{lbl}"
                        escolhido['horarios_ocupados'].append(slot)
                        escolhido['aulas_atribuidas'] += 1
                        escolhido['escolas_atendidas_atual'].add(esc)
                        alocado = True
                        break
            if not alocado: sucesso=False; break
        if sucesso: return True, grade, None, profs_sim
    return False, None, "Não foi possível alocar.", []

def desenhar_xls(writer, escola, dados):
    wb = writer.book
    ws = wb.add_worksheet(escola[:30].replace("/","-"))
    fmt = wb.add_format({'border':1, 'align':'center', 'text_wrap':True})
    r=0
    ws.write(r,0,escola, fmt); r+=2
    for tit, df in dados:
        ws.write(r,0,tit); r+=1
        for i, col in enumerate(df.columns): ws.write(r, i+1, col, fmt)
        r+=1
        for idx, row in df.iterrows():
            ws.write(r, 0, f"{idx+1}ª", fmt)
            for i, val in enumerate(row): ws.write(r, i+1, val if val else "", fmt)
            r+=1
        r+=1

def criar_preview_com_recreio(df):
    d = df.copy()
    top, bot = d.iloc[:3], d.iloc[3:]
    rec = pd.DataFrame([["RECREIO"]*len(d.columns)], columns=d.columns)
    final = pd.concat([top, rec, bot]).reset_index(drop=True)
    final.index = ["1ª", "2ª", "3ª", "INT", "4ª", "5ª"]
    return final

with t6:
    if sistema_seguro:
        if st.button("🚀 Gerar Grade", type="primary"):
            profs_obj = carregar_objetos_professores(dp)
            rotas_obj = carregar_mapa_rotas(da)
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
                merged = pd.merge(dt, dd, on="SÉRIE/ANO", how="inner")
                escolas = merged['ESCOLA'].unique()
                if len(escolas)==0: st.error("Erro cruzamento"); st.stop()
                prog = st.progress(0)
                for i, esc in enumerate(escolas):
                    prog.progress((i+1)/len(escolas))
                    df_e = merged[merged['ESCOLA'] == esc]
                    blocos = df_e[['DIA_PLANEJAMENTO', 'TURNO']].drop_duplicates()
                    dados_xls = []
                    for _, b in blocos.iterrows():
                        dia, turno = b['DIA_PLANEJAMENTO'], b['TURNO']
                        turmas = df_e[(df_e['DIA_PLANEJAMENTO']==dia) & (df_e['TURNO']==turno)]
                        lt = []
                        for _, row in turmas.iterrows():
                            lt.append({'nome_turma': row['TURMA'], 'ano': row['SÉRIE/ANO'], 'escola_real': esc, 'regiao_real': row['REGIÃO']})
                        suc, res, err, profs_obj = resolver_grade(lt, dc, profs_obj, rotas_obj, turno)
                        if suc: dados_xls.append((f"{turno}-{dia}", pd.DataFrame(res)))
                        else: st.warning(f"{esc}: {err}")
                    if dados_xls:
                        desenhar_xls(writer, esc, dados_xls)
                        st.write(f"**{esc}**")
                        for ti, dx in dados_xls:
                            st.caption(ti)
                            st.dataframe(criar_preview_com_recreio(dx))
                # Update Link
                mapa = {p['id']: ",".join(sorted(list(p['escolas_atendidas_atual']))) for p in profs_obj}
                df_new = dp.copy()
                for idx, r in df_new.iterrows():
                    if str(r['CÓDIGO']) in mapa: df_new.at[idx, 'ESCOLAS_ALOCADAS'] = mapa[str(r['CÓDIGO'])]
                try:
                    conn.update(worksheet="Professores", data=df_new)
                    st.success("Sucesso! Vínculos salvos.")
                except: pass
            buf.seek(0)
            st.download_button("Baixar Planilha", buf, "Grades.xlsx")
    else:
        st.error("Corrija as abas antes de gerar.")