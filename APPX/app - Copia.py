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
import unicodedata

# ==========================================
# 1. CONFIGURAÇÕES & ESTILO
# ==========================================
st.set_page_config(page_title="Gerador Escolar Pro", page_icon="🎓", layout="wide")

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
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. DEFINIÇÕES GLOBAIS
# ==========================================
REGIOES = ["FUNDÃO", "PRAIA GRANDE", "TIMBUÍ"]
MATERIAS_ESPECIALISTAS = ["ARTE", "EDUCAÇÃO FÍSICA", "ENSINO RELIGIOSO", "LÍNGUA INGLESA", "CONTAÇÃO DE HISTÓRIA"]
ORDEM_SERIES = ["BERÇÁRIO", "CRECHE I", "CRECHE II", "CRECHE III", "PRÉ I", "PRÉ II", "1º ANO", "2º ANO", "3º ANO", "4º ANO", "5º ANO"]

COLS_PADRAO = {
    "Turmas": ["ESCOLA", "NÍVEL", "TURMA", "TURNO", "SÉRIE/ANO", "REGIÃO"],
    "Curriculo": ["SÉRIE/ANO", "COMPONENTE", "QTD_AULAS"],
    "Professores": ["CÓDIGO", "NOME", "COMPONENTES", "CARGA_HORÁRIA", "REGIÃO", "VÍNCULO", "TURNO_FIXO", "ESCOLAS_ALOCADAS", "QTD_PL"],
    "ConfigDias": ["SÉRIE/ANO", "DIA_PLANEJAMENTO"],
    "Agrupamentos": ["NOME_ROTA", "LISTA_ESCOLAS"],
    "Horario": ["ESCOLA", "TURMA", "TURNO", "DIA", "1ª", "2ª", "3ª", "4ª", "5ª"]
}

conn = st.connection("gsheets", type=GSheetsConnection)

# ==========================================
# 3. UTILITÁRIOS
# ==========================================
def remover_acentos(texto):
    if not isinstance(texto, str): return str(texto)
    nfkd = unicodedata.normalize('NFKD', texto)
    return "".join([c for c in nfkd if not unicodedata.combining(c)])

def padronizar(texto):
    if pd.isna(texto): return ""
    txt = remover_acentos(str(texto).upper().strip())
    if txt == "NAN": return ""
    return " ".join(txt.split())

def limpar_materia(nome):
    nome_padrao = padronizar(nome)
    if "ART" in nome_padrao: return "ARTE"
    if "FISICA" in nome_padrao: return "EDUCAÇÃO FÍSICA"
    if "INGLE" in nome_padrao: return "LÍNGUA INGLESA"
    if "RELIGIO" in nome_padrao: return "ENSINO RELIGIOSO"
    if "HIST" in nome_padrao and "CONTA" in nome_padrao: return "CONTAÇÃO DE HISTÓRIA"
    return nome

def padronizar_materia_interna(nome):
    return remover_acentos(limpar_materia(nome)).upper()

def gerar_sigla_regiao(regiao):
    reg = padronizar(regiao)
    if "PRAIA" in reg: return "P"
    if "FUND" in reg: return "F"
    if "TIMB" in reg: return "T"
    return "X"

def gerar_sigla_materia(nome):
    nome = padronizar(nome)
    if "ART" in nome: return "ARTE"
    if "FISICA" in nome: return "EDFI"
    if "INGLE" in nome: return "LIIN"
    if "RELIGIO" in nome: return "ENRE"
    if "HIST" in nome and "CONTA" in nome: return "COHI"
    palavras = nome.split()
    if len(palavras) > 1:
        return (palavras[0][:2] + palavras[1][:2]).upper()
    return nome[:4].upper()

def gerar_codigo_padrao(numero, tipo, regiao, materia):
    t = "D" if tipo == "DT" else "E"
    r = gerar_sigla_regiao(regiao)
    m = gerar_sigla_materia(materia)
    return f"P{numero}{t}{r}{m}"

