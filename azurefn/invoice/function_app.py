import azure.functions as func
import logging
import os
import tempfile
import json
import uuid
import re

from azure.storage.blob import BlobServiceClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.data.tables import TableServiceClient
from openai import AzureOpenAI


import azure.functions as func
from azure.data.tables import TableServiceClient
import os
import logging
import requests
from datetime import datetime, timedelta
import jwt

#-------------------------Env Variables-------------------------
DOC_INTEL_ENDPOINT = os.environ["DOC_INTEL_ENDPOINT"]
DOC_INTEL_KEY = os.environ["DOC_INTEL_KEY"]
OPENAI_ENDPOINT = os.environ["OPENAI_ENDPOINT"]
OPENAI_KEY = os.environ["OPENAI_KEY"]
OPENAI_DEPLOYMENT = os.environ["OPENAI_DEPLOYMENT"]
OPENAI_API_VERSION = os.environ.get("OPENAI_API_VERSION", "2024-12-01-preview")
BLOB_CONN_STR = os.environ["AzureWebJobsStorage"]

#-------------------------Main Blob Trigger-------------------------
app = func.FunctionApp()

@app.blob_trigger(arg_name="myblob", path="fileuploads/{name}", connection="AzureWebJobsStorage")
def blob_trigger_v2(myblob: func.InputStream):
    logging.info(f"Blob trigger: {myblob.name} ({myblob.length} bytes)")

    # Skip unsupported file formats
    supported_exts = ('.pdf', '.png', '.jpg', '.jpeg', '.tiff')
    if not myblob.name.lower().endswith(supported_exts):
        logging.warning(f"Skipping unsupported file type: {myblob.name}")
        return

    temp_pdf_path = None
    try:
        # Save blob to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
            temp_pdf.write(myblob.read())
            temp_pdf_path = temp_pdf.name
        logging.info("Saved blob to local temp file.")

        # Document Intelligence
        try:
            doc_client = DocumentIntelligenceClient(DOC_INTEL_ENDPOINT, AzureKeyCredential(DOC_INTEL_KEY))
            with open(temp_pdf_path, "rb") as f:
                poller = doc_client.begin_analyze_document("prebuilt-invoice", body=f)
                doc_intel_result = poller.result(timeout=300)

            extracted_fields = {}
            if hasattr(doc_intel_result, "documents") and doc_intel_result.documents:
                doc = doc_intel_result.documents[0]
                for key, value in doc.fields.items():
                    extracted_fields[key] = value.content if hasattr(value, "content") else str(value)

            extracted_tables = []
            if hasattr(doc_intel_result, "tables"):
                for table in doc_intel_result.tables:
                    cells = [
                        {
                            "rowIndex": cell.row_index,
                            "columnIndex": cell.column_index,
                            "content": cell.content
                        }
                        for cell in table.cells if cell.content.strip()
                    ]
                    if cells:
                        extracted_tables.append({
                            "rowCount": table.row_count,
                            "columnCount": table.column_count,
                            "cells": cells
                        })

            docintel_combined = {
                "fields": extracted_fields,
                "tables": extracted_tables
            }

            logging.info("Document Intelligence extraction successful.")

        except Exception as doc_err:
            logging.error(f"Document Intelligence extraction failed: {doc_err}", exc_info=True)
            raise

        # OpenAI Formatting (combine fields + extract power usage from tables)
        try:
            client = AzureOpenAI(
                api_key=OPENAI_KEY,
                azure_endpoint=OPENAI_ENDPOINT,
                api_version=OPENAI_API_VERSION,
            )

            combined_payload = {
                "fields": extracted_fields,
                "tables": extracted_tables
            }

            prompt = (
                "You are given raw invoice data extracted from Azure Document Intelligence.\n"
                "It contains key-value fields and also one or more tables.\n\n"
                "Your task is to extract the required fields below and return them in JSON format "
                "with exactly the following keys (flat, no nesting). If a value is not found, use an empty string.\n\n"
                "**Important Instructions:**\n"
                "- Only extract energy usage (kWh) values from columns labeled with 'kWh', 'Energy Usage', or similar.\n"
                "- **Do NOT use values from columns labeled 'DERS', 'DER', 'Solar', or 'Export'.**\n"
                "- Return only a JSON object with the following keys and no extra text or explanation.\n\n"
                "**Required Output Format:**\n"
                "{\n"
                '  "InvoiceNumber": "",\n'
                '  "VendorName": "",\n'
                '  "VendorTaxId": "",\n'
                '  "CustomerName": "",\n'
                '  "CustomerAddress": "",\n'
                '  "InvoiceDate": "",\n'
                '  "DueDate": "",\n'
                '  "ServiceEndDate": "",\n'
                '  "InvoiceTotal": "",\n'
                '  "SubTotal": "",\n'
                '  "TotalTax": "",\n'
                '  "AmountDue": "",\n'
                '  "EnergyUsage_kWh": ""\n'
                "}\n\n"
                f"Extraction result:\n{json.dumps(combined_payload, indent=2)}"
            )




            response = client.chat.completions.create(
                model=OPENAI_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": "You are an expert at reading invoices and extracting clean structured data."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=4096,
                temperature=0
            )

            formatted_json = response.choices[0].message.content.strip()
            logging.info("OpenAI formatting complete.")

            match = re.search(r'{.*}', formatted_json, re.DOTALL)
            if match:
                formatted_json = match.group(0)
            else:
                raise ValueError("No valid JSON found in GPT response.")

        except Exception as gpt_err:
            logging.error(f"OpenAI formatting failed: {gpt_err}", exc_info=True)
            raise

        # Store to Azure Table Storage
        try:
            parsed_output = json.loads(formatted_json)
            base_filename = os.path.splitext(os.path.basename(myblob.name))[0]
            partition_key = base_filename
            row_key = str(uuid.uuid4())

            entity = {
                "PartitionKey": partition_key,
                "RowKey": row_key,
                **{k: str(v) for k, v in parsed_output.items()},
                "Verified": False
            }
            entity = {
                "PartitionKey": partition_key,
                "RowKey": row_key,
                **{k: str(v) for k, v in parsed_output.items()},
                "Verified": False
            }

            logging.info(f"Final entity to insert:\n{json.dumps(entity, indent=2)}")

            table_service = TableServiceClient.from_connection_string(BLOB_CONN_STR)
            table_client = table_service.get_table_client(table_name="InvoiceData")
            table_client.upsert_entity(entity=entity)

            logging.info("Document Intelligence extraction successful.")

        except Exception as doc_err:
            logging.error(f"Document Intelligence extraction failed: {doc_err}", exc_info=True)
            raise

        # OpenAI Formatting (combine fields + extract power usage from tables)
        try:
            client = AzureOpenAI(
                api_key=OPENAI_KEY,
                azure_endpoint=OPENAI_ENDPOINT,
                api_version=OPENAI_API_VERSION,
            )

            combined_payload = {
                "fields": extracted_fields,
                "tables": extracted_tables
            }

            prompt = (
                "You are given raw invoice data extracted from Azure Document Intelligence.\n"
                "It contains key-value fields and also one or more tables.\n\n"
                "Your task is to extract the required fields below and return them in JSON format "
                "with exactly the following keys (flat, no nesting). If a value is not found, use an empty string.\n\n"
                "**Important Instructions:**\n"
                "- Only extract energy usage (kWh) values from columns labeled with 'kWh', 'Energy Usage', or similar.\n"
                "- **Do NOT use values from columns labeled 'DERS', 'DER', 'Solar', or 'Export'.**\n"
                "- Return only a JSON object with the following keys and no extra text or explanation.\n\n"
                "**Required Output Format:**\n"
                "{\n"
                '  "InvoiceNumber": "",\n'
                '  "VendorName": "",\n'
                '  "VendorTaxId": "",\n'
                '  "CustomerName": "",\n'
                '  "CustomerAddress": "",\n'
                '  "InvoiceDate": "",\n'
                '  "DueDate": "",\n'
                '  "ServiceEndDate": "",\n'
                '  "InvoiceTotal": "",\n'
                '  "SubTotal": "",\n'
                '  "TotalTax": "",\n'
                '  "AmountDue": "",\n'
                '  "EnergyUsage_kWh": ""\n'
                "}\n\n"
                f"Extraction result:\n{json.dumps(combined_payload, indent=2)}"
            )




            response = client.chat.completions.create(
                model=OPENAI_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": "You are an expert at reading invoices and extracting clean structured data."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=4096,
                temperature=0
            )

            formatted_json = response.choices[0].message.content.strip()
            logging.info("OpenAI formatting complete.")

            match = re.search(r'{.*}', formatted_json, re.DOTALL)
            if match:
                formatted_json = match.group(0)
            else:
                raise ValueError("No valid JSON found in GPT response.")

        except Exception as gpt_err:
            logging.error(f"OpenAI formatting failed: {gpt_err}", exc_info=True)
            raise

        # Store to Azure Table Storage
        try:
            parsed_output = json.loads(formatted_json)
            base_filename = os.path.splitext(os.path.basename(myblob.name))[0]
            partition_key = base_filename
            row_key = str(uuid.uuid4())

            entity = {
                "PartitionKey": partition_key,
                "RowKey": row_key,
                **{k: str(v) for k, v in parsed_output.items()},
                "Verified": False
            }

            logging.info(f"Final entity to insert:\n{json.dumps(entity, indent=2)}")

            table_service = TableServiceClient.from_connection_string(BLOB_CONN_STR)
            table_client = table_service.get_table_client(table_name="InvoiceData")
            table_client.upsert_entity(entity=entity)

            logging.info(f"Inserted invoice entity for {partition_key}/{row_key} into Azure Table Storage.")

        except Exception as table_err:
            logging.error(f"Writing to Table Storage failed: {table_err}", exc_info=True)
            raise

    except Exception as exc:
        logging.error(f"Pipeline error for {myblob.name}: {exc}", exc_info=True)
        raise
    finally:
        if temp_pdf_path and os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)
            logging.info("Temp file cleaned up.")



#-------------------------Generate Token for Graph API-------------------------

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
    

    

#-------------------------Update Excel-------------------------

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
