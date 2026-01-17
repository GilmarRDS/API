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
import copy

# ==========================================
# 1. CONFIGURAÇÕES & ESTILO
# ==========================================
st.set_page_config(page_title="Gerador Escolar Pro", page_icon="🎓", layout="wide")

# --- CORREÇÃO DO ERRO (INICIALIZAÇÃO DO ESTADO) ---
if 'hora_db' not in st.session_state:
    st.session_state['hora_db'] = datetime.now().strftime("%H:%M")

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
    txt = str(texto).strip().upper()
    if txt == "NAN": return ""
    return " ".join(txt.split())

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
            st.error(f"🚨 Faltam colunas na aba {aba}: {colunas_faltantes}")
            return pd.DataFrame(), False
            
        df = df[colunas_esperadas].dropna(how='all').fillna("")
        
        for c in df.columns:
            if c in ["QTD_AULAS", "CARGA_HORÁRIA", "QTD_PL"]:
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0).astype(int)
            else:
                df[c] = df[c].astype(str).apply(padronizar)
        return df, True
    except Exception as e:
        st.error(f"Erro ao ler {aba}: {e}") 
        return pd.DataFrame(), False

@st.cache_data(ttl=60, show_spinner=False)
def carregar_banco():
    with st.spinner("🔄 Carregando sistema..."):
        t, ok_t = ler_aba_segura("Turmas", COLS_PADRAO["Turmas"])
        c, ok_c = ler_aba_segura("Curriculo", COLS_PADRAO["Curriculo"])
        p, ok_p = ler_aba_segura("Professores", COLS_PADRAO["Professores"])
        d, ok_d = ler_aba_segura("ConfigDias", COLS_PADRAO["ConfigDias"])
        r, ok_r = ler_aba_segura("Agrupamentos", COLS_PADRAO["Agrupamentos"])
    return t, c, p, d, r, (ok_t and ok_c and ok_p and ok_d and ok_r)

def salvar_seguro(dt, dc, dp, dd, da):
    try:
        with st.status("💾 Salvando...", expanded=True) as status:
            conn.update(worksheet="Turmas", data=dt.replace("nan","").fillna(""))
            conn.update(worksheet="Curriculo", data=dc.replace("nan","").fillna(""))
            conn.update(worksheet="Professores", data=dp.replace("nan","").fillna(""))
            conn.update(worksheet="ConfigDias", data=dd.replace("nan","").fillna(""))
            conn.update(worksheet="Agrupamentos", data=da.replace("nan","").fillna(""))
            
            definir_hora() # Atualiza hora
            st.cache_data.clear()
            status.update(label="✅ Salvo com sucesso!", state="complete", expanded=False)
        time.sleep(1)
        st.rerun()
    except Exception as e: st.error(f"Erro ao salvar: {e}")

def restaurar_cabecalhos_emergencia():
    pass 

