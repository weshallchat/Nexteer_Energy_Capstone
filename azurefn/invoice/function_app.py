import azure.functions as func
import logging

#-------------------------Added Imports Start-------------------------
import os
import tempfile

from azure.storage.blob import BlobServiceClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from openai import AzureOpenAI

import json
#-------------------------Added Imports End-------------------------

#-------------------------Added Env Variables Start-------------------------
# Environment variables (set in Azure portal or local.settings.json)
DOC_INTEL_ENDPOINT = os.environ["DOC_INTEL_ENDPOINT"]
DOC_INTEL_KEY = os.environ["DOC_INTEL_KEY"]
OPENAI_ENDPOINT = os.environ["OPENAI_ENDPOINT"]
OPENAI_KEY = os.environ["OPENAI_KEY"]
OPENAI_DEPLOYMENT = os.environ["OPENAI_DEPLOYMENT"]
OPENAI_API_VERSION = os.environ.get("OPENAI_API_VERSION", "2024-12-01-preview")
BLOB_CONN_STR = os.environ["AzureWebJobsStorage"]
#-------------------------Added Env Variables End-------------------------

#-------------------------Main Blob Tigger Function Start-------------------------

# Main function to handle blob trigger
app = func.FunctionApp()

@app.blob_trigger(arg_name="myblob", path="fileuploads/{name}", connection="AzureWebJobsStorage")
def blob_trigger_v2(myblob: func.InputStream):
    logging.info(f"Blob trigger: {myblob.name} ({myblob.length} bytes)")

    temp_pdf_path = None
    try:
        # Save incoming blob to a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
            temp_pdf.write(myblob.read())
            temp_pdf_path = temp_pdf.name
        logging.info("Saved blob to local temp file.")

        # Document Intelligence Extraction with correct manual extraction
        try:
            doc_client = DocumentIntelligenceClient(DOC_INTEL_ENDPOINT, AzureKeyCredential(DOC_INTEL_KEY))
            with open(temp_pdf_path, "rb") as f:
                # Use the prebuilt-invoice model to analyze the document - this currently only extracts summary fields, may need to add additional parsing logic for additional field extraction
                poller = doc_client.begin_analyze_document("prebuilt-invoice", body=f)
                doc_intel_result = poller.result(timeout=300)
            
            # MANUALLY extract fields as a dict
            extracted_fields = {}
            if hasattr(doc_intel_result, "documents") and doc_intel_result.documents:
                doc = doc_intel_result.documents[0]
                for key, value in doc.fields.items():
                    # Use .content if present, else fallback to str(value)
                    extracted_fields[key] = value.content if hasattr(value, "content") else str(value)
            else:
                extracted_fields = {}
            logging.info(f"Document Intelligence extraction successful. Extracted fields: {extracted_fields}")
        except Exception as doc_err:
            logging.error(f"Document Intelligence extraction failed: {doc_err}", exc_info=True)
            raise

        # Format extracted data with Azure OpenAI GPT
        try:
            client = AzureOpenAI(
                api_key=OPENAI_KEY,
                azure_endpoint=OPENAI_ENDPOINT,
                api_version=OPENAI_API_VERSION,
            )
            # Pass a JSON string of the fields into the prompt for GPT context
            extracted_json_str = json.dumps(extracted_fields, indent=2)
            prompt = (
                "You are given the following raw invoice extraction result from Azure Document Intelligence. "
                "Format the important invoice fields (such as Invoice Number, Date, Vendor, Amount, Filename, Energy Usage etc.) as clear key-value pairs in JSON format. "
                "If any fields are missing, leave them blank.\n\n"
                f"Extraction result:\n{extracted_json_str}\n\n"
                "Format as key-value pairs:"
            )
            response = client.chat.completions.create(
                model=OPENAI_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": "You are an expert at formatting invoice data."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=4096,
                temperature=0
            )
            formatted_json = response.choices[0].message.content.strip()
            logging.info("OpenAI formatting complete.")
        except Exception as gpt_err:
            logging.error(f"OpenAI formatting failed: {gpt_err}", exc_info=True)
            raise

        # Write formatted JSON to blob storage with matching base name
        try:
            blob_service = BlobServiceClient.from_connection_string(BLOB_CONN_STR)
            container_name = "fileuploads"  # hardcoded to match your trigger, or parse from path if generalized
            base_filename = os.path.splitext(os.path.basename(myblob.name))[0]
            output_blob_name = f"{base_filename}_formatted.json"

            output_blob_client = blob_service.get_blob_client(container=container_name, blob=output_blob_name)
            output_blob_client.upload_blob(formatted_json, overwrite=True)
            logging.info(f"Formatted JSON saved as: {output_blob_name}")
        except Exception as storage_err:
            logging.error(f"Writing JSON to blob storage failed: {storage_err}", exc_info=True)
            raise

    except Exception as exc:
        logging.error(f"Pipeline error for {myblob.name}: {exc}", exc_info=True)
        raise
    finally:
        # Always remove the temp file created
        if temp_pdf_path and os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)
            logging.info("Temp file cleaned up.")

    #-------------------------Main Blob Tigger Function End-------------------------