# ==========================================
# 4. LEITURA DE DADOS
# ==========================================
def ler_aba_segura(aba, colunas_esperadas):
    try:
        df = conn.read(worksheet=aba, ttl=0)
        if df.empty: return pd.DataFrame(columns=colunas_esperadas), True
        df.columns = [padronizar(c) for c in df.columns]
        cols_padrao_norm = [padronizar(c) for c in colunas_esperadas]
        mapa_cols = {}
        for c_esperada, c_norm in zip(colunas_esperadas, cols_padrao_norm):
            if c_norm in df.columns: mapa_cols[c_norm] = c_esperada
        df = df.rename(columns=mapa_cols)
        for col in colunas_esperadas:
            if col not in df.columns: return pd.DataFrame(), False
        df = df[colunas_esperadas].dropna(how='all').fillna("")
        for c in df.columns:
            if c in ["QTD_AULAS", "CARGA_HORÁRIA", "QTD_PL"]:
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0).astype(int)
            else:
                df[c] = df[c].astype(str).apply(padronizar)
        return df, True
    except: return pd.DataFrame(), False

@st.cache_data(ttl=60, show_spinner=False)
def carregar_banco():
    with st.spinner("🔄 Carregando sistema..."):
        t, ok_t = ler_aba_segura("Turmas", COLS_PADRAO["Turmas"])
        c, ok_c = ler_aba_segura("Curriculo", COLS_PADRAO["Curriculo"])
        p, ok_p = ler_aba_segura("Professores", COLS_PADRAO["Professores"])
        d, ok_d = ler_aba_segura("ConfigDias", COLS_PADRAO["ConfigDias"])
        r, ok_r = ler_aba_segura("Agrupamentos", COLS_PADRAO["Agrupamentos"])
        h, ok_h = ler_aba_segura("Horario", COLS_PADRAO["Horario"])
    return t, c, p, d, r, h, (ok_t and ok_c and ok_p and ok_d and ok_r)

dt, dc, dp, dd, da, dh, sistema_seguro = carregar_banco()

def salvar_seguro(dt, dc, dp, dd, da, dh=None):
    try:
        with st.status("💾 Salvando...", expanded=True) as status:
            conn.update(worksheet="Turmas", data=dt.fillna(""))
            conn.update(worksheet="Curriculo", data=dc.fillna(""))
            conn.update(worksheet="Professores", data=dp.fillna(""))
            conn.update(worksheet="ConfigDias", data=dd.fillna(""))
            conn.update(worksheet="Agrupamentos", data=da.fillna(""))
            if dh is not None: conn.update(worksheet="Horario", data=dh.fillna(""))
            st.cache_data.clear()
            status.update(label="✅ Salvo!", state="complete", expanded=False)
        time.sleep(1)
        st.rerun()
    except Exception as e: st.error(f"Erro ao salvar: {e}")

def botao_salvar(label, key):
    if sistema_seguro:
        if st.button(label, key=key, type="primary", use_container_width=True):
            salvar_seguro(dt, dc, dp, dd, da)
    else: st.button(f"🔒 {label}", key=key, disabled=True, use_container_width=True)