# ==========================================
# CÉREBRO: RH AUTOMÁTICO (INTELIGÊNCIA DE TURNO)
# ==========================================
def gerar_professores_automaticos(dt, dc, dp_existente, carga_padrao=20):
    MAX_AULAS_POR_TURNO = 25 
    
    # 1. Demanda
    demanda = {} 
    for _, turma in dt.iterrows():
        regiao = turma['REGIÃO']
        serie = turma['SÉRIE/ANO']
        turno = turma['TURNO']
        curr = dc[dc['SÉRIE/ANO'] == serie]
        for _, item in curr.iterrows():
            mat = limpar_materia(item['COMPONENTE'])
            qtd = int(item['QTD_AULAS'])
            chave = (regiao, mat, turno)
            demanda[chave] = demanda.get(chave, 0) + qtd
            
    # 2. Oferta
    oferta = {} 
    for _, p in dp_existente.iterrows():
        reg = p['REGIÃO']
        mats = [limpar_materia(m) for m in str(p['COMPONENTES']).split(',')]
        carga = int(p['CARGA_HORÁRIA'])
        vinculo = p['VÍNCULO']
        turno_fixo = p['TURNO_FIXO']
        if not mats: continue
        carga_por_mat = carga / len(mats)
        
        for m in mats:
            if vinculo == "EFETIVO" and turno_fixo in ["MATUTINO", "VESPERTINO"]:
                chave = (reg, m, turno_fixo)
                oferta[chave] = oferta.get(chave, 0) + carga_por_mat
            else:
                cap_mat = min(carga_por_mat, MAX_AULAS_POR_TURNO)
                oferta[(reg, m, "MATUTINO")] = oferta.get((reg, m, "MATUTINO"), 0) + cap_mat
                sobra = max(0, carga_por_mat - cap_mat)
                if sobra > 0:
                    oferta[(reg, m, "VESPERTINO")] = oferta.get((reg, m, "VESPERTINO"), 0) + sobra

    # 3. Geração
    novos_profs = []
    ult_cod = 0
    # Extrai números de códigos existentes
    for c in dp_existente['CÓDIGO']:
        nums = re.findall(r'\d+', str(c))
        if nums:
            val = int(nums[0])
            if val > ult_cod: ult_cod = val
    count = ult_cod + 1
    log = []

    for (regiao, materia, turno), qtd_necessaria in demanda.items():
        qtd_coberta = oferta.get((regiao, materia, turno), 0)
        saldo = qtd_necessaria - qtd_coberta
        
        if saldo > 0:
            carga_max = min(carga_padrao, MAX_AULAS_POR_TURNO)
            qtd_profs = math.ceil(saldo / carga_max)
            restante = saldo
            
            for i in range(qtd_profs):
                carga_este = min(carga_max, restante)
                restante -= carga_este
                
                novos_profs.append({
                    "CÓDIGO": f"DT-{count}",
                    "NOME": f"VAGA {materia} ({regiao}-{turno[:3]})",
                    "COMPONENTES": materia,
                    "CARGA_HORÁRIA": int(carga_este),
                    "REGIÃO": regiao,
                    "VÍNCULO": "DT",
                    "TURNO_FIXO": "",
                    "ESCOLAS_ALOCADAS": "",
                    "QTD_PL": 0
                })
                count += 1
            log.append(f"Criados {qtd_profs} profs para {regiao}/{materia}/{turno}")
            
    return pd.DataFrame(novos_profs), log

# ==========================================
# CÉREBRO: GERADOR BLINDADO
# ==========================================
def carregar_objs(df):
    l = []
    for _, r in df.iterrows():
        ms = [limpar_materia(m) for m in str(r['COMPONENTES']).split(',') if limpar_materia(m)]
        vinc = str(r['VÍNCULO']).strip().upper()
        if "VAGA" in str(r['NOME']): vinc = "DT"
        
        tf = "" if vinc == "DT" else padronizar(r['TURNO_FIXO'])
        ef = [] if vinc == "DT" else [padronizar(x) for x in str(r['ESCOLAS_ALOCADAS']).split(',') if padronizar(x)]

        for m in ms:
            if m in MATERIAS_ESPECIALISTAS:
                l.append({
                    'id': str(r['CÓDIGO']), 'nome': r['NOME'], 'mat': m,
                    'reg': padronizar(r['REGIÃO']), 'vin': vinc, 'tf': tf, 'ef': ef,
                    'max': int(r['CARGA_HORÁRIA']), 'atrib': 0, 'ocup': {}, 'escolas': set(), 'turnos_ativos': set()
                })
    return l

def carregar_rotas(df):
    m = {}
    for _, row in df.iterrows():
        escs = [padronizar(x) for x in str(row['LISTA_ESCOLAS']).split(',') if padronizar(x)]
        for e in escs: m[e] = escs
    return m

