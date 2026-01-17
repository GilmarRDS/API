import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import time
from datetime import datetime
import re
import random
import io
import xlsxwriter
import math

# ==========================================
# 1. CONFIGURAÇÕES & ESTILO
# ==========================================
st.set_page_config(page_title="Gerador Escolar Pro", page_icon="🎓", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #f8f9fa; }
    div[data-testid="stMetric"] {
        background-color: white; padding: 15px; border-radius: 10px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05); border: 1px solid #e0e0e0;
    }
    .stButton>button { border-radius: 8px; font-weight: 600; height: 3em; }
    .stDataFrame { border-radius: 10px; overflow: hidden; }
    .stAlert { border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

MATERIAS_ESPECIALISTAS = [
    "ARTE", "EDUCAÇÃO FÍSICA", "ENSINO RELIGIOSO", 
    "LÍNGUA INGLESA", "CONTAÇÃO DE HISTÓRIA"
]

REGIOES = ["FUNDÃO", "PRAIA GRANDE", "TIMBUÍ"]

ORDEM_SERIES = [
    "BERÇÁRIO", "CRECHE I", "CRECHE II", "CRECHE III", 
    "PRÉ I", "PRÉ II", 
    "1º ANO", "2º ANO", "3º ANO", "4º ANO", "5º ANO"
]

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
    st.session_state['hora_db'] = datetime.now().strftime("%H:%M")

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
# 3. LEITURA SEGURA
# ==========================================
def ler_aba_segura(aba, colunas_esperadas):
    try:
        df = conn.read(worksheet=aba, ttl=0)
        if df.empty: return pd.DataFrame(columns=colunas_esperadas), True
        
        df.columns = [str(c).strip().upper() for c in df.columns]
        
        colunas_faltantes = [c for c in colunas_esperadas if c not in df.columns]
        if colunas_faltantes:
            st.error(f"🚨 **ERRO ESTRUTURAL NA ABA: '{aba}'**")
            st.code(f"Faltam: {', '.join(colunas_faltantes)}")
            return pd.DataFrame(), False 
            
        df = df[colunas_esperadas]
        df = df.dropna(how='all')
        
        for c in df.columns:
            if c in ["QTD_AULAS", "CARGA_HORÁRIA", "QTD_PL"]:
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0).astype(int)
            else:
                df[c] = df[c].astype(str).apply(padronizar)
        return df, True
        
    except Exception as e:
        st.error(f"Erro técnico ao ler {aba}: {e}")
        return pd.DataFrame(), False

@st.cache_data(ttl=60, show_spinner=False)
def carregar_banco():
    with st.spinner("🔄 Sincronizando com a nuvem..."):
        t, ok_t = ler_aba_segura("Turmas", COLS_PADRAO["Turmas"])
        c, ok_c = ler_aba_segura("Curriculo", COLS_PADRAO["Curriculo"])
        p, ok_p = ler_aba_segura("Professores", COLS_PADRAO["Professores"])
        d, ok_d = ler_aba_segura("ConfigDias", COLS_PADRAO["ConfigDias"])
        r, ok_r = ler_aba_segura("Agrupamentos", COLS_PADRAO["Agrupamentos"])
    return t, c, p, d, r, (ok_t and ok_c and ok_p and ok_d and ok_r)

def salvar_seguro(dt, dc, dp, dd, da):
    try:
        with st.status("💾 Salvando alterações...", expanded=True) as status:
            conn.update(worksheet="Turmas", data=dt)
            conn.update(worksheet="Curriculo", data=dc)
            conn.update(worksheet="Professores", data=dp)
            conn.update(worksheet="ConfigDias", data=dd)
            conn.update(worksheet="Agrupamentos", data=da)
            
            st.cache_data.clear()
            definir_hora()
            status.update(label="✅ Salvo com sucesso!", state="complete", expanded=False)
        time.sleep(1)
        st.rerun()
    except Exception as e:
        if "429" in str(e): st.error("⚠️ Google bloqueou. Aguarde 1 minuto.")
        else: st.error(f"Erro ao salvar: {e}")

