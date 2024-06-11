import streamlit as st
import pandas as pd

st.set_page_config(page_title='Ženy')

# Caching data for faster loading
csvZenyPath = "./dataSources/zeny.csv"

@st.cache_data
def load_female_data(path):
    df = pd.read_csv(path)
    return df

zenyDF = load_female_data(csvZenyPath)
st.dataframe(zenyDF, hide_index=True)