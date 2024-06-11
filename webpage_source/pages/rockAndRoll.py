import streamlit as st
import pandas as pd

st.set_page_config(page_title='Rock&Roll!')

csvRokenrolPath = "./dataSources/rokenrol.csv"

@st.cache_data
def load_rr_data(path):
    df = pd.read_csv(path)
    return df

rokenrolDF = load_rr_data(csvRokenrolPath)
st.dataframe(rokenrolDF, hide_index=True)