# Azure Functions and external libraries
import azure.functions as func
import os 
import logging
import requests
from datetime import datetime, timedelta
import jwt
import json
import traceback

# Register the function app
app = func.FunctionApp()

# Function to authenticate with Microsoft Graph API and get an access token
def get_graph_token():
    url = f"https://login.microsoftonline.com/{os.environ['TENANT_ID']}/oauth2/v2.0/token"
    data = {
        "client_id": os.environ["CLIENT_ID"],
        "client_secret": os.environ["CLIENT_SECRET"],
        "grant_type": "client_credentials",
        "scope": "https://graph.microsoft.com/.default"
    }
    response = requests.post(url, headers={"Content-Type": "application/x-www-form-urlencoded"}, data=data)
    logging.info(f"Token response: {response.status_code} - {response.text}")
    return response.json()["access_token"]

# HTTP-triggered Azure Function to update an Excel file on SharePoint using Graph API
@app.route(route="updateexcel", methods=["POST"])
def update_excel(req: func.HttpRequest) -> func.HttpResponse:
    try:
        # Parse JSON payload and extract required fields
        data = req.get_json()
        ym, val, pid, utype = data.get("year_month"), data.get("value"), data.get("plant_id"), data.get("utility_type")
        if not all([ym, val, pid, utype]):
            return func.HttpResponse("Missing parameters", 400)

        # Get OAuth token for Graph API
        token = get_graph_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # Get SharePoint Site ID
        logging.info("Getting SharePoint site ID")
        site_resp = requests.get("https://graph.microsoft.com/v1.0/sites/nexteerautomotive.sharepoint.com:/sites/GlobalEnvironmentalData", headers=headers)
        site_id = site_resp.json()["id"]
        logging.info(site_resp.text)

        # Get Drive ID of the SharePoint site
        logging.info("Getting Drive ID of the Sharepoint Site")
        drive_resp = requests.get(f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive", headers=headers)
        drive_id = drive_resp.json()["id"]
        logging.info(drive_resp.text)

        # Locate the folder named "Plant Data Test"
        logging.info("Locating the correct folder in Sharepoint Drive")
        folder_items = requests.get(f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/General:/children", headers=headers).json()
        folder_id = next((f["id"] for f in folder_items["value"] if f["name"] == "Plant Data Test"), None) #-------Change the name from Plant Data Test to respective folder name
        logging.info(json.dumps(folder_items, indent=2))
        if not folder_id:
            return func.HttpResponse("Folder not found", 404)

        # Find the Excel file corresponding to the plant
        logging.info("Locating the correct excel sheet in the Sharepoint folder")
        file_items = requests.get(f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{folder_id}/children", headers=headers).json()
        logging.info(json.dumps(file_items, indent=2))
        file = next((f for f in file_items["value"] if f["name"] == f"{pid} Utility and Environmental Test Data.xlsx"), None) #-------Change the name to respective excel file name
        if not file:
            return func.HttpResponse("Excel file not found", 404)

        # Get used range of the 'Utilities' worksheet
        logging.info("Getting the full range of data in Utilities")
        range_data = requests.get(
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{file['id']}/workbook/worksheets/Utilities/usedRange",
            headers=headers
        ).json()["values"]
        logging.info(json.dumps(range_data, indent=2))

        # Convert Excel date serial or string to datetime
        excel_epoch = datetime(1899, 12, 30)
        input_date = datetime.strptime(ym, "%Y-%m")

        # Find the matching row index for the given year-month
        for i, row in enumerate(range_data):
            try:
                cell = row[0]
                cell_date = excel_epoch + timedelta(days=cell) if isinstance(cell, int) else datetime.strptime(cell, "%m/%d/%Y")
                if cell_date.year == input_date.year and cell_date.month == input_date.month:
                    target_row = i + 1  # Excel is 1-indexed
                    break
            except:
                continue
        else:
            return func.HttpResponse("Date not found", 404)
        

        #------------EDIT THIS TO MODIFY WHICH EXCEL FILE AND COLUMN YOU WANT TO UPDATE---------

        # Mapping of plant_id and utility_type to Excel column letters
        col_map = {
            "999": {"electricity": "B"},
            "881": {"electricity": "B"},
            "789": {"electricity": "C"}
        }

        # Get the appropriate column letter
        col = col_map.get(pid, {}).get(utype)
        if not col:
            return func.HttpResponse("Unsupported plant or utility", 400)

        # Construct patch URL for updating cell in the worksheet
        patch_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{file['id']}/workbook/worksheets/Utilities/range(address='{col}{target_row}')"

        # Perform the update via PATCH
        logging.info("Update Excel")
        patch_resp = requests.patch(patch_url, headers=headers, json={"values": [[val]]})
        logging.info(patch_resp.text)
        if patch_resp.status_code != 200:
            return func.HttpResponse(body="Failed to update Excel", status_code=patch_resp.status_code)

        return func.HttpResponse("Excel updated successfully", 200)

    except Exception as e:
        tb = traceback.format_exc()
        logging.error("Exception occurred:")
        logging.error(tb)
        return func.HttpResponse(f"Exception: {str(e)}\n\nTraceback:\n{tb}", status_code=500)