def restaurar_cabecalhos_emergencia():
    with st.status("🛠️ Reparando planilha...", expanded=True) as status:
        try:
            for aba, cols in COLS_PADRAO.items():
                try: df_raw = conn.read(worksheet=aba, ttl=0)
                except: df_raw = pd.DataFrame()
                
                if df_raw.empty:
                    conn.update(worksheet=aba, data=pd.DataFrame(columns=cols))
                else:
                    if len(df_raw.columns) == len(cols):
                        df_raw.columns = cols
                        conn.update(worksheet=aba, data=df_raw)
                    else:
                        for c in cols: 
                            if c not in df_raw.columns: df_raw[c] = ""
                        conn.update(worksheet=aba, data=df_raw[cols])
            st.cache_data.clear()
            status.update(label="✅ Restaurado!", state="complete", expanded=False)
            time.sleep(1)
            st.rerun()
        except Exception as e: st.error(f"Erro: {e}")

# ==========================================
# 4. INTERFACE VISUAL
# ==========================================
if 'hora_db' not in st.session_state: st.session_state['hora_db'] = datetime.now().strftime("%H:%M")

dt, dc, dp, dd, da, sistema_seguro = carregar_banco()

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2997/2997322.png", width=60)
    st.title("Gestor Escolar")
    st.markdown("---")
    if sistema_seguro: st.success("🟢 Sistema Online")
    else:
        st.error("🔴 Erro de Estrutura")
        if st.button("🛠️ Reparar"): restaurar_cabecalhos_emergencia()
    st.caption(f"Atualizado: {st.session_state['hora_db']}")
    if st.button("🔄 Atualizar"):
        st.cache_data.clear()
        st.rerun()

st.markdown("## 🎓 Painel de Controle")

t1, t2, t3, t4, t5, t6 = st.tabs([
    "📊 Dashboard RH", "⚙️ Config", "📍 Rotas", 
    "🏫 Turmas", "👨‍🏫 Professores", "🚀 Gerador"
])

def botao_salvar(label, key):
    if sistema_seguro:
        if st.button(label, key=key, type="primary", use_container_width=True):
            salvar_seguro(dt, dc, dp, dd, da)
    else: st.button(f"🔒 {label}", key=key, disabled=True, use_container_width=True)

