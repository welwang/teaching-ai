import streamlit as st
from workflow_v2 import brand
st.set_page_config(page_title='教材簡報工作室', page_icon=brand.page_icon(), layout='wide', initial_sidebar_state='collapsed')
from workflow_v2.panel import show
show()
