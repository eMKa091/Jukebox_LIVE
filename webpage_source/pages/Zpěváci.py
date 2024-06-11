import streamlit as st
import pandas as pd

st.set_page_config(page_title='Muži')

# Caching data for faster loading
csvMuziPath = "./dataSources/muzi.csv"

@st.cache_data
def load_male_data(path):
    df = pd.read_csv(path)
    return df

zenyDF = load_male_data(csvMuziPath)
st.dataframe(zenyDF, hide_index=True)