def resolver_grade(turmas, curriculo, profs, rotas, turno_atual):
    turno_atual = padronizar(turno_atual)
    for p in profs: p['ocup'] = {} # Reset
    
    demandas = []
    for turma in turmas:
        curr = curriculo[curriculo['SÉRIE/ANO'] == turma['ano']]
        aulas = []
        for _, r in curr.iterrows():
            mat = limpar_materia(r['COMPONENTE'])
            if r['QTD_AULAS'] > 0 and mat: aulas.extend([mat] * int(r['QTD_AULAS']))
        while len(aulas) < 5: aulas.append("---")
        for slot_idx, mat in enumerate(aulas[:5]): 
            demandas.append({'turma': turma, 'mat': mat, 'slot': slot_idx, 'pri': 0 if mat=="---" else 1})
    
    demandas.sort(key=lambda x: (x['pri'], random.random()), reverse=True)
    
    for _ in range(500):
        grade = {t['nome_turma']: [None]*5 for t in turmas}
        profs_sim = copy.deepcopy(profs)
        random.shuffle(demandas)
        demandas.sort(key=lambda x: x['pri'], reverse=True)
        sucesso = True
        motivo_falha = ""
        
        for item in demandas:
            turma, mat = item['turma'], item['mat']
            nm_t = turma['nome_turma']
            esc = padronizar(turma['escola_real'])
            reg = padronizar(turma['regiao_real'])
            slot = item['slot']
            
            if mat == "---":
                if grade[nm_t][slot] is None: grade[nm_t][slot] = "---"
                continue
            
            candidatos = []
            for p in profs_sim:
                if p['mat'] != mat: continue
                score = 0
                
                if p['vin'] == "EFETIVO":
                    if p['tf'] and p['tf'] not in ["AMBOS", "", turno_atual]: continue
                    if not any(padronizar(ef) == esc for ef in p['ef']): continue
                    score += 3000
                else: # DT
                    if p['reg'] != reg: continue
                    if p['atrib'] >= p['max']: continue
                    
                    # 1. TRAVA HORÁRIO
                    ocupado_agora = False
                    for esc_ocupada, turmas_ocupadas in p['ocup'].items():
                        for slots_ocupados in turmas_ocupadas.values():
                            if slot in slots_ocupados:
                                ocupado_agora = True; break
                        if ocupado_agora: break
                    if ocupado_agora: continue 

                    # 2. TRAVA GEOGRÁFICA
                    if esc in p['escolas']: score += 2000 
                    elif any(padronizar(x) in p['escolas'] for x in rotas.get(esc, [])): score += 1000
                    elif len(p['escolas']) == 0: 
                        if turno_atual[:3] in p['nome']: score += 2500
                        else: score += 1500 
                    else: score += 10
                
                candidatos.append((score, p))
            
            if candidatos:
                candidatos.sort(key=lambda x: -x[0])
                escolhido = candidatos[0][1]
                
                # SÓ CÓDIGO
                lbl = f"{escolhido['id']}" 
                grade[nm_t][slot] = f"{mat}\n{lbl}"
                
                if esc not in escolhido['ocup']: escolhido['ocup'][esc] = {}
                if nm_t not in escolhido['ocup'][esc]: escolhido['ocup'][esc][nm_t] = []
                escolhido['ocup'][esc][nm_t].append(slot)
                escolhido['atrib'] += 1
                escolhido['escolas'].add(esc)
            else:
                motivo_falha = f"Falta {mat} em {esc}"
                sucesso = False; break
        
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

def criar_preview_com_recreio(df):
    d = df.copy()
    top, bot = d.iloc[:3], d.iloc[3:]
    rec = pd.DataFrame([["RECREIO"]*len(d.columns)], columns=d.columns)
    final = pd.concat([top, rec, bot]).reset_index(drop=True)
    final.index = ["1ª", "2ª", "3ª", "INT", "4ª", "5ª"]
    return final

# ==========================================
# UI - LAYOUT ORIGINAL 6 ABAS
# ==========================================
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
    if st.button("🔄 Atualizar"): st.cache_data.clear(); st.rerun()

t1, t2, t3, t4, t5, t6 = st.tabs([
    "📊 Dashboard", "⚙️ Config", "📍 Rotas", 
    "🏫 Turmas", "👨‍🏫 Professores", "🚀 Gerador"
])

