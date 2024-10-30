import streamlit as st
from band_control import get_band_page_content

# Band Page Display
def band_page():
    st.title("Band Page")
    st.subheader("Playlist for the Band")

    # Retrieve the current playlist content from the database
    playlist_content = get_band_page_content()
    
    if playlist_content:
        st.markdown(playlist_content)
    else:
        st.info("No playlist content defined yet.")