# ==========================================
# 5. CÉREBRO: RH ROBIN HOOD CORRIGIDO
# ==========================================
def gerar_professores_v52(dt, dc, dp_existente, carga_minima=14, carga_maxima=30, media_alvo=20):
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
    
    # 3. Reduzir demanda com professores existentes
    demanda_restante = {}
    
    for (reg, mat), total in demanda_total.items():
        demanda_restante[(reg, mat)] = total
        if (reg, mat) in professores_por_regiao_materia:
            for prof in professores_por_regiao_materia[(reg, mat)]:
                carga_disponivel = min(prof['carga'], carga_maxima)
                if carga_disponivel > 0:
                    if demanda_restante[(reg, mat)] > 0:
                        usado = min(demanda_restante[(reg, mat)], carga_disponivel)
                        demanda_restante[(reg, mat)] -= usado
    
    # 4. Calcular necessidade real
    necessidade = {}
    for chave, restante in demanda_restante.items():
        if restante > 0:
            necessidade[chave] = restante
    
    # 5. Criar novos professores apenas para necessidade real
    novos_profs = []
    
    for (reg, mat), deficit in necessidade.items():
        if deficit <= 0:
            continue
        
        # Calcula quantos professores precisamos
        qtd_profs = max(1, math.ceil(deficit / media_alvo))
        
        # Ajusta para ficar dentro dos limites
        carga_por_prof = deficit / qtd_profs
        
        while qtd_profs > 1 and carga_por_prof < carga_minima:
            qtd_profs -= 1
            carga_por_prof = deficit / qtd_profs
        
        while carga_por_prof > carga_maxima:
            qtd_profs += 1
            carga_por_prof = deficit / qtd_profs
        
        # Distribui a carga
        cargas = []
        restante = deficit
        
        for i in range(qtd_profs):
            if i == qtd_profs - 1:
                carga = restante
            else:
                carga = min(carga_maxima, max(carga_minima, round(carga_por_prof)))
                restante -= carga
            cargas.append(carga)
        
        # Cria os professores
        for i, carga in enumerate(cargas):
            if carga > 0:
                # Atualiza contador
                chave_cont = (reg, mat)
                contadores[chave_cont] = contadores.get(chave_cont, 0) + 1
                
                # Gera código
                cod = gerar_codigo_padrao(contadores[chave_cont], "DT", reg, mat)
                
                # Obtém escolas da região
                escolas_regiao = list(set(dt[dt['REGIÃO'] == reg]['ESCOLA'].unique()))
                
                novos_profs.append({
                    "CÓDIGO": cod,
                    "NOME": f"VAGA {mat} {reg}",
                    "COMPONENTES": mat,
                    "CARGA_HORÁRIA": round(carga),
                    "REGIÃO": reg,
                    "VÍNCULO": "DT",
                    "TURNO_FIXO": "",
                    "ESCOLAS_ALOCADAS": ",".join(escolas_regiao[:2]),  # Atribui até 2 escolas
                    "QTD_PL": 0
                })
    
    return pd.DataFrame(novos_profs), []

# ==========================================
# 6. CÉREBRO: GERAÇÃO E ALOCAÇÃO INTELIGENTE
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