# 1. DASHBOARD / VAGAS
with t1:
    if dt.empty:
        st.info("👋 Cadastre turmas para ver o painel.")
    else:
        st.markdown("##### 🔍 Filtros de Visualização")
        c1, c2, c3, c4, c5 = st.columns(5)
        
        with c1:
            regioes_disp = sorted(dt['REGIÃO'].unique().tolist())
            sel_regiao = st.multiselect("🌍 Região", regioes_disp, placeholder="Todas")
            
        with c2:
            df_escolas = dt[dt['REGIÃO'].isin(sel_regiao)] if sel_regiao else dt
            escolas_disp = ["Rede Completa"] + sorted(df_escolas['ESCOLA'].unique().tolist())
            sel_escola = st.selectbox("🏢 Escola", escolas_disp)
            
        with c3:
            niveis = ["Todos"] + sorted(dt['NÍVEL'].unique().tolist())
            sel_nivel = st.selectbox("👶/👦 Nível", niveis)
            
        with c4:
            series_raw = dt['SÉRIE/ANO'].unique().tolist()
            series_ord = sorted(series_raw, key=lambda x: ORDEM_SERIES.index(x) if x in ORDEM_SERIES else 99)
            sel_serie = st.selectbox("📚 Série/Ano", ["Todas"] + series_ord)
            
        with c5:
            df_turmas = dt.copy()
            if sel_regiao: df_turmas = df_turmas[df_turmas['REGIÃO'].isin(sel_regiao)]
            if sel_escola != "Rede Completa": df_turmas = df_turmas[df_turmas['ESCOLA'] == sel_escola]
            if sel_serie != "Todas": df_turmas = df_turmas[df_turmas['SÉRIE/ANO'] == sel_serie]
            
            turmas_disp = ["Todas"] + sorted(df_turmas['TURMA'].unique().tolist())
            sel_turma = st.selectbox("🔠 Turma", turmas_disp)
        
        st.markdown("---")

        alvo = dt.copy()
        if sel_regiao: alvo = alvo[alvo['REGIÃO'].isin(sel_regiao)]
        if sel_escola != "Rede Completa": alvo = alvo[alvo['ESCOLA'] == sel_escola]
        if sel_nivel != "Todos": alvo = alvo[alvo['NÍVEL'] == sel_nivel]
        if sel_serie != "Todas": alvo = alvo[alvo['SÉRIE/ANO'] == sel_serie]
        if sel_turma != "Todas": alvo = alvo[alvo['TURMA'] == sel_turma]
            
        dem = {}
        total_aulas_demanda = 0
        for _, r in alvo.iterrows():
            curr = dc[dc['SÉRIE/ANO'] == r['SÉRIE/ANO']]
            for _, i in curr.iterrows():
                m = limpar_materia(i['COMPONENTE'])
                qtd = int(i['QTD_AULAS'])
                dem[m] = dem.get(m, 0) + qtd
                total_aulas_demanda += qtd
        
        oferta = {}
        total_aulas_oferta = 0
        
        for _, p in dp.iterrows():
            if sel_regiao and p['REGIÃO'] not in sel_regiao: continue
            if p['VÍNCULO'] == 'EFETIVO':
                if sel_escola != "Rede Completa" and sel_escola not in str(p['ESCOLAS_ALOCADAS']): continue
            
            ms = [limpar_materia(x) for x in str(p['COMPONENTES']).split(',')]
            ch_total = int(p['CARGA_HORÁRIA'])
            
            if len(ms) > 0:
                ch_por_materia = ch_total / len(ms)
                for m in ms: 
                    oferta[m] = oferta.get(m, 0) + ch_por_materia
                total_aulas_oferta += ch_total
        
        col_metrics, col_rh = st.columns([3, 1])
        with col_rh:
            st.markdown("⚙️ **Planejamento**")
            ch_padrao = st.slider("Média de Aulas por Professor", min_value=5, max_value=40, value=20, help="Use este valor para estimar contratações.")
        
        with col_metrics:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Turmas", len(alvo))
            m2.metric("Demanda Total", f"{total_aulas_demanda} Aulas")
            m3.metric("Oferta Atual", f"{int(total_aulas_oferta)} Aulas")
            
            deficit_aulas = max(0, total_aulas_demanda - total_aulas_oferta)
            profs_estimados_total = math.ceil(deficit_aulas / ch_padrao) if deficit_aulas > 0 else 0
            
            m4.metric("Déficit Geral", f"{int(deficit_aulas)} Aulas", delta_color="inverse")

        if deficit_aulas > 0:
            st.info(f"💡 Para cobrir a falta de **{int(deficit_aulas)} aulas**, considerando uma média de {ch_padrao} aulas/prof, estima-se contratar **{profs_estimados_total} Professores (DTs)**.")
        else:
            st.success("✅ A carga horária atual cobre a demanda das turmas selecionadas.")

        st.markdown("### 📋 Quadro de Necessidades por Disciplina")
        res = []
        for m, q in dem.items():
            o = oferta.get(m, 0)
            saldo = q - o
            
            if saldo > 0:
                qtd_contratar = saldo / ch_padrao
                status = "🔴 Contratar"
            else:
                qtd_contratar = 0
                status = "🟢 Completo"
                
            res.append({
                "Disciplina": m, 
                "Demanda (Aulas)": q, 
                "Oferta (Aulas)": round(o, 1), 
                "Saldo (Aulas)": round(saldo, 1), 
                "Est. Contratação": round(qtd_contratar, 1),
                "Situação": status
            })
        
        df_res = pd.DataFrame(res)
        if not df_res.empty:
            st.dataframe(
                df_res, use_container_width=True, hide_index=True,
                column_config={
                    "Saldo (Aulas)": st.column_config.NumberColumn("Falta (Aulas)", format="%d"),
                    "Est. Contratação": st.column_config.NumberColumn("Novos Profs (Qtd)", format="%.1f"),
                    "Situação": st.column_config.TextColumn("Status")
                }
            )
        else:
            st.info("Nenhuma demanda encontrada.")

