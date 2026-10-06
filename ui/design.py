"""Shared visual design with bundled artwork and no external fonts or services."""
import base64
from functools import lru_cache
from html import escape
from pathlib import Path
from urllib.parse import quote
import streamlit as st


MARK = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><rect width="48" height="48" rx="14" fill="#087f8c"/><g fill="none" stroke="#b8f4e6" stroke-width="1.5" stroke-linejoin="round"><path d="M24 9L11 17v15l13 8 13-8V17L24 9zM11 17l13 8 13-8M24 25v15M24 9v16"/></g><circle cx="37" cy="11" r="4" fill="#f4bc78"/></svg>'''


def _image(svg):
    return 'data:image/svg+xml,'+quote(svg)


@lru_cache(maxsize=1)
def crystal_image():
    asset = Path(__file__).resolve().parent/'assets'/'crystal-formation.png'
    return 'data:image/png;base64,'+base64.b64encode(asset.read_bytes()).decode('ascii')


def apply_theme():
    st.markdown('''<style>
    :root { --dm-ink:#16334c; --dm-teal:#087f8c; --dm-border:#dce6ee; }
    .stApp { background:#f4f7fb; color:var(--dm-ink); }
    [data-testid="stHeader"] { background:rgba(244,247,251,.94); }
    [data-testid="stMainBlockContainer"] { padding:2.1rem 2.4rem 3rem; max-width:1500px; }
    [data-testid="stSidebar"] { background:#edf3f7; border-right:1px solid var(--dm-border); }
    [data-testid="stSidebar"] [data-testid="stSidebarContent"] { padding-top:1.1rem; }
    h1,h2,h3 { color:var(--dm-ink); letter-spacing:-.035em; }
    [data-testid="stCaptionContainer"] { color:#526b7d; line-height:1.65; }
    button:focus-visible, input:focus-visible, textarea:focus-visible { outline:3px solid #61bfc5 !important; outline-offset:3px; }
    [data-testid="stButton"] button,[data-testid="stDownloadButton"] button,[data-testid="stFormSubmitButton"] button {
        border:1px solid #c7d9e3; border-radius:10px; background:white; color:#21475e; min-height:2.6rem; font-weight:600; transition:background .15s,border-color .15s; }
    [data-testid="stButton"] button:hover,[data-testid="stDownloadButton"] button:hover,[data-testid="stFormSubmitButton"] button:hover { background:#e8f5f4; border-color:#087f8c; color:#086c77; }
    button[kind="primary"],[data-testid="stFormSubmitButton"] button { background:#087f8c; border-color:#087f8c; color:white; }
    button[kind="primary"]:hover,[data-testid="stFormSubmitButton"] button:hover { background:#066671; color:white; }
    button:disabled { opacity:.48; }
    [data-testid="stTextInputRootElement"],[data-testid="stTextAreaRootElement"],[data-testid="stNumberInputContainer"] { background:white; border-radius:10px; }
    [data-testid="stTextInputRootElement"]:focus-within,[data-testid="stTextAreaRootElement"]:focus-within { border-color:#087f8c; box-shadow:0 0 0 3px #087f8c12; }
    [data-testid="stFileUploaderDropzone"] { background:#fff; border:1.5px dashed #b3cbd7; border-radius:15px; padding:1.5rem; }
    [data-testid="stExpander"],[data-testid="stForm"] { border:1px solid var(--dm-border); border-radius:14px; background:#fff; }
    [data-testid="stMetric"] { background:white; border:1px solid var(--dm-border); padding:1rem 1.2rem; border-radius:14px; box-shadow:0 4px 15px #17384d04; }
    [data-testid="stDataFrame"] { border:1px solid var(--dm-border); border-radius:12px; overflow:hidden; }
    [data-testid="stAlert"] { border-radius:12px; }
    [role="tablist"] { gap:4px; background:white; border:1px solid var(--dm-border); padding:6px; border-radius:13px; overflow-x:auto; }
    [data-testid="stTab"] { height:42px; border-radius:8px; padding:0 10px; color:#526b7d; flex-shrink:0; }
    [data-testid="stTab"] p { font-size:.8rem; font-weight:600; }
    [data-testid="stTab"][aria-selected="true"] { background:#e6f3f2; color:#066671; }
    .react-aria-SelectionIndicator { display:none; }
    [data-testid="stChatMessage"] { border:1px solid var(--dm-border); background:white; border-radius:16px; padding:1.3rem; box-shadow:0 5px 20px #16334c04; }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { background:#e8f4f3; border-color:#c6e3df; }
    [data-testid="stChatMessageAvatarAssistant"] { background:#087f8c; color:white; }
    [data-testid="stChatInput"] { background:white; border:1px solid #b8d3d9; border-radius:16px; box-shadow:0 5px 24px #0b405611; }
    [data-testid="stBottom"] { background:linear-gradient(transparent,#f4f7fb 25%); }
    [data-testid="stMain"]:has(.dm-student) [data-testid="stMainBlockContainer"] { max-width:1100px; }
    [data-testid="stMain"]:has(.dm-login) [data-testid="stMainBlockContainer"] { max-width:1180px; padding-top:5vh; }
    [data-testid="stMain"]:has(.dm-login) [data-testid="stButton"] button { min-height:3.2rem; }
    .dm-brand { display:flex; gap:11px; align-items:center; margin:0 0 24px; }
    .dm-brand img { width:43px; height:43px; }
    .dm-brand strong { display:block; font-size:1.22rem; color:#15374b; letter-spacing:-.025em; }
    .dm-brand small { display:block; color:#5a7486; font-size:.73rem; margin-top:1px; }
    .dm-hero { position:relative; isolation:isolate; overflow:hidden; background:#102f46; border:1px solid #24485d; border-radius:23px; padding:36px 40px; margin-bottom:14px; box-shadow:0 14px 40px #15364c12; min-height:205px; }
    .dm-hero:before { content:""; position:absolute; inset:0; z-index:-1; opacity:.2; background-image:radial-gradient(#80c8ca 1px,transparent 1px); background-size:24px 24px; mask-image:linear-gradient(90deg,transparent,#000); }
    .dm-eyebrow { color:#83d9d2; font-size:.71rem; font-weight:700; letter-spacing:.17em; text-transform:uppercase; margin-bottom:14px; }
    .dm-hero h1 { color:#f3fbff; font-size:2.15rem; font-weight:650; line-height:1.15; margin:0 0 12px; padding:0 !important; max-width:72%; }
    .dm-hero p { color:#bad1dc; margin:0; max-width:64%; line-height:1.7; font-size:.96rem; }
    .dm-hero-art { position:absolute; width:270px; height:calc(100% - 16px); right:4px; top:8px; object-fit:contain; opacity:1; z-index:-1; filter:drop-shadow(0 10px 20px #53e2e326); }
    .dm-login { min-height:390px; padding:56px; }
    .dm-login h1 { font-size:3.3rem; max-width:60%; }
    .dm-login p { max-width:52%; font-size:1.08rem; }
    .dm-login .dm-hero-art { width:440px; height:360px; top:15px; right:6px; opacity:1; }
    .dm-pills { display:flex; flex-wrap:wrap; gap:8px; margin-top:23px; }
    .dm-pills span { border:1px solid #477080; color:#ceecea; border-radius:30px; padding:5px 11px; font-size:.7rem; background:#123e4d99; }
    .dm-login-note { margin:22px 0 8px; font-size:.8rem; color:#526b7d; }
    .dm-welcome { background:white; border:1px solid var(--dm-border); border-radius:18px; padding:25px 27px; margin:6px 0 14px; }
    .dm-welcome h2 { font-size:1.25rem; margin:0 0 6px; padding:0 !important; }
    .dm-welcome > p { color:#526b7d; font-size:.89rem; margin:0 0 20px; }
    .dm-topics { display:grid; grid-template-columns:repeat(3,1fr); gap:13px; }
    .dm-topic { background:#f3f8fa; border:1px solid #e2edf1; border-radius:12px; padding:17px; }
    .dm-topic b { display:block; color:#16737d; font-size:.86rem; margin-bottom:9px; }
    .dm-topic p { font-size:.79rem; color:#506a7a; line-height:1.6; margin:0; }
    .dm-section-label { text-transform:uppercase; font-size:.7rem; letter-spacing:.12em; font-weight:700; color:#637f90; margin:22px 0 10px; }
    @media (max-width:760px) { [data-testid="stMainBlockContainer"] { padding:1.2rem 1rem 2rem; }
      .dm-hero { padding:27px 25px; border-radius:17px; } .dm-hero h1 { font-size:1.7rem; max-width:90%; } .dm-hero p { max-width:87%; font-size:.85rem; }
      .dm-hero-art { opacity:.25; right:-70px; } .dm-login { padding:30px 25px 175px; } .dm-login h1 { font-size:2.25rem; max-width:100%; } .dm-login p { max-width:100%; }
      .dm-login .dm-hero-art { width:250px; height:185px; right:-15px; top:auto; bottom:-15px; opacity:.75; }
      .dm-topics { grid-template-columns:1fr; } .dm-welcome { padding:20px; }
    }
    @media (prefers-reduced-motion:reduce) { * { transition:none !important; } }
    </style>''',unsafe_allow_html=True)


def brand():
    st.markdown(f'<div class="dm-brand"><img src="{_image(MARK)}" alt="DocuMind crystal mark"><div><strong>DocuMind</strong><small>CHEMISTRY RESEARCH</small></div></div>',unsafe_allow_html=True)


def hero(view):
    titles = {
        'login':('A workspace for chemistry.','Explore your shared research through clear answers, connected evidence and cited sources.','Research, with clarity.'),
        'student':('Chemistry research assistant','Explore the chemistry documents shared with you. Ask a question, follow the evidence, and review the sources.','Your research companion'),
        'admin':('Your research, connected.','Manage the knowledge library, follow document processing, and understand how your chemistry assistant performs.','Administrator workspace')}
    title,description,eyebrow = titles[view]
    pills = '<div class="dm-pills"><span>Verified UCI sign-in</span><span>Document-based answers</span><span>Cited evidence</span></div>' if view=='login' else ''
    st.markdown(f'<section class="dm-hero dm-{view}"><div class="dm-eyebrow">{escape(eyebrow)}</div><h1>{escape(title)}</h1><p>{escape(description)}</p>{pills}<img class="dm-hero-art" src="{crystal_image()}" alt="Decorative translucent aquamarine crystal formation"></section>',unsafe_allow_html=True)


def login(provider):
    brand()
    hero('login')
    left,right = st.columns([1,1],gap='large')
    with left:
        st.markdown('<p class="dm-login-note">A shared chemistry workspace for the UCI community.</p>',unsafe_allow_html=True)
        clicked = st.button(f'Sign in with UCI {provider}',type='primary',width='stretch')
        st.caption('Use your verified @uci.edu account to continue.')
    with right:
        st.markdown('<p class="dm-login-note"><strong>From documents to discovery.</strong><br>Ask about synthesis, molecular structure and crystal properties. Access is limited to documents reviewed and shared by your administrator.</p>',unsafe_allow_html=True)
    return clicked


def welcome():
    st.markdown('''<section class="dm-welcome"><h2>Where would you like to begin?</h2><p>Start with a question about the chemistry in your shared documents.</p><div class="dm-topics"><article class="dm-topic"><b>Synthesis &amp; methods</b><p>Which conditions, solvents and yields are reported?</p></article><article class="dm-topic"><b>Molecules &amp; structure</b><p>What formula, bonding or characterization is described?</p></article><article class="dm-topic"><b>Crystals &amp; materials</b><p>Which cell parameters and structural properties are given?</p></article></div></section>''',unsafe_allow_html=True)
