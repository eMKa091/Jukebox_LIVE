import streamlit as st

st.header('Dobrý den, vážení hosté!')
st.write('Zadejte prosím vaši přezdívku')
uniqueID = st.text_input(label="Jmeno ci prezdivka", label_visibility='hidden')

if uniqueID:
    st.session_state.uniqueID = uniqueID
    st.success("Uloženo! Přesuneme vás na další stránku...")
    st.switch_page("pages/Duety.py")

#col1, col2 = st.columns(2, gap="small")

#with col1:
#    if st.button("Duety"):
#        st.switch_page("pages/Duety.py")
#with col1:
#    if st.button("Rock and Roll"):
#        st.switch_page("pages/Rock and Roll.py")
#with col1:
#    if st.button("Zpěvačky"):
#        st.switch_page("pages/Zpěvačky.py")
#with col2:
#    if st.button("Zpěváci"):
#        st.switch_page("pages/Zpěváci.py")
#with col2:
#    if st.button("České písně"):
#        st.switch_page("pages/České písně.py")

#st.write('or see the full list of songs:')
