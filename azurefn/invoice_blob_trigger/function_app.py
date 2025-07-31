import azure.functions as func
import logging
import os
import tempfile
import json
import uuid
import re
import requests

from azure.storage.blob import BlobServiceClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.data.tables import TableServiceClient
from openai import AzureOpenAI

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

            logging.info(f"Final entity to insert:\n{json.dumps(entity, indent=2)}")

            table_service = TableServiceClient.from_connection_string(BLOB_CONN_STR)
            table_client = table_service.get_table_client(table_name="InvoiceData")
            table_client.upsert_entity(entity=entity)

            logging.info(f"Inserted invoice entity for {partition_key}/{row_key} into Azure Table Storage.")

        except Exception as table_err:
            logging.error(f"Writing to Table Storage failed: {table_err}", exc_info=True)
            raise

        # Optional: Automatically trigger the HTTP function
        
        try:
            requests.post(
                url=os.environ["EXCEL_UPDATE_URL"],  # e.g., https://<your-function-app>.azurewebsites.net/api/updateexcel
                json={
                    "year_month": parsed_output.get("InvoiceDate", "")[:7],  # Format: "2024-05"
                    "value": parsed_output.get("EnergyUsage_kWh", ""),
                    "plant_id": "999",  #-------Change to relevant plant
                    "utility_type": "electricity"
                },
                headers={"x-functions-key": os.environ["EXCEL_UPDATE_KEY"]}  # Optional: if secured
            )
            #print(f"Sending these info to update to excel: {json.dumps(json, indent=2)}")
            logging.info("Triggered Excel update function successfully.")
        except Exception as e:
            logging.error(f"Failed to call Excel update function: {e}")
    except Exception as exc:
        logging.error(f"Pipeline error for {myblob.name}: {exc}", exc_info=True)
        raise
    finally:
        if temp_pdf_path and os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)
            logging.info("Temp file cleaned up.")