import streamlit as st
import pandas as pd

from config import MATERIAS_ESPECIALISTAS
from utils import padronizar, padronizar_materia_interna


def render_dashboard(dt: pd.DataFrame,
                     dc: pd.DataFrame,
                     dp: pd.DataFrame,
                     gerar_estilo_professor_dinamico):
    """Renderiza a aba de Dashboard Gerencial."""

    if dt.empty or dc.empty:
        st.info("📝 O Dashboard ficará ativo assim que você cadastrar Turmas e Currículo.")
        return

    st.markdown("### 📊 Visão Geral da Rede")

    # --- 1. FILTROS GLOBAIS ---
    c_f1, c_f2, c_f3 = st.columns(3)
    with c_f1:
        regioes_disp = sorted(dt['REGIÃO'].unique())
        filtro_regiao = st.multiselect("🌍 Região", regioes_disp, default=regioes_disp)
    with c_f2:
        if filtro_regiao:
            opcoes_escolas = dt[dt['REGIÃO'].isin(filtro_regiao)]['ESCOLA'].unique()
        else:
            opcoes_escolas = dt['ESCOLA'].unique()
        filtro_escola = st.selectbox("🏢 Escola", ["Todas"] + sorted(list(opcoes_escolas)))
    with c_f3:
        filtro_materia = st.selectbox("📚 Matéria", ["Todas"] + MATERIAS_ESPECIALISTAS)

    # 2. CÁLCULO DE DEMANDA (NECESSIDADE)
    df_turmas_filt = dt.copy()
    if filtro_regiao:
        df_turmas_filt = df_turmas_filt[df_turmas_filt['REGIÃO'].isin(filtro_regiao)]
    if filtro_escola != "Todas":
        df_turmas_filt = df_turmas_filt[df_turmas_filt['ESCOLA'] == filtro_escola]

    demanda_por_materia = {}
    total_aulas_demanda = 0
    auditoria_demanda = []

    for _, row in df_turmas_filt.iterrows():
        serie = row['SÉRIE/ANO']
        turma_nome = row['TURMA']
        escola_nome = row['ESCOLA']

        curr = dc[dc['SÉRIE/ANO'] == serie]

        for _, item in curr.iterrows():
            mat_nome = padronizar_materia_interna(item['COMPONENTE'])
            if mat_nome in [padronizar_materia_interna(m) for m in MATERIAS_ESPECIALISTAS]:
                if filtro_materia == "Todas" or padronizar_materia_interna(filtro_materia) == mat_nome:
                    qtd = int(item['QTD_AULAS'])
                    demanda_por_materia[mat_nome] = demanda_por_materia.get(mat_nome, 0) + qtd
                    total_aulas_demanda += qtd
                    auditoria_demanda.append(f"📌 {escola_nome} - {turma_nome}: +{qtd} {mat_nome}")

    # 3. CÁLCULO DE OFERTA (PROFESSORES)
    df_profs_filt = dp.copy()

    # Filtro de Região
    if filtro_regiao:
        df_profs_filt = df_profs_filt[df_profs_filt['REGIÃO'].isin(filtro_regiao)]

    # Filtro de Escola (Lógica: Professor está alocado nesta escola?)
    if filtro_escola != "Todas":
        esc_alvo_norm = padronizar(filtro_escola)

        def checar_escola(escolas_str):
            if pd.isna(escolas_str) or escolas_str == "":
                return False
            # Separa a lista de escolas do professor e verifica
            escolas_prof = [padronizar(e.strip()) for e in str(escolas_str).split(',')]
            return esc_alvo_norm in escolas_prof

        df_profs_filt = df_profs_filt[df_profs_filt['ESCOLAS_ALOCADAS'].apply(checar_escola)]

    oferta_por_materia = {}
    total_aulas_oferta = 0
    auditoria_oferta = []

    for _, row in df_profs_filt.iterrows():
        nome_prof = row['NOME']
        cod_prof = row['CÓDIGO']
        # Pega as matérias que esse professor dá
        comps = [padronizar_materia_interna(c.strip()) for c in str(row['COMPONENTES']).split(',')]

        # --- CÁLCULO DE AULAS ---
        # Lê diretamente a coluna CARGA_HORÁRIA como sendo a quantidade de aulas
        carga_aulas = int(row['CARGA_HORÁRIA'])

        # Filtra apenas especialistas
        mats_validas = [c for c in comps if c in [padronizar_materia_interna(m) for m in MATERIAS_ESPECIALISTAS]]

        if mats_validas:
            # Se der mais de uma matéria, divide. Se der só uma, pega tudo.
            carga_por_mat = carga_aulas / len(mats_validas)

            for c in mats_validas:
                if filtro_materia == "Todas" or padronizar_materia_interna(filtro_materia) == c:
                    oferta_por_materia[c] = oferta_por_materia.get(c, 0) + carga_por_mat
                    total_aulas_oferta += carga_por_mat

                    auditoria_oferta.append(
                        f"👨‍🏫 {cod_prof} ({nome_prof}): Dispõe de {carga_por_mat:.1f} aulas de {c}"
                    )

    # --- 4. EXIBIÇÃO DOS INDICADORES ---
    st.divider()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Turmas Analisadas", len(df_turmas_filt))
    k2.metric("Demanda (Necessidade)", total_aulas_demanda)
    k3.metric("Oferta (Professores)", int(total_aulas_oferta))

    saldo = int(total_aulas_oferta - total_aulas_demanda)
    k4.metric("Saldo", saldo, delta_color="normal" if saldo >= 0 else "inverse")

    # --- 5. DETETIVE DE CÁLCULOS (ABRA AQUI PARA CONFERIR) ---
    with st.expander("🕵️‍♀️ Detetive de Cálculos (Clique para ver de onde vêm os números) 🕵️‍♀️"):
        d1, d2 = st.columns(2)
        with d1:
            st.markdown("**🔍 Detalhe da Demanda (Turmas)**")
            if auditoria_demanda:
                st.text("\n".join(auditoria_demanda[:50]))  # Mostra os primeiros 50
                if len(auditoria_demanda) > 50:
                    st.caption("... e mais turmas.")
            else:
                st.write("Nenhuma demanda encontrada.")

        with d2:
            st.markdown("**🔍 Detalhe da Oferta (Professores)**")
            if auditoria_oferta:
                # AQUI VOCÊ VAI VER O VALOR QUE O SISTEMA ESTÁ LENDO
                st.text("\n".join(auditoria_oferta))
            else:
                st.write("Nenhum professor encontrado para esta escola.")

    # --- 6. TABELA DE BALANÇO ---
    st.subheader("📉 Balanço por Matéria")
    dados_tabela = []
    todas_mats = set(list(demanda_por_materia.keys()) + list(oferta_por_materia.keys()))

    for m in sorted(list(todas_mats)):
        dem = demanda_por_materia.get(m, 0)
        ofe = int(oferta_por_materia.get(m, 0))
        dif = ofe - dem
        status = "✅ OK" if dif == 0 else (f"🔵 Sobra {dif}" if dif > 0 else f"🔴 Falta {abs(dif)}")

        dados_tabela.append({
            "Matéria": m,
            "Necessidade": dem,
            "Disponível": ofe,
            "Saldo": dif,
            "Status": status
        })

    if dados_tabela:
        st.dataframe(pd.DataFrame(dados_tabela), use_container_width=True, hide_index=True)

    # --- 7. GALERIA VISUAL (RESTAURADA) ---
    st.divider()
    st.subheader(f"🎨 Professores Alocados: {filtro_escola}")
    st.caption("Cores de identificação geradas pelo sistema:")

    if not df_profs_filt.empty:
        # Ordena para ficar bonito
        df_profs_filt['MAT_PRINCIPAL'] = df_profs_filt['COMPONENTES'].apply(lambda x: str(x).split(',')[0])
        df_vis = df_profs_filt.sort_values(by=['MAT_PRINCIPAL', 'NOME'])

        cols_vis = st.columns(6)
        for idx, (_, p) in enumerate(df_vis.iterrows()):
            cod = p['CÓDIGO']
            # Pega primeiro e último nome
            nomes = p['NOME'].split()
            nome_curto = f"{nomes[0]} {nomes[-1]}" if len(nomes) > 1 else nomes[0]

            # Gera a cor
            estilo = gerar_estilo_professor_dinamico(cod)

            with cols_vis[idx % 6]:
                st.markdown(f"""
                <div style="
                    background-color: {estilo['bg']};
                    color: {estilo['text']};
                    border: 1px solid {estilo['border']};
                    border-radius: 6px;
                    padding: 8px;
                    margin-bottom: 10px;
                    text-align: center;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                ">
                    <div style="font-weight: 800; font-size: 13px;">{cod}</div>
                    <div style="font-size: 11px; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{nome_curto}</div>
                    <div style="font-size: 9px; opacity: 0.9; margin-top: 2px;">{p['COMPONENTES'][:15]}</div>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.info("Nenhum professor alocado nesta escola para exibir na galeria.")