def resolver_grade_inteligente(turmas, curriculo, profs, rotas, turno_atual, mapa_escola_regiao, max_tentativas=50):
    """Versão corrigida: não cria professores em excesso"""
    turno_atual = padronizar(turno_atual)
    
    # NÃO FAZER RESET AQUI (CORREÇÃO 4)
    # O reset deve ser feito apenas uma vez antes do loop principal de geração.
    
    # Preparar demandas REAIS
    demandas = []
    for turma in turmas:
        curr = curriculo[curriculo['SÉRIE/ANO'] == turma['ano']]
        aulas = []
        for _, r in curr.iterrows():
            mat = padronizar_materia_interna(r['COMPONENTE'])
            if mat in [padronizar_materia_interna(m) for m in MATERIAS_ESPECIALISTAS]:
                aulas.extend([mat] * int(r['QTD_AULAS']))
        
        while len(aulas) < 5:
            aulas.append("---")
        
        for slot, mat in enumerate(aulas[:5]):
            if mat != "---":
                demandas.append({
                    'turma': turma,
                    'mat': mat,
                    'slot': slot,
                    'prioridade': 1
                })
    
    # LIMITE de novos professores para evitar criação excessiva (CORREÇÃO 2: AUMENTADO)
    LIMITE_NOVOS_PROFESSORES = 50 
    novos_professores_criados = 0
    
    for tentativa in range(max_tentativas):
        grade = {t['nome_turma']: [None]*5 for t in turmas}
        profs_temp = copy.deepcopy(profs)
        random.shuffle(demandas)
        
        sucesso = True
        
        for item in demandas:
            turma, mat, slot = item['turma'], item['mat'], item['slot']
            esc, reg = padronizar(turma['escola_real']), padronizar(turma['regiao_real'])
            
            # Encontrar candidatos
            candidatos = []
            
            for p in profs_temp:
                if mat not in p['mats']:
                    continue
                
                if p['tf'] and p['tf'] not in ["AMBOS", "", turno_atual]:
                    continue
                
                if reg != p['reg']:
                    continue
                
                if p['atrib'] >= min(p['max'], 30):
                    continue
                
                # Verifica conflitos
                conflito = False
                if slot in p['ocup']:
                    conflito = True
                else:
                    for s_occ, e_occ in p['ocup'].items():
                        if e_occ != esc:
                            dist = abs(s_occ - slot)
                            mesma_rota = esc in rotas.get(e_occ, set())
                            if (not mesma_rota and dist < 2) or (mesma_rota and dist < 1):
                                conflito = True
                                break
                
                if conflito:
                    continue
                
                # Score
                score = 0
                if p['vin'] == "EFETIVO" and esc in p['escolas_base']:
                    score += 10000
                if esc in p['escolas_base']:
                    score += 2000
                if esc in p['escolas_reais']:
                    score += 1000
                score += (30 - p['atrib']) * 10
                
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
                # Tenta criar novo professor APENAS se estiver dentro do limite
                if novos_professores_criados < LIMITE_NOVOS_PROFESSORES:
                    # Encontra próximo número disponível
                    numeros_existentes = []
                    for p in profs_temp:
                        match = re.search(r'P(\d+)', p['id'])
                        if match:
                            numeros_existentes.append(int(match.group(1)))
                    novo_num = max(numeros_existentes) + 1 if numeros_existentes else 1
                    
                    novo_id = gerar_codigo_padrao(novo_num, "DT", reg, mat)
                    
                    novo_prof = {
                        'id': novo_id,
                        'nome': f"NOVO {mat} {reg}",
                        'mats': {mat},
                        'reg': reg,
                        'vin': 'DT',
                        'tf': '',
                        'escolas_base': {esc},
                        'max': 30,
                        'atrib': 1,
                        'ocup': {slot: esc},
                        'escolas_reais': {esc},
                        'regs_alocadas_historico': {reg}
                    }
                    
                    profs_temp.append(novo_prof)
                    novos_professores_criados += 1
                    grade[turma['nome_turma']][slot] = novo_id
                else:
                    # Se atingiu o limite, marca como falha
                    sucesso = False
                    grade[turma['nome_turma']][slot] = "---"
        
        # Verifica se todas as aulas foram alocadas
        todas_alocadas = all(all(v is not None for v in linha) for linha in grade.values())
        
        if todas_alocadas and sucesso:
            # Preenche qualquer slot None com "---"
            for t_nome, aulas in grade.items():
                for i in range(5):
                    if aulas[i] is None:
                        grade[t_nome][i] = "---"
            
            # Atualiza a lista original de professores
            for p_novo in profs_temp:
                if p_novo['id'] not in [p['id'] for p in profs]:
                    profs.append(p_novo)
            
            return True, grade, f"Sucesso na tentativa {tentativa+1}", profs
    
    # Se não conseguiu, retorna o que tem
    for t_nome, aulas in grade.items():
        for i in range(5):
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
# 7. UI COM DEPURAÇÃO
# ==========================================
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2997/2997322.png", width=60)
    st.title("Gestor Escolar")
    if not sistema_seguro: st.error("Erro dados")
    else: st.success("Online")
    if st.button("Atualizar"): st.cache_data.clear(); st.rerun()

t1, t2, t3, t4, t5, t6, t7 = st.tabs(["📊 Dashboard", "⚙️ Config", "📍 Rotas", "🏫 Turmas", "👨‍🏫 Professores", "🚀 Gerador", "📅 Ver Horário"])

