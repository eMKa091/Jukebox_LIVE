import streamlit as st
import pandas as pd

st.set_page_config(page_title='Duety')

csvDuetyPath = "./dataSources/duety.csv"

@st.cache_data
def load_duets_data(path):
    df = pd.read_csv(path)
    return df

duetsDF = load_duets_data(csvDuetyPath)
st.dataframe(duetsDF, hide_index=True)