# 2. CONFIG
with t2:
    col_d, col_c = st.columns(2)
    with col_d:
        with st.container(border=True):
            st.subheader("📅 Dias de Planejamento")
            st.info("Selecione a linha e aperte **Delete** para apagar.")
            if not dd.empty: dd = st.data_editor(dd, num_rows="dynamic", use_container_width=True, key="edd", hide_index=True)
            with st.popover("➕ Adicionar"):
                with st.form("fd"):
                    a = st.selectbox("Série", ORDEM_SERIES)
                    d = st.selectbox("Dia", ["SEGUNDA-FEIRA", "TERÇA-FEIRA", "QUARTA-FEIRA", "QUINTA-FEIRA", "SEXTA-FEIRA"])
                    if st.form_submit_button("Add"):
                        if sistema_seguro:
                            dd = pd.concat([dd, pd.DataFrame([{"SÉRIE/ANO": a, "DIA_PLANEJAMENTO": d}])], ignore_index=True)
                            salvar_seguro(dt, dc, dp, dd, da)
    with col_c:
        with st.container(border=True):
            st.subheader("📚 Currículo")
            st.info("Selecione a linha e aperte **Delete** para apagar.")
            if not dc.empty: dc = st.data_editor(dc, num_rows="dynamic", use_container_width=True, key="edc", hide_index=True)
            with st.popover("➕ Adicionar"):
                with st.form("fc"):
                    a = st.selectbox("Série", ORDEM_SERIES, key="aca")
                    m = st.selectbox("Matéria", MATERIAS_ESPECIALISTAS)
                    q = st.number_input("Qtd", 1, 10, 2)
                    if st.form_submit_button("Add"):
                        if sistema_seguro:
                            dc = pd.concat([dc, pd.DataFrame([{"SÉRIE/ANO": a, "COMPONENTE": m, "QTD_AULAS": q}])], ignore_index=True)
                            salvar_seguro(dt, dc, dp, dd, da)
    st.markdown("###"); botao_salvar("💾 Salvar Configurações", "btn_save_config")

# 3. ROTAS
with t3:
    c_lista, c_form = st.columns([2,1])
    with c_lista:
        if not da.empty: da = st.data_editor(da, num_rows="dynamic", use_container_width=True, key="edr", hide_index=True)
    with c_form:
        with st.container(border=True):
            st.write("Nova Rota")
            n = st.text_input("Nome Rota")
            l = st.multiselect("Escolas", sorted(dt['ESCOLA'].unique()) if not dt.empty else [])
            if st.button("Criar", use_container_width=True):
                if sistema_seguro:
                    da = pd.concat([da, pd.DataFrame([{"NOME_ROTA": n, "LISTA_ESCOLAS": ",".join(l)}])], ignore_index=True)
                    salvar_seguro(dt, dc, dp, dd, da)
    st.markdown("###"); botao_salvar("💾 Salvar Rotas", "btn_save_rotas")

# 4. TURMAS
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
                if sistema_seguro:
                    nv = "INFANTIL" if "ANO" not in an else "FUNDAMENTAL"
                    dt = pd.concat([dt, pd.DataFrame([{"ESCOLA": padronizar(e), "TURMA": padronizar(t), "TURNO": tn, "SÉRIE/ANO": an, "REGIÃO": rg, "NÍVEL": nv}])], ignore_index=True)
                    salvar_seguro(dt, dc, dp, dd, da)
    if not dt.empty:
        st.info("🗑️ **Para Excluir:** Selecione a linha (clique no número à esquerda) e aperte **Delete** no teclado.")
        dt = st.data_editor(dt, num_rows="dynamic", use_container_width=True, key="edt", hide_index=True)
        botao_salvar("💾 Salvar Turmas", "btn_save_turmas")