# 1. DASHBOARD
with t1:
    if dt.empty: st.info("Cadastre turmas.")
    else:
        # Cálculo REAL da demanda
        total_aulas_especialistas = 0
        for _, turma in dt.iterrows():
            curr = dc[dc['SÉRIE/ANO'] == turma['SÉRIE/ANO']]
            for _, item in curr.iterrows():
                if padronizar_materia_interna(item['COMPONENTE']) in [padronizar_materia_interna(m) for m in MATERIAS_ESPECIALISTAS]:
                    total_aulas_especialistas += int(item['QTD_AULAS'])
        
        st.info(f"📊 **Demanda Real:** {total_aulas_especialistas} aulas semanais de especialistas")
        
        c1,c2,c3,c4,c5 = st.columns(5)
        with c1: sel_regiao = st.multiselect("🌍 Região", sorted(dt['REGIÃO'].unique()))
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

# 5. PROFS
with t5:
    # Exibir estatísticas reais
    if not dt.empty and not dc.empty:
        st.info("📊 **Estatísticas Reais da Rede:**")
        col1, col2, col3 = st.columns(3)
        
        # Calcular demanda real
        demanda_real = 0
        for _, turma in dt.iterrows():
            curr = dc[dc['SÉRIE/ANO'] == turma['SÉRIE/ANO']]
            for _, item in curr.iterrows():
                if padronizar_materia_interna(item['COMPONENTE']) in [padronizar_materia_interna(m) for m in MATERIAS_ESPECIALISTAS]:
                    demanda_real += int(item['QTD_AULAS'])
        
        # Calcular oferta real
        oferta_real = 0
        for _, prof in dp.iterrows():
            oferta_real += int(prof['CARGA_HORÁRIA'])
        
        with col1:
            st.metric("Aulas Demanda", demanda_real)
        with col2:
            st.metric("Aulas Oferta", oferta_real)
        with col3:
            st.metric("Saldo", demanda_real - oferta_real)
        
        if demanda_real > oferta_real:
            st.warning(f"⚠️ Déficit de {demanda_real - oferta_real} aulas")
    
    with st.expander("🤖 Ferramenta: Gerar Vagas Automáticas (Balanceamento)", expanded=False):
        st.info("Distribui a carga de forma equilibrada (Teto 30h, Mínimo 14h, Média Alvo 20h).")
        c_rh1, c_rh2, c_rh3, c_btn = st.columns([1,1,1,1])
        with c_rh1: carga_min = st.number_input("Carga Mínima", 5, 20, 14)
        with c_rh2: carga_max = st.number_input("Carga Máxima (Teto)", 20, 50, 30)
        with c_rh3: media_alvo = st.number_input("Média Alvo", 10, 40, 20)
        with c_btn:
            st.write(""); st.write("")
            if st.button("🚀 Calcular e Criar"):
                # Mostrar demanda real antes de calcular
                demanda_real = 0
                for _, turma in dt.iterrows():
                    curr = dc[dc['SÉRIE/ANO'] == turma['SÉRIE/ANO']]
                    for _, item in curr.iterrows():
                        if padronizar_materia_interna(item['COMPONENTE']) in [padronizar_materia_interna(m) for m in MATERIAS_ESPECIALISTAS]:
                            demanda_real += int(item['QTD_AULAS'])
                
                st.write(f"**Demanda real:** {demanda_real} aulas")
                
                novos, log = gerar_professores_v52(dt, dc, dp, carga_min, carga_max, media_alvo)
                if not novos.empty:
                    st.write(f"**Criando {len(novos)} novos professores:**")
                    st.dataframe(novos[['CÓDIGO', 'NOME', 'CARGA_HORÁRIA']])
                    
                    if st.button("✅ Confirmar Criação"):
                        dp = pd.concat([dp, novos], ignore_index=True)
                        salvar_seguro(dt, dc, dp, dd, da)
                        st.success(f"{len(novos)} novos contratos criados!")
                else: 
                    st.success("✅ Tudo otimizado! Sem vagas novas.")

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

