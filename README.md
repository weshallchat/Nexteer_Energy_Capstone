# Nexteer Energy Capstone

**Team Members:** Sumedh Bhoir, Shyuan Chang, Ian Hash, Heather Yang, Vishal Chatterjee, Shreyas Nopany  
**Advisor:** Christopher Stephens  
**Nexteer Representative:** Jason Hatfield

As regulators and energy markets evolve with new corporate reporting requirements, Nexteer is positioning itself to respond with data-informed decisions. Nexteer aims to track and analyze Scope 2 energy usage and climate impact across 27 manufacturing plants, five technical centers, and 13 customer service centers on six continents.

Although their current reporting framework is functioning, it is manual, fragmented, and incurs high overhead. Our capstone team developed a streamlined, Azure-based infrastructure and data pipeline to automate utility data collection and reporting—reducing time, improving robustness, and enabling faster strategy adjustments.

The system targets three utility types—**electricity, water, and gas**—and processes both digital and handwritten utility bills using cutting-edge AI and ML services. This project automates the data ingestion process to feed existing Power BI dashboards used by Nexteer for internal reporting and climate roadmap tracking.

During the discovery phase, our team identified energy usage reporting automation as the most critical need. With Nexteer's support, we engaged with over 13 stakeholders including directors, project managers, and environmental/IT engineers. Together, we built a solution that seamlessly integrates into Nexteer’s existing workflows.

---


## Installation & Configuration

This solution is deployed within Nexteer’s native Azure environment and **requires no external installation**.

---

## Product Overview

The core product is a **document processing pipeline** hosted in Azure. It leverages:

- Azure Blob Storage
- Azure Functions (Python-based)
- Azure Document Intelligence (OCR)
- Azure Table Storage
- OpenAI for structured field extraction
- Power BI for dashboarding

The pipeline ingests and processes utility bills and uploads the extracted, structured data to be visualized in Nexteer’s existing Power BI dashboards.

---

## Code Overview

The code is split into two parts.

**FrontEnd:** 

- Flask based app written in Python.
- Upload invoice on the web application.
- Invoice stored in Azure Blob Storage.

**BackEnd:**

- Blob trigger based Azure Function pulls invoice from Blob Storage.
- Uses Azure DocuSign API and GPT API to extract fields.
- Extracted fields loaded to Azure Data Table.
- HTTP based Azure Function uses MS Graph API to locate SharePoint drive.
- Uploads extracted fields to corresponding excel in SharePoint.

