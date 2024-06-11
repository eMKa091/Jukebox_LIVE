import streamlit as st
import pandas as pd

st.set_page_config(page_title='České písně')

csvCeskePath = "./dataSources/ceske.csv"

@st.cache_data
def load_ceske_data(path):
    df = pd.read_csv(path)
    return df

ceskeDF = load_ceske_data(csvCeskePath)
st.dataframe(ceskeDF, hide_index=True)