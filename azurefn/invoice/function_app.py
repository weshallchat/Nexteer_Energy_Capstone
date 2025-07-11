import azure.functions as func
from azure.data.tables import TableServiceClient
import os
import json
import logging

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

@app.route(route="writeinvoice", methods=["POST"])
def write_invoice(req: func.HttpRequest) -> func.HttpResponse:
    try:
        data = req.get_json()

        partition_key = data.get("PartitionKey")
        row_key = data.get("RowKey")

        if not partition_key or not row_key:
            return func.HttpResponse("Missing PartitionKey or RowKey", status_code=400)

        entity = {
            "PartitionKey": partition_key,
            "RowKey": row_key,
            **{k: v for k, v in data.items() if k not in ["PartitionKey", "RowKey"]},
            "Verified": False
        }

        conn_str = os.environ["AzureWebJobsStorage"]
        table_service = TableServiceClient.from_connection_string(conn_str)
        table_client = table_service.get_table_client(table_name="InvoiceData")
        table_client.upsert_entity(entity=entity)

        return func.HttpResponse("Record inserted with Verified=False", status_code=200)

    except Exception as e:
        logging.exception("Error inserting record")
        return func.HttpResponse(f"Error: {str(e)}", status_code=500)

@app.route(route="writeinvoice", methods=["GET"])
def get_invoice(req: func.HttpRequest) -> func.HttpResponse:
    try:
        partition_key = req.params.get("PartitionKey")
        row_key = req.params.get("RowKey")

        if not partition_key or not row_key:
            return func.HttpResponse("Missing PartitionKey or RowKey", status_code=400)

        conn_str = os.environ["AzureWebJobsStorage"]
        table_service = TableServiceClient.from_connection_string(conn_str)
        table_client = table_service.get_table_client(table_name="InvoiceData")
        entity = table_client.get_entity(partition_key=partition_key, row_key=row_key)

        return func.HttpResponse(json.dumps(entity), mimetype="application/json", status_code=200)

    except Exception as e:
        logging.exception("Error retrieving record")
        return func.HttpResponse(f"Error: {str(e)}", status_code=500)
    
@app.route(route="updateexcel", methods=["POST"])
def update_excel(req: func.HttpRequest) -> func.HttpResponse:
    import requests
    from datetime import datetime
    import base64
    import jwt

    try:
        body = req.get_json()
        year_month = body.get("year_month")
        value = body.get("value")
        plant_id = body.get("plant_id")
        utility_type = body.get("utility_type")

        if not (year_month and value and plant_id and utility_type):
            return func.HttpResponse("Missing parameters", status_code=400)

        # Token and environment setup
        access_token = os.environ["GRAPH_ACCESS_TOKEN"]
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
        site_url = "https://graph.microsoft.com/v1.0/sites/andrewcmu.sharepoint.com:/sites/Capstone-Nexteer"
        site_resp = requests.get(site_url, headers=headers)
        site_id = site_resp.json()["id"]
        logging.info(f"Site ID: {site_id}")

        # Get drive ID
        drive_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive"
        drive_resp = requests.get(drive_url, headers=headers)
        drive_id = drive_resp.json()["id"]

        # Get item ID of the folder
        root_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children"
        root_resp = requests.get(root_url, headers=headers)
        folder_item_id = next((item["id"] for item in root_resp.json()["value"] if item["name"] == "Plant Data"), None)

        if not folder_item_id:
            return func.HttpResponse("Folder 'Plant Data' not found", status_code=404)

        # Get file inside folder
        folder_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{folder_item_id}/children"
        folder_resp = requests.get(folder_url, headers=headers)
        file_item = next((f for f in folder_resp.json()["value"] if plant_id in f["name"]), None)

        if not file_item:
            return func.HttpResponse(f"No Excel file found for plant ID: {plant_id}", status_code=404)

        file_id = file_item["id"]

        # Find the matching row
        sheet_name = utility_type.capitalize() + "s"  # e.g., Utilities
        range_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{file_id}/workbook/worksheets/{sheet_name}/usedRange"
        range_resp = requests.get(range_url, headers=headers)
        rows = range_resp.json()["values"]

        target_row = None
        for idx, row in enumerate(rows):
            if len(row) > 0 and row[0] == year_month:
                target_row = idx + 1  # Excel is 1-based
                break

        if not target_row:
            return func.HttpResponse(f"Date {year_month} not found in column A", status_code=404)

        # Write the value into column B
        patch_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{file_id}/workbook/worksheets/{sheet_name}/range(address='B{target_row}')"
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