# 5. PROFS
with t5:
    with st.expander("➕ Novo Professor", expanded=False):
        tp = st.radio("Vínculo", ["DT", "EFETIVO"], horizontal=True)
        with st.form("fp"):
            c1,c2 = st.columns([1,3])
            cd = c1.text_input("Cod")
            nm = c2.text_input("Nome")
            c3,c4,c5 = st.columns(3)
            ch = c3.number_input("Qtd. Aulas (Carga)", 1, 60, 20)
            pl = c4.number_input("PL (Planejamento)", 0, 10, 0)
            rg = c5.selectbox("Região", REGIOES)
            cm = st.multiselect("Matérias", MATERIAS_ESPECIALISTAS)
            
            if tp == "EFETIVO":
                ef_esc = st.multiselect("Escola Fixa (Efetivo)", sorted(dt['ESCOLA'].unique()) if not dt.empty else [])
                ef_trn = st.selectbox("Turno Fixo", ["", "MATUTINO", "VESPERTINO", "AMBOS"])
            else:
                ef_esc = []
                ef_trn = ""
                
            if st.form_submit_button("Salvar"):
                if sistema_seguro:
                    str_esc = ",".join(ef_esc) if ef_esc else ""
                    dp = pd.concat([dp, pd.DataFrame([{"CÓDIGO": cd, "NOME": padronizar(nm), "CARGA_HORÁRIA": ch, "QTD_PL": pl, "REGIÃO": rg, "COMPONENTES": ",".join(cm), "VÍNCULO": tp, "ESCOLAS_ALOCADAS": str_esc, "TURNO_FIXO": ef_trn}])], ignore_index=True)
                    salvar_seguro(dt, dc, dp, dd, da)
                    
    if not dp.empty:
        st.info("🗑️ **Para Excluir:** Selecione a linha (clique no número à esquerda) e aperte **Delete** no teclado.")
        dp = st.data_editor(dp, num_rows="dynamic", use_container_width=True, key="edp", hide_index=True, column_config={"CARGA_HORÁRIA": st.column_config.NumberColumn("Aulas", format="%d"), "QTD_PL": st.column_config.NumberColumn("PL", format="%d")})
        botao_salvar("💾 Salvar Professores", "btn_save_profs")

# 6. GERAR
def carregar_objs(df):
    l = []
    for _, r in df.iterrows():
        ms = [limpar_materia(m) for m in str(r['COMPONENTES']).split(',')]
        for m in ms:
            if m in MATERIAS_ESPECIALISTAS:
                l.append({
                    'id': str(r['CÓDIGO']), 'nome': r['NOME'], 'mat': m,
                    'reg': r['REGIÃO'], 'vin': r['VÍNCULO'],
                    'tf': r['TURNO_FIXO'], 'ef': str(r['ESCOLAS_ALOCADAS']).split(','),
                    'max': int(r['CARGA_HORÁRIA']), 'atrib': 0, 'ocup': [], 'escolas': set(), 'turnos_ativos': set()
                })
    return l

def carregar_rotas(df):
    m = {}
    for _, row in df.iterrows():
        escs = str(row['LISTA_ESCOLAS']).split(',')
        for e in escs: m[padronizar(e)] = [padronizar(x) for x in escs]
    return m