def botao_salvar(label, key):
    if sistema_seguro:
        if st.button(label, key=key, type="primary", use_container_width=True):
            salvar_seguro(dt, dc, dp, dd, da)
    else: st.button(f"🔒 {label}", key=key, disabled=True, use_container_width=True)

# 1. DASHBOARD
with t1:
    if dt.empty: st.info("Cadastre turmas.")
    else:
        c1,c2,c3,c4,c5 = st.columns(5)
        with c1: 
            sel_regiao = st.multiselect("🌍 Região", sorted(dt['REGIÃO'].unique()))
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

# 2. CONFIG
with t2:
    c1, c2 = st.columns(2)
    with c1:
        st.write("📅 Dias"); dd = st.data_editor(dd, num_rows="dynamic", key="edd")
        with st.form("fd"):
            a = st.selectbox("Série", ORDEM_SERIES)
            d = st.selectbox("Dia", ["SEGUNDA-FEIRA", "TERÇA-FEIRA", "QUARTA-FEIRA", "QUINTA-FEIRA", "SEXTA-FEIRA"])
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

# 3. ROTAS
with t3:
    da = st.data_editor(da, num_rows="dynamic", key="edr")
    with st.expander("Nova Rota"):
        with st.form("fr"):
            n = st.text_input("Nome")
            l = st.multiselect("Escolas", sorted(dt['ESCOLA'].unique()) if not dt.empty else [])
            if st.form_submit_button("Criar"):
                da = pd.concat([da, pd.DataFrame([{"NOME_ROTA": n, "LISTA_ESCOLAS": ",".join(l)}])], ignore_index=True); salvar_seguro(dt, dc, dp, dd, da)
    botao_salvar("Salvar Rotas", "brot")

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
                nv = "INFANTIL" if "ANO" not in an else "FUNDAMENTAL"
                dt = pd.concat([dt, pd.DataFrame([{"ESCOLA": padronizar(e), "TURMA": padronizar(t), "TURNO": tn, "SÉRIE/ANO": an, "REGIÃO": rg, "NÍVEL": nv}])], ignore_index=True); salvar_seguro(dt, dc, dp, dd, da)
    dt = st.data_editor(dt, num_rows="dynamic", key="edt")
    botao_salvar("Salvar Turmas", "btur")

# 5. PROFS (COM RH EMBUTIDO)
with t5:
    with st.expander("🤖 Ferramenta: Gerar Vagas Automáticas (RH)", expanded=False):
        st.info("Cria códigos de professores (DT) automaticamente baseado na falta de aulas.")
        c_rh, c_btn = st.columns([1,1])
        with c_rh: carga_padrao = st.number_input("Carga Padrão", 10, 40, 20)
        with c_btn:
            st.write("")
            st.write("")
            if st.button("🚀 Calcular e Criar Vagas"):
                novos, log = gerar_professores_automaticos(dt, dc, dp, carga_padrao)
                if not novos.empty:
                    dp = pd.concat([dp, novos], ignore_index=True)
                    salvar_seguro(dt, dc, dp, dd, da)
                    st.success(f"{len(novos)} vagas criadas!")
                    for l in log: st.caption(l)
                else: st.warning("Quadro completo.")

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
                dp = pd.concat([dp, pd.DataFrame([{"CÓDIGO": cd, "NOME": padronizar(nm), "CARGA_HORÁRIA": ch, "QTD_PL": pl, "REGIÃO": rg, "COMPONENTES": ",".join(cm), "VÍNCULO": tp, "ESCOLAS_ALOCADAS": str_esc, "TURNO_FIXO": ef_trn}])], ignore_index=True); salvar_seguro(dt, dc, dp, dd, da)
    
    dp = st.data_editor(dp, num_rows="dynamic", key="edp")
    botao_salvar("Salvar Profs", "bprof")

# 6. GERADOR
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
                    if len(escolas) == 0: st.error("Erro dados."); st.stop()
                    
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
                            for ti, dx in dados_xls: st.caption(ti); st.dataframe(criar_preview_com_recreio(dx), use_container_width=True)
                    
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