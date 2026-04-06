import streamlit as st
import ee
import geemap.foliumap as geemap
import osmnx as ox
import requests
from fpdf import FPDF
import datetime
import os
import urllib.request
import time
from google.oauth2 import service_account

# ==========================================
# 1. SYSTEM INITIALIZATION & C2 STYLING
# ==========================================
st.set_page_config(page_title="PMRDA GEWS | Active Node", layout="wide", initial_sidebar_state="expanded")

# Injecting 'Share Tech Mono' font and Tactical C2 styling
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
    
    html, body, [class*="css"]  {
        font-family: 'Share Tech Mono', monospace !important;
    }
    
    .main { background-color: #050505; }
    
    /* Tactical Metric Cards */
    [data-testid="stMetric"] {
        background-color: #0a0a0a;
        border: 1px solid #1f77b4;
        border-left: 4px solid #00ffcc;
        padding: 15px;
        box-shadow: 0 0 15px rgba(0, 255, 204, 0.1);
        margin-bottom: 20px; /* Added to handle 2x2 vertical spacing cleanly */
    }
    
    [data-testid="stMetricLabel"] {
        color: #888888 !important;
        font-size: 0.9rem !important;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    
    [data-testid="stMetricValue"] {
        color: #00ffcc !important;
        font-size: 1.8rem !important;
    }

    /* Terminal Console Output */
    .terminal-console {
        background-color: #000000;
        border: 1px solid #333333;
        padding: 15px;
        color: #00ff00;
        font-family: 'Share Tech Mono', monospace;
        height: 150px;
        overflow-y: hidden;
        margin-bottom: 20px;
    }
    
    h1 { color: #ffffff; text-transform: uppercase; letter-spacing: 2px; }
    h2, h3 { color: #1f77b4; text-transform: uppercase; }
    hr { border-color: #333333; }
    </style>
""", unsafe_allow_html=True)

st.title("PMRDA Geospatial Intelligence Portal")
st.markdown("<span style='color:#888;'>NODE IDENT: ALPHA-ACTUAL | SUBSYSTEM: AUTOMATED SAR/OPTICAL FUSION ENGINE</span>", unsafe_allow_html=True)
st.markdown("---")

# Tactical Dashboard Metrics (Converted to 2x2 Grid)
row1_col1, row1_col2 = st.columns(2)
row1_col1.metric("Uplink Status", "SECURE / TLS 1.3")
row1_col2.metric("Primary Sensor", "SAR C-Band (VV)")

row2_col1, row2_col2 = st.columns(2)
row2_col1.metric("Optical Verification", "MSI (10m Res)")
row2_col2.metric("Phenological Filter", "ACTIVE (NDVI Δ)")
st.markdown("---")

# Authenticate Earth Engine
try:
    if "gcp_service_account" in st.secrets:
        # CLOUD DEPLOYMENT ROUTE: Secure memory injection
        key_dict = dict(st.secrets["gcp_service_account"])
        creds = service_account.Credentials.from_service_account_info(
            key_dict,
            scopes=['https://www.googleapis.com/auth/earthengine']
        )
        ee.Initialize(credentials=creds, project='localqol')
        ee.data._credentials = creds  # MONKEY-PATCH: Forces geemap to recognize the cloud credentials
    else:
        # LOCAL MAC ROUTE: Fallback to terminal authentication
        ee.Initialize(project='localqol')
except Exception as e:
    st.error(f"SYSTEM HALTED: Earth Engine authentication protocol failed. {e}")
    st.stop()

# ==========================================
# 2. SECTOR COORDINATE DICTIONARY
# ==========================================
pmrda_villages = {
    "Hinjewadi (Phase 1 & 2) [GRID: HNJ-1]": [18.5913, 73.7389],
    "Maan (Phase 3) [GRID: MAN-3]": [18.5770, 73.6850],
    "Marunji [GRID: MRN-0]": [18.6010, 73.7220],
    "Mahalunge [GRID: MHL-0]": [18.5675, 73.7460],
    "Sus Sector [GRID: SUS-0]": [18.5435, 73.7435],
    "Wakad Node [GRID: WKD-0]": [18.5987, 73.7688],
    "Manual Override (Custom Coordinates)": [None, None]
}

# ==========================================
# 3. CONTROL PANEL (SIDEBAR)
# ==========================================
with st.sidebar:
    st.header("PIPELINE PARAMETERS")
    
    st.subheader("1. Target Acquisition")
    selected_location = st.selectbox("Select Jurisdictional Sector:", options=list(pmrda_villages.keys()))
    
    if selected_location == "Manual Override (Custom Coordinates)":
        lat = st.number_input("Latitude (EPSG:4326)", value=18.585000, format="%.6f")
        lon = st.number_input("Longitude (EPSG:4326)", value=73.715000, format="%.6f")
    else:
        lat = pmrda_villages[selected_location][0]
        lon = pmrda_villages[selected_location][1]
        st.info(f"TARGET LOCKED: {lat}, {lon}")
        
    st.subheader("2. Temporal Baselines")
    before_dates = st.date_input("T0 Epoch (Pre-Analysis Baseline)", 
                                 [datetime.date(2024, 1, 1), datetime.date(2024, 3, 31)])
    after_dates = st.date_input("T1 Epoch (Current State)", 
                                [datetime.date(2026, 1, 1), datetime.date(2026, 4, 5)])
    
    st.subheader("3. Backscatter Calibration")
    radar_thresh = st.slider("Vertical Structure SAR Threshold (dB)", 
                             min_value=2.0, max_value=8.0, value=5.5, step=0.1)
    
    with st.expander("ADVANCED CALIBRATION"):
        fetch_limit = st.slider("Vector Output Limit (Max Entities)", 5, 50, 10, step=1)
        ndbi_thresh = st.number_input("Minimum NDBI Variance Matrix", value=0.15, step=0.01)
        buffer_radius = st.number_input("Analysis Radius (Meters)", value=3000, step=500)
    
    st.subheader("4. External APIs")
    try:
        gmaps_api_key = st.secrets["GMAPS_API_KEY"]
        st.success("Google Static Optical API: CONNECTED")
    except KeyError:
        gmaps_api_key = st.text_input("Optical API Key (Optional)", type="password")

    st.markdown("<br>", unsafe_allow_html=True)
    run_btn = st.button("EXECUTE ANALYSIS PIPELINE", type="primary", use_container_width=True)

# ==========================================
# 4. MAIN PIPELINE EXECUTION
# ==========================================
if run_btn:
    if len(before_dates) != 2 or len(after_dates) != 2:
        st.error("SEQUENCE ABORTED: Temporal Baselines require exact Start/End dates.")
        st.stop()
        
    # Simulated Live Telemetry Output
    telemetry_placeholder = st.empty()
    telemetry_logs = [
        f"> Initiating connection to Earth Engine datacenters...",
        f"> Target coordinates locked: Lat {lat}, Lon {lon}",
        f"> Requesting Copernicus Sentinel-1 GRD SAR data [T0 & T1]...",
        f"> Requesting Copernicus Sentinel-2 MSI Optical data [T0 & T1]...",
        f"> Executing Cloud Masking (<10% tolerance)...",
        f"> Calculating Normalized Difference Built-up Index (NDBI)...",
        f"> Calculating Normalized Difference Vegetation Index (NDVI)...",
        f"> Applying Dynamic Phenological Filter for agricultural masking...",
        f"> Extracting multi-temporal SAR backscatter variance...",
        f"> Compiling anomaly vectors..."
    ]
    
    console_text = ""
    for log in telemetry_logs:
        console_text += log + "<br>"
        telemetry_placeholder.markdown(f"<div class='terminal-console'>{console_text}</div>", unsafe_allow_html=True)
        time.sleep(0.3) # Artificial delay for cinematic C2 effect
        
    with st.spinner('FINALIZING RASTER COMPUTATIONS...'):
        b_start, b_end = before_dates[0].strftime('%Y-%m-%d'), before_dates[1].strftime('%Y-%m-%d')
        a_start, a_end = after_dates[0].strftime('%Y-%m-%d'), after_dates[1].strftime('%Y-%m-%d')
        
        roi = ee.Geometry.Point([lon, lat]).buffer(buffer_radius)
        
        # 4a. Sensor Data Retrieval
        s1_before = ee.ImageCollection('COPERNICUS/S1_GRD').filterBounds(roi).filterDate(b_start, b_end).filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV')).median()
        s1_after = ee.ImageCollection('COPERNICUS/S1_GRD').filterBounds(roi).filterDate(a_start, a_end).filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV')).median()
        
        core_s2_bands = ['B2', 'B3', 'B4', 'B8', 'B11', 'B12']
        s2_before = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterBounds(roi).filterDate(b_start, b_end).filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 10)).select(core_s2_bands).median()
        s2_after = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterBounds(roi).filterDate(a_start, a_end).filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 10)).select(core_s2_bands).median()
        
        # 4b. Multi-Spectral Processing
        ndbi_before = s2_before.normalizedDifference(['B11', 'B8'])
        ndbi_after = s2_after.normalizedDifference(['B11', 'B8'])
        ndbi_change = ndbi_after.subtract(ndbi_before)
        
        ndvi_before = s2_before.normalizedDifference(['B8', 'B4']) 
        ndvi_after = s2_after.normalizedDifference(['B8', 'B4'])
        
        radar_change = s1_after.select('VV').subtract(s1_before.select('VV'))
        is_road = ndbi_change.gt(ndbi_thresh).And(radar_change.lt(3))
        
        # 4c. Phenomenological Adjustment (Dynamic Farm Filter)
        was_crop = ndvi_before.gt(0.3)
        smart_radar_thresh = ee.Image(radar_thresh).where(was_crop, radar_thresh + 2.5)
        
        # 4d. Anomaly Classification Engine
        is_clearing = radar_change.gte(3).And(radar_change.lt(smart_radar_thresh)).And(ndbi_change.gt(0.1)).And(ndvi_after.lt(0.3)).And(is_road.Not())
        is_vertical = radar_change.gte(smart_radar_thresh).And(ndbi_change.gt(ndbi_thresh)).And(ndvi_after.lt(0.3)).And(is_road.Not())
        
        alert_img = ee.Image(0).where(is_clearing, 1).where(is_vertical, 2).selfMask()
        
        # 4e. OpenStreetMap Masking
        try:
            osm_gdf = ox.features_from_point((lat, lon), {"building": True}, dist=buffer_radius)
            osm_ee = geemap.gdf_to_ee(osm_gdf[['geometry']])
            buffered_osm = osm_ee.map(lambda f: f.buffer(2))
            osm_raster_mask = ee.Image.constant(0).paint(buffered_osm, 1)
            final_alerts = alert_img.updateMask(osm_raster_mask.eq(0))
        except Exception as e:
            st.warning("OSM Database unreachable. Proceeding with unmasked analysis.")
            final_alerts = alert_img
            osm_ee = None

        console_text += "> COMPUTATIONS COMPLETE. RENDERING DATA LAYERS...<br>"
        telemetry_placeholder.markdown(f"<div class='terminal-console'>{console_text}</div>", unsafe_allow_html=True)

        # ==========================================
        # 5. DATA VISUALIZATION & OUTPUT
        # ==========================================
        tab1, tab2 = st.tabs(["GEOSPATIAL RENDER", "VECTOR EXTRACTION LOG"])
        
        with tab1:
            # ee_initialize=False OVERRIDE: Prevents the map from triggering the legacy auth check
            Map = geemap.Map(center=[lat, lon], zoom=14, ee_initialize=False)
            Map.addLayer(final_alerts.eq(1).selfMask(), {'palette': 'orange'}, 'Pre-Construction (Land Clearing)')
            Map.addLayer(final_alerts.eq(2).selfMask(), {'palette': 'red'}, 'Confirmed Vertical Structure')
            if osm_ee:
                Map.addLayer(osm_ee, {'color': 'blue'}, 'Authorized OSM Structures')
            Map.to_streamlit(height=650)

        # ==========================================
        # 6. DOSSIER GENERATION
        # ==========================================
        with tab2:
            st.markdown("### COMPILING INTELLIGENCE DOSSIER")
            clearing_vectors = final_alerts.eq(1).selfMask().reduceToVectors(
                geometry=roi, crs='EPSG:4326', scale=10, geometryType='centroid', maxPixels=1e8
            ).limit(fetch_limit).map(lambda f: f.set('alert_type', 1))
            
            vertical_vectors = final_alerts.eq(2).selfMask().reduceToVectors(
                geometry=roi, crs='EPSG:4326', scale=10, geometryType='centroid', maxPixels=1e8
            ).limit(fetch_limit).map(lambda f: f.set('alert_type', 2))
            
            combined_vectors = clearing_vectors.merge(vertical_vectors)
            points_data = combined_vectors.getInfo()

            if 'features' in points_data and len(points_data['features']) > 0:
                total_alerts = len(points_data['features'])
                st.success(f"PIPELINE COMPLETE: {total_alerts} ANOMALIES SECURED.")
                
                with st.expander("VIEW RAW GEOJSON TELEMETRY"):
                    st.json(points_data)
                
                # PDF Setup
                class PMRDAReport(FPDF):
                    def header(self):
                        self.set_font('Courier', 'B', 14) 
                        self.cell(0, 10, 'GEOSPATIAL INTELLIGENCE REPORT - PMRDA [RESTRICTED]', 0, 1, 'C')
                        self.set_font('Courier', '', 10)
                        self.cell(0, 5, f'Generated: {datetime.date.today()} | Sector: {selected_location}', 0, 1, 'C')
                        self.line(10, 25, 200, 25)
                        self.ln(10)

                pdf = PMRDAReport()

                def get_s2_thumb(img, lat, lon, filename):
                    box = ee.Geometry.Point([lon, lat]).buffer(150)
                    url = img.visualize(bands=['B4', 'B3', 'B2'], min=0, max=3000).getThumbURL({
                        'region': box, 'dimensions': '300x300', 'format': 'png'
                    })
                    urllib.request.urlretrieve(url, filename)

                for idx, feature in enumerate(points_data['features']):
                    lon_feat, lat_feat = feature['geometry']['coordinates']
                    alert_type = feature['properties']['alert_type']
                    
                    tag = "CLASS 1: LAND CLEARING ANOMALY" if alert_type == 1 else "CLASS 2: VERTICAL STRUCTURE ANOMALY"
                    color = (200, 100, 0) if alert_type == 1 else (150, 0, 0)
                        
                    pdf.add_page()
                    pdf.set_font('Courier', 'B', 12)
                    pdf.set_text_color(*color)
                    pdf.cell(0, 10, f"TARGET ID #{idx + 1} of {total_alerts} - {tag}", 0, 1)
                    
                    pdf.set_text_color(0, 0, 0)
                    pdf.set_font('Courier', '', 10)
                    pdf.cell(0, 8, f"COORDINATES: {lat_feat:.6f}, {lon_feat:.6f}", 0, 1)
                    
                    before_file, after_file = f"before_{idx}.png", f"after_{idx}.png"
                    get_s2_thumb(s2_before, lat_feat, lon_feat, before_file)
                    get_s2_thumb(s2_after, lat_feat, lon_feat, after_file)
                    
                    pdf.ln(5)
                    pdf.set_font('Courier', 'B', 10)
                    pdf.cell(90, 10, "EPOCH T0 (Sentinel-2 MSI)", 0, 0)
                    pdf.cell(90, 10, "EPOCH T1 (Sentinel-2 MSI)", 0, 1)
                    pdf.image(before_file, x=10, w=80)
                    pdf.image(after_file, x=105, y=pdf.get_y() - 80, w=80)
                    os.remove(before_file)
                    os.remove(after_file)
                    
                    if gmaps_api_key:
                        pdf.ln(5)
                        pdf.cell(0, 10, "OPTICAL VERIFICATION SENSOR (High-Res API):", 0, 1)
                        img_url = f"https://maps.googleapis.com/maps/api/staticmap?center={lat_feat},{lon_feat}&zoom=19&size=500x500&maptype=satellite&markers=color:red|{lat_feat},{lon_feat}&key={gmaps_api_key}"
                        img_path = f"proof_{idx}.png"
                        
                        resp = requests.get(img_url)
                        if resp.status_code == 200:
                            with open(img_path, 'wb') as f:
                                f.write(resp.content)
                            pdf.image(img_path, x=55, w=100)
                            os.remove(img_path)
                        else:
                            pdf.cell(0, 10, f"[VERIFICATION ERROR: Target acquisition failed]", 0, 1)

                pdf_output_path = "temp_report.pdf"
                pdf.output(pdf_output_path)
                
                with open(pdf_output_path, "rb") as f:
                    pdf_bytes = f.read()
                
                st.download_button(
                    label="DOWNLINK SECURE INTELLIGENCE DOSSIER (PDF)",
                    data=pdf_bytes,
                    file_name=f"PMRDA_Portal_Report_{selected_location.split('[')[0].strip().replace(' ', '_')}.pdf",
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True
                )
                
                os.remove(pdf_output_path)
                
            else:
                st.info("SCAN COMPLETE: No targets meeting defined parameters detected in this sector.")
