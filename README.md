# Nexteer Energy Capstone

**Team Members:** Sumedh Bhoir, Shyuan Chang, Ian Hash, Heather Yang, Vishal Chatterjee, Shreyas Nopany  
**Advisor:** Christopher Stephens  
**Nexteer Representative:** Jason Hatfield

As regulators and energy markets evolve with new corporate reporting requirements, Nexteer is positioning itself to respond with data-informed decisions. Nexteer aims to track and analyze Scope 2 energy usage and climate impact across 27 manufacturing plants, five technical centers, and 13 customer service centers on six continents.

Although their current reporting framework is functioning, it is manual, fragmented, and incurs high overhead. Our capstone team developed a streamlined, Azure-based infrastructure and data pipeline to automate utility data collection and reporting—reducing time, improving robustness, and enabling faster strategy adjustments.

The system targets three utility types—**electricity, water, and gas**—and processes both digital and handwritten utility bills using cutting-edge AI and ML services. This project automates the data ingestion process to feed existing Power BI dashboards used by Nexteer for internal reporting and climate roadmap tracking.

During the discovery phase, our team identified energy usage reporting automation as the most critical need. With Nexteer's support, we engaged with over 13 stakeholders including directors, project managers, and environmental/IT engineers. Together, we built a solution that seamlessly integrates into Nexteer’s existing workflows.

---

## Deliverables

| Deliverable                    | Description                                                                |
|-------------------------------|-----------------------------------------------------------------------------|
| **Executive Summary**         | Overview document (this README)                                            |
| **Final Report & Docs**       | Project summary, methodology, lessons learned, future work, usage guide    |
| **Mid-Semester Slides**       | Presentation of progress and preliminary solution                          |
| **Final Presentation Slides** | Final product, demo, impact, limitations, and handoff plan                 |
| **Presentation Recording**    | Video of the final presentation                                            |
| **Creative Video**            | Product teaser and overview                                                |
| **Codebase**                  | Fully developed and deployed in Nexteer's Azure environment                |

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