# 6. GERADOR COM DEPURAÇÃO
with t6:
    if sistema_seguro:
        # Seção de depuração
        st.subheader("🔍 Depuração da Demanda")
        
        # Calcular demanda real
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
                profs_obj = carregar_objs(dp)
                rotas_obj = carregar_rotas(da)
                map_esc_reg = dict(zip(dt['ESCOLA'], dt['REGIÃO']))
                
                # CORREÇÃO 1: Usar left merge para incluir todas as turmas
                merged = pd.merge(dt, dd, on="SÉRIE/ANO", how="left").fillna({'DIA_PLANEJAMENTO': 'NÃO CONFIGURADO'})
                escolas = merged['ESCOLA'].unique()
                
                # CORREÇÃO 4: Resetar o estado dos professores APENAS UMA VEZ
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
                    
                    # Iterar sobre todos os dias/turnos únicos para a escola
                    for _, b in df_e[['DIA_PLANEJAMENTO', 'TURNO']].drop_duplicates().iterrows():
                        dia, turno = b['DIA_PLANEJAMENTO'], b['TURNO']
                        turmas_f = df_e[(df_e['DIA_PLANEJAMENTO']==dia) & (df_e['TURNO']==turno)]
                        
                        lt = [{
                            'nome_turma': r['TURMA'], 
                            'ano': r['SÉRIE/ANO'], 
                            'escola_real': esc, 
                            'regiao_real': r['REGIÃO']
                        } for _, r in turmas_f.iterrows()]
                        
                        # A função resolver_grade_inteligente agora acumula o estado em profs_obj
                        sucesso, res, mensagem, profs_obj = resolver_grade_inteligente(
                            lt, dc, profs_obj, rotas_obj, turno, map_esc_reg
                        )
                        
                        status.write(f"    • {dia} - {turno}: {mensagem}")
                        
                        for t_nome, aulas in res.items():
                            novos_horarios.append([esc, t_nome, turno, dia] + aulas)
                    
                    escolas_processadas += 1
                
                df_horario = pd.DataFrame(novos_horarios, columns=COLS_PADRAO["Horario"])
                
                # Atualizar professores
                profs_finais_list = []
                ids_existentes = set(dp['CÓDIGO'].astype(str))
                
                for p in profs_obj:
                    if p['id'] in ids_existentes:
                        idx = dp[dp['CÓDIGO'] == p['id']].index[0]
                        dados_originais = dp.iloc[idx].to_dict()
                        dados_originais['CARGA_HORÁRIA'] = p['atrib']
                        dados_originais['ESCOLAS_ALOCADAS'] = ",".join(list(p['escolas_reais']))
                        profs_finais_list.append(dados_originais)
                    else:
                        profs_finais_list.append({
                            "CÓDIGO": p['id'],
                            "NOME": p['nome'],
                            "COMPONENTES": list(p['mats'])[0] if p['mats'] else "",
                            "CARGA_HORÁRIA": p['atrib'],
                            "REGIÃO": p['reg'],
                            "VÍNCULO": p['vin'],
                            "TURNO_FIXO": p['tf'],
                            "ESCOLAS_ALOCADAS": ",".join(list(p['escolas_reais'])),
                            "QTD_PL": 0
                        })
                
                dp_atualizado = pd.DataFrame(profs_finais_list)
                
                status.write("💾 Salvando no banco de dados...")
                salvar_seguro(dt, dc, dp_atualizado, dd, da, df_horario)
                
                status.update(label="✅ Grade Gerada com Sucesso!", state="complete", expanded=False)
                st.success(f"Processamento concluído! {escolas_processadas} escolas processadas.")

