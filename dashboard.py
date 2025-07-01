import os
import pandas as pd
import streamlit as st
import plotly.express as px
from dotenv import load_dotenv
from openai import OpenAI
from streamlit_chat import message

# ─── Configurações de página ─────────────────────────────
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

# ─── Cliente OpenAI ──────────────────────────────────────
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.error("🚨 Defina OPENAI_API_KEY no .env")
    st.stop()
client = OpenAI(api_key=OPENAI_API_KEY)

# ─── Funções de carregamento e agregação ─────────────────
@st.cache_data
def load_data(path):
    df_ss = pd.read_excel(path, sheet_name="Solic. de Serviço") \
             .rename(columns={"Funcionário":"Atendido por","Quantidade":"Qtd"})
    df_ss["Tipo"] = "SS"
    df_wa = pd.read_excel(path, sheet_name="03-25 Atend conc")
    df_wa = df_wa[df_wa["Status"]=="Concluído"].copy()
    df_wa["Qtd"]  = 1
    df_wa["Tipo"] = "WA"

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

    # Garante que todos os nomes estejam mapeados (SS + WA)
    pessoas_set = set(df_ss["Atendido por"]) | set(df_wa["Atendido por"])
    df_pessoas = pd.DataFrame([split_info(p) for p in pessoas_set], columns=["Pessoa", "Departamento", "Núcleo"])
    df_pessoas["Atendido por"] = pessoas_set

    df = pd.concat([df_ss, df_wa], ignore_index=True)
    df["Data"] = pd.to_datetime(df["Data"], errors="ignore")
    return df, df_pessoas

@st.cache_data
def aggregate_data(df, df_pessoas):
    # Agrupa por pessoa, setor, núcleo e tipo de atendimento
    agg = (
        df.groupby(["Atendido por", "Pessoa", "Departamento", "Núcleo", "Tipo"])["Qtd"]
        .sum().unstack(fill_value=0).reset_index()
    )
    for col in ("SS", "WA"):
        if col not in agg:
            agg[col] = 0

    # Adiciona clientes únicos atendidos por colaborador (de qualquer tipo)
    clientes_count = (
        df.groupby("Atendido por")["Cliente"].nunique() if "Cliente" in df.columns else pd.Series()
    )
    agg["Clientes"] = agg["Atendido por"].map(clientes_count).fillna(0).astype(int)

    # Garante que todos os colaboradores apareçam (mesmo que zeros)
    agg = pd.merge(df_pessoas, agg, how="left", on=["Atendido por", "Pessoa", "Departamento", "Núcleo"])
    agg["SS"] = agg["SS"].fillna(0).astype(int)
    agg["WA"] = agg["WA"].fillna(0).astype(int)
    agg["Clientes"] = agg["Clientes"].fillna(0).astype(int)

    # Percentual SS = SS / Clientes (evita divisão por zero)
    agg["Percentual SS"] = agg.apply(lambda row: row["SS"] / row["Clientes"] if row["Clientes"] > 0 else 0, axis=1)
    return agg

# ─── Carrega dados ──────────────────────────────────────
df, df_pessoas = load_data("Teste 1 (1).xlsx")
df_agg = aggregate_data(df, df_pessoas)

# ─── Título e KPIs ──────────────────────────────────────
st.title("Dashboard de Eficiência MegaOffice")

ss_total  = int(df_agg["SS"].sum())
wa_total  = int(df_agg["WA"].sum())
dias      = df["Data"].dt.date.nunique() if "Data" in df.columns else 1
ss_diaria = ss_total / dias if dias else ss_total
wa_diaria = wa_total / dias if dias else wa_total

c1, c2, c3, c4 = st.columns(4)
c1.metric("SS Total",     ss_total)
c2.metric("WA Total",     wa_total)
c3.metric("Média SS/Dia", f"{ss_diaria:.1f}")
c4.metric("Média WA/Dia", f"{wa_diaria:.1f}")

# ─── Dados Tratados ─────────────────────────────────────
st.subheader("Dados Tratados")

df_show = df_agg[[
    "Atendido por", "SS", "WA", "Clientes", "Percentual SS", "Pessoa", "Departamento", "Núcleo"
]].copy()
df_show["Percentual SS"] = df_show["Percentual SS"].apply(lambda x: f"{100 * x:.2f}%")
df_show = df_show.sort_values("Atendido por")

st.dataframe(
    df_show.rename(columns={"Percentual SS":"% SS"}),
    use_container_width=True
)

# ─── Dados Agregados (ordenados) ────────────────────────
df_agg["Total"] = df_agg["SS"] + df_agg["WA"]
df_agg_sorted = df_agg.sort_values("Total", ascending=False).reset_index(drop=True)

st.subheader("Dados Agregados por Operador (ordenados por total)")
st.dataframe(
    df_agg_sorted.drop(columns="Total"),
    use_container_width=True
)

# ─── Filtro de Núcleo ───────────────────────────────────
st.sidebar.header("Filtros")
nucleos = sorted(df_agg_sorted["Núcleo"].dropna().unique())
selecionados = st.sidebar.multiselect(
    "Selecione Núcleo(s):",
    options=nucleos,
    default=nucleos,
    key="nucleo_filter"
)
df_filtrado = df_agg_sorted[df_agg_sorted["Núcleo"].isin(selecionados)]

# ─── Gráfico de Barras ──────────────────────────────────
st.subheader("Atendimentos por Operador")
fig = px.bar(
    df_filtrado,
    x="Pessoa",
    y=["SS", "WA"],
    barmode="group",
    labels={"value":"Total", "variable":"Tipo", "Pessoa":"Operador"},
    title=f"Núcleos: {', '.join(selecionados)}"
)
st.plotly_chart(fig, use_container_width=True)

# ─── Insights Automáticos ───────────────────────────────
if st.button("✨ Gerar Insights Automáticos"):
    prompt = (
        "Você é um analista de dados da MegaOffice. "
        "IMPORTANTE: 'SS' significa 'Serviços Solicitados' e 'WA' significa 'Atendimentos no WhatsApp'. "
        "Considere estes dados de eficiência por colaborador:\n"
        f"{df_filtrado[['Pessoa','Departamento','Núcleo','SS','WA','Clientes','Percentual SS']].to_dict(orient='records')}\n"
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

# ─── Chat Integrado ────────────────────────────────────
st.subheader("💬 Chat com seus dados")
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

query = st.text_input("Pergunte algo sobre os dados", key="chat_input")
if st.button("Enviar", key="chat_send"):
    system_msg = (
        "Você é um assistente de análise de dados da MegaOffice. "
        "IMPORTANTE: 'SS' significa 'Serviços Solicitados' e 'WA' significa 'Atendimentos no WhatsApp'. "
        f"Núcleos selecionados: {selecionados}. "
        f"Dados:\n{df_filtrado[['Pessoa','SS','WA','Clientes','Percentual SS']].to_dict(orient='records')}"
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
