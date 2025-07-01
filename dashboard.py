import os
import pandas as pd
import streamlit as st
import plotly.express as px
from dotenv import load_dotenv
from openai import OpenAI
from streamlit_chat import message

# ─── Configurações de página ─────────────────────────────────────────────────────
st.set_page_config(
    page_title="MegaOffice Dashboard",
    layout="wide",
    initial_sidebar_state="expanded"
)
st.markdown(
    """
    <style>
      .css-1d391kg h1 { font-size: 2rem; }
      .css-1d391kg h2 { font-size: 1.5rem; }
    </style>
    """,
    unsafe_allow_html=True
)

# ─── Cliente OpenAI ────────────────────────────────────────────────────────────────
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.error("🚨 Defina OPENAI_API_KEY no .env")
    st.stop()
client = OpenAI(api_key=OPENAI_API_KEY)

# ─── Funções de carregamento e agregação ──────────────────────────────────────────
@st.cache_data
def load_data(path):
    df_ss = pd.read_excel(path, sheet_name="Solic. de Serviço") \
             .rename(columns={"Funcionário":"Atendido por","Quantidade":"Qtd"})
    df_ss["Tipo"] = "SS"
    df_wa = pd.read_excel(path, sheet_name="03-25 Atend conc")
    df_wa = df_wa[df_wa["Status"]=="Concluído"].copy()
    df_wa["Qtd"]  = 1; df_wa["Tipo"] = "WA"

    def split_info(s: str):
        if "|" in s:
            pessoa, resto = s.split("|",1)
        else:
            return s.strip(), None, None
        if "-" in resto:
            depto, nucleo = resto.split("-",1)
        else:
            depto, nucleo = resto, None
        return pessoa.strip(), depto.strip(), (nucleo.strip() if nucleo else None)

    for df in (df_ss, df_wa):
        df[["Pessoa","Departamento","Núcleo"]] = (
            df["Atendido por"].apply(lambda x: pd.Series(split_info(x)))
        )

    df = pd.concat([df_ss, df_wa], ignore_index=True)
    df["Data"] = pd.to_datetime(df["Data"], errors="ignore")
    return df

@st.cache_data
def aggregate_data(df):
    agg = (df
           .groupby(["Departamento","Núcleo","Pessoa","Tipo"])["Qtd"]
           .sum()
           .unstack(fill_value=0)
           .reset_index())
    for col in ("SS","WA"):
        if col not in agg:
            agg[col] = 0
    return agg

# ─── Carrega dados ────────────────────────────────────────────────────────────────
df     = load_data("Teste 1 (1).xlsx")
df_agg = aggregate_data(df)

# ─── Título e KPIs ────────────────────────────────────────────────────────────────
st.title("Dashboard de Eficiência MegaOffice")

ss_total  = int(df_agg["SS"].sum())
wa_total  = int(df_agg["WA"].sum())
dias      = df["Data"].dt.date.nunique()
ss_diaria = ss_total / dias
wa_diaria = wa_total / dias

c1, c2, c3, c4 = st.columns(4)
c1.metric("SS Total",     ss_total)
c2.metric("WA Total",     wa_total)
c3.metric("Média SS/Dia", f"{ss_diaria:.1f}")
c4.metric("Média WA/Dia", f"{wa_diaria:.1f}")

# ─── Dados Tratados ──────────────────────────────────────────────────────────────
st.subheader("Dados Tratados")
st.dataframe(df.head(), use_container_width=True)

# ─── Dados Agregados (ordenados) ─────────────────────────────────────────────────
# adiciona total para ordenação
df_agg["Total"] = df_agg["SS"] + df_agg["WA"]
df_agg_sorted   = df_agg.sort_values("Total", ascending=False).reset_index(drop=True)

st.subheader("Dados Agregados por Operador (ordenados por total)")
st.dataframe(
    df_agg_sorted.drop(columns="Total"),
    use_container_width=True
)

# ─── Filtro de Núcleo ────────────────────────────────────────────────────────────
st.sidebar.header("Filtros")
nucleos      = sorted(df_agg_sorted["Núcleo"].dropna().unique())
selecionados = st.sidebar.multiselect(
    "Selecione Núcleo(s):",
    options=nucleos,
    default=nucleos,
    key="nucleo_filter"
)
df_filtrado = df_agg_sorted[df_agg_sorted["Núcleo"].isin(selecionados)]

# ─── Gráfico de Barras ───────────────────────────────────────────────────────────
st.subheader("Atendimentos por Operador")
fig = px.bar(
    df_filtrado,
    x="Pessoa",
    y=["SS","WA"],
    barmode="group",
    labels={"value":"Total","variable":"Tipo","Pessoa":"Operador"},
    title=f"Núcleos: {', '.join(selecionados)}"
)
st.plotly_chart(fig, use_container_width=True)

# ─── Insights Automáticos ────────────────────────────────────────────────────────
if st.button("✨ Gerar Insights Automáticos"):
    prompt = (
        f"Considere estes dados de eficiência:\n"
        f"{df_filtrado[['Pessoa','Departamento','Núcleo','SS','WA']].to_dict(orient='records')}\n"
        "Gere 3 insights principais em português, focando em eficiência e pontos de melhoria."
    )
    with st.spinner("Gerando insights..."):
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":prompt}],
            temperature=0.7
        )
    st.markdown("**Insights Automáticos:**")
    st.write(resp.choices[0].message.content)

# ─── Chat Integrado ──────────────────────────────────────────────────────────────
st.subheader("💬 Chat com seus dados")
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

query = st.text_input("Pergunte algo sobre os dados", key="chat_input")
if st.button("Enviar", key="chat_send"):
    system_msg = (
        "Você é um assistente de análise de dados da MegaOffice. "
        f"Núcleos selecionados: {selecionados}. "
        f"Dados:\n{df_filtrado[['Pessoa','SS','WA']].to_dict(orient='records')}"
    )
    messages = [
        {"role":"system","content":system_msg},
        {"role":"user","content":query}
    ]
    with st.spinner("Pensando…"):
        chat_resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.5
        )
    st.session_state.chat_history.append((query, chat_resp.choices[0].message.content))

for user_q, bot_a in st.session_state.chat_history:
    message(user_q, is_user=True)
    message(bot_a)