# 7. VER HORÁRIO
with t7:
    if dh.empty: 
        st.info("✨ Nenhum horário gerado ainda. Vá na aba '🚀 Gerador' para criar a primeira grade da rede.")
    else:
        st.markdown("### 📅 Visualização da Grade Consolidada")
        
        with st.container():
            c1, c2, c3 = st.columns([2, 2, 1])
            with c1:
                esc_sel = st.selectbox("🏢 Selecione a Escola", ["Todas as Escolas"] + sorted(dh['ESCOLA'].unique().tolist()))
            with c2:
                dia_sel = st.selectbox("📆 Selecione o Dia", ["Todos os Dias"] + sorted(dh['DIA'].unique().tolist()))
            with c3:
                st.write("")
                buf = io.BytesIO()
                df_exp = dh.copy()
                if esc_sel != "Todas as Escolas": df_exp = df_exp[df_exp['ESCOLA'] == esc_sel]
                if dia_sel != "Todos os Dias": df_exp = df_exp[df_exp['DIA'] == dia_sel]
                
                with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
                    for esc in df_exp['ESCOLA'].unique():
                        df_esc = df_exp[df_exp['ESCOLA'] == esc]
                        dados_xls = []
                        for turno_dia in df_esc[['TURNO', 'DIA']].drop_duplicates().values:
                            t, d = turno_dia
                            df_bloco = df_esc[(df_esc['TURNO'] == t) & (df_esc['DIA'] == d)]
                            grade_visual = df_bloco.set_index('TURMA')[['1ª', '2ª', '3ª', '4ª', '5ª']].T
                            dados_xls.append((f"{t}-{d}", grade_visual))
                        desenhar_xls(writer, esc, dados_xls)
                
                st.download_button(
                    label="📥 Baixar Excel",
                    data=buf.getvalue(),
                    file_name=f"Horario_{esc_sel}_{datetime.now().strftime('%d_%m')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    type="primary"
                )

        st.markdown("---")
        df_view = dh.copy()
        if esc_sel != "Todas as Escolas": df_view = df_view[df_view['ESCOLA'] == esc_sel]
        if dia_sel != "Todos os Dias": df_view = df_view[df_view['DIA'] == dia_sel]

        if df_view.empty:
            st.warning("Nenhum dado encontrado para os filtros selecionados.")
        else:
            def style_grade(df):
                def color_vagas(val):
                    if 'VAGA' in str(val): return 'background-color: #ffebee; color: #c62828; font-weight: bold; border: 1px solid #ffcdd2'
                    if val == '---': return 'color: #d1d1d1; background-color: #fafafa'
                    return 'background-color: #ffffff; color: #2c3e50; font-weight: 500'
                
                return df.style.applymap(color_vagas).set_properties(**{
                    'text-align': 'center',
                    'font-size': '14px',
                    'border': '1px solid #eee'
                })

            for escola in sorted(df_view['ESCOLA'].unique()):
                st.markdown(f"""
                <div style="background-color: #2c3e50; padding: 10px; border-radius: 10px 10px 0 0; margin-top: 20px;">
                    <h2 style="color: white; margin: 0; text-align: center; font-size: 22px;">🏫 {escola}</h2>
                </div>
                """, unsafe_allow_html=True)
                
                df_esc = df_view[df_view['ESCOLA'] == escola]
                
                for dia in ["SEGUNDA-FEIRA", "TERÇA-FEIRA", "QUARTA-FEIRA", "QUINTA-FEIRA", "SEXTA-FEIRA"]:
                    df_dia = df_esc[df_esc['DIA'] == dia]
                    if df_dia.empty: continue
                    
                    st.markdown(f"<h3 style='border-bottom: 2px solid #2c3e50; padding-top: 15px;'>📅 {dia}</h3>", unsafe_allow_html=True)
                    
                    for turno in sorted(df_dia['TURNO'].unique()):
                        df_turno = df_dia[df_dia['TURNO'] == turno]
                        
                        turmas = sorted(df_turno['TURMA'].unique())
                        cols = st.columns(min(len(turmas), 3))
                        
                        for idx, turma in enumerate(turmas):
                            with cols[idx % 3]:
                                st.markdown(f"""
                                <div style="background-color: #f1f3f4; padding: 5px 10px; border-radius: 5px; border-left: 5px solid #3498db; margin-bottom: 5px;">
                                    <span style="font-weight: bold; color: #34495e;">👥 Turma: {turma}</span> | 
                                    <span style="color: #7f8c8d; font-size: 12px;">☀️ {turno}</span>
                                </div>
                                """, unsafe_allow_html=True)
                                
                                df_turma = df_turno[df_turno['TURMA'] == turma][['1ª', '2ª', '3ª', '4ª', '5ª']]
                                df_final = df_turma.T
                                df_final.columns = ["Professor"]
                                
                                st.table(style_grade(df_final))
                st.markdown("---")
