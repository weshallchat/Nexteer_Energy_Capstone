import os
from flask import Flask, request, jsonify, render_template
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv
from flask_cors import CORS

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)

# Azure Blob Storage setup
connect_str = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
container_name = os.getenv('AZURE_CONTAINER_NAME')

if not connect_str or not container_name:
    raise ValueError("AZURE_STORAGE_CONNECTION_STRING or AZURE_CONTAINER_NAME is not set.")

blob_service_client = BlobServiceClient.from_connection_string(connect_str)
container_client = blob_service_client.get_container_client(container_name)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_pdf():
    try:
        uploaded_file = request.files['pdf']
        if not uploaded_file:
            return jsonify({'error': 'No file uploaded'}), 400

        blob_name = f"{int(os.times()[4] * 1000)}-{uploaded_file.filename}"
        blob_client = container_client.get_blob_client(blob_name)

        blob_client.upload_blob(uploaded_file.read(), overwrite=True, content_type=uploaded_file.mimetype)

        return jsonify({'message': 'Upload successful', 'url': blob_client.url})
    except Exception as e:
        print(f"Upload Error: {e}")
        return jsonify({'error': str(e)}), 500

# Main entry (needed for local dev only; Azure uses gunicorn)
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))