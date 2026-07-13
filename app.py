import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta
import os
import io
import re
import json
import gspread
from google.oauth2.service_account import Credentials

# ==============================================================================
# CONFIGURACIÓN DE TU BASE DE DATOS PERMANENTE (GOOGLE SHEETS)
# ==============================================================================
URL_BD_NUBE = "https://docs.google.com/spreadsheets/d/1DhPSc6-qqwzaP1UuF_1JaNI9Z8HMx9_2JAHBQxiPAhw/edit?usp=sharing"

HOJA_ATENCIONES = "Atenciones"
HOJA_USUARIOS = "Usuarios"
HOJA_PACIENTES = "Pacientes"
HOJA_PROFESIONALES = "Profesionales"

# ==============================================================================
# CONFIGURACIÓN GENERAL Y ESTILOS VISUALES
# ==============================================================================
st.set_page_config(page_title="Registro de Emergencias - Orellana", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    .stApp { background-color: #f4f7f9; }
    .stButton>button { background-color: #005A9C; color: white; border-radius: 8px; border: none; padding: 0.5rem 1rem; font-weight: 600; transition: all 0.3s ease; }
    .stButton>button:hover { background-color: #003F7A; color: white; transform: translateY(-2px); }
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div { border-radius: 6px; }
    .stTabs [data-baseweb="tab-list"] { gap: 24px; }
    .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; background-color: transparent; border-radius: 4px 4px 0px 0px; padding-top: 10px; padding-bottom: 10px; }
    .stTabs [aria-selected="true"] { background-color: #e6f0fa; border-bottom: 3px solid #005A9C; color: #005A9C; font-weight: bold; }
    div[data-testid="stTextInput"] div.st-key-id_0 input, div[data-testid="stTextInput"] div[data-baseweb="input"]:has(input[aria-label="Número de Identificación (Presione ENTER para buscar)"]) { background-color: #e8f5e9 !important; border: 2px solid #2e7d32 !important; box-shadow: 0 0 5px rgba(46, 125, 50, 0.4) !important; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# ==============================================================================
# FUNCIONES DE LIMPIEZA DE TEXTO
# ==============================================================================
def limpiar_texto(texto):
    """Convierte a mayúsculas y quita todas las tildes de un texto."""
    if texto is None or pd.isna(texto):
        return ""
    t = str(texto).strip().upper()
    reemplazos = {
        'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O', 'Ú': 'U',
        'Ä': 'A', 'Ë': 'E', 'Ï': 'I', 'Ö': 'O', 'Ü': 'U'
    }
    for con_tilde, sin_tilde in reemplazos.items():
        t = t.replace(con_tilde, sin_tilde)
    return t

# ==============================================================================
# MOTOR DE CONEXIÓN A GOOGLE SHEETS
# ==============================================================================
@st.cache_resource
def get_gsheets_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    s_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS_JSON"])
    creds = Credentials.from_service_account_info(s_dict, scopes=scopes)
    return gspread.authorize(creds)

@st.cache_data(ttl=10, show_spinner=False)
def cargar_tabla(hoja_nombre):
    try:
        client = get_gsheets_client()
        sheet = client.open_by_url(URL_BD_NUBE).worksheet(hoja_nombre)
        registros = sheet.get_all_records()
        if not registros:
            return pd.DataFrame()
        return pd.DataFrame(registros, dtype=str)
    except Exception as e:
        return pd.DataFrame()

def proteger_ceros(val):
    val_str = str(val).strip()
    if val_str.isdigit() and val_str.startswith("0"):
        return "'" + val_str
    return val_str

def normalizar_id(val):
    return str(val).replace("'", "").replace(".0", "").strip().lstrip("0")

def guardar_tabla(hoja_nombre, df):
    try:
        client = get_gsheets_client()
        sheet = client.open_by_url(URL_BD_NUBE).worksheet(hoja_nombre)
        sheet.clear()
        df_str = df.fillna("").astype(str)
        for col in df_str.columns:
            df_str[col] = df_str[col].apply(proteger_ceros)
            
        datos = [df_str.columns.values.tolist()] + df_str.values.tolist()
        try:
            sheet.update(values=datos, range_name="A1")
        except TypeError:
            sheet.update("A1", datos)
        cargar_tabla.clear()
    except Exception as e:
        st.error(f"Error guardando {hoja_nombre}: {e}")

# ==============================================================================
# GESTIÓN DE SESIÓN Y CATÁLOGOS
# ==============================================================================
def cargar_usuarios():
    df = cargar_tabla(HOJA_USUARIOS)
    if df.empty:
        df = pd.DataFrame([{"USUARIO": "admin", "CONTRASENA": "orellana2026", "ROL": "ADMIN", "UNICODIGO": "TODOS"}])
        guardar_tabla(HOJA_USUARIOS, df)
    return df

def cargar_profesionales():
    df = cargar_tabla(HOJA_PROFESIONALES)
    if df.empty: return pd.DataFrame(columns=["CEDULA", "PRIMER NOMBRE", "SEGUNDO NOMBRE", "PRIMER APELLIDO", "SEGUNDO APELLIDO", "NOMBRE_COMPLETO"])
    return df

if 'autenticado' not in st.session_state:
    st.session_state.autenticado = False
    st.session_state.usuario_actual = ""
    st.session_state.rol_actual = ""
    st.session_state.unicodigo_actual = ""
    st.session_state.prefill_auto = {} 
    st.session_state.last_checked_id = ""

def login():
    st.markdown("<br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("""
            <div style='text-align: center; margin-bottom: 2rem;'>
                <h1 style='color: #005A9C; font-size: 2.2rem; font-weight: bold; margin-bottom: 0.2rem;'>Ministerio de Salud Pública</h1>
                <h2 style='color: #4A769E; font-size: 1.4rem; font-weight: 600; margin-top: 0; margin-bottom: 0.2rem;'>Dirección Provincial de Orellana</h2>
                <h3 style='color: #6C8EAD; font-size: 1.1rem; margin-top: 0; font-weight: normal; letter-spacing: 1px;'>Registro de Emergencias en la Nube</h3>
            </div>
        """, unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown("<h4 style='text-align: center; color: #333; font-weight:600;'>Inicio de Sesión</h4>", unsafe_allow_html=True)
            st.markdown("<hr style='margin-top: 0.5rem; margin-bottom: 1.5rem; border: 0.5px solid #eee;'>", unsafe_allow_html=True)
            usuario = st.text_input("👤 Nombre de Usuario", placeholder="Ej: admin")
            contrasena = st.text_input("🔑 Contraseña", type="password", placeholder="Ingrese su contraseña")
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Ingresar al Sistema", use_container_width=True):
                df_usuarios = cargar_usuarios()
                user_match = df_usuarios[(df_usuarios['USUARIO'] == usuario) & (df_usuarios['CONTRASENA'] == contrasena)]
                if not user_match.empty:
                    st.session_state.autenticado = True
                    st.session_state.usuario_actual = user_match.iloc[0]['USUARIO']
                    st.session_state.rol_actual = user_match.iloc[0]['ROL']
                    st.session_state.unicodigo_actual = user_match.iloc[0]['UNICODIGO']
                    st.session_state.prefill_auto = {}
                    st.session_state.last_checked_id = ""
                    st.rerun()
                else:
                    st.error("❌ Credenciales incorrectas. Verifique e intente nuevamente.")

TIPOS_DOCUMENTO = ["CEDULA DE IDENTIDAD O CIUDADANÍA", "PASAPORTE", "VISA", "CARNE DE REFUGIADO", "SIN DOCUMENTO DE IDENTIFICACION"]
SEXO_OPCIONES = ["HOMBRE", "MUJER", "INTERSEXUAL"]
CONDICION_EDAD = ["AÑO/S", "MES/ES", "DIA/S", "HORA/S"]
ETNIAS = ["Indígena", "Mestizo/a", "Afro ecuatoriano/a Afro descendiente", "Negro/a", "Montubio/a", "Mulato/a", "Blanco/a", "Otro/a", "Ninguno"]
GRUPO_PRIORITARIO = ["NO APLICA", "EMBARAZADAS", "PERSONAS CON DISCAPACIDAD", "PERSONAS POR DESASTRES NATURALES", "PERSONAS POR DESASTRES ANTROPOGÉNICOS", "ENFERMEDADES CATASTRÓFICAS Y RARAS", "MALTRATO INFANTIL", "PERSONAS PRIVADAS DE LA LIBERTAD", "VÍCTIMAS DE VIOLENCIA FÍSICA", "VÍCTIMAS DE VIOLENCIA PSICOLÓGICA", "VÍCTIMAS DE VIOLENCIA SEXUAL", "TRABAJADOR/A SEXUAL *", "EXPUESTO PERINATAL", "PLANIFICACIÓN FAMILIAR*", "HSH*"]
TIPO_SEGURO = ["IESS (GENERAL,VOLUNTARIO)_SEGURO", "IESS SEGURO CAMPESINO", "ISSFA_SEGURO", "ISSPOL_SEGURO", "PRIVADO_SEGURO", "NO APORTA_SEGURO"]
CONDICION_DIAGNOSTICO = ["PRESUNTIVO", "DEFINITIVO INICIAL", "DEFINITIVO INICIAL CONFIRMADO POR LABORATORIO", "NO APLICA"]
CONDICION_ALTA = ["VIVO/A", "FALLECIDO/A"]
CAUSA_ATENCION = ["ATENCIÓN NORMAL", "ATENCIONES POR MANIFESTACIÓN"]
ESPECIALIDADES_PROFESIONAL = ["MEDICO", "OBSTETRIZ"]
NACIONALIDAD = ["ECUATORIANO/A", "COLOMBIANO/A", "VENEZOLANO/A", "PERUANO/A", "OTRO"]

HOSPITALES_REFERENCIA = [
    "", "002045 HOSPITAL GENERAL FRANCISCO DE ORELLANA", "001548 HOSPITAL GENERAL JOSE MARIA VELASCO IBARRA",
    "001602 HOSPITAL GENERAL PUYO", "001999 HOSPITAL GENERAL MARCO VINICIO IZA",
    "000359 HOSPITAL GENERAL LATACUNGA", "001549 HOSPITAL BASICO DE BAEZA", "000000 OTRO"
]

COLUMNAS_OFICIALES = [
    "INSTITUCIÓN DEL SISTEMA", "UNICODIGO", "NOMBRE DEL ESTABLECIMIENTO DE SALUD", "ZONA", "PROVINCIA", "CANTON", "DISTRITO", "NIVEL", 
    "FECHA DE ATENCIÓN", "HORA ATENCION", "FECHA DE NACIMIENTO DEL PACIENTE", "TIPO DE DOCUMENTO DE IDENTIFICACIÓN", "NÚMERO DE IDENTIFICACION", 
    "PRIMER APELLIDO", "SEGUNDO APELLIDO", "PRIMER NOMBRE", "SEGUNDO NOMBRE", "SEXO", "EDAD", "CONDICIÓN DE LA EDAD", "NACIONALIDAD", 
    "ETNIA", "GRUPO PRIORITARIO", "TIPO DE SEGURO", "PROV_RES", "CANT_RES", "PARR_RES", "ESPECIALIDAD DEL PROFESIONAL", 
    "CIE-10 (PRINCIPAL)", "DIGANÓSTICO 1 (PRINCIPAL)", "CONDICIÓN DEL DIAGNÓSTICO", "CIE-10 (CAUSA EXTERNA)", 
    "DIAGNOSTICO (CAUSA EXTERNA)", "CONDICIÓN DEL ALTA", "REQUIERE HOSPITALIZACIÓN", 
    "NOMBRE DEL HOSPITAL AL QUE FUE REFERIDO PARA LA HOSPITALIZACIÓN", "CAUSA DE ATENCIÓN", 
    "NÚMERO DE IDENTIFICACIÓN DEL PROFESIONAL DE SALUD", "NOMBRES Y APELLIDOS DEL PROFESIONAL DE SALUD"
]

@st.cache_data
def cargar_cie(archivo, sep=';'):
    if os.path.exists(archivo):
        try:
            try: df = pd.read_csv(archivo, sep=sep, dtype=str, encoding='utf-8-sig')
            except: df = pd.read_csv(archivo, sep=sep, dtype=str, encoding='latin1')
            df.columns = df.columns.str.strip().str.upper()
            col_cie = [c for c in df.columns if 'CIE' in c]
            col_desc = [c for c in df.columns if 'DESCRIPCION' in c or 'DESCRIPCIÓN' in c]
            if col_cie and col_desc:
                df = df.dropna(subset=[col_cie[0], col_desc[0]])
                return [""] + (df[col_cie[0]].str.strip() + " - " + df[col_desc[0]].str.strip()).tolist()
        except Exception: pass
    return [""]

CIE10_PRIN_OPCIONES = cargar_cie("CIE 10 PRINCIPALES.csv")
CIE10_SEC_OPCIONES = cargar_cie("CIE 10 secundarios.csv")

@st.cache_data
def cargar_base_establecimientos():
    archivo_excel = "BASE ESTABLECIMIENTOS.xlsx"
    df = None
    if os.path.exists(archivo_excel):
        try:
            diccionario_hojas = pd.read_excel(archivo_excel, sheet_name=None, dtype=str)
            for nombre_hoja, df_hoja in diccionario_hojas.items():
                df_hoja.columns = df_hoja.columns.astype(str).str.strip().str.upper().str.replace('Ó', 'O').str.replace('Í', 'I')
                if any('UNICODIGO' in c or 'CODIGO' in c for c in df_hoja.columns):
                    df = df_hoja
                    break
        except Exception: pass
    if df is not None and not df.empty:
        for col in df.columns:
            if 'UNICODIGO' in col or 'CODIGO' in col:
                df.rename(columns={col: 'UNICODIGO'}, inplace=True)
                break
        df.fillna("", inplace=True)
        return df
    return None

base_est = cargar_base_establecimientos()

def validar_cedula_ecuatoriana(cedula):
    if len(cedula) != 10 or not cedula.isdigit(): return False
    provincia = int(cedula[0:2])
    if provincia < 1 or (provincia > 24 and provincia != 30): return False
    tercer_digito = int(cedula[2])
    if tercer_digito >= 6: return False
    coeficientes = [2, 1, 2, 1, 2, 1, 2, 1, 2]
    total = sum(int(cedula[i]) * coeficientes[i] - 9 if int(cedula[i]) * coeficientes[i] > 9 else int(cedula[i]) * coeficientes[i] for i in range(9))
    digito_verificador = int(cedula[9])
    calculado = ((total + 9) // 10) * 10 - total
    if calculado == 10: calculado = 0
    return calculado == digito_verificador

def safe_index(lista, valor, default=0):
    try:
        if pd.isna(valor) or str(valor).strip() == "": return default
        val_clean = limpiar_texto(valor)
        for i, item in enumerate(lista):
            if str(item).strip().upper() == val_clean or str(item).split(" - ")[0].strip() == val_clean:
                return i
        return default
    except Exception: return default

def safe_date(date_str, default_today=False):
    if pd.isna(date_str) or str(date_str).strip() == "" or str(date_str).strip().upper() in ["N/A", "NAN", "NAT", "NONE"]:
        return date.today() if default_today else None
    d_str = str(date_str).strip().split(" ")[0].split("T")[0]
    try:
        parsed = pd.to_datetime(d_str, errors='coerce', dayfirst=True)
        if pd.notna(parsed): return parsed.date()
    except: pass
    formats = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d", "%d/%m/%y"]
    for fmt in formats:
        try: return datetime.strptime(d_str, fmt).date()
        except ValueError: pass
    return date.today() if default_today else None

def calcular_edad(fecha_nacimiento):
    hoy = date.today()
    if not fecha_nacimiento: return 0, "AÑO/S"
    anios = hoy.year - fecha_nacimiento.year - ((hoy.month, hoy.day) < (fecha_nacimiento.month, fecha_nacimiento.day))
    meses = (hoy.year - fecha_nacimiento.year) * 12 + hoy.month - fecha_nacimiento.month
    if hoy.day < fecha_nacimiento.day: meses -= 1
    dias = (hoy - fecha_nacimiento).days
    if anios >= 1: return anios, "AÑO/S"
    elif meses >= 1: return meses, "MES/ES"
    else: return max(0, dias), "DIA/S"

# ==========================================
# VENTANA EMERGENTE PARA PROFESIONAL
# ==========================================
@st.dialog("👨‍⚕️ Registrar Nuevo Profesional de Salud")
def modal_nuevo_profesional(cedula_prof):
    st.markdown(f"La cédula **{cedula_prof}** no figura en la Nube. Ingrese los datos en estricto orden:")
    p_nom = st.text_input("1. Primer Nombre", key="new_prof_pnom")
    s_nom = st.text_input("2. Segundo Nombre", key="new_prof_snom")
    p_ape = st.text_input("3. Primer Apellido", key="new_prof_pape")
    s_ape = st.text_input("4. Segundo Apellido", key="new_prof_sape")
    
    if st.button("💾 Guardar en Base Nube", use_container_width=True):
        if not p_nom or not p_ape:
            st.error("❌ El Primer Nombre y Primer Apellido son obligatorios.")
        else:
            nom_completo = f"{limpiar_texto(p_nom)} {limpiar_texto(s_nom)} {limpiar_texto(p_ape)} {limpiar_texto(s_ape)}"
            nom_completo = re.sub(r'\s+', ' ', nom_completo).strip()
            df_nuevo_p = pd.DataFrame([{
                "CEDULA": cedula_prof.strip(), 
                "PRIMER NOMBRE": limpiar_texto(p_nom),
                "SEGUNDO NOMBRE": limpiar_texto(s_nom), 
                "PRIMER APELLIDO": limpiar_texto(p_ape),
                "SEGUNDO APELLIDO": limpiar_texto(s_ape), 
                "NOMBRE_COMPLETO": nom_completo
            }])
            df_profs = cargar_profesionales()
            df_final_profs = pd.concat([df_profs, df_nuevo_p], ignore_index=True) if not df_profs.empty else df_nuevo_p
            guardar_tabla(HOJA_PROFESIONALES, df_final_profs)
            st.rerun()

# ==========================================
# RENDERIZADO DEL FORMULARIO
# ==========================================
def renderizar_campos_paciente(fk, prefill=None, df_global=None):
    if prefill is None: prefill = {}
    st.markdown("### 📝 2. Datos de Atención y Paciente")
    
    col_doc1, col_doc2 = st.columns(2)
    tipo_doc = col_doc1.selectbox("Tipo de Documento", TIPOS_DOCUMENTO, index=safe_index(TIPOS_DOCUMENTO, prefill.get("TIPO DE DOCUMENTO DE IDENTIFICACIÓN")), key=f"td_{fk}")
    identificacion = col_doc2.text_input("Número de Identificación (Presione ENTER para buscar)", value=prefill.get("NÚMERO DE IDENTIFICACION", ""), key=f"id_{fk}")
    
    id_valida = False
    if identificacion:
        if tipo_doc == "CEDULA DE IDENTIDAD O CIUDADANÍA":
            if not validar_cedula_ecuatoriana(identificacion): col_doc2.error("❌ Cédula ecuatoriana inválida.")
            else: id_valida = True
        elif tipo_doc == "SIN DOCUMENTO DE IDENTIFICACION":
            if len(identificacion) != 17: col_doc2.error("❌ Debe contener exactamente 17 caracteres.")
            else: id_valida = True
        else:
            id_valida = True

    current_id = identificacion.strip()
    
    if fk.startswith("nuevo") and current_id and id_valida:
        if st.session_state.get("last_checked_id") != current_id:
            match_row = {}
            current_id_norm = normalizar_id(current_id) 
            
            df_loc = cargar_tabla(HOJA_PACIENTES)
            if not df_loc.empty and "NÚMERO DE IDENTIFICACION" in df_loc.columns:
                res_loc = df_loc[df_loc["NÚMERO DE IDENTIFICACION"].apply(normalizar_id) == current_id_norm]
                if not res_loc.empty: match_row = res_loc.iloc[-1].to_dict()

            if not match_row and df_global is not None and not df_global.empty and "NÚMERO DE IDENTIFICACION" in df_global.columns:
                res_hist = df_global[df_global["NÚMERO DE IDENTIFICACION"].apply(normalizar_id) == current_id_norm]
                if not res_hist.empty: match_row = res_hist.iloc[-1].to_dict()

            st.session_state["prefill_auto"] = match_row
            st.session_state["last_checked_id"] = current_id
            st.session_state["rt"] = st.session_state.get("rt", 0) + 1

    if fk.startswith("nuevo") and st.session_state.get("prefill_auto"):
        prefill.update(st.session_state["prefill_auto"])
        
    rt = st.session_state.get("rt", 0)
    dyn_k = f"_{st.session_state.get('last_checked_id', '')}_{rt}" if fk.startswith("nuevo") else ""
    
    paciente_encontrado = True if st.session_state.get("prefill_auto") else False
    bloquear_campos = paciente_encontrado if (fk.startswith("nuevo") and st.session_state.rol_actual == "USUARIO") else False

    if identificacion and id_valida and fk.startswith("nuevo") and paciente_encontrado:
        st.success("✅ Paciente encontrado en la Nube y cargado exitosamente.")

    if identificacion and id_valida and fk.startswith("nuevo") and not paciente_encontrado:
        st.warning("⚠️ El paciente NO está registrado en la Nube. Por favor, ingrese sus datos.")
        with st.expander("👤 INGRESO DE NUEVO PACIENTE", expanded=True):
            st.markdown("Complete los datos demográficos. La edad se calculará automáticamente.")
            c_np1, c_np2, c_np3, c_np4 = st.columns(4)
            np_pa = c_np1.text_input("Primer Apellido", key=f"np_pa_{fk}")
            np_sa = c_np2.text_input("Segundo Apellido", key=f"np_sa_{fk}")
            np_pn = c_np3.text_input("Primer Nombre", key=f"np_pn_{fk}")
            np_sn = c_np4.text_input("Segundo Nombre", key=f"np_sn_{fk}")
            
            c_np5, c_np6, c_np7 = st.columns(3)
            np_fn = c_np5.date_input("Fecha de Nacimiento", value=None, min_value=date(1900, 1, 1), max_value=date.today(), format="DD/MM/YYYY", key=f"np_fn_form_{fk}")
            calc_edad, calc_cond_edad = calcular_edad(np_fn)
            c_np6.text_input("Edad Calculada", value=str(calc_edad), disabled=True, key=f"np_edadcalc_{fk}")
            c_np7.text_input("Condición Calculada", value=calc_cond_edad, disabled=True, key=f"np_condcalc_{fk}")

            c_np8, c_np9, c_np10, c_np11 = st.columns(4)
            np_sexo = c_np8.selectbox("Sexo", SEXO_OPCIONES, key=f"np_sx_{fk}")
            np_nac = c_np9.selectbox("Nacionalidad", NACIONALIDAD, key=f"np_nc_{fk}")
            np_etn = c_np10.selectbox("Etnia", ETNIAS, key=f"np_et_{fk}")
            np_gp = c_np11.selectbox("Grupo Prioritario", GRUPO_PRIORITARIO, key=f"np_gp_{fk}")

            c_np12, c_np13, c_np14, c_np15 = st.columns(4)
            np_ts = c_np12.selectbox("Tipo de Seguro", TIPO_SEGURO, key=f"np_ts_{fk}")
            np_pr = c_np13.text_input("Provincia de Residencia", key=f"np_pr_{fk}")
            np_cr = c_np14.text_input("Cantón de Residencia", key=f"np_cr_{fk}")
            np_par = c_np15.text_input("Parroquia de Residencia", key=f"np_par_{fk}")

            if st.button("💾 Guardar Paciente en Nube", key=f"btn_save_pac_{fk}"):
                if not np_pa or not np_pn or not np_fn:
                    st.error("Debe llenar al menos el Primer Nombre, Primer Apellido y la Fecha de Nacimiento.")
                else:
                    payload = {
                        "NÚMERO DE IDENTIFICACION": current_id, 
                        "PRIMER APELLIDO": limpiar_texto(np_pa), 
                        "SEGUNDO APELLIDO": limpiar_texto(np_sa),
                        "PRIMER NOMBRE": limpiar_texto(np_pn), 
                        "SEGUNDO NOMBRE": limpiar_texto(np_sn), 
                        "SEXO": np_sexo, "EDAD": str(calc_edad),
                        "CONDICIÓN DE LA EDAD": calc_cond_edad, "NACIONALIDAD": np_nac, "ETNIA": np_etn, "GRUPO PRIORITARIO": np_gp,
                        "TIPO DE SEGURO": np_ts, 
                        "PROV_RES": limpiar_texto(np_pr), 
                        "CANT_RES": limpiar_texto(np_cr), 
                        "PARR_RES": limpiar_texto(np_par),
                        "FECHA DE NACIMIENTO DEL PACIENTE": np_fn.strftime("%d/%m/%Y")
                    }
                    try:
                        df_nuevo_paciente = pd.DataFrame([payload])
                        df_loc = cargar_tabla(HOJA_PACIENTES)
                        df_final_p = pd.concat([df_loc, df_nuevo_paciente], ignore_index=True) if not df_loc.empty else df_nuevo_paciente
                        guardar_tabla(HOJA_PACIENTES, df_final_p)
                        
                        st.session_state["prefill_auto"] = payload
                        st.session_state["rt"] = st.session_state.get("rt", 0) + 1
                        st.rerun() 
                    except Exception as e:
                        st.error(f"Error al guardar: {e}")
        st.stop()

    col9, col10, col11 = st.columns(3)
    
    # === BLOQUEO DE FECHA A MÁXIMO 2 DÍAS ATRÁS ===
    fecha_hoy = date.today()
    limite_inferior = fecha_hoy - timedelta(days=2)
    valor_fecha_atencion = safe_date(prefill.get("FECHA DE ATENCIÓN", ""), default_today=True)
    
    # Ajuste dinámico de seguridad para registros editados que son antiguos
    if valor_fecha_atencion and valor_fecha_atencion < limite_inferior:
        min_calendario = valor_fecha_atencion
    else:
        min_calendario = limite_inferior

    fecha_atencion = col9.date_input("Fecha de Atención", value=valor_fecha_atencion, min_value=min_calendario, max_value=fecha_hoy, format="DD/MM/YYYY", key=f"fa_{fk}")
    # ==============================================

    hora_atencion = col10.text_input("Hora de Atención (HH:MM)", value=prefill.get("HORA ATENCION", ""), placeholder="Ej: 08:30", key=f"ha_{fk}")
    hora_valida = True
    if hora_atencion and not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", str(hora_atencion)):
        col10.error("❌ Formato inválido (HH:MM).")
        hora_valida = False

    fn_val = prefill.get("FECHA DE NACIMIENTO DEL PACIENTE", "")
    if not fn_val:
        for k, v in prefill.items():
            if "NACIMIENTO" in str(k).upper():
                fn_val = v
                break
    fecha_nacimiento = col11.date_input("Fecha de Nacimiento", value=safe_date(fn_val, default_today=False), min_value=date(1900, 1, 1), max_value=fecha_hoy, format="DD/MM/YYYY", key=f"fn_{fk}{dyn_k}", disabled=bloquear_campos)

    col14, col15, col16, col17 = st.columns(4)
    primer_apellido = col14.text_input("Primer Apellido", value=limpiar_texto(prefill.get("PRIMER APELLIDO", "")), key=f"pa_{fk}{dyn_k}", disabled=bloquear_campos)
    segundo_apellido = col15.text_input("Segundo Apellido", value=limpiar_texto(prefill.get("SEGUNDO APELLIDO", "")), key=f"sa_{fk}{dyn_k}", disabled=bloquear_campos)
    primer_nombre = col16.text_input("Primer Nombre", value=limpiar_texto(prefill.get("PRIMER NOMBRE", "")), key=f"pn_{fk}{dyn_k}", disabled=bloquear_campos)
    segundo_nombre = col17.text_input("Segundo Nombre", value=limpiar_texto(prefill.get("SEGUNDO NOMBRE", "")), key=f"sn_{fk}{dyn_k}", disabled=bloquear_campos)
    
    col18, col19, col20, col21 = st.columns(4)
    sexo = col18.selectbox("Sexo", SEXO_OPCIONES, index=safe_index(SEXO_OPCIONES, prefill.get("SEXO")), key=f"sx_{fk}{dyn_k}", disabled=bloquear_campos)
    
    try: edad_val = int(float(str(prefill.get("EDAD", 0))))
    except: edad_val = 0
    edad = col19.number_input("Edad", min_value=0, max_value=120, step=1, value=edad_val, key=f"ed_{fk}{dyn_k}", disabled=bloquear_campos)
    
    cond_edad = col20.selectbox("Condición de la Edad", CONDICION_EDAD, index=safe_index(CONDICION_EDAD, prefill.get("CONDICIÓN DE LA EDAD")), key=f"ce_{fk}{dyn_k}", disabled=bloquear_campos)
    nacionalidad = col21.selectbox("Nacionalidad", NACIONALIDAD, index=safe_index(NACIONALIDAD, prefill.get("NACIONALIDAD")), key=f"nc_{fk}{dyn_k}", disabled=bloquear_campos)

    col22, col23, col24 = st.columns(3)
    etnia = col22.selectbox("Etnia", ETNIAS, index=safe_index(ETNIAS, prefill.get("ETNIA")), key=f"et_{fk}{dyn_k}", disabled=bloquear_campos)
    grupo_prio = col23.selectbox("Grupo Prioritario", GRUPO_PRIORITARIO, index=safe_index(GRUPO_PRIORITARIO, prefill.get("GRUPO PRIORITARIO")), key=f"gp_{fk}{dyn_k}", disabled=False)
    tipo_seguro = col24.selectbox("Tipo de Seguro", TIPO_SEGURO, index=safe_index(TIPO_SEGURO, prefill.get("TIPO DE SEGURO")), key=f"ts_{fk}{dyn_k}", disabled=False)

    st.markdown("### 🏠 3. Datos de Residencia")
    col25, col26, col27 = st.columns(3)
    prov_res = col25.text_input("Provincia de Residencia", value=limpiar_texto(prefill.get("PROV_RES", "ORELLANA")), key=f"pr_{fk}{dyn_k}", disabled=bloquear_campos)
    cant_res = col26.text_input("Cantón de Residencia", value=limpiar_texto(prefill.get("CANT_RES", "")), key=f"cr_{fk}{dyn_k}", disabled=bloquear_campos)
    parr_res = col27.text_input("Parroquia de Residencia", value=limpiar_texto(prefill.get("PARR_RES", "")), key=f"par_{fk}{dyn_k}", disabled=bloquear_campos)

    st.markdown("### 🩺 4. Diagnóstico y Profesional")
    especialidad = st.selectbox("Especialidad del Profesional", ESPECIALIDADES_PROFESIONAL, index=safe_index(ESPECIALIDADES_PROFESIONAL, prefill.get("ESPECIALIDAD DEL PROFESIONAL")), key=f"esp_{fk}")
    
    col_bus_p, col_cond_p = st.columns([2, 1])
    buscador_cie10_p = col_bus_p.selectbox("🔍 Buscar Diagnóstico Principal", CIE10_PRIN_OPCIONES, index=safe_index(CIE10_PRIN_OPCIONES, prefill.get("CIE-10 (PRINCIPAL)")), key=f"bus_p_{fk}")
    cond_diag = col_cond_p.selectbox("Condición del Diagnóstico", CONDICION_DIAGNOSTICO, index=safe_index(CONDICION_DIAGNOSTICO, prefill.get("CONDICIÓN DEL DIAGNÓSTICO")), key=f"cd_{fk}")
    if buscador_cie10_p:
        cod_p = buscador_cie10_p.split(" - ")[0]
        desc_p = buscador_cie10_p.split(" - ", 1)[1] if " - " in buscador_cie10_p else ""
    else:
        cod_p = prefill.get("CIE-10 (PRINCIPAL)", "")
        desc_p = prefill.get("DIGANÓSTICO 1 (PRINCIPAL)", "")
    
    col_bus_e, col_cond_e = st.columns([2, 1])
    buscador_cie10_e = col_bus_e.selectbox("🔍 Buscar Causa Externa", CIE10_SEC_OPCIONES, index=safe_index(CIE10_SEC_OPCIONES, prefill.get("CIE-10 (CAUSA EXTERNA)")), key=f"bus_e_{fk}")
    condicion_alta = col_cond_e.selectbox("Condición del Alta", CONDICION_ALTA, index=safe_index(CONDICION_ALTA, prefill.get("CONDICIÓN DEL ALTA")), key=f"ca_{fk}")
    if buscador_cie10_e:
        cod_e = buscador_cie10_e.split(" - ")[0]
        desc_e = buscador_cie10_e.split(" - ", 1)[1] if " - " in buscador_cie10_e else ""
    else:
        cod_e = prefill.get("CIE-10 (CAUSA EXTERNA)", "")
        desc_e = prefill.get("DIAGNOSTICO (CAUSA EXTERNA)", "")

    valido_sexo = True
    if sexo == "HOMBRE":
        if grupo_prio == "EMBARAZADAS": col23.error("❌ Inválido para hombres."); valido_sexo = False
        palabras_mujer = ["OVARIO", "UTERO", "ÚTERO", "VAGINA", "VULVA", "CERVIX", "CÉRVIX", "TROMPA", "PLACENTA", "PARTO", "EMBARAZO", "PUERPERIO", "MENSTRUACION", "MENSTRUACIÓN"]
        if cod_p.startswith("O") or any(p in desc_p.upper() for p in palabras_mujer): col_cond_p.error("❌ Diagnóstico no válido para hombres."); valido_sexo = False
        if cod_e.startswith("O") or any(p in desc_e.upper() for p in palabras_mujer): col_cond_e.error("❌ Causa no válida para hombres."); valido_sexo = False
    elif sexo == "MUJER":
        palabras_hombre = ["PROSTATA", "PRÓSTATA", "TESTICULO", "TESTÍCULO", "PENE", "PREPUCIO", "ESCROTO", "ESPERMATOZOIDE", "SEMEN"]
        if any(p in desc_p.upper() for p in palabras_hombre): col_cond_p.error("❌ Diagnóstico no válido para mujeres."); valido_sexo = False
        if any(p in desc_e.upper() for p in palabras_hombre): col_cond_e.error("❌ Causa no válida para mujeres."); valido_sexo = False

    col34, col35, col36 = st.columns(3)
    req_hosp = col34.selectbox("Requiere Hospitalización", ["NO", "SI"], index=safe_index(["NO", "SI"], prefill.get("REQUIERE HOSPITALIZACIÓN")), key=f"rh_{fk}")
    hosp_referido = col35.selectbox("Hospital de Referencia (si aplica)", HOSPITALES_REFERENCIA, index=safe_index(HOSPITALES_REFERENCIA, prefill.get("NOMBRE DEL HOSPITAL AL QUE FUE REFERIDO PARA LA HOSPITALIZACIÓN", "")), disabled=(req_hosp == "NO"), key=f"hr_{fk}")
    causa_atencion = col36.selectbox("Causa de Atención", CAUSA_ATENCION, index=safe_index(CAUSA_ATENCION, prefill.get("CAUSA DE ATENCIÓN")), key=f"cau_{fk}")
    
    col37, col38 = st.columns(2)
    id_profesional = col37.text_input("Identificación del Profesional (ENTER para buscar)", value=prefill.get("NÚMERO DE IDENTIFICACIÓN DEL PROFESIONAL DE SALUD", ""), key=f"ip_{fk}")
    
    id_prof_valida = False
    nombre_prof_auto = prefill.get("NOMBRES Y APELLIDOS DEL PROFESIONAL DE SALUD", "")
    profesional_encontrado = False

    if id_profesional:
        if not validar_cedula_ecuatoriana(id_profesional):
            col37.error("❌ Cédula de profesional incorrecta.")
            if fk.startswith("nuevo") and f"np_{fk}" in st.session_state: st.session_state[f"np_{fk}"] = ""
        else:
            id_prof_valida = True
            df_profs = cargar_profesionales()
            
            id_prof_norm = normalizar_id(id_profesional)
            match_p = df_profs[df_profs["CEDULA"].apply(normalizar_id) == id_prof_norm]
            
            if not match_p.empty:
                nombre_prof_auto = match_p.iloc[-1]["NOMBRE_COMPLETO"]
                profesional_encontrado = True
                st.session_state[f"np_{fk}"] = nombre_prof_auto
            elif fk.startswith("nuevo"):
                if f"np_{fk}" in st.session_state: st.session_state[f"np_{fk}"] = ""
                col37.warning("⚠️ Profesional no registrado.")
                if col37.button("➕ Ingresar a la Nube", key=f"btn_add_p_{fk}"):
                    modal_nuevo_profesional(id_profesional.strip())
    else:
        if fk.startswith("nuevo") and f"np_{fk}" in st.session_state: st.session_state[f"np_{fk}"] = ""

    nombre_profesional = col38.text_input("Nombres y Apellidos del Profesional", value=limpiar_texto(nombre_prof_auto), key=f"np_{fk}", disabled=(profesional_encontrado and fk.startswith("nuevo")))

    val_fecha_nacimiento = fecha_nacimiento.strftime("%d/%m/%Y") if fecha_nacimiento else "N/A"
    val_fecha_atencion = fecha_atencion.strftime("%d/%m/%Y") if fecha_atencion else ""

    return {
        "FECHA DE ATENCIÓN": val_fecha_atencion, "HORA ATENCION": hora_atencion, "FECHA DE NACIMIENTO DEL PACIENTE": val_fecha_nacimiento,
        "TIPO DE DOCUMENTO DE IDENTIFICACIÓN": tipo_doc, "NÚMERO DE IDENTIFICACION": identificacion.strip(),
        "PRIMER APELLIDO": limpiar_texto(primer_apellido), 
        "SEGUNDO APELLIDO": limpiar_texto(segundo_apellido), 
        "PRIMER NOMBRE": limpiar_texto(primer_nombre), 
        "SEGUNDO NOMBRE": limpiar_texto(segundo_nombre),
        "SEXO": sexo, "EDAD": str(edad), "CONDICIÓN DE LA EDAD": cond_edad, "NACIONALIDAD": nacionalidad,
        "ETNIA": etnia, "GRUPO PRIORITARIO": grupo_prio, "TIPO DE SEGURO": tipo_seguro,
        "PROV_RES": limpiar_texto(prov_res), 
        "CANT_RES": limpiar_texto(cant_res), 
        "PARR_RES": limpiar_texto(parr_res), 
        "ESPECIALIDAD DEL PROFESIONAL": especialidad,
        "CIE-10 (PRINCIPAL)": cod_p, 
        "DIGANÓSTICO 1 (PRINCIPAL)": limpiar_texto(desc_p), 
        "CONDICIÓN DEL DIAGNÓSTICO": cond_diag,
        "CIE-10 (CAUSA EXTERNA)": cod_e, 
        "DIAGNOSTICO (CAUSA EXTERNA)": limpiar_texto(desc_e), 
        "CONDICIÓN DEL ALTA": condicion_alta,
        "REQUIERE HOSPITALIZACIÓN": req_hosp, 
        "NOMBRE DEL HOSPITAL AL QUE FUE REFERIDO PARA LA HOSPITALIZACIÓN": limpiar_texto(hosp_referido) if req_hosp == "SI" else "",
        "CAUSA DE ATENCIÓN": causa_atencion, "NÚMERO DE IDENTIFICACIÓN DEL PROFESIONAL DE SALUD": id_profesional, 
        "NOMBRES Y APELLIDOS DEL PROFESIONAL DE SALUD": limpiar_texto(nombre_profesional),
        "_valido": hora_valida and id_valida and id_prof_valida and identificacion and primer_apellido and primer_nombre and hora_atencion and (val_fecha_nacimiento != "N/A") and valido_sexo and bool(nombre_profesional.strip())
    }

# ==============================================================================
# APLICACIÓN PRINCIPAL
# ==============================================================================
def formulario_principal():
    with st.sidebar:
        st.write("### Panel de Control")
        st.write(f"👤 **Usuario:** {st.session_state.usuario_actual}")
        st.write(f"🛡️ **Rol:** {st.session_state.rol_actual}")
        if st.session_state.rol_actual == "USUARIO":
            st.write(f"📍 **Unidad:** {st.session_state.unicodigo_actual}")
        st.markdown("---")
        if st.button("🚪 Cerrar Sesión", use_container_width=True):
            st.session_state.autenticado = False
            st.session_state.usuario_actual = ""
            st.session_state.rol_actual = ""
            st.session_state.unicodigo_actual = ""
            st.session_state.prefill_auto = {} 
            st.session_state.last_checked_id = ""
            st.rerun()

    df_global = cargar_tabla(HOJA_ATENCIONES)

    if st.session_state.rol_actual == "ADMIN":
        tab1, tab2, tab3 = st.tabs(["🔍 Auditoría y Búsqueda Global", "⚙️ Gestión de Usuarios", "🧹 Mantenimiento de BD Nube"])
    else:
        tab1, tab2 = st.tabs(["📝 Ingresar Nuevo Registro", "🔍 Buscar y Editar Registro"])

    # ========================== ROL USUARIO ==========================
    if st.session_state.rol_actual == "USUARIO":
        with tab1:
            if 'form_key' not in st.session_state: st.session_state.form_key = 0
            fk = st.session_state.form_key

            if st.session_state.get('registro_exitoso', False):
                st.success("✅ ¡Atención médica guardada con éxito en la Nube Permanente!")
                st.toast("Guardado exitoso", icon="💾")
                st.session_state.registro_exitoso = False

            st.markdown("### 🏥 1. Datos del Establecimiento")
            with st.container(border=True):
                val_institucion, val_nombre, val_nivel, val_zona, val_provincia, val_canton, val_distrito = "MSP", "", "", "", "", "", ""
                unicodigo_seleccionado = st.session_state.unicodigo_actual
                st.info(f"📍 Sesión bloqueada para el establecimiento: **{unicodigo_seleccionado}**")

                if base_est is not None and not base_est.empty and unicodigo_seleccionado:
                    def limpiar_cod(cod):
                        return str(cod).strip().replace('.0', '').lstrip('0')
                    
                    busqueda = base_est[base_est['UNICODIGO'].apply(limpiar_cod) == limpiar_cod(unicodigo_seleccionado)]
                    
                    if not busqueda.empty:
                        fila_est = busqueda.iloc[0]
                        def get_val(f, words, df=""):
                            for c in f.index:
                                for w in words:
                                    if w in str(c).upper(): return str(f[c])
                            return df
                        val_institucion = get_val(fila_est, ['INSTITUCION', 'SISTEMA'], 'MSP')
                        val_nombre = get_val(fila_est, ['NOMBRE', 'ESTABLECIMIENTO'], '')
                        val_nivel = get_val(fila_est, ['NIVEL'], '')
                        val_zona = get_val(fila_est, ['ZONA'], '')
                        val_provincia = get_val(fila_est, ['PROVINCIA'], '')
                        val_canton = get_val(fila_est, ['CANTON'], '')
                        val_distrito = get_val(fila_est, ['DISTRITO'], '')
                    else:
                        st.warning(f"⚠️ El unicódigo '{unicodigo_seleccionado}' no se encontró en el catálogo de establecimientos.")

                col1, col2, col3, col4 = st.columns(4)
                col1.text_input("Institución", value=val_institucion, disabled=True, key=f"ins_u_{fk}")
                col2.text_input("Unicódigo", value=unicodigo_seleccionado, disabled=True, key=f"uni_u_{fk}")
                col3.text_input("Nombre del Establecimiento", value=val_nombre, disabled=True, key=f"nom_u_{fk}")
                col4.text_input("Nivel", value=val_nivel, disabled=True, key=f"niv_u_{fk}")

            datos_nuevo = renderizar_campos_paciente(f"nuevo_{fk}", df_global=df_global)

            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("💾 Guardar Atención Médica", key=f"btn_nuevo_g_{fk}", use_container_width=True):
                if not datos_nuevo["_valido"]:
                    st.error("❌ Hay conflictos o faltan datos obligatorios. Revise las alertas en el formulario.")
                else:
                    del datos_nuevo["_valido"]
                    datos_nuevo.update({
                        "INSTITUCIÓN DEL SISTEMA": val_institucion, "UNICODIGO": unicodigo_seleccionado, "NOMBRE DEL ESTABLECIMIENTO DE SALUD": val_nombre,
                        "ZONA": val_zona, "PROVINCIA": val_provincia, "CANTON": val_canton, "DISTRITO": val_distrito, "NIVEL": val_nivel
                    })
                    
                    df_nuevo = pd.DataFrame([{k: str(v) for k, v in datos_nuevo.items()}], columns=COLUMNAS_OFICIALES)
                    df_final = pd.concat([df_global, df_nuevo], ignore_index=True) if not df_global.empty else df_nuevo
                    
                    guardar_tabla(HOJA_ATENCIONES, df_final)
                    
                    st.session_state["prefill_auto"] = {}
                    st.session_state["last_checked_id"] = ""
                    st.session_state.registro_exitoso = True
                    st.session_state.form_key += 1
                    
                    for key in list(st.session_state.keys()):
                        if key.startswith("np_") or key.startswith("ip_"):
                            del st.session_state[key]
                            
                    st.rerun()

        with tab2:
            st.subheader("🔍 Buscar y Corregir Registro Local")
            busqueda_cedula = st.text_input("Ingrese la Identificación del paciente:", key="search_edit_local")
            if busqueda_cedula and not df_global.empty:
                busqueda_norm = normalizar_id(busqueda_cedula)
                df_paciente = df_global[(df_global['NÚMERO DE IDENTIFICACION'].apply(normalizar_id) == busqueda_norm) & (df_global['UNICODIGO'] == st.session_state.unicodigo_actual)]
                
                if df_paciente.empty:
                    st.warning("⚠️ No se encontraron atenciones de su unidad operativa para este paciente.")
                else:
                    opciones = df_paciente.apply(lambda r: f"{r['FECHA DE ATENCIÓN']} - {r['HORA ATENCION']} ({r['ESPECIALIDAD DEL PROFESIONAL']})", axis=1)
                    seleccion_cita = st.selectbox("Seleccione la atención que desea corregir:", opciones.tolist())
                    idx_original = df_paciente.index[opciones.tolist().index(seleccion_cita)]
                    fila_editar = df_global.iloc[idx_original].to_dict()

                    with st.container(border=True):
                        datos_editados = renderizar_campos_paciente(f"edit_{idx_original}", prefill=fila_editar, df_global=df_global)
                        if st.button("🔄 Actualizar Atención", use_container_width=True):
                            if not datos_editados["_valido"]:
                                st.error("❌ Verifique los errores en rojo antes de actualizar.")
                            else:
                                del datos_editados["_valido"]
                                for k, v in datos_editados.items(): df_global.loc[idx_original, k] = str(v)
                                guardar_tabla(HOJA_ATENCIONES, df_global)
                                st.success("✅ ¡Atención editada con éxito en la Nube!")
                                st.toast("Edición guardada en la nube", icon="🔄")
                                st.session_state["search_edit_local"] = ""
                                st.rerun()

    # ========================== ROL ADMIN ==========================
    if st.session_state.rol_actual == "ADMIN":
        with tab1:
            st.markdown("### 🔍 Buscador Universal de Emergencias (Conectado a la Nube)")
            cedula_auditoria = st.text_input("Digite la Cédula o Documento del Paciente:")
            
            if cedula_auditoria and not df_global.empty:
                ced_audit_norm = normalizar_id(cedula_auditoria)
                df_audit = df_global[df_global['NÚMERO DE IDENTIFICACION'].apply(normalizar_id) == ced_audit_norm]
                if df_audit.empty:
                    st.error("❌ No se registra ninguna atención médica en la provincia para la identificación ingresada.")
                else:
                    st.success(f"✅ Se encontraron {len(df_audit)} registros históricos.")
                    for index, fila in df_audit.iterrows():
                        with st.expander(f"🏥 Establecimiento: {fila.get('NOMBRE DEL ESTABLECIMIENTO DE SALUD','')} | 📅 Fecha: {fila.get('FECHA DE ATENCIÓN','')}", expanded=False):
                            c_au1, c_audit2, c_audit3 = st.columns(3)
                            c_au1.markdown(f"**Paciente:** {fila.get('PRIMER NOMBRE','')} {fila.get('PRIMER APELLIDO','')}")
                            c_audit2.markdown(f"**Edad/Sexo:** {fila.get('EDAD','')} {fila.get('CONDICIÓN DE LA EDAD','')} | {fila.get('SEXO','')}")
                            c_audit3.markdown(f"**Seguro:** {fila.get('TIPO DE SEGURO','')}")
                            c_audit4, c_audit5 = st.columns([2, 1])
                            c_audit4.markdown(f"**Diagnóstico Principal:** {fila.get('CIE-10 (PRINCIPAL)','')} - {fila.get('DIGANÓSTICO 1 (PRINCIPAL)','')}")
                            c_audit5.markdown(f"**Condición:** {fila.get('CONDICIÓN DEL DIAGNÓSTICO','')}")

        with tab2:
            st.subheader("👥 Administrar Usuarios y Accesos en la Nube")
            df_usuarios = cargar_usuarios()
            st.dataframe(df_usuarios, use_container_width=True)
            st.markdown("---")
            st.markdown("#### ➕ Crear Nuevo Usuario")
            c_nu1, c_nu2 = st.columns(2)
            n_usr = c_nu1.text_input("Nombre de Usuario Nuevo")
            n_pwd = c_nu2.text_input("Contraseña Nueva")
            c_nu3, c_nu4 = st.columns(2)
            n_rol = c_nu3.selectbox("Rol del Usuario", ["USUARIO", "ADMIN"])
            if n_rol == "ADMIN": 
                n_uni = c_nu4.selectbox("Unicódigo Permitido", ["TODOS"], disabled=True)
            else:
                lista_unis = [str(x) for x in base_est['UNICODIGO'].tolist() if str(x).strip() != "" and str(x).lower() != "nan"] if base_est is not None else []
                n_uni = c_nu4.selectbox("Unicódigo Asignado", lista_unis)
                
            if st.button("Crear Usuario", use_container_width=True):
                if not n_usr or not n_pwd: st.error("Usuario y Contraseña son obligatorios.")
                elif n_usr in df_usuarios['USUARIO'].values: st.error("⚠️ El usuario ya existe.")
                else:
                    nuevo_u = pd.DataFrame([{"USUARIO": n_usr.strip(), "CONTRASENA": n_pwd.strip(), "ROL": n_rol, "UNICODIGO": "TODOS" if n_rol=="ADMIN" else n_uni}])
                    df_final_u = pd.concat([df_usuarios, nuevo_u], ignore_index=True)
                    guardar_tabla(HOJA_USUARIOS, df_final_u)
                    st.success(f"Usuario '{n_usr}' creado en la Nube.")
                    st.rerun()

            st.markdown("---")
            st.markdown("#### 🗑️ Eliminar Usuario")
            usuarios_borrables = df_usuarios[df_usuarios['USUARIO'] != 'admin']['USUARIO'].tolist()
            if usuarios_borrables:
                usr_a_eliminar = st.selectbox("Seleccione el usuario que desea eliminar", usuarios_borrables)
                if st.button("Eliminar Acceso", use_container_width=True):
                    df_usuarios = df_usuarios[df_usuarios['USUARIO'] != usr_a_eliminar]
                    guardar_tabla(HOJA_USUARIOS, df_usuarios)
                    st.success(f"Acceso para el usuario '{usr_a_eliminar}' eliminado de la Nube.")
                    st.rerun()
            else:
                st.info("No hay usuarios adicionales para eliminar.")

        with tab3:
            st.subheader("🧹 Mantenimiento del Sistema (Bases de Nube)")
            st.warning("⚠️ **¡ZONA DE PELIGRO!** Las acciones aquí borrarán los datos permanentemente del Google Sheet.")

            with st.expander("Limpiar Base de Datos de Atenciones (Cierre de Mes)", expanded=False):
                st.write("Esta acción eliminará todas las atenciones médicas del Google Sheet para iniciar un nuevo mes en blanco.")
                confirmar_atenciones = st.checkbox("Confirmo que deseo eliminar todas las atenciones médicas.", key="chk_atenciones")
                if st.button("🗑️ Encerar Base de Atenciones en la Nube", disabled=not confirmar_atenciones, use_container_width=True):
                    guardar_tabla(HOJA_ATENCIONES, pd.DataFrame(columns=COLUMNAS_OFICIALES))
                    st.success("✅ Base de atenciones encerada en la Nube.")
                    st.toast("Matriz de Nube limpia", icon="🧹")
                    st.rerun()

            with st.expander("Limpiar Base de Pacientes y Profesionales", expanded=False):
                st.write("Esta acción vaciará los catálogos en línea de pacientes y profesionales.")
                confirmar_pac_prof = st.checkbox("Confirmo que deseo eliminar los registros de pacientes y profesionales en la Nube.", key="chk_pac_prof")
                if st.button("🗑️ Encerar Catálogos Nube", disabled=not confirmar_pac_prof, use_container_width=True):
                    payload_keys = ["NÚMERO DE IDENTIFICACION", "PRIMER APELLIDO", "SEGUNDO APELLIDO", "PRIMER NOMBRE", "SEGUNDO NOMBRE", "SEXO", "EDAD", "CONDICIÓN DE LA EDAD", "NACIONALIDAD", "ETNIA", "GRUPO PRIORITARIO", "TIPO DE SEGURO", "PROV_RES", "CANT_RES", "PARR_RES", "FECHA DE NACIMIENTO DEL PACIENTE"]
                    guardar_tabla(HOJA_PACIENTES, pd.DataFrame(columns=payload_keys))
                    guardar_tabla(HOJA_PROFESIONALES, pd.DataFrame(columns=["CEDULA", "PRIMER NOMBRE", "SEGUNDO NOMBRE", "PRIMER APELLIDO", "SEGUNDO APELLIDO", "NOMBRE_COMPLETO"]))
                    cargar_profesionales.clear()
                    st.success("✅ Catálogos encerados en la Nube correctamente.")
                    st.toast("Bases limpias", icon="🧹")
                    st.rerun()

    # ==========================================
    # DESCARGAR MATRIZ GLOBAL
    # ==========================================
    st.markdown("---")
    st.subheader("📥 Centro de Descarga de Datos (Sincronizado con Google Sheets)")
    if not df_global.empty:
        if st.session_state.rol_actual == "ADMIN":
            c_des1, c_des2 = st.columns(2)
            with c_des1:
                st.markdown("##### 📁 Matriz Consolidada Total")
                buf1 = io.BytesIO()
                with pd.ExcelWriter(buf1, engine='openpyxl') as w: df_global.to_excel(w, index=False, sheet_name='Consolidado_Provincial')
                st.download_button(label="Descargar Consolidado Distrital (.xlsx)", data=buf1.getvalue(), file_name="Matriz_Consolidada_Orellana.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
            
            with c_des2:
                st.markdown("##### 🏢 Matriz por Establecimiento")
                lista_unidades = df_global['NOMBRE DEL ESTABLECIMIENTO DE SALUD'].dropna().unique().tolist()
                unidad_sel = st.selectbox("Seleccione la Unidad Operativa:", lista_unidades)
                df_filtrado_adm = df_global[df_global['NOMBRE DEL ESTABLECIMIENTO DE SALUD'] == unidad_sel]
                
                buf2 = io.BytesIO()
                with pd.ExcelWriter(buf2, engine='openpyxl') as w: df_filtrado_adm.to_excel(w, index=False, sheet_name='Produccion_Unidad')
                st.download_button(label=f"Descargar Excel de la Unidad", data=buf2.getvalue(), file_name=f"Matriz_{str(unidad_sel).replace(' ','_')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        else:
            df_usuario_final = df_global[df_global['UNICODIGO'] == st.session_state.unicodigo_actual]
            if not df_usuario_final.empty:
                st.dataframe(df_usuario_final.tail(3), use_container_width=True)
                buf3 = io.BytesIO()
                with pd.ExcelWriter(buf3, engine='openpyxl') as w: df_usuario_final.to_excel(w, index=False, sheet_name='Mi_Produccion')
                st.download_button(label="Descargar Mi Matriz de Producción (.xlsx)", data=buf3.getvalue(), file_name=f"Matriz_Produccion_{st.session_state.unicodigo_actual}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
            else:
                st.info("Su unidad aún no registra atenciones médicas este mes.")
    else:
        st.info("No existen registros grabados en el sistema actualmente.")

if __name__ == "__main__":
    if not st.session_state.autenticado:
        login()
    else:
        formulario_principal()
