import streamlit as st
from band_control import get_band_page_content

def band_page():
    st.title("Band Page")

    # Retrieve the current playlist content from the database
    playlist_content = get_band_page_content()

    if playlist_content:
        # Replace newline characters with <br> for line breaks
        playlist_content = playlist_content.replace("\n", "<br>")
        # Replace tab characters with four non-breaking spaces for indentation
        playlist_content = playlist_content.replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")
        
        # Wrap the content in a <div> with custom style for larger, bold text
        styled_content = f"""
        <div style="font-size:20px; font-weight:bold; line-height:1.5;">
            {playlist_content}
        </div>
        """
        st.markdown(styled_content, unsafe_allow_html=True)
    else:
        st.info("Playlist nebyl definován.")