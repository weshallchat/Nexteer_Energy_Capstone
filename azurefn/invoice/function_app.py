import azure.functions as func
from azure.data.tables import TableServiceClient
from azure.storage.blob import BlobServiceClient
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
    

@app.blob_trigger(arg_name="myblob",
                  path="fileuploads/{name}",
                  connection="AzureWebJobsStorage")
def blob_trigger_func(myblob: func.InputStream):
    logging.info(f"Blob trigger fired! Name: {myblob.name}, Size: {myblob.length} bytes")


#blob trigger function for confirmation - this logs the blob name and size, and writes a confirmation blob to another container -ihash

# @app.blob_trigger(arg_name="confirmationblob", path="fileuploads/{name}",
#                   connection="58ebfd_STORAGE")
# def BlobTrigger(confirmationblob: func.InputStream):
#     logging.info(f"Python blob trigger function processed blob "
#                  f"Name: {confirmationblob.name} "
#                  f"Blob Size: {confirmationblob.length} bytes")

#     # Write a confirmation blob to another container for testing
#     try:
#         conn_str = os.environ["AzureWebJobsStorage"]
#         blob_service_client = BlobServiceClient.from_connection_string(conn_str)
#         confirmation_container = "fileuploads-confirmation"
#         confirmation_blob_name = f"confirmation-{confirmationblob.name}.txt"
#         confirmation_content = (
#             f"Blob {confirmationblob.name} of size {confirmationblob.length} bytes was processed successfully."
#         )

#         # Ensure the container exists
#         container_client = blob_service_client.get_container_client(confirmation_container)
#         try:
#             container_client.create_container()
#         except Exception:
#             pass  # Container may already exist

#         # Upload the confirmation blob
#         container_client.upload_blob(
#             name=confirmation_blob_name,
#             data=confirmation_content,
#             overwrite=True
#         )
#         logging.info(f"Confirmation blob written: {confirmation_blob_name}")
#     except Exception as e:
#         logging.error(f"Failed to write confirmation blob: {str(e)}")
