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


@app.blob_trigger(arg_name="myblob", path="fileuploads/{name}",
                               connection="58ebfd_STORAGE") 
def BlobTrigger(myblob: func.InputStream):
    logging.info(f"Python blob trigger function processed blob"
                f"Name: {myblob.name}"
                f"Blob Size: {myblob.length} bytes")
