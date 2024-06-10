import streamlit as st
import pandas as pd
csvZenyPath = "./dataSources/zeny.csv"
csvMuziPath = "./dataSources/muzi.csv"

st.header('Hello Marku a Rudy!')
st.write('Tohle bude zaklad vaseho Jukeboxu!')
csvZeny = pd.read_csv(csvZenyPath)
st.dataframe(csvZeny, hide_index=True)

st.write('Nize budeme iterovat skrz sloupecek "Umelec" plus "pisen" a pouzijeme to jako jmeno checkboxu')
st.checkbox('Ahoj')
st.checkbox('Ahoj2')
st.checkbox('Ahoj3')
st.checkbox('Ahoj4')

csvMuzi = pd.read_csv(csvMuziPath)
st.dataframe(csvMuzi, hide_index=True)