def resolver_grade(turmas, curriculo, profs, rotas, turno_atual):
    turno_atual = padronizar(turno_atual)
    for p in profs: p['ocup'] = [] # Reseta ocupação por dia/bloco
    
    demandas = []
    for turma in turmas:
        curr = curriculo[curriculo['SÉRIE/ANO'] == turma['ano']]
        aulas = []
        for _, r in curr.iterrows():
            if r['QTD_AULAS'] > 0: aulas.extend([limpar_materia(r['COMPONENTE'])] * int(r['QTD_AULAS']))
        while len(aulas) < 5: aulas.append("---")
        for mat in aulas[:5]: demandas.append({'turma': turma, 'mat': mat, 'pri': 0 if mat=="---" else 1})
    
    demandas.sort(key=lambda x: x['pri'], reverse=True)
    
    for _ in range(500):
        grade = {t['nome_turma']: [None]*5 for t in turmas}
        profs_sim = [p.copy() for p in profs]
        for p in profs_sim: 
            p['ocup'] = list(p['ocup'])
            p['escolas'] = set(p['escolas'])
            p['turnos_ativos'] = set(p['turnos_ativos'])
        
        random.shuffle(demandas)
        demandas.sort(key=lambda x: x['pri'], reverse=True)
        sucesso = True
        motivo_falha = ""
        
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
                        if p['mat'] != mat: continue
                        score = 0
                        
                        # --- REGRAS INTELIGENTES ---
                        if p['vin'] == "EFETIVO":
                            if p['tf'] and p['tf'] not in ["AMBOS", ""] and p['tf'] != turno_atual: continue
                            atende = False
                            for ef in p['ef']:
                                if padronizar(ef) == padronizar(esc): atende = True
                            if atende: score += 2000
                            else: continue 
                        else:
                            # DT - Lógica Volante
                            if p['reg'] != reg: continue 
                            if slot in p['ocup']: continue 
                            if p['atrib'] >= p['max']: continue 
                            
                            # Inteligência de Rota e Turno
                            if esc in p['escolas']: score += 1000 # Já está na escola
                            elif any(x in p['escolas'] for x in rotas.get(esc,[])): score += 500 # Está na vizinhança
                            
                            # Prioriza quem já está nesse turno em outro lugar (para fechar a agenda)
                            if turno_atual in p['turnos_ativos']: score += 200
                            elif len(p['escolas']) == 0: score += 50 # Começar novo
                        
                        candidatos.append((score, p))
                    
                    if candidatos:
                        candidatos.sort(key=lambda x: x[0], reverse=True)
                        escolhido = random.choice([c[1] for c in candidatos if c[0]==candidatos[0][0]])
                        
                        lbl = escolhido['nome']
                        if escolhido['vin'] == "EFETIVO": lbl += " (Ef)"
                        grade[nm_t][slot] = f"{mat}\n{lbl}"
                        
                        escolhido['ocup'].append(slot)
                        escolhido['atrib'] += 1
                        escolhido['escolas'].add(esc)
                        escolhido['turnos_ativos'].add(turno_atual)
                        alocado = True
                        break
            
            if not alocado:
                motivo_falha = f"Falta Prof: **{mat}** em {esc}"
                sucesso = False
                break
        
        if sucesso: return True, grade, None, profs_sim
        
    return False, None, motivo_falha, []

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

with t6:
    if sistema_seguro:
        if st.button("🚀 Gerar Grade"):
            with st.status("Gerando...", expanded=True) as status:
                profs_obj = carregar_objs(dp)
                rotas_obj = carregar_rotas(da)
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
                    merged = pd.merge(dt, dd, on="SÉRIE/ANO", how="inner")
                    escolas = merged['ESCOLA'].unique()
                    
                    if len(escolas) == 0:
                        st.error("Nenhuma turma tem dia de planejamento.")
                        st.stop()
                    
                    prog = st.progress(0)
                    for i, esc in enumerate(escolas):
                        prog.progress((i+1)/len(escolas))
                        st.write(f"Processando {esc}...")
                        df_e = merged[merged['ESCOLA'] == esc]
                        blocos = df_e[['DIA_PLANEJAMENTO', 'TURNO']].drop_duplicates()
                        dados_xls = []
                        
                        for _, b in blocos.iterrows():
                            dia, turno = b['DIA_PLANEJAMENTO'], b['TURNO']
                            turmas = df_e[(df_e['DIA_PLANEJAMENTO']==dia) & (df_e['TURNO']==turno)]
                            lt = []
                            for _, row in turmas.iterrows(): lt.append({'nome_turma': row['TURMA'], 'ano': row['SÉRIE/ANO'], 'escola_real': esc, 'regiao_real': row['REGIÃO']})
                            
                            suc, res, err, profs_obj = resolver_grade(lt, dc, profs_obj, rotas_obj, turno)
                            
                            if suc: dados_xls.append((f"{turno}-{dia}", pd.DataFrame(res)))
                            else: st.warning(f"{esc}: {err}")
                        
                        if dados_xls:
                            desenhar_xls(writer, esc, dados_xls)
                    
                    # Atualiza Planilha
                    mapa = {p['id']: ",".join(sorted(list(p['escolas']))) for p in profs_obj}
                    df_new = dp.copy()
                    for idx, r in df_new.iterrows():
                        if str(r['CÓDIGO']) in mapa: df_new.at[idx, 'ESCOLAS_ALOCADAS'] = mapa[str(r['CÓDIGO'])]
                    try: conn.update(worksheet="Professores", data=df_new)
                    except: pass
                
                status.update(label="Concluído!", state="complete")
            
            st.success("Feito!")
            buf.seek(0)
            st.download_button("Baixar", buf, "Grades.xlsx")