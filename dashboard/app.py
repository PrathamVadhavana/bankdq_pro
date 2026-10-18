import os
import requests
import streamlit as st
import pandas as pd

st.set_page_config(page_title="BankDQ Pro", page_icon="🏦", layout="wide")
st.title("🏦 BankDQ Pro")
st.caption("Portfolio prototype: transaction data quality, batch processing and source-to-ledger reconciliation.")

api = st.sidebar.text_input("API base URL", os.getenv("BANKDQ_API_URL","http://127.0.0.1:8000")).rstrip("/")
st.sidebar.subheader("Account")
with st.sidebar.form("account_form"):
    username = st.text_input("Username", key="username")
    password = st.text_input("Password", type="password", key="password")
    register_submitted = st.form_submit_button("Register account")
    sign_in_submitted = st.form_submit_button("Sign in")

if register_submitted or sign_in_submitted:
    username = username.strip()
    if len(username) < 3:
        st.sidebar.error("Username must be at least 3 characters.")
    elif len(password) < 10:
        st.sidebar.error("Password must be at least 10 characters.")
    else:
        endpoint = "register" if register_submitted else "login"
        try:
            r = requests.post(
                f"{api}/auth/{endpoint}",
                json={"username": username, "password": password},
                timeout=15,
            )
        except requests.RequestException as exc:
            st.sidebar.error(f"Could not reach the API: {exc}")
        else:
            if r.ok and register_submitted:
                st.sidebar.success("Registered. Now sign in.")
            elif r.ok:
                st.session_state["token"] = r.json()["access_token"]
                st.sidebar.success("Signed in")
            else:
                st.sidebar.error(r.text)

token=st.session_state.get("token")
if not token:
    st.info("Register or sign in in the sidebar. Passwords must be at least 10 characters.")
    st.stop()
headers={"Authorization":f"Bearer {token}"}
st.subheader("Create a processing batch")
with st.form("batch_upload"):
    name=st.text_input("Batch name", "October transaction review")
    chunk_size=st.select_slider("Processing chunk size", options=[50,100,250,500,1000,2500,5000,10000], value=500,
                                help="Rows are processed and flushed in chunks. This is a configurable batch size, not a parallel-worker count.")
    sources=st.file_uploader("Source transaction CSV(s)", type=["csv"], accept_multiple_files=True)
    ledger=st.file_uploader("Optional ledger/reference CSV", type=["csv"], accept_multiple_files=False)
    submitted=st.form_submit_button("Upload and process")
if submitted:
    if not sources: st.error("Choose at least one source CSV.")
    else:
        payload=[("files",(f.name,f.getvalue(),"text/csv")) for f in sources]
        if ledger: payload.append(("ledger_file",(ledger.name,ledger.getvalue(),"text/csv")))
        data={"name":name,"chunk_size":str(chunk_size)}
        with st.spinner("Processing uploaded files..."):
            r=requests.post(f"{api}/batches",headers=headers,data=data,files=payload,timeout=180)
        if r.ok:
            st.session_state["last_batch"]=r.json()["batch_id"]
            st.success("Batch processed")
            st.json(r.json())
        else: st.error(f"{r.status_code}: {r.text}")

st.divider()
st.subheader("Your batches")
r=requests.get(f"{api}/batches?page=1&page_size=50",headers=headers,timeout=15)
if r.ok:
    items=r.json()["items"]
    if items:
        st.dataframe(pd.DataFrame(items),width="stretch",hide_index=True)
        batch_ids=[x["id"] for x in items]
        selected=st.selectbox("Inspect batch",batch_ids,format_func=lambda x: next((i["name"]+" — "+x[:8] for i in items if i["id"]==x),x))
        c1,c2,c3=st.columns(3)
        detail=requests.get(f"{api}/batches/{selected}",headers=headers,timeout=15)
        if detail.ok:
            d=detail.json()
            c1.metric("Rows",d["rows_received"]); c2.metric("Invalid rows",d["rows_invalid"]); c3.metric("Issues",d["issue_count"])
        mr=requests.get(f"{api}/batches/{selected}/metrics",headers=headers,timeout=15)
        if mr.ok:
            m=mr.json()
            st.markdown("#### Reconciliation exposure estimate")
            st.caption(m["exposure_currency_note"])
            e1,e2,e3,e4=st.columns(4)
            e1.metric("Total estimated exposure",m["financial_exposure_estimate"])
            e2.metric("Amount mismatch",m["amount_mismatch_exposure"])
            e3.metric("Source only",m["source_only_exposure"])
            e4.metric("Ledger only",m["ledger_only_exposure"])
        tabs=st.tabs(["Issues","Reconciliation","Audit"])
        with tabs[0]:
            ir=requests.get(f"{api}/batches/{selected}/issues?page=1&page_size=200",headers=headers,timeout=15)
            if ir.ok and ir.json()["items"]: st.dataframe(pd.DataFrame(ir.json()["items"]),width="stretch",hide_index=True)
            else: st.write("No issues on this page.")
        with tabs[1]:
            rr=requests.get(f"{api}/batches/{selected}/reconciliation?page=1&page_size=200",headers=headers,timeout=15)
            if rr.ok and rr.json()["items"]:
                df=pd.DataFrame(rr.json()["items"]); st.dataframe(df,width="stretch",hide_index=True)
                dl=requests.get(f"{api}/batches/{selected}/reconciliation.csv",headers=headers,timeout=15)
                if dl.ok: st.download_button("Download reconciliation CSV",dl.content,file_name="reconciliation.csv",mime="text/csv")
            else: st.write("No reconciliation data. Upload a ledger CSV to enable matching.")
        with tabs[2]:
            ar=requests.get(f"{api}/audit?page=1&page_size=100",headers=headers,timeout=15)
            if ar.ok and ar.json()["items"]: st.dataframe(pd.DataFrame(ar.json()["items"]),width="stretch",hide_index=True)
    else: st.info("No batches yet. Upload source CSVs above.")
else: st.warning("Could not load batches. Confirm the API is running.")
