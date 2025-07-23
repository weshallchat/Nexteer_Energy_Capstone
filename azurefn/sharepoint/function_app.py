import azure.functions as func
from azure.data.tables import TableServiceClient
import os
import logging
import requests
from datetime import datetime, timedelta
import jwt
 
def get_graph_token():
    tenant_id = os.environ["TENANT_ID"]
    client_id = os.environ["CLIENT_ID"]
    client_secret = os.environ["CLIENT_SECRET"]

    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    data = {"client_id": client_id,
            "scope": "https://graph.microsoft.com/.default",
            "client_secret": client_secret,
            "grant_type": "client_credentials"
    }

    response = requests.post(url, headers=headers, data=data)
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        raise Exception(f"Token request failed: {response.status_code} - {response.text}")
    
app = func.FunctionApp()
@app.route(route="updateexcel", methods=["POST"])
def update_excel(req: func.HttpRequest) -> func.HttpResponse:

    try:
        body = req.get_json()
        year_month = body.get("year_month")
        value = body.get("value")
        plant_id = body.get("plant_id")
        utility_type = body.get("utility_type")

        if not (year_month and value and plant_id and utility_type):
            return func.HttpResponse("Missing parameters", status_code=400)
        

        # Token and environment setup
        access_token = get_graph_token()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        # Decode token for debugging
        try:
            decoded = jwt.decode(access_token, options={"verify_signature": False})
            logging.info(f"Token issued to: {decoded.get('upn', 'unknown')}")
        except Exception as e:
            logging.warning(f"Token decode failed: {str(e)}")

        # Get site ID
        site_url = "https://graph.microsoft.com/v1.0/sites/nexteerautomotive.sharepoint.com:/sites/GlobalEnvironmentalData"
        site_resp = requests.get(site_url, headers=headers)
        site_id = site_resp.json()["id"]
        logging.info(f"Site ID: {site_id}")

        # Get drive ID
        drive_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive"
        drive_resp = requests.get(drive_url, headers=headers)
        drive_id = drive_resp.json()["id"]

        # Get item ID of the folder
        general_folder_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/General:/children"
        general_resp = requests.get(general_folder_url, headers=headers)
        folder_item_id = next((item["id"] for item in general_resp.json()["value"] if item["name"] == "Plant Data Test"), None) # Test folder. Adjust to "Plant Data" for production   

        if not folder_item_id:
            return func.HttpResponse("Folder 'Plant Data Test' not found in General folder", status_code=404)

        # Get file inside folder
        folder_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{folder_item_id}/children"
        folder_resp = requests.get(folder_url, headers=headers)
        expected_filename = f"{plant_id} Utility and Environmental Test Data.xlsx"
        file_item = next((f for f in folder_resp.json()["value"] if f["name"] == expected_filename), None)

        if not file_item:
            return func.HttpResponse(f"Excel file '{expected_filename}' not found", status_code=404)   
        
        file_id = file_item["id"]

        # Use "Utilities" sheet 
        sheet_name = "Utilities"

        # Determine target column based on utility_type and plant_id using mapping
        plant_utility_column_map = {
            "999": {
                "electricity": "B",  # Test Plant
            },
            "881": {
                "electricity": "B",  # Electric-Non Renewable
            },
            "789": {
                "electricity": "C",  # Electric-Renewable
            },
            # Add more plant_id and utility_type mappings here
        }
        
        plant_map = plant_utility_column_map.get(plant_id)
        if not plant_map:
            return func.HttpResponse(f"Unsupported plant_id: {plant_id}", status_code=400)

        column_letter = plant_map.get(utility_type)
        if not column_letter:
            return func.HttpResponse(f"Utility type '{utility_type}' not supported for plant {plant_id}", status_code=400)


        # Find the matching row
        range_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{file_id}/workbook/worksheets/{sheet_name}/usedRange"
        range_resp = requests.get(range_url, headers=headers)
        rows = range_resp.json()["values"]

        EXCEL_EPOCH = datetime(1899, 12, 30)
    
        target_row = None
        for idx, row in enumerate(rows):
            # Convert input "year_month" to datetime object
            try:
                input_date = datetime.strptime(year_month, "%Y-%m")
            except ValueError:
                return func.HttpResponse(f"Invalid date format: {year_month}. Expected 'YYYY-MM'", status_code=400)

            # Match Excel's actual date object (not string format)
            if len(row) > 0:
                cell_value = row[0]
                try:
                    if isinstance(cell_value, int):
                        excel_cell_date = EXCEL_EPOCH + timedelta(days=cell_value)
                    elif isinstance(cell_value, str):
                        excel_cell_date = datetime.strptime(cell_value, "%m/%d/%Y")
                    else:
                        continue
                except Exception:
                    continue  # skip rows where the first column is not a valid date
                if excel_cell_date.year == input_date.year and excel_cell_date.month == input_date.month:
                    target_row = idx + 1  # Excel is 1-based
                    break
                
        if not target_row:
            return func.HttpResponse(f"Date {year_month} not found in column A", status_code=404)

        # Write the value into the determined column
        patch_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{file_id}/workbook/worksheets/{sheet_name}/range(address='{column_letter}{target_row}')"
        patch_body = {
            "values": [[value]]
        }

        patch_resp = requests.patch(patch_url, headers=headers, json=patch_body)
        if patch_resp.status_code != 200:
            return func.HttpResponse(f"Failed to update cell: {patch_resp.text}", status_code=patch_resp.status_code)

        return func.HttpResponse("Excel updated successfully", status_code=200)

    except Exception as e:
        logging.exception("Error updating Excel")
        return func.HttpResponse(f"Error: {str(e)}", status_code